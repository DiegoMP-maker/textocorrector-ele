import streamlit as st
import json
import gspread
import requests
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

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
Actúa como un profesor de español como lengua extranjera (ELE), experto y empático. Analiza primero el tipo de texto (por ejemplo: carta formal, correo informal, opinión, narrativa, etc.) y menciónalo al inicio.

Después, corrige el texto según estos criterios:

1. Clasificación de errores:
   - Gramática
   - Léxico
   - Puntuación
   - Estructura textual

2. Explicaciones claras y breves por cada error.

3. Versión corregida del texto (respetando el estilo del alumno y adecuado al tipo textual detectado).

4. Consejo final personalizado para el alumno llamado {nombre}.

Además, aplica criterios específicos de corrección según el tipo de texto detectado. Por ejemplo:
- En una carta formal: fórmulas de saludo y despedida, registro formal, estructuras convencionales.
- En un correo informal: tono cercano, naturalidad, expresividad.
- En textos argumentativos: uso de conectores, claridad de ideas, estructura de tesis-argumentos.

Texto original:
{texto}
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

            # PDF bien formateado con márgenes
            pdf_buffer = BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=A4,
                                    rightMargin=50, leftMargin=50,
                                    topMargin=50, bottomMargin=50)

            styles = getSampleStyleSheet()
            story = []

            def add_section(title, content):
                story.append(Paragraph(f"<b>{title}</b>", styles["Heading4"]))
                story.append(Spacer(1, 6))
                for line in content.strip().splitlines():
                    story.append(Paragraph(line, styles["BodyText"]))
                    story.append(Spacer(1, 4))
                story.append(Spacer(1, 12))

            story.append(Paragraph(f"Corrección para: <b>{nombre}</b>", styles["Title"]))
            story.append(Spacer(1, 20))
            if tipo_texto:
                add_section("Tipo de texto", tipo_texto)
            add_section("Errores detectados", errores)
            add_section("Versión corregida", version_corregida)
            add_section("Consejo final", consejo_final)

            doc.build(story)
            pdf_buffer.seek(0)
            st.download_button("📄 Descargar corrección en PDF", data=pdf_buffer, file_name=f"correccion_{nombre}.pdf")

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
