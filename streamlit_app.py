import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials

# ÁMBITOS de acceso (lectura y escritura en hojas de cálculo)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Cargar las credenciales desde los SECRETS
creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

# Autorizar cliente gspread
client_gsheets = gspread.authorize(creds)

# Abrir hoja por ID (más seguro que por nombre)
sheet = client_gsheets.open_by_key("1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8").sheet1


def analizar_errores(texto):
    errores = {
        "gramaticales": texto.lower().count("gramática"),
        "léxicos": texto.lower().count("léxico"),
        "puntuación": texto.lower().count("puntuación"),
        "estructura": texto.lower().count("estructura")
    }
    errores["total"] = sum(errores.values())
    return errores

def generar_pdf(nombre, correccion):
    buffer = BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica", 10)
    p.drawString(50, 820, f"Alumno: {nombre}")
    p.drawString(50, 805, f"Fecha: {datetime.date.today()}")
    y = 780
    for line in correccion.split("\n"):
        if y < 40:
            p.showPage()
            y = 800
        p.drawString(50, y, line[:100])
        y -= 15
    p.save()
    buffer.seek(0)
    return buffer

if st.button("Corregir texto y guardar historial"):
    if not texto or not nombre_alumno:
        st.warning("Faltan datos obligatorios.")
        st.stop()

    with st.spinner("Corrigiendo y generando feedback..."):
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=texto
        )

        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id
        )

        while True:
            run_check = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if run_check.status == "completed":
                break
            time.sleep(1)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        respuesta = messages.data[0].content[0].text.value

        st.markdown("### ✅ Corrección completa:")
        st.write(respuesta)

        consejo = respuesta.strip().split("\n")[-1]
        errores = analizar_errores(respuesta)

        fecha = str(datetime.date.today())
        row = [
            nombre_alumno, fecha, errores["total"], errores["gramaticales"],
            errores["léxicos"], errores["puntuación"], errores["estructura"],
            texto, respuesta, consejo
        ]
        sheet.append_row(row)

        pdf = generar_pdf(nombre_alumno, respuesta)
        st.download_button("⬇️ Descargar PDF de la corrección", data=pdf, file_name=f"correccion_{nombre_alumno}.pdf")

        headers = {
            "xi-api-key": elevenlabs_api_key,
            "Content-Type": "application/json"
        }
        json_data = {
            "text": consejo,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
            "model_id": "eleven_monolingual_v1"
        }

        audio_response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers=headers,
            json=json_data
        )

        if audio_response.status_code == 200:
            st.audio(audio_response.content, format="audio/mp3")
            st.success("Consejo final leído con la voz de Diego.")
        else:
            st.error("No se pudo generar el audio con ElevenLabs.")
