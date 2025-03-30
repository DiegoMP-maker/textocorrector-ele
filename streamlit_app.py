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
    idioma = st.selectbox("Selecciona lenguaje para la corrección", ["Español", "Francés", "Inglés"])
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# --- Traducciones de encabezados ---
encabezados = {
    "Español": {
        "saludo": "Saludo",
        "tipo_texto": "Tipo de texto y justificación",
        "errores": "Errores detectados",
        "texto_corregido": "Texto corregido en español (propuesta ideal)",
        "consejo_final": "Consejo final (en español)",
        "fragmento": "Fragmento erróneo",
        "correccion": "Corrección",
        "explicacion": "Explicación",
        "sin_errores": "Sin errores en esta categoría."
    },
    "Francés": {
        "saludo": "Salutation",
        "tipo_texto": "Type de texte et justification",
        "errores": "Erreurs détectées",
        "texto_corregido": "Texte corrigé en espagnol (proposition idéale)",
        "consejo_final": "Conseil final (en espagnol)",
        "fragmento": "Fragment erroné",
        "correccion": "Correction",
        "explicacion": "Explication",
        "sin_errores": "Pas d'erreurs dans cette catégorie."
    },
    "Inglés": {
        "saludo": "Greeting",
        "tipo_texto": "Text type and justification",
        "errores": "Detected errors",
        "texto_corregido": "Corrected text in Spanish (ideal proposal)",
        "consejo_final": "Final advice (in Spanish)",
        "fragmento": "Error fragment",
        "correccion": "Correction",
        "explicacion": "Explanation",
        "sin_errores": "No errors in this category."
    }
}

# --- 4. CORREGIR TEXTO CON IA ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):

        traducciones = encabezados[idioma]

        prompt = f'''
Texto del alumno:
"""
{texto}
"""
Nivel: {nivel}
Nombre del alumno: {nombre}
Idioma de corrección: {idioma}
'''

        client = OpenAI(api_key=openai_api_key)

        response = client.chat.completions.create(
            model="gpt-4-turbo",
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": f"""Eres Diego, un profesor experto en enseñanza de español como lengua extranjera (ELE), con formación filológica y gran sensibilidad pedagógica.
Corrige los textos escritos por estudiantes de ELE y responde con una estructura clara. IMPORTANTE: El campo 'texto_corregido' debe estar siempre redactado en ESPAÑOL, como modelo ideal del texto corregido.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        correccion = response.choices[0].message.content

        st.subheader(f"📘 {traducciones['errores']}")
        st.markdown(correccion)

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet.append_row([nombre, nivel, fecha, texto, correccion])
        st.success("✅ Corrección guardada en Google Sheets.")

        match = re.search(r"(?i)Consejo final:\s*(.*?)\s*(?:Fin de texto corregido|$)", correccion, re.DOTALL)
        consejo = match.group(1).strip() if match else "No se encontró un consejo final claro en la corrección."

        st.markdown("**🔊 Consejo leído en voz alta:**")
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
                    "stability": 0.5,
                    "similarity_boost": 0.8
                }
            }
            response_audio = requests.post(url, headers=headers, json=data)
            if response_audio.ok:
                audio_bytes = BytesIO(response_audio.content)
                st.audio(audio_bytes, format="audio/mpeg")
            else:
                st.warning(f"⚠️ No se pudo reproducir el consejo con ElevenLabs. (Status code: {response_audio.status_code})")

        feedback_txt = f"Texto original:\n{texto}\n\n{correccion}"
        txt_buffer = BytesIO()
        txt_buffer.write(feedback_txt.encode("utf-8"))
        txt_buffer.seek(0)

        download_label = {
            "Español": "📝 Descargar corrección en TXT",
            "Francés": "📝 Télécharger correction en TXT",
            "Inglés": "📝 Download correction in TXT"
        }[idioma]

        st.download_button(
            download_label,
            data=txt_buffer,
            file_name=f"correccion_{nombre}.txt",
            mime="text/plain"
        )
