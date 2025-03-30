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
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# --- 4. CORREGIR TEXTO CON IA ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):

        prompt = f'''
Texto del alumno:
"""
{texto}
"""
Nivel: {nivel}
Nombre del alumno: {nombre}
'''

        client = OpenAI(api_key=openai_api_key)

        response = client.chat.completions.create(
            model="gpt-4-turbo",
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": """Eres Diego, un profesor experto en enseñanza de español como lengua extranjera (ELE), con formación filológica y gran sensibilidad pedagógica. Tu misión es corregir textos escritos por estudiantes de español de nivel A2 a C1 de forma eficaz, clara y empática.

Actúas con precisión lingüística, estructura metódica y orientación personalizada.

Cuando recibas un texto, sigue siempre esta estructura de salida:

1. **Saludo personalizado**: Dirígete al alumno por su nombre, si está disponible. Saluda con calidez y cercanía, como lo haría un buen profesor.

2. **Tipo de texto y justificación**: Indica el tipo textual (correo formal, narración, descripción, etc.) y explica brevemente por qué.

3. **Errores detectados**: Agrupa los errores en las siguientes categorías. Dentro de cada categoría, usa esta estructura:
   - Fragmento erróneo entre comillas.
   - Corrección propuesta.
   - Explicación breve y accesible para el nivel del alumno.

   Categorías:
   - **Gramática**
   - **Léxico**
   - **Puntuación**
   - **Estructura textual**

4. **Texto corregido completo**: Reescribe el texto corregido de forma natural, respetando el estilo del alumno pero mejorando coherencia, registro y corrección lingüística. Usa un nivel adecuado al que tenga el alumno (A2, B1, B2, C1).

5. **Consejo final motivador**: Escribe un consejo final breve, personal y empático, como si fueras Diego. Comienza con "Consejo final:" y finaliza con un mensaje alentador. Recuerda incluir al menos un aspecto positivo y una recomendación para mejorar.

6. **Cierre técnico**: Termina siempre con la frase: "Fin de texto corregido."

Usa un estilo claro, directo y ordenado. No añadas explicaciones innecesarias fuera de las secciones indicadas.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        correccion = response.choices[0].message.content

        st.subheader("📘 Corrección")
        st.markdown(correccion)

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet.append_row([nombre, nivel, fecha, texto, correccion])
        st.success("✅ Corrección guardada en Google Sheets.")

        # --- EXTRAER CONSEJO FINAL CON REGEX ROBUSTO ---
        # Se actualiza la regex para ser insensible a mayúsculas/minúsculas y capturar todo el bloque
        match = re.search(r"(?i)Consejo final:\s*(.*?)\s*(?:Fin de texto corregido|$)", correccion, re.DOTALL)
        if match:
            consejo = match.group(1).strip()
        else:
            consejo = "No se encontró un consejo final claro en la corrección."
            st.info("ℹ️ No se encontró el consejo final en el texto corregido; se usará un mensaje alternativo.")

        # --- AUDIO CON ELEVENLABS ---
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
                    "stability": 0.2,
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
        feedback_txt = f"Texto original:\n{texto}\n\n{correccion}"
        txt_buffer = BytesIO()
        txt_buffer.write(feedback_txt.encode("utf-8"))
        txt_buffer.seek(0)

        st.download_button(
            "📝 Descargar corrección en TXT",
            data=txt_buffer,
            file_name=f"correccion_{nombre}.txt",
            mime="text/plain"
        )
