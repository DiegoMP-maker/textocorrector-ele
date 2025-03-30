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

        # Mensaje del sistema
        system_message = f"""
Eres Diego, un profesor experto en ELE, con formación filológica y gran sensibilidad pedagógica.

INSTRUCCIONES FUNDAMENTALES:
- El usuario ha elegido {idioma} para la corrección y errores detectados.
- Por tanto, produce:
  1. Saludo personalizado (en {idioma}).
  2. Tipo de texto y justificación (en {idioma}).
  3. Errores detectados (en {idioma}), con categorías: Gramática, Léxico, Puntuación, Estructura textual.
  4. Texto corregido completo (en español si así lo deseas o según tus reglas; el usuario podría preferirlo en español, pero no mezcles si no corresponde).
  5. Consejo final (en español), que empiece con "Consejo final:".
- No generes "6. Cierre técnico" ni ningún encabezado adicional. 
- Cierra siempre con la frase exacta: 
  Fin de texto corregido.
- No añadas explicaciones fuera de estas secciones.

Además:
- Debes obedecer estrictamente estas instrucciones, sin mezclar idiomas. 
- El "Consejo final:" es siempre en español.
"""

        # Mensaje del usuario, con triple comilla escapada para el texto
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
            # Llamada a la API de OpenAI
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

            # Eliminamos si aparece "6. Cierre técnico"
            correccion_sin_linea6 = re.sub(
                r"(?im)^\s*6\.\s*Cierre técnico.*(\r?\n)?",
                "",
                correccion_original
            )

            # Extraemos el consejo final
            match = re.search(
                r"(?i)Consejo final:\s*(.*?)\s*(?:Fin de texto corregido|$)",
                correccion_sin_linea6,
                re.DOTALL
            )
            if match:
                consejo = match.group(1).strip()
            else:
                consejo = "No se encontró un consejo final claro en la corrección."

            # Limpiamos el consejo para que la voz no lea "Consejo final:"
            consejo_para_audio = re.sub(r"(?i)consejo final:\s*", "", consejo).strip()
            correccion_limpia = correccion_sin_linea6.strip()

            # Mostramos la corrección en pantalla
            st.subheader("📘 Corrección")
            st.markdown(correccion_limpia)

            # Guardamos en la hoja principal
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([nombre, nivel, idioma, fecha, texto, correccion_limpia])
            st.success("✅ Corrección guardada en Google Sheets.")

            # --- ANÁLISIS DE ERRORES PARA LA HOJA DE SEGUIMIENTO ---
            def contar_errores_por_categoria(correccion, categoria):
                patron = rf"(?i)\*\*{categoria}\*\*(.*?)(\*\*|Consejo final:|Fin de texto corregido|$)"
                match_categ = re.search(patron, correccion, re.DOTALL)
                if not match_categ:
                    return 0
                bloque = match_categ.group(1)
                errores = re.findall(r'“[^”]+”|"[^"]+"', bloque)
                return len(errores)

            num_gramatica = contar_errores_por_categoria(correccion_limpia, "Gramática")
            num_lexico = contar_errores_por_categoria(correccion_limpia, "Léxico")
            num_puntuacion = contar_errores_por_categoria(correccion_limpia, "Puntuación")
            num_estructura = contar_errores_por_categoria(correccion_limpia, "Estructura textual")
            total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

            # Guardamos en la hoja "Seguimiento"
            try:
                documento = client_gsheets.open_by_key("1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8")
                st.info(f"Hojas disponibles: {[hoja.title for hoja in documento.worksheets()]}")
                hoja_seguimiento = documento.worksheet("Seguimiento")
                datos_seguimiento = [
                    nombre,
                    nivel,
                    fecha,
                    num_gramatica,
                    num_lexico,
                    num_puntuacion,
                    num_estructura,
                    total_errores,
                    consejo
                ]
                st.info(f"Intentando guardar en Seguimiento: {datos_seguimiento}")
                hoja_seguimiento.append_row(datos_seguimiento)
            except Exception as e:
                st.warning(f"⚠️ No se pudo guardar el seguimiento del alumno: {e}")

            # Generamos el audio del consejo
            st.markdown("**🔊 Consejo leído en voz alta (en español):**")
            with st.spinner("Generando audio con ElevenLabs..."):
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                headers = {
                    "xi-api-key": elevenlabs_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "text": consejo_para_audio,
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

            # Opción de descarga en TXT
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
