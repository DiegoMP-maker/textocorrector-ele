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

def obtener_json_de_ia(system_msg, user_msg, max_retries=2):
    """
    Llama a la API de OpenAI hasta max_retries veces,
    intentando parsear la respuesta como JSON.
    Si no se obtiene un JSON válido, envía un mensaje
    correctivo y reintenta.
    Devuelve (raw_output, data_json) si tiene éxito,
    o lanza excepción si no logra parsear.
    """
    client = OpenAI(api_key=openai_api_key)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    for intento in range(max_retries):
        response = client.chat.completions.create(
            model="gpt-4",
            temperature=0.5,
            messages=messages
        )
        raw_output = response.choices[0].message.content

        # 1. Intentar parsear como JSON
        data_json = None
        try:
            data_json = json.loads(raw_output)
        except json.JSONDecodeError:
            # 2. Si falla, buscar un bloque con llaves
            match_json = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if match_json:
                json_str = match_json.group(0)
                try:
                    data_json = json.loads(json_str)
                except json.JSONDecodeError:
                    data_json = None

        if data_json is not None:
            return raw_output, data_json
        else:
            # Añadir mensaje correctivo y reintentar
            correction_message = {
                "role": "system",
                "content": (
                    "Tu respuesta anterior no cumplió el formato JSON requerido. "
                    "Por favor, responde ÚNICAMENTE en JSON válido con la estructura solicitada. "
                    "No incluyas texto extra."
                )
            }
            messages.append(correction_message)

    raise ValueError("No se pudo obtener un JSON válido tras varios reintentos.")

# --- 4. CORREGIR TEXTO CON IA Y JSON ESTRUCTURADO ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):
        system_message = """
Eres Diego, un profesor experto en ELE. 
Cuando corrijas un texto, DEBES devolver la respuesta únicamente en un JSON válido, sin texto adicional, con la siguiente estructura EXACTA:

{
  "saludo": "string",
  "tipo_texto": "string",
  "errores": [
    {
      "categoria": "Gramática" | "Léxico" | "Puntuación" | "Estructura textual",
      "fragmento_erroneo": "string",
      "correccion": "string",
      "explicacion": "string"
    }
  ],
  "texto_corregido": "string",
  "consejo_final": "string",
  "fin": "Fin de texto corregido."
}

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
"""

        try:
            raw_output, data_json = obtener_json_de_ia(system_message, user_message, max_retries=2)

            # Extraer campos del JSON
            saludo = data_json.get("saludo", "")
            tipo_texto = data_json.get("tipo_texto", "")
            errores = data_json.get("errores", [])
            texto_corregido = data_json.get("texto_corregido", "")
            consejo_final = data_json.get("consejo_final", "")
            fin = data_json.get("fin", "")

            # MOSTRAR RESULTADOS
            st.subheader("Saludo")
            st.write(saludo)
            st.subheader("Tipo de texto y justificación")
            st.write(tipo_texto)
            st.subheader("Errores detectados")
            if not errores:
                st.write("No se han detectado errores.")
            else:
                for err in errores:
                    st.markdown(f"**Categoría:** {err.get('categoria','')}")
                    st.write(f"- Fragmento erróneo: {err.get('fragmento_erroneo','')}")
                    st.write(f"- Corrección: {err.get('correccion','')}")
                    st.write(f"- Explicación: {err.get('explicacion','')}")
                    st.write("---")

            st.subheader("Texto corregido completo (en español)")
            st.write(texto_corregido)

            st.subheader("Consejo final (en español)")
            st.write(consejo_final)
            st.write(fin)

            # GUARDAR EN HISTORIAL
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            corrections_sheet.append_row([nombre, nivel, idioma, fecha, texto, raw_output])
            st.success("✅ Corrección guardada en Historial_Correcciones_ELE.")

            # CONTEO DE ERRORES
            num_gramatica = sum(1 for e in errores if e.get("categoria", "").strip() == "Gramática")
            num_lexico = sum(1 for e in errores if e.get("categoria", "").strip() == "Léxico")
            num_puntuacion = sum(1 for e in errores if e.get("categoria", "").strip() == "Puntuación")
            num_estructura = sum(1 for e in errores if e.get("categoria", "").strip() == "Estructura textual")
            total_errores = len(errores)

            # GUARDAR SEGUIMIENTO
            try:
                tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
                hojas = [hoja.title for hoja in tracking_doc.worksheets()]
                st.info(f"Hojas disponibles en el documento Seguimiento: {hojas}")

                try:
                    hoja_seguimiento = tracking_doc.worksheet("Seguimiento")
                except gspread.exceptions.WorksheetNotFound:
                    hoja_seguimiento = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=10)
                    st.info("Hoja 'Seguimiento' creada automáticamente.")

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
                hoja_seguimiento.append_row(datos_seguimiento)
                st.info(f"Guardado seguimiento: {datos_seguimiento}")

            except Exception as e:
                st.warning(f"⚠️ No se pudo guardar el seguimiento del alumno: {e}")

            # GENERAR AUDIO
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
                response_audio = requests.post(tts_url, headers=headers, json=data)
                if response_audio.ok:
                    audio_bytes = BytesIO(response_audio.content)
                    st.audio(audio_bytes, format="audio/mpeg")
                else:
                    st.warning(f"⚠️ No se pudo reproducir el consejo con ElevenLabs. (Status code: {response_audio.status_code})")

            # DESCARGA EN TXT
            feedback_txt = (
                f"Texto original:\n{texto}\n\n"
                f"Saludo:\n{saludo}\n\n"
                f"Tipo de texto:\n{tipo_texto}\n\n"
                f"Errores:\n{json.dumps(errores, indent=2)}\n\n"
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
