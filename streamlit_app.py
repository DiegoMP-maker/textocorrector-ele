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
        
        # Instrucciones para el modelo:
        # - Produce el saludo, el análisis, la detección de errores y demás secciones en el idioma seleccionado (si es francés o inglés).
        # - Sin embargo, la sección "Texto corregido completo:" se debe dejar en español, sin traducir.
        # - El "Consejo final:" también se debe producir en español.
        system_message = f"""
Eres Diego, profesor experto en ELE, con formación filológica y gran sensibilidad pedagógica.

INSTRUCCIONES:
- El alumno ha seleccionado el idioma de corrección: {idioma}.
- Produce las secciones **Saludo personalizado**, **Tipo de texto y justificación** y **Errores detectados** (con sus categorías) en {idioma}.
- Para la sección **Texto corregido completo:**, DEJA el texto en español sin traducir.
- El **Consejo final:** debe escribirse en español.
- Finaliza siempre con la frase "Fin de texto corregido."
    
Estructura de salida obligatoria:
1. **Saludo personalizado** (en {idioma}).
2. **Tipo de texto y justificación** (en {idioma}).
3. **Errores detectados** (en {idioma}) – agrupa en:
   - Gramática
   - Léxico
   - Puntuación
   - Estructura textual
   Para cada error: muestra el fragmento erróneo, la corrección propuesta y una breve explicación.
4. **Texto corregido completo:** [Deja esta sección en español, sin traducir]
5. **Consejo final:** (en español), que comience con "Consejo final:" y que sea breve, personal y motivador.
6. **Cierre técnico:** La salida debe terminar con "Fin de texto corregido."
No añadas explicaciones fuera de estas secciones.
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
                model="gpt-4",  # O usa "gpt-3.5-turbo" según tu suscripción
                temperature=0.5,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )

            correccion = response.choices[0].message.content

            st.subheader("📘 Corrección")
            st.markdown(correccion)

            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([nombre, nivel, idioma, fecha, texto, correccion])
            st.success("✅ Corrección guardada en Google Sheets.")

            # --- EXTRAER CONSEJO FINAL ---
            match = re.search(r"(?i)Consejo final:\s*(.*?)\s*(?:Fin de texto corregido|$)", correccion, re.DOTALL)
            if match:
                consejo = match.group(1).strip()
            else:
                consejo = "No se encontró un consejo final claro en la corrección."
                st.info("ℹ️ No se encontró el consejo final en el texto corregido; se usará un mensaje alternativo.")

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

        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")
