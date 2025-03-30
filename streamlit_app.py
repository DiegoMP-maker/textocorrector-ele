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
        # Añadir encabezados a la hoja con nuevas columnas para análisis semántico
        headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                   "Errores Puntuación", "Errores Estructura", "Total Errores", 
                   "Puntuación Coherencia", "Puntuación Cohesión", "Puntuación Registro", 
                   "Puntuación Adecuación Cultural", "Consejo Final"]
        tracking_sheet.append_row(headers)
        st.success("✅ Hoja 'Seguimiento' creada y preparada correctamente.")
except Exception as e:
    st.warning(f"⚠️ Advertencia con documento de Seguimiento: {e}")

# --- 3. INTERFAZ ---
st.title("📝 Textocorrector ELE (por Diego)")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback con análisis contextual avanzado.")

with st.expander("ℹ️ Información sobre el análisis contextual", expanded=False):
    st.markdown("""
    Esta versión mejorada del Textocorrector incluye:
    
    - **Análisis de coherencia**: Evalúa si las ideas están conectadas de manera lógica y si el texto tiene sentido en su conjunto.
    - **Análisis de cohesión**: Revisa los mecanismos lingüísticos que conectan las diferentes partes del texto.
    - **Evaluación del registro lingüístico**: Determina si el lenguaje usado es apropiado para el contexto y propósito del texto.
    - **Análisis de adecuación cultural**: Identifica si hay expresiones o referencias culturalmente apropiadas o inapropiadas.
    
    Las correcciones se adaptan automáticamente al nivel del estudiante.
    """)

