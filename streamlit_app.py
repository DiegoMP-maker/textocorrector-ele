import streamlit as st
import json
import gspread
import requests
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

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

            tipo_texto = ""
            errores = ""
            version_corregida = ""
            consejo_final = ""

            if "Versión corregida:" in correccion:
                partes = correccion.split("Versión corregida:", 1)
                encabezado_y_errores = partes[0].strip()
                resto = partes[1]
                if "Consejo final:" in resto:
                    version_corregida, consejo_final = resto.split("Consejo final:", 1)
                else:
                    version_corregida = resto

                if "Tipo de texto:" in encabezado_y_errores:
                    tipo_texto, errores = encabezado_y_errores.split("Tipo de texto:", 1)
                    tipo_texto = "Tipo de texto:" + tipo_texto.strip()
                    errores = errores.strip()
                else:
                    errores = encabezado_y_errores
            else:
                errores = correccion

            pdf_buffer = BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            width, height = A4

            margin = inch
            x = margin
            y = height - margin

            def draw_text_block(title, content):
                nonlocal y
                c.setFont("Helvetica-Bold", 14)
                c.drawString(x, y, title)
                y -= 18
                c.setFont("Helvetica", 11)
                for line in content.strip().splitlines():
                    for subline in [line[i:i+100] for i in range(0, len(line), 100)]:
                        if y < margin:
                            c.showPage()
                            y = height - margin
                        c.drawString(x, y, subline)
                        y -= 14
                y -= 10

            c.setFont("Helvetica-Bold", 16)
            c.drawString(x, y, f"Corrección para: {nombre}")
            y -= 24

            draw_text_block("Texto original", texto)
            if tipo_texto:
                draw_text_block("Tipo de texto", tipo_texto)
            draw_text_block("Errores detectados", errores)
            draw_text_block("Versión corregida", version_corregida)
            draw_text_block("Consejo final", consejo_final)

            c.save()
            pdf_buffer.seek(0)

            st.download_button("📄 Descargar corrección en PDF", data=pdf_buffer, file_name=f"correccion_{nombre}.pdf")

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
