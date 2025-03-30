# Este script requiere un entorno con acceso a las bibliotecas necesarias.
# Asegúrate de ejecutarlo localmente o en un entorno de Streamlit compatible.

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
st.title("📝 Textocorrector ELE")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback.")

with st.form("formulario"):
    nombre = st.text_input("¿Cómo te llamas?")
    nivel = st.selectbox("¿Cuál es tu nivel?", [
        "Nivel principiante (A1-A2)",
        "Nivel intermedio (B1-B2)",
        "Nivel avanzado (C1-C2)"
    ])
    idioma = st.selectbox("Idioma de las explicaciones de errores (no afecta el texto corregido en español)", ["Español", "Francés", "Inglés"])
    texto = st.text_area("Escribe tu texto para corregirlo:", height=250)
    enviar = st.form_submit_button("Corregir")

# --- Traducciones de encabezados ---
encabezados = {
    "Español": {
        "saludo": "Saludo",
        "tipo_texto": "Tipo de texto y justificación",
        "errores": "Errores detectados",
        "texto_corregido": "Texto corregido",
        "fragmento": "Fragmento erróneo",
        "correccion": "Corrección",
        "explicacion": "Explicación",
        "sin_errores": "Sin errores en esta categoría.",
        "consejo_final": "Consejo final"
    },
    "Francés": {
        "saludo": "Salutation",
        "tipo_texto": "Type de texte et justification",
        "errores": "Erreurs détectées",
        "texto_corregido": "Texte corrigé",
        "fragmento": "Fragment erroné",
        "correccion": "Correction",
        "explicacion": "Explication",
        "sin_errores": "Pas d'erreurs dans cette catégorie.",
        "consejo_final": "Conseil final"
    },
    "Inglés": {
        "saludo": "Greeting",
        "tipo_texto": "Text type and justification",
        "errores": "Detected errors",
        "texto_corregido": "Corrected text",
        "fragmento": "Error fragment",
        "correccion": "Correction",
        "explicacion": "Explanation",
        "sin_errores": "No errors in this category.",
        "consejo_final": "Final advice"
    }
}

# --- 4. CORREGIR TEXTO CON IA ---
if enviar and nombre and texto:
    with st.spinner("Corrigiendo con IA…"):

        traducciones = encabezados[idioma]
        encabezados_es = encabezados["Español"]

        prompt = f'''
Estás corrigiendo un texto de un estudiante de Español como Lengua Extranjera (ELE).

Datos del alumno:
- Nombre: {nombre}
- Nivel aproximado: {nivel}
- Idioma preferido para las explicaciones: {idioma}

IMPORTANTE:
La sección **Texto corregido completo** debe estar **siempre redactada en español**, independientemente del idioma del texto original o del idioma elegido para las explicaciones. Esta sección representa una **propuesta de texto ideal**, corregido y mejorado a partir del texto del alumno, con un nivel adecuado a su competencia lingüística.

Texto a corregir:
\"\"\"
{texto}
\"\"\"

Corrige este texto siguiendo estas indicaciones:

1. **Saluda al alumno por su nombre** y motívalo con un tono cálido.
2. **Indica el tipo de texto** y justifica brevemente.
3. **Detecta y clasifica los errores** en: gramática, léxico, puntuación y estructura textual.
   - Muestra el fragmento erróneo entre comillas.
   - Propón una corrección.
   - Explica de forma clara y adaptada al nivel del alumno.
4. **Reescribe el texto completo corregido** (en español) con un nivel adecuado, respetando el estilo original del alumno.
5. **Finaliza con un consejo personalizado y alentador** que incluya una fortaleza y una sugerencia de mejora.
6. **Termina con la frase obligatoria**: "Fin de texto corregido."
'''


        client = OpenAI(api_key=openai_api_key)

        response = client.chat.completions.create(
            model="gpt-4-turbo",
            temperature=0.5,
            messages=[
                {
                  "role": "system",
"content": f"""
Eres Diego, un profesor experto en la enseñanza de Español como Lengua Extranjera (ELE), con formación filológica y gran sensibilidad pedagógica. Corriges textos de estudiantes con un enfoque didáctico, afectivo y estructurado.

🚨 INSTRUCCIONES CRÍTICAS:

El campo **"texto_corregido"** debe estar **siempre redactado en español**, sin excepción. No importa si el texto original está en otro idioma o si el alumno ha elegido otro idioma para las explicaciones.

➡️ Si generas el texto corregido en otro idioma, se considerará un **error grave**. Repite: **"texto_corregido"** es una **propuesta ideal** del texto del alumno, **corregida y mejorada en español**, adaptada a su nivel de ELE.

✅ Solo el campo **"explicacion"** dentro de cada error puede estar en el idioma solicitado por el usuario: **{idioma}**.  
Los fragmentos erróneos y las correcciones deben estar siempre en español.

📦 Estructura obligatoria de salida en formato JSON:
```json
{{
  "saludo": "...",
  "tipo_texto": "...",
  "errores": [
    {{
      "categoria": "gramática | léxico | puntuación | estructura textual",
      "fragmento": "...",
      "correccion": "...",
      "explicacion": "..."  // En {idioma}
    }},
    ...
  ],
  "texto_corregido": "...",  // SIEMPRE en español
  "consejo_final": "...",     // En español
  "fin": "Fin de texto corregido."
}}


        correccion = response.choices[0].message.content

        st.subheader(f"📘 {traducciones['errores']}")
        st.markdown(correccion)

        st.subheader(encabezados_es['texto_corregido'])

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