with st.form("formulario"):
    nombre = st.text_input("¿Cómo te llamas?")
    
    nivel = st.selectbox("¿Cuál es tu nivel?", [
        "Nivel principiante (A1-A2)",
        "Nivel intermedio (B1-B2)",
        "Nivel avanzado (C1-C2)"
    ])
    
    idioma = st.selectbox("Selecciona lenguaje para la corrección", ["Español", "Francés", "Inglés"])
    
    col1, col2 = st.columns(2)
    with col1:
        tipo_texto = st.selectbox("Tipo de texto", [
            "General/No especificado",
            "Académico",
            "Profesional/Laboral",
            "Informal/Cotidiano",
            "Creativo/Literario"
        ])
    
    with col2:
        contexto_cultural = st.selectbox("Contexto cultural", [
            "General/Internacional",
            "España",
            "Latinoamérica",
            "Contexto académico",
            "Contexto empresarial"
        ])
    
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    info_adicional = st.text_area("Información adicional o contexto (opcional):", height=100)
    
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
    with st.spinner("Analizando texto y generando corrección contextual..."):
        # Mapeo de niveles para instrucciones más específicas
        nivel_map = {
            "Nivel principiante (A1-A2)": {
                "descripcion": "principiante (A1-A2)",
                "enfoque": "Enfócate en estructuras básicas, vocabulario fundamental y errores comunes. Utiliza explicaciones simples y claras. Evita terminología lingüística compleja."
            },
            "Nivel intermedio (B1-B2)": {
                "descripcion": "intermedio (B1-B2)",
                "enfoque": "Puedes señalar errores más sutiles de concordancia, uso de tiempos verbales y preposiciones. Puedes usar alguna terminología lingüística básica en las explicaciones."
            },
            "Nivel avanzado (C1-C2)": {
                "descripcion": "avanzado (C1-C2)",
                "enfoque": "Céntrate en matices, coloquialismos, registro lingüístico y fluidez. Puedes usar terminología lingüística específica y dar explicaciones más detalladas y técnicas."
            }
        }
        
        nivel_info = nivel_map.get(nivel, nivel_map["Nivel intermedio (B1-B2)"])
        
        # Instrucciones para el modelo de IA con análisis contextual avanzado
        system_message = f"""
Eres Diego, un profesor experto en ELE (Español como Lengua Extranjera) especializado en análisis lingüístico contextual.
Tu objetivo es corregir textos adaptando tu feedback al nivel {nivel_info['descripcion']} del estudiante.
{nivel_info['enfoque']}

Cuando corrijas un texto, DEBES devolver la respuesta únicamente en un JSON válido, sin texto adicional, con la siguiente estructura EXACTA:

{{
  "saludo": "string",                // en {idioma}
  "tipo_texto": "string",            // en {idioma}
  "errores": {{
       "Gramática": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
           // más errores de Gramática (o [] si ninguno)
       ],
       "Léxico": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ],
       "Puntuación": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ],
       "Estructura textual": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ]
  }},
  "texto_corregido": "string",       // siempre en español
  "analisis_contextual": {{
       "coherencia": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "cohesion": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "registro_linguistico": {{
           "puntuacion": number,     // del 1 al 10
           "tipo_detectado": "string", // tipo de registro detectado en {idioma}
           "adecuacion": "string",   // evaluación de adecuación en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "adecuacion_cultural": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "elementos_destacables": [  // elementos culturales destacables en {idioma}
               "string",
               "string"
           ],
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }}
  }},
  "consejo_final": "string",         // en español
  "fin": "Fin de texto corregido."
}}

IMPORTANTE:
- Las explicaciones de los errores deben estar en {idioma}
- Todo el análisis contextual debe estar en {idioma}
- El texto corregido completo SIEMPRE debe estar en español, independientemente del idioma seleccionado
- El consejo final SIEMPRE debe estar en español
- Adapta tus explicaciones y sugerencias al nivel {nivel_info['descripcion']} del estudiante
- Considera el tipo de texto "{tipo_texto}" y el contexto cultural "{contexto_cultural}" en tu análisis

No devuelvas ningún texto extra fuera de este JSON.
"""
        # Mensaje para el usuario con contexto adicional
        user_message = f"""
Texto del alumno:
\"\"\"
{texto}
\"\"\"
Nivel: {nivel}
Nombre del alumno: {nombre}
Idioma de corrección: {idioma}
Tipo de texto: {tipo_texto}
Contexto cultural: {contexto_cultural}
{f"Información adicional: {info_adicional}" if info_adicional else ""}
"""

        try:
            raw_output, data_json = obtener_json_de_ia(system_message, user_message, max_retries=3)

            # Extraer campos del JSON
            saludo = data_json.get("saludo", "")
            tipo_texto_detectado = data_json.get("tipo_texto", "")
            errores_obj = data_json.get("errores", {})
            texto_corregido = data_json.get("texto_corregido", "")
            analisis_contextual = data_json.get("analisis_contextual", {})
            consejo_final = data_json.get("consejo_final", "")
            fin = data_json.get("fin", "")

            # Extraer puntuaciones del análisis contextual
            coherencia = analisis_contextual.get("coherencia", {})
            cohesion = analisis_contextual.get("cohesion", {})
            registro = analisis_contextual.get("registro_linguistico", {})
            adecuacion = analisis_contextual.get("adecuacion_cultural", {})
            
            puntuacion_coherencia = coherencia.get("puntuacion", 0)
            puntuacion_cohesion = cohesion.get("puntuacion", 0)
            puntuacion_registro = registro.get("puntuacion", 0)
            puntuacion_adecuacion = adecuacion.get("puntuacion", 0)

            # --- MOSTRAR RESULTADOS EN LA INTERFAZ ---
            st.subheader("Saludo")
            st.write(saludo)
            
            st.subheader("Tipo de texto y justificación")
            st.write(tipo_texto_detectado)
            
            # Errores detectados
            st.subheader("Errores detectados")
            if not any(errores_obj.get(cat, []) for cat in ["Gramática", "Léxico", "Puntuación", "Estructura textual"]):
                st.success("¡Felicidades! No se han detectado errores significativos.")
            else:
                for categoria in ["Gramática", "Léxico", "Puntuación", "Estructura textual"]:
                    lista_errores = errores_obj.get(categoria, [])
                    if lista_errores:
                        with st.expander(f"**{categoria}** ({len(lista_errores)} errores)"):
                            for i, err in enumerate(lista_errores, 1):
                                st.markdown(f"**Error {i}:**")
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.error(f"❌ {err.get('fragmento_erroneo','')}")
                                with col2:
                                    st.success(f"✅ {err.get('correccion','')}")
                                st.info(f"💡 {err.get('explicacion','')}")
                                if i < len(lista_errores):
                                    st.divider()

            # Texto corregido
            st.subheader("Texto corregido completo")
            st.write(texto_corregido)
            
            # --- ANÁLISIS CONTEXTUAL ---
            st.header("Análisis contextual avanzado")
            
            # Crear columnas para las puntuaciones generales
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Coherencia", f"{puntuacion_coherencia}/10")
            with col2:
                st.metric("Cohesión", f"{puntuacion_cohesion}/10")
            with col3:
                st.metric("Registro", f"{puntuacion_registro}/10")
            with col4:
                st.metric("Adecuación cultural", f"{puntuacion_adecuacion}/10")
            
            # Gráfico sencillo para visualizar las puntuaciones
            puntuaciones = [puntuacion_coherencia, puntuacion_cohesion, puntuacion_registro, puntuacion_adecuacion]
            categorias = ["Coherencia", "Cohesión", "Registro", "Ad. Cultural"]
            
            # Calcular el promedio de las puntuaciones
            promedio_contextual = sum(puntuaciones) / len(puntuaciones) if puntuaciones else 0
            
            # Mostrar un progreso general
            st.markdown(f"##### Evaluación global: {promedio_contextual:.1f}/10")
            st.progress(promedio_contextual / 10)
            
            # Detalles de coherencia
            with st.expander("Coherencia textual", expanded=True):
                st.markdown(f"**Comentario**: {coherencia.get('comentario', '')}")
                st.markdown("**Sugerencias para mejorar:**")
                for sug in coherencia.get("sugerencias", []):
                    st.markdown(f"- {sug}")
            
            # Detalles de cohesión
            with st.expander("Cohesión textual", expanded=True):
                st.markdown(f"**Comentario**: {cohesion.get('comentario', '')}")
                st.markdown("**Sugerencias para mejorar:**")
                for sug in cohesion.get("sugerencias", []):
                    st.markdown(f"- {sug}")
            
            # Detalles de registro lingüístico
            with st.expander("Registro lingüístico", expanded=True):
                st.markdown(f"**Tipo de registro detectado**: {registro.get('tipo_detectado', '')}")
                st.markdown(f"**Adecuación al contexto**: {registro.get('adecuacion', '')}")
                st.markdown("**Sugerencias para mejorar:**")
                for sug in registro.get("sugerencias", []):
                    st.markdown(f"- {sug}")
            
            # Detalles de adecuación cultural
            with st.expander("Adecuación cultural y pragmática", expanded=True):
                st.markdown(f"**Comentario**: {adecuacion.get('comentario', '')}")
                if adecuacion.get("elementos_destacables", []):
                    st.markdown("**Elementos culturales destacables:**")
                    for elem in adecuacion.get("elementos_destacables", []):
                        st.markdown(f"- {elem}")
                st.markdown("**Sugerencias para mejorar:**")
                for sug in adecuacion.get("sugerencias", []):
                    st.markdown(f"- {sug}")

            # Consejo final
            st.subheader("Consejo final")
            st.info(consejo_final)
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
                    puntuacion_coherencia,
                    puntuacion_cohesion,
                    puntuacion_registro,
                    puntuacion_adecuacion,
                    consejo_final
                ]
                
                # Intenta aprovechar la variable tracking_sheet que definimos al inicio
                try:
                    tracking_sheet.append_row(datos_seguimiento)
                    st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento.")
                except NameError:
                    # Si tracking_sheet no está definido, intentamos recuperarlo
                    tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
                    try:
                        tracking_sheet = tracking_doc.worksheet("Seguimiento")
                    except gspread.exceptions.WorksheetNotFound:
                        tracking_sheet = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=14)
                        headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                                "Errores Puntuación", "Errores Estructura", "Total Errores", 
                                "Puntuación Coherencia", "Puntuación Cohesión", "Puntuación Registro", 
                                "Puntuación Adecuación Cultural", "Consejo Final"]
                        tracking_sheet.append_row(headers)
                    
                    tracking_sheet.append_row(datos_seguimiento)
                    st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento (recuperada).")
            except Exception as e:
                st.error(f"❌ Error al guardar estadísticas en Seguimiento: {str(e)}")
                st.info("Detalles del error para depuración:")
                st.code(str(e))

            # --- GENERAR AUDIO CON ELEVENLABS (Consejo final en español) ---
            st.markdown("**🔊 Consejo leído en voz alta:**")
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
                f"Tipo de texto:\n{tipo_texto_detectado}\n\n"
                f"Errores:\n{json.dumps(errores_obj, indent=2, ensure_ascii=False)}\n\n"
                f"Texto corregido:\n{texto_corregido}\n\n"
                f"Análisis contextual:\n{json.dumps(analisis_contextual, indent=2, ensure_ascii=False)}\n\n"
                f"Consejo final:\n{consejo_final}\n\n"
                f"{fin}"
            )
            txt_buffer = BytesIO()
            txt_buffer.write(feedback_txt.encode("utf-8"))
            txt_buffer.seek(0)
            st.download_button(
                label="📝 Descargar corrección completa en TXT",
                data=txt_buffer,
                file_name=f"correccion_{nombre}.txt",
                mime="text/plain"
            )

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
            import traceback
            st.code(traceback.format_exc())
