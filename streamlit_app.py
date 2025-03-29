import streamlit as st
import json
import gspread
import requests
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO
from docx import Document
from docx.shared import Pt, Inches

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
Eres un profesor de español como lengua extranjera (ELE), experto y empático. Tu tarea es CORREGIR textos escritos por estudiantes entre A2 y C1, con el siguiente enfoque:

1. **Identifica y nombra el tipo de texto** (carta formal, correo informal, narración, etc.). Debes empezar siempre con esto.
2. **Detecta y clasifica los errores** en:
   - Gramática
   - Léxico
   - Puntuación
   - Estructura textual
   Añade explicaciones breves y claras.
3. **Reescribe el texto corregido** de forma adecuada al tipo textual, sin cambiar el estilo del alumno.
4. **Da un consejo final personalizado y positivo al alumno llamado {nombre}**.

**Texto del alumno**:
"""{texto}"""
"""

        try:
            client = OpenAI(api_key=openai_api_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                temperature=0.5,
                messages=[
                    {"role": "system", "content": "Corrige textos como profesor ELE experto. Identifica el tipo textual, explica errores, reescribe y da un consejo personalizado."},
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

            doc = Document()
            sections = doc.sections
            for section in sections:
                section.top_margin = Inches(1)
                section.bottom_margin = Inches(1)
                section.left_margin = Inches(1)
                section.right_margin = Inches(1)

            def add_paragraph(title, content):
                doc.add_heading(title, level=2)
                for line in content.strip().splitlines():
                    if line.strip():
                        p = doc.add_paragraph(line.strip())
                        p.style.font.size = Pt(11)

            doc.add_heading(f"Corrección para: {nombre}", 0)
            doc.add_heading("Texto original", level=2)
            for line in texto.strip().splitlines():
                if line.strip():
                    p = doc.add_paragraph(line.strip())
                    p.style.font.size = Pt(11)
            if tipo_texto:
                add_paragraph("Tipo de texto", tipo_texto)
            add_paragraph("Errores detectados", errores)
            add_paragraph("Versión corregida", version_corregida)
            add_paragraph("Consejo final", consejo_final)

            word_buffer = BytesIO()
            doc.save(word_buffer)
            word_buffer.seek(0)

            st.download_button("📄 Descargar corrección en Word", data=word_buffer, file_name=f"correccion_{nombre}.docx")

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
