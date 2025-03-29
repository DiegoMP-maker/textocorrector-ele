import streamlit as st
import json
import gspread
import requests
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

try:
    sheet = client_gsheets.open_by_key("1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8").sheet1
    st.success("✅ Conectado a Google Sheets correctamente.")
except Exception as e:
    st.error("❌ Error al conectar con Google Sheets. Revisa los permisos o el ID del documento.")
    st.stop()

# --- 3. INTERFAZ ---
st.title("📝 Textocorrector ELE (por Diego)")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback.")

with st.form("formulario"):
    nombre = st.text_input("¿Cómo te llamas?")
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# --- 4. CORREGIR TEXTO CON IA ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):

        prompt = f'''
Eres un profesor de español como lengua extranjera (ELE), experto y empático. Tu tarea es CORREGIR textos escritos por estudiantes entre A2 y C1, con el siguiente enfoque:

1. Indica claramente el TIPO DE TEXTO (carta formal, mensaje informal, correo profesional, narración, descripción, etc.) y justifica brevemente por qué.
2. Clasifica los errores en secciones: Gramática, Léxico, Puntuación, Estructura textual. Dentro de cada sección, presenta:
   - El fragmento erróneo entre comillas.
   - La corrección correspondiente.
   - Una explicación breve.
3. Reescribe el texto corregido adaptando el registro al tipo textual.
4. Da un consejo final personalizado y empático para el alumno llamado {nombre}.

Texto del alumno:
"""
{texto}
"""
'''

        try:
            client = OpenAI(api_key=openai_api_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                temperature=0.5,
                messages=[
                    {"role": "system", "content": "Corrige textos como profesor ELE experto. Identifica el tipo textual con justificación, explica errores con ejemplo/corrección/explicación, reescribe con el registro adecuado y da un consejo personalizado."},
                    {"role": "user", "content": prompt}
                ]
            )

            correccion = response.choices[0].message.content

            st.subheader("📘 Corrección")
            st.markdown(correccion)

            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([nombre, fecha, texto, correccion])

            st.success("✅ Corrección guardada en Google Sheets.")

            if "Consejo final:" in correccion:
                consejo = correccion.split("Consejo final:", 1)[-1].strip()
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                headers = {
                    "xi-api-key": elevenlabs_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "text": consejo,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.8
                    }
                }
                response_audio = requests.post(url, headers=headers, json=data)
                if response_audio.ok:
                    with open("consejo_final.mp3", "wb") as f:
                        f.write(response_audio.content)
                    st.audio("consejo_final.mp3")
                else:
                    st.warning("No se pudo reproducir el consejo con ElevenLabs.")

            feedback_txt = f"Texto original:\n{texto}\n\n{correccion}"
            txt_buffer = BytesIO()
            txt_buffer.write(feedback_txt.encode("utf-8"))
            txt_buffer.seek(0)

            st.download_button("📄 Descargar corrección en TXT", data=txt_buffer, file_name=f"correccion_{nombre}.txt", mime="text/plain")

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
