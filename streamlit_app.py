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
    nivel = st.selectbox("¿Cuál es tu nivel?", [
        "Nivel principiante (A1-A2)",
        "Nivel intermedio (B1-B2)",
        "Nivel avanzado (C1-C2)"
    ])
    idioma = st.selectbox(
        "Selecciona lenguaje para la corrección",
        ["Español", "Francés", "Inglés"]
    )
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# --- 4. CORREGIR TEXTO CON IA ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):

        system_message = f"""
Eres Diego, un profesor experto en ELE. 
Sigue siempre esta estructura:
1. Saludo personalizado
2. Tipo de texto y justificación
3. Errores detectados (Gramática, Léxico, Puntuación, Estructura textual)
4. Texto corregido completo (en español, si así se indica)
5. Consejo final (en español) iniciando con "Consejo final:"
6. Cierre técnico con "Fin de texto corregido."
        
- El usuario selecciona el idioma para la corrección y errores detectados: {idioma}.
- El consejo final siempre en español.
- No añadas contenido adicional.
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
            client = OpenAI(api_key=openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4",
                temperature=0.5,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )

            correccion_original = response.choices[0].message.content

            # 1) Extraemos el consejo del texto original para el audio.
            match = re.search(r"(?i)Consejo final:\s*(.*?)\s*(?:Fin de texto corregido|$)", correccion_original, re.DOTALL)
            if match:
                consejo = match.group(1).strip()
            else:
                consejo = "No se encontró un consejo final claro en la corrección."

            # 2) Evitamos que la voz lea la frase "Consejo final:"
            #    (por si el modelo la repitiera dentro del texto capturado).
            consejo = re.sub(r"(?i)consejo final:\s*", "", consejo).strip()

            # 3) Limpiamos el texto mostrado para no incluir la línea "6. Cierre técnico"
            #    pero conservamos "Fin de texto corregido."
            correccion_limpia = re.sub(
                r"(?im)^\s*\d+\.\s*Cierre técnico.*$", 
                "", 
                correccion_original
            ).strip()

            # Mostramos la corrección limpia (sin la línea 6. Cierre técnico).
            st.subheader("📘 Corrección")
            st.markdown(correccion_limpia)

            # Registramos todo (con la línea 6 incluida) en Google Sheets,
            # o si prefieres, registra la versión limpia.
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([nombre, nivel, idioma, fecha, texto, correccion_original])
            st.success("✅ Corrección guardada en Google Sheets.")

            # --- AUDIO CON ELEVENLABS ---
            st.markdown("**🔊 Consejo leído en voz alta (en español):**")
            with st.spinner("Generando audio con ElevenLabs..."):
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                headers = {
                    "xi-api-key": elevenlabs_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "text": consejo,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.3,
                        "similarity_boost": 0.9
                    }
                }
                response_audio = requests.post(url, headers=headers, json=data)
                if response_audio.ok:
                    audio_bytes = BytesIO(response_audio.content)
                    st.audio(audio_bytes, format="audio/mpeg")
                else:
                    st.warning(f"⚠️ No se pudo reproducir el consejo con ElevenLabs. (Status code: {response_audio.status_code})")

            # --- DESCARGA EN TXT ---
            feedback_txt = f"Texto original:\n{texto}\n\n{correccion_limpia}"
            txt_buffer = BytesIO()
            txt_buffer.write(feedback_txt.encode("utf-8"))
            txt_buffer.seek(0)

            st.download_button(
                "📝 Descargar corrección en TXT",
                data=txt_buffer,
                file_name=f"correccion_{nombre}.txt",
                mime="text/plain"
            )

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
