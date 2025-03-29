import streamlit as st
import json
import gspread
import requests
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO
from reportlab.pdfgen import canvas

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

        prompt = f"""
Actúa como un profesor de español como lengua extranjera (ELE), experto y empático. Corrige el siguiente texto según estos criterios:

1. Clasificación de errores:
   - Gramática
   - Léxico
   - Puntuación
   - Estructura textual

2. Explicaciones claras y breves por cada error.

3. Versión corregida del texto (respetando el estilo del alumno).

4. Consejo final personalizado para el alumno llamado {nombre}.

Texto original:
"""{texto}"""
"""

        try:
            client = OpenAI(api_key=openai_api_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                temperature=0.5,
                messages=[
                    {"role": "system", "content": "Eres Diego, un profesor experto en ELE. Corrige textos de estudiantes entre A2 y C1. Señala errores, explica brevemente por qué, reescribe el texto corregido y da un consejo personalizado final."},
                    {"role": "user", "content": prompt}
                ]
            )

            correccion = response.choices[0].message.content

            # Mostrar resultado
            st.subheader("📘 Corrección")
            st.markdown(correccion)

            # Guardar en Google Sheets
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([nombre, fecha, texto, correccion])

            st.success("✅ Corrección guardada en Google Sheets.")

            # Reproducir consejo final con voz clonada
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

            # Generar PDF con estructura por secciones
            errores = ""
            version_corregida = ""
            consejo_final = ""

            if "Versión corregida:" in correccion:
                partes = correccion.split("Versión corregida:", 1)
                errores = partes[0].strip()
                resto = partes[1]
                if "Consejo final:" in resto:
                    version_corregida, consejo_final = resto.split("Consejo final:", 1)
                else:
                    version_corregida = resto
            else:
                errores = correccion

            pdf_buffer = BytesIO()
            pdf = canvas.Canvas(pdf_buffer)
            y = 800
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(50, y, f"Corrección para: {nombre}")

            def add_section(title, content):
                nonlocal y
                y -= 30
                pdf.setFont("Helvetica-Bold", 12)
                pdf.drawString(50, y, title)
                y -= 20
                pdf.setFont("Helvetica", 10)
                for line in content.strip().splitlines():
                    if y < 50:
                        pdf.showPage()
                        y = 800
                    pdf.drawString(50, y, line[:100])
                    y -= 15

            add_section("Errores detectados", errores)
            add_section("Versión corregida", version_corregida)
            add_section("Consejo final", consejo_final)

            pdf.save()
            pdf_buffer.seek(0)
            st.download_button("📄 Descargar corrección en PDF", data=pdf_buffer, file_name=f"correccion_{nombre}.pdf")

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")

