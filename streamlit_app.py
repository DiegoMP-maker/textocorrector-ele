import streamlit as st
import json
import gspread
import requests
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO

# --- 1. CONFIGURACIÓN DE CLAVES SEGURAS ---
openai_api_key = st.secrets["OPENAI_API_KEY"]
elevenlabs_api_key = st.secrets["ELEVENLABS_API_KEY"]
elevenlabs_voice_id = st.secrets["ELEVENLABS_VOICE_ID"]

# --- 2. CONEXIÓN A GOOGLE SHEETS ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
client_gsheets = gspread.authorize(creds)

# IDs de los documentos
CORRECTIONS_DOC_ID = "1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8"  # Historial_Correcciones_ELE
TRACKING_DOC_ID    = "1-OQsMGgWseZ__FyUVh0UtYVOLui_yoTMG0BxxTGPOU8"  # Seguimiento

# --- Abrir documento de correcciones (Historial_Correcciones_ELE) ---
try:
    corrections_sheet = client_gsheets.open_by_key(CORRECTIONS_DOC_ID).sheet1
    st.success("✅ Conectado a Historial_Correcciones_ELE correctamente.")
except Exception as e:
    st.error(f"❌ Error al conectar con Historial_Correcciones_ELE: {e}")
    st.stop()

# --- Verificar y preparar documento de seguimiento ---
try:
    tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
    hojas = [hoja.title for hoja in tracking_doc.worksheets()]
    
    # Verificar si existe la hoja Seguimiento
    try:
        tracking_sheet = tracking_doc.worksheet("Seguimiento")
        st.success("✅ Conectado a hoja Seguimiento correctamente.")
    except gspread.exceptions.WorksheetNotFound:
        # Crear la hoja si no existe
        tracking_sheet = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=10)
        # Añadir encabezados a la hoja
        headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                   "Errores Puntuación", "Errores Estructura", "Total Errores", "Consejo Final"]
        tracking_sheet.append_row(headers)
        st.success("✅ Hoja 'Seguimiento' creada y preparada correctamente.")
except Exception as e:
    st.warning(f"⚠️ Advertencia con documento de Seguimiento: {e}")

# --- 3. INTERFAZ ---
st.title("📝 Textocorrector ELE (por Diego)")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback.")

with st.form("formulario"):
    nombre = st.text_input("¿Cómo te llamas?")
    nivel = st.selectbox("¿Cuál es tu nivel?", [
        "Nivel principiante (A1-A2)",
        "Nivel intermedio (B1-B2)",
        "Nivel avanzado (C1-C2)"
    ])
    idioma = st.selectbox("Selecciona lenguaje para la corrección", ["Español", "Francés", "Inglés"])
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# Función para obtener JSON de la IA con reintentos
def obtener_json_de_ia(system_msg, user_msg, max_retries=3):
    client = OpenAI(api_key=openai_api_key)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.5,
                messages=messages
            )
            raw_output = response.choices[0].message.content

            try:
                data_json = json.loads(raw_output)
                return raw_output, data_json
            except json.JSONDecodeError:
                # Intenta extraer JSON usando regex
                match_json = re.search(r"\{.*\}", raw_output, re.DOTALL)
                if match_json:
                    json_str = match_json.group(0)
                    try:
                        data_json = json.loads(json_str)
                        return raw_output, data_json
                    except json.JSONDecodeError:
                        pass

                # Si aún no hay JSON válido, pide al modelo que corrija
                if attempt < max_retries - 1:
                    messages.append({
                        "role": "system",
                        "content": (
                            "Tu respuesta anterior no cumplió el formato JSON requerido. "
                            "Por favor, responde ÚNICAMENTE en JSON válido con la estructura solicitada. "
                            "No incluyas texto extra, backticks, ni marcadores de código fuente."
                        )
                    })
        except Exception as e:
            st.warning(f"Intento {attempt+1}: Error en la API de OpenAI: {e}")
            if attempt == max_retries - 1:
                raise

    raise ValueError("No se pudo obtener un JSON válido tras varios reintentos.")

