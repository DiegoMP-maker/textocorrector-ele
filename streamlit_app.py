import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI

# --- 1. CONFIGURACIÓN DE CLAVES SEGURAS ---
openai_api_key = st.secrets["OPENAI_API_KEY"]

# --- 2. CONEXIÓN A GOOGLE SHEETS ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Cargar credenciales desde secrets
creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
client_gsheets = gspread.authorize(creds)

# Abrir hoja por ID
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
\"\"\"{texto}\"\"\"
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
        except Exception as e:
            st.error(f"Error al generar la corrección o guardar: {e}")