# --- 4. CORREGIR TEXTO CON IA Y JSON ESTRUCTURADO ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):
        # Instrucciones para el modelo de IA
        system_message = f"""
Eres Diego, un profesor experto en ELE.
Cuando corrijas un texto, DEBES devolver la respuesta únicamente en un JSON válido, sin texto adicional, con la siguiente estructura EXACTA:

{{
  "saludo": "string",                // en {idioma}
  "tipo_texto": "string",            // en {idioma}
  "errores": {{
       "Gramática": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"  // Explicación en {idioma}
           }}
           // más errores de Gramática (o [] si ninguno)
       ],
       "Léxico": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"  // Explicación en {idioma}
           }}
       ],
       "Puntuación": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"  // Explicación en {idioma}
           }}
       ],
       "Estructura textual": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"  // Explicación en {idioma}
           }}
       ]
  }},
  "texto_corregido": "string",       // en {idioma}
  "consejo_final": "string",         // SOLO esta parte va en español, independientemente del idioma seleccionado
  "fin": "Fin de texto corregido."
}}

INSTRUCCIONES IMPORTANTES:
1. Las categorías "Gramática", "Léxico", "Puntuación", "Estructura textual" siempre van en español, no las traduzcas.
2. "saludo", "tipo_texto", "texto_corregido" y TODAS las explicaciones de errores deben estar en el idioma: {idioma}
3. SOLO "consejo_final" va SIEMPRE en español, independientemente del idioma seleccionado.
4. No traduzcas ni "fragmento_erroneo" ni "correccion", deben mantener el idioma del texto original.

No devuelvas ningún texto extra fuera de este JSON.
"""
        user_message = f"""
Texto del alumno:
\"\"\"
{texto}
\"\"\"
Nivel: {nivel}
Nombre del alumno: {nombre}
Idioma de corrección: {idioma}

IMPORTANTE: Recuerda que la corrección debe estar en el idioma seleccionado ({idioma}). 
El "saludo", "tipo_texto", "texto_corregido" y todas las explicaciones de errores deben estar en {idioma}. 
Solo el "consejo_final" va siempre en español.
"""

        try:
            raw_output, data_json = obtener_json_de_ia(system_message, user_message, max_retries=3)

            # Extraer campos del JSON
            saludo = data_json.get("saludo", "")
            tipo_texto = data_json.get("tipo_texto", "")
            errores_obj = data_json.get("errores", {})
            texto_corregido = data_json.get("texto_corregido", "")
            consejo_final = data_json.get("consejo_final", "")
            fin = data_json.get("fin", "")

            # Adaptamos las cabeceras según el idioma seleccionado
            headers_by_language = {
                "Español": {
                    "saludo": "Saludo", 
                    "tipo_texto": "Tipo de texto y justificación", 
                    "errores": "Errores detectados",
                    "texto_corregido": "Texto corregido completo", 
                    "consejo_final": "Consejo final (en español)"
                },
                "Francés": {
                    "saludo": "Salutation", 
                    "tipo_texto": "Type de texte et justification", 
                    "errores": "Erreurs détectées",
                    "texto_corregido": "Texte corrigé complet", 
                    "consejo_final": "Conseil final (en espagnol)"
                },
                "Inglés": {
                    "saludo": "Greeting", 
                    "tipo_texto": "Text type and justification", 
                    "errores": "Detected errors",
                    "texto_corregido": "Complete corrected text", 
                    "consejo_final": "Final advice (in Spanish)"
                }
            }
            
            h = headers_by_language.get(idioma, headers_by_language["Español"])

            st.subheader(h["saludo"])
            st.write(saludo)
            st.subheader(h["tipo_texto"])
            st.write(tipo_texto)
            st.subheader(h["errores"])
            if not errores_obj:
                if idioma == "Español":
                    st.write("No se han detectado errores.")
                elif idioma == "Francés":
                    st.write("Aucune erreur détectée.")
                else:  # Inglés
                    st.write("No errors detected.")
            else:
                for categoria in ["Gramática", "Léxico", "Puntuación", "Estructura textual"]:
                    lista_errores = errores_obj.get(categoria, [])
                    st.markdown(f"**{categoria}**")
                    if not lista_errores:
                        if idioma == "Español":
                            st.write("  - Sin errores en esta categoría.")
                        elif idioma == "Francés":
                            st.write("  - Pas d'erreurs dans cette catégorie.")
                        else:  # Inglés
                            st.write("  - No errors in this category.")
                    else:
                        for err in lista_errores:
                            # Adaptamos las etiquetas según el idioma
                            if idioma == "Español":
                                st.write(f"  - Fragmento erróneo: {err.get('fragmento_erroneo','')}")
                                st.write(f"    Corrección: {err.get('correccion','')}")
                                st.write(f"    Explicación: {err.get('explicacion','')}")
                            elif idioma == "Francés":
                                st.write(f"  - Fragment erroné: {err.get('fragmento_erroneo','')}")
                                st.write(f"    Correction: {err.get('correccion','')}")
                                st.write(f"    Explication: {err.get('explicacion','')}")
                            else:  # Inglés
                                st.write(f"  - Erroneous fragment: {err.get('fragmento_erroneo','')}")
                                st.write(f"    Correction: {err.get('correccion','')}")
                                st.write(f"    Explanation: {err.get('explicacion','')}")
                    st.write("---")

            st.subheader(h["texto_corregido"])
            st.write(texto_corregido)

            st.subheader(h["consejo_final"])
            st.write(consejo_final)
            st.write(fin)

            # Guardar en Historial_Correcciones_ELE
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            corrections_sheet.append_row([nombre, nivel, idioma, fecha, texto, raw_output])
            st.success("✅ Corrección guardada en Historial_Correcciones_ELE.")

            # --- CONTEO DE ERRORES ---
            num_gramatica = len(errores_obj.get("Gramática", []))
            num_lexico = len(errores_obj.get("Léxico", []))
            num_puntuacion = len(errores_obj.get("Puntuación", []))
            num_estructura = len(errores_obj.get("Estructura textual", []))
            total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

            # --- GUARDAR SEGUIMIENTO EN EL DOCUMENTO "Seguimiento" ---
            try:
                datos_seguimiento = [
                    nombre,
                    nivel,
                    fecha,
                    num_gramatica,
                    num_lexico,
                    num_puntuacion,
                    num_estructura,
                    total_errores,
                    consejo_final
                ]
                
                # Intenta aprovechar la variable tracking_sheet que definimos al inicio
                try:
                    tracking_sheet.append_row(datos_seguimiento)
                    st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento.")
                    
                    # Mostrar resumen de errores
                    st.subheader("Resumen de errores")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Gramática", num_gramatica)
                    with col2:
                        st.metric("Léxico", num_lexico)
                    with col3:
                        st.metric("Puntuación", num_puntuacion)
                    with col4:
                        st.metric("Estructura", num_estructura)
                    st.metric("Total errores", total_errores)
                    
                except NameError:
                    # Si tracking_sheet no está definido, intentamos recuperarlo
                    tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
                    try:
                        tracking_sheet = tracking_doc.worksheet("Seguimiento")
                    except gspread.exceptions.WorksheetNotFound:
                        tracking_sheet = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=10)
                        headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                                "Errores Puntuación", "Errores Estructura", "Total Errores", "Consejo Final"]
                        tracking_sheet.append_row(headers)
                    
                    tracking_sheet.append_row(datos_seguimiento)
                    st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento (recuperada).")
            except Exception as e:
                st.error(f"❌ Error al guardar estadísticas en Seguimiento: {str(e)}")
                st.info("Detalles del error para depuración:")
                st.code(str(e))

            # --- GENERAR AUDIO CON ELEVENLABS (Consejo final en español) ---
            st.markdown("**🔊 Consejo leído en voz alta (en español):**")
            with st.spinner("Generando audio con ElevenLabs..."):
                tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                headers = {
                    "xi-api-key": elevenlabs_api_key,
                    "Content-Type": "application/json"
                }
                audio_text = consejo_final.replace("Consejo final:", "").strip()
                data = {
                    "text": audio_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.3,
                        "similarity_boost": 0.9
                    }
                }
                try:
                    response_audio = requests.post(tts_url, headers=headers, json=data)
                    if response_audio.ok:
                        audio_bytes = BytesIO(response_audio.content)
                        st.audio(audio_bytes, format="audio/mpeg")
                    else:
                        st.warning(f"⚠️ No se pudo reproducir el consejo con ElevenLabs. (Status code: {response_audio.status_code})")
                except Exception as e:
                    st.warning(f"⚠️ Error al generar audio: {e}")

            # --- DESCARGA EN TXT ---
            feedback_txt = (
                f"Texto original:\n{texto}\n\n"
                f"Saludo:\n{saludo}\n\n"
                f"Tipo de texto:\n{tipo_texto}\n\n"
                f"Errores:\n{json.dumps(errores_obj, indent=2, ensure_ascii=False)}\n\n"
                f"Texto corregido:\n{texto_corregido}\n\n"
                f"Consejo final:\n{consejo_final}\n\n"
                f"{fin}"
            )
            txt_buffer = BytesIO()
            txt_buffer.write(feedback_txt.encode("utf-8"))
            txt_buffer.seek(0)
            st.download_button(
                label="📝 Descargar corrección en TXT",
                data=txt_buffer,
                file_name=f"correccion_{nombre}.txt",
                mime="text/plain"
            )

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
            import traceback
            st.code(traceback.format_exc())
