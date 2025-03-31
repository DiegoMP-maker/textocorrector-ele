import streamlit as st
import json
import gspread
import requests
import re
import pandas as pd
import matplotlib.pyplot as plt
import altair as alt
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO, StringIO
from PIL import Image
import qrcode
import base64
from docx import Document
from docx.shared import Pt, RGBColor, Inches

# Importar el asistente de escritura en tiempo real
from real_time_writing_assistant import RealTimeWritingAssistant

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

# IDs de los documentos
CORRECTIONS_DOC_ID = "1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8"  # Historial_Correcciones_ELE
TRACKING_DOC_ID    = "1-OQsMGgWseZ__FyUVh0UtYVOLui_yoTMG0BxxTGPOU8"  # Seguimiento

# --- Abrir documento de correcciones (Historial_Correcciones_ELE) ---
try:
    corrections_sheet = client_gsheets.open_by_key(CORRECTIONS_DOC_ID).sheet1
    st.success("✅ Conectado a Historial_Correcciones_ELE correctamente.")
except Exception as e:
    st.error(f"❌ Error al conectar con Historial_Correcciones_ELE: {e}")
    st.stop()

# --- Verificar y preparar documento de seguimiento ---
try:
    tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
    hojas = [hoja.title for hoja in tracking_doc.worksheets()]
    
    # Verificar si existe la hoja Seguimiento
    try:
        tracking_sheet = tracking_doc.worksheet("Seguimiento")
        st.success("✅ Conectado a hoja Seguimiento correctamente.")
    except gspread.exceptions.WorksheetNotFound:
        # Crear la hoja si no existe
        tracking_sheet = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=14)
        # Añadir encabezados a la hoja con nuevas columnas para análisis semántico
        headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                   "Errores Puntuación", "Errores Estructura", "Total Errores", 
                   "Puntuación Coherencia", "Puntuación Cohesión", "Puntuación Registro", 
                   "Puntuación Adecuación Cultural", "Consejo Final"]
        tracking_sheet.append_row(headers)
        st.success("✅ Hoja 'Seguimiento' creada y preparada correctamente.")
except Exception as e:
    st.warning(f"⚠️ Advertencia con documento de Seguimiento: {e}")

# --- FUNCIONES AUXILIARES ---

# --- INICIALIZACIÓN DEL ASISTENTE DE ESCRITURA ---
@st.cache_resource
def init_writing_assistant():
    """Inicializar el asistente de escritura en tiempo real (singleton)"""
    return RealTimeWritingAssistant(openai_api_key)

# Inicializar asistente
writing_assistant = init_writing_assistant()

# Función para obtener JSON de la IA con reintentos
def obtener_json_de_ia(system_msg, user_msg, max_retries=3):
    client = OpenAI(api_key=openai_api_key)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.5,
                messages=messages
            )
            raw_output = response.choices[0].message.content

            try:
                data_json = json.loads(raw_output)
                return raw_output, data_json
            except json.JSONDecodeError:
                # Intenta extraer JSON usando regex
                match_json = re.search(r"\{.*\}", raw_output, re.DOTALL)
                if match_json:
                    json_str = match_json.group(0)
                    try:
                        data_json = json.loads(json_str)
                        return raw_output, data_json
                    except json.JSONDecodeError:
                        pass

                # Si aún no hay JSON válido, pide al modelo que corrija
                if attempt < max_retries - 1:
                    messages.append({
                        "role": "system",
                        "content": (
                            "Tu respuesta anterior no cumplió el formato JSON requerido. "
                            "Por favor, responde ÚNICAMENTE en JSON válido con la estructura solicitada. "
                            "No incluyas texto extra, backticks, ni marcadores de código fuente."
                        )
                    })
        except Exception as e:
            st.warning(f"Intento {attempt+1}: Error en la API de OpenAI: {e}")
            if attempt == max_retries - 1:
                raise

    raise ValueError("No se pudo obtener un JSON válido tras varios reintentos.")

# Obtener historial para análisis del progreso
def obtener_historial_estudiante(nombre, tracking_sheet):
    try:
        # Obtener todos los datos
        todos_datos = tracking_sheet.get_all_records()
        
        if not todos_datos:
            return None
        
        # Crear una versión limpia del nombre buscado
        nombre_buscar = nombre.strip().lower()
        
        # Buscar en todos los registros con un enfoque más flexible
        datos_estudiante = []
        for row in todos_datos:
            for key, value in row.items():
                if 'nombre' in key.lower() and value:  # Buscar en cualquier columna que tenga 'nombre'
                    if str(value).strip().lower() == nombre_buscar:
                        datos_estudiante.append(row)
                        break
        
        # Convertir a DataFrame
        if datos_estudiante:
            df = pd.DataFrame(datos_estudiante)
            return df
        return None
    except Exception as e:
        print(f"Error en obtener_historial_estudiante: {e}")
        return None
# Función para mostrar gráficos de progreso
def mostrar_progreso(df):
    if df is None or df.empty:
        st.warning("No hay suficientes datos para mostrar el progreso.")
        return

    # Verificar si existe la columna Fecha
    fecha_col = None
    # Buscar la columna de fecha de manera más flexible
    for col in df.columns:
        if 'fecha' in col.lower().strip():
            fecha_col = col
            break
    
    if fecha_col is None:
        st.error("Error: No se encontró la columna 'Fecha' en los datos.")
        st.write("Columnas disponibles:", list(df.columns))
        return
        
    # Asegurarse de que la columna Fecha está en formato datetime
    try:
        df[fecha_col] = pd.to_datetime(df[fecha_col], errors='coerce')
        df = df.sort_values(fecha_col)
    except Exception as e:
        st.error(f"Error al convertir la columna {fecha_col} a formato de fecha: {str(e)}")
        return
    
    # Gráfico de errores a lo largo del tiempo
    st.subheader("Progreso en la reducción de errores")
    
    # Crear un gráfico con Altair para total de errores
    chart_errores = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X(f'{fecha_col}:T', title='Fecha'),
        y=alt.Y('Total Errores:Q', title='Total Errores'),
        tooltip=[f'{fecha_col}:T', 'Total Errores:Q', 'Nivel:N']
    ).properties(
        title='Evolución de errores totales a lo largo del tiempo'
    ).interactive()
    
    st.altair_chart(chart_errores, use_container_width=True)
    
    # Gráfico de tipos de errores
    # Usar exactamente los nombres de columnas que vemos en la tabla
    columnas_errores = [
        'Errores Gramática',
        'Errores Léxico',
        'Errores Puntuación',
        'Errores Estructura'
    ]

    # Encontrar las columnas que realmente existen en el DataFrame
    columnas_errores_existentes = [col for col in columnas_errores if col in df.columns]

    # Si no hay columnas de errores, mostrar un mensaje
    if not columnas_errores_existentes:
        st.warning("No se encontraron columnas de tipos de errores en los datos.")
        # Mostrar columnas disponibles para depuración
        st.write("Columnas disponibles:", list(df.columns))
    else:
        # Usar solo las columnas que existen
        tipos_error_df = pd.melt(
            df, 
            id_vars=[fecha_col], 
            value_vars=columnas_errores_existentes,
            var_name='Tipo de Error', 
            value_name='Cantidad'
        )
        
        chart_tipos = alt.Chart(tipos_error_df).mark_line(point=True).encode(
            x=alt.X(f'{fecha_col}:T', title='Fecha'),
            y=alt.Y('Cantidad:Q', title='Cantidad'),
            color=alt.Color('Tipo de Error:N', title='Tipo de Error'),
            tooltip=[f'{fecha_col}:T', 'Tipo de Error:N', 'Cantidad:Q']
        ).properties(
            title='Evolución por tipo de error'
        ).interactive()
        
        st.altair_chart(chart_tipos, use_container_width=True)
    
    # Gráfico de radar para habilidades contextuales (última entrada)
    if 'Puntuación Coherencia' in df.columns and len(df) > 0:
        ultima_entrada = df.iloc[-1]
        
        # Datos para el gráfico de radar
        categorias = ['Coherencia', 'Cohesión', 'Registro', 'Ad. Cultural']
        valores = [
            ultima_entrada.get('Puntuación Coherencia', 0),
            ultima_entrada.get('Puntuación Cohesión', 0),
            ultima_entrada.get('Puntuación Registro', 0),
            ultima_entrada.get('Puntuación Adecuación Cultural', 0)
        ]
        
        # Crear gráfico de radar
        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
        
        # Número de categorías
        N = len(categorias)
        
        # Ángulos para cada eje
        angulos = [n / float(N) * 2 * 3.14159 for n in range(N)]
        angulos += angulos[:1]  # Cerrar el círculo
        
        # Añadir los valores, repitiendo el primero
        valores_radar = valores + [valores[0]]
        
        # Dibujar los ejes
        plt.xticks(angulos[:-1], categorias)
        
        # Dibujar el polígono
        ax.plot(angulos, valores_radar)
        ax.fill(angulos, valores_radar, alpha=0.1)
        
        # Ajustar escala
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_ylim(0, 10)
        
        plt.title("Habilidades contextuales (última evaluación)")
        st.pyplot(fig)

# Base de datos simple de recursos por niveles y categorías
RECURSOS_DB = {
    "A1-A2": {
        "Gramática": [
            {"título": "Presente de indicativo", "tipo": "Ficha", "url": "https://www.profedeele.es/gramatica/presente-indicativo/", "nivel": "A1"},
            {"título": "Los artículos en español", "tipo": "Vídeo", "url": "https://www.youtube.com/watch?v=example1", "nivel": "A1"},
            {"título": "Ser y estar", "tipo": "Ejercicios", "url": "https://aprenderespanol.org/ejercicios/ser-estar", "nivel": "A2"},
            {"título": "Pretérito indefinido", "tipo": "Explicación", "url": "https://www.cervantes.es/gramatica/indefinido", "nivel": "A2"}
        ],
        "Léxico": [
            {"título": "Vocabulario básico", "tipo": "Ficha", "url": "https://www.spanishdict.com/vocabulario-basico", "nivel": "A1"},
            {"título": "Alimentos y comidas", "tipo": "Tarjetas", "url": "https://quizlet.com/es/alimentos", "nivel": "A1"},
            {"título": "La ciudad", "tipo": "Podcast", "url": "https://spanishpod101.com/la-ciudad", "nivel": "A2"}
        ],
        "Cohesión": [
            {"título": "Conectores básicos", "tipo": "Guía", "url": "https://www.lingolia.com/es/conectores-basicos", "nivel": "A2"},
            {"título": "Organizar ideas", "tipo": "Ejercicios", "url": "https://www.todo-claro.com/organizacion", "nivel": "A2"}
        ],
        "Registro": [
            {"título": "Saludos formales e informales", "tipo": "Vídeo", "url": "https://www.youtube.com/watch?v=example2", "nivel": "A1"},
            {"título": "Peticiones corteses", "tipo": "Diálogos", "url": "https://www.lingoda.com/es/cortesia", "nivel": "A2"}
        ]
    },
    "B1-B2": {
        "Gramática": [
            {"título": "Subjuntivo presente", "tipo": "Guía", "url": "https://www.profedeele.es/subjuntivo-presente/", "nivel": "B1"},
            {"título": "Estilo indirecto", "tipo": "Ejercicios", "url": "https://www.cervantes.es/estilo-indirecto", "nivel": "B2"}
        ],
        "Léxico": [
            {"título": "Expresiones idiomáticas", "tipo": "Podcast", "url": "https://spanishpod101.com/expresiones", "nivel": "B1"},
            {"título": "Vocabulario académico", "tipo": "Glosario", "url": "https://cvc.cervantes.es/vocabulario-academico", "nivel": "B2"}
        ],
        "Cohesión": [
            {"título": "Marcadores discursivos", "tipo": "Guía", "url": "https://www.cervantes.es/marcadores", "nivel": "B1"},
            {"título": "Conectores argumentativos", "tipo": "Ejercicios", "url": "https://www.todo-claro.com/conectores", "nivel": "B2"}
        ],
        "Registro": [
            {"título": "Lenguaje formal e informal", "tipo": "Curso", "url": "https://www.coursera.org/spanish-registers", "nivel": "B1"},
            {"título": "Comunicación profesional", "tipo": "Ejemplos", "url": "https://www.cervantes.es/comunicacion-profesional", "nivel": "B2"}
        ]
    },
    "C1-C2": {
        "Gramática": [
            {"título": "Construcciones pasivas", "tipo": "Análisis", "url": "https://www.profedeele.es/pasivas-avanzadas/", "nivel": "C1"},
            {"título": "Subordinadas complejas", "tipo": "Guía", "url": "https://www.cervantes.es/subordinadas", "nivel": "C2"}
        ],
        "Léxico": [
            {"título": "Lenguaje académico", "tipo": "Corpus", "url": "https://www.rae.es/corpus-academico", "nivel": "C1"},
            {"título": "Variantes dialectales", "tipo": "Curso", "url": "https://www.coursera.org/variantes-espanol", "nivel": "C2"}
        ],
        "Cohesión": [
            {"título": "Estructura textual avanzada", "tipo": "Manual", "url": "https://www.uned.es/estructura-textual", "nivel": "C1"},
            {"título": "Análisis del discurso", "tipo": "Investigación", "url": "https://cvc.cervantes.es/analisis-discurso", "nivel": "C2"}
        ],
        "Registro": [
            {"título": "Pragmática intercultural", "tipo": "Seminario", "url": "https://www.cervantes.es/pragmatica", "nivel": "C1"},
            {"título": "Lenguaje literario", "tipo": "Análisis", "url": "https://www.rae.es/lenguaje-literario", "nivel": "C2"}
        ]
    }
}

# Función para generar recomendaciones de ejercicios con IA
def generar_ejercicios_personalizado(errores_obj, analisis_contextual, nivel, idioma, openai_api_key):
    client = OpenAI(api_key=openai_api_key)
    
    # Preparar datos para el prompt
    errores_gramatica = errores_obj.get("Gramática", [])
    errores_lexico = errores_obj.get("Léxico", [])
    errores_puntuacion = errores_obj.get("Puntuación", [])
    errores_estructura = errores_obj.get("Estructura textual", [])
    
    # Extraer puntos débiles del análisis contextual
    coherencia = analisis_contextual.get("coherencia", {})
    cohesion = analisis_contextual.get("cohesion", {})
    registro = analisis_contextual.get("registro_linguistico", {})
    
    # Mapear nivel para el prompt
    if "principiante" in nivel:
        nivel_prompt = "A1-A2"
    elif "intermedio" in nivel:
        nivel_prompt = "B1-B2"
    else:
        nivel_prompt = "C1-C2"
    
    # Construir prompt para OpenAI
    prompt_ejercicios = f"""
    Basándote en los errores y análisis contextual de un estudiante de español de nivel {nivel_prompt}, 
    crea 3 ejercicios personalizados que le ayuden a mejorar. El estudiante tiene:
    
    - Errores gramaticales: {len(errores_gramatica)} (ejemplos: {', '.join([e.get('fragmento_erroneo', '') for e in errores_gramatica[:2]])})
    - Errores léxicos: {len(errores_lexico)} (ejemplos: {', '.join([e.get('fragmento_erroneo', '') for e in errores_lexico[:2]])})
    - Errores de puntuación: {len(errores_puntuacion)}
    - Errores de estructura: {len(errores_estructura)}
    
    - Puntuación en coherencia: {coherencia.get('puntuacion', 0)}/10
    - Puntuación en cohesión: {cohesion.get('puntuacion', 0)}/10
    - Registro lingüístico: {registro.get('tipo_detectado', 'No especificado')}
    
    Crea ejercicios breves y específicos en formato JSON con esta estructura:
    {{
      "ejercicios": [
        {{
          "titulo": "Título del ejercicio",
          "tipo": "tipo de ejercicio (completar huecos, ordenar frases, etc.)",
          "instrucciones": "instrucciones claras y breves",
          "contenido": "el contenido del ejercicio",
          "solucion": "la solución del ejercicio"
        }},
        ...
      ]
    }}
    """
    
    # Idioma para las instrucciones
    if idioma != "Español":
        prompt_ejercicios += f"\nTraduce las instrucciones y el título al {idioma}, pero mantén el contenido del ejercicio en español."
    
    try:
        # Llamada a la API
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            temperature=0.7,
            messages=[{"role": "system", "content": "Eres un experto profesor de ELE especializado en crear ejercicios personalizados."}, 
                      {"role": "user", "content": prompt_ejercicios}]
        )
        
        # Extraer JSON de la respuesta
        content = response.choices[0].message.content
        
        # Buscar JSON en el texto
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            json_str = match.group(0)
            ejercicios_data = json.loads(json_str)
            return ejercicios_data
        else:
            return {"ejercicios": [{"titulo": "Error en la generación", "instrucciones": "No se pudieron generar ejercicios personalizados", "contenido": "", "solucion": ""}]}
    
    except Exception as e:
        st.error(f"Error al generar ejercicios: {str(e)}")
        return {"ejercicios": [{"titulo": "Error en la generación", "instrucciones": "No se pudieron generar ejercicios personalizados", "contenido": "", "solucion": ""}]}
# Función para obtener recursos recomendados según errores
def obtener_recursos_recomendados(errores_obj, analisis_contextual, nivel):
    recursos_recomendados = []
    
    # Determinar el nivel para buscar recursos
    if "principiante" in nivel:
        nivel_db = "A1-A2"
    elif "intermedio" in nivel:
        nivel_db = "B1-B2"
    else:
        nivel_db = "C1-C2"
    
    # Verificar errores gramaticales
    if len(errores_obj.get("Gramática", [])) > 0:
        recursos_gramatica = RECURSOS_DB.get(nivel_db, {}).get("Gramática", [])
        if recursos_gramatica:
            recursos_recomendados.extend(recursos_gramatica[:2])
    
    # Verificar errores léxicos
    if len(errores_obj.get("Léxico", [])) > 0:
        recursos_lexico = RECURSOS_DB.get(nivel_db, {}).get("Léxico", [])
        if recursos_lexico:
            recursos_recomendados.extend(recursos_lexico[:2])
    
    # Verificar problemas de cohesión
    if analisis_contextual.get("cohesion", {}).get("puntuacion", 10) < 7:
        recursos_cohesion = RECURSOS_DB.get(nivel_db, {}).get("Cohesión", [])
        if recursos_cohesion:
            recursos_recomendados.extend(recursos_cohesion[:1])
    
    # Verificar problemas de registro
    if analisis_contextual.get("registro_linguistico", {}).get("puntuacion", 10) < 7:
        recursos_registro = RECURSOS_DB.get(nivel_db, {}).get("Registro", [])
        if recursos_registro:
            recursos_recomendados.extend(recursos_registro[:1])
    
    return recursos_recomendados

# UI para mostrar recomendaciones
def mostrar_seccion_recomendaciones(errores_obj, analisis_contextual, nivel, idioma, openai_api_key):
    st.header("📚 Recomendaciones personalizadas")
    
    # Pestañas para diferentes tipos de recomendaciones
    tab1, tab2 = st.tabs(["📖 Recursos recomendados", "✏️ Ejercicios personalizados"])
    
    with tab1:
        recursos = obtener_recursos_recomendados(errores_obj, analisis_contextual, nivel)
        
        if recursos:
            st.write("Basado en tu análisis, te recomendamos estos recursos:")
            
            for i, recurso in enumerate(recursos):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.markdown(f"**{recurso['título']}**")
                with col2:
                    st.write(f"Tipo: {recurso['tipo']}")
                with col3:
                    st.write(f"Nivel: {recurso['nivel']}")
                st.markdown(f"[Ver recurso]({recurso['url']})")
                if i < len(recursos) - 1:
                    st.divider()
        else:
            st.info("No hay recursos específicos para recomendar en este momento.")
    
    with tab2:
        st.write("Ejercicios personalizados según tus necesidades:")
        
        with st.spinner("Generando ejercicios personalizados..."):
            ejercicios_data = generar_ejercicios_personalizado(
                errores_obj, analisis_contextual, nivel, idioma, openai_api_key
            )
            
            ejercicios = ejercicios_data.get("ejercicios", [])
            
            for i, ejercicio in enumerate(ejercicios):
                # Usar st.expander para el ejercicio principal
                with st.expander(f"{ejercicio.get('titulo', f'Ejercicio {i+1}')}"):
                    # Crear pestañas para ejercicio y solución
                    ejercicio_tab, solucion_tab = st.tabs(["Ejercicio", "Solución"])
                    
                    with ejercicio_tab:
                        st.markdown(f"**{ejercicio.get('tipo', 'Actividad')}**")
                        st.markdown(f"*Instrucciones:* {ejercicio.get('instrucciones', '')}")
                        st.markdown("---")
                        st.markdown(ejercicio.get('contenido', ''))
                    
                    with solucion_tab:
                        st.markdown(f"#### Solución del ejercicio:")
                        st.markdown(ejercicio.get('solucion', ''))

# Función para generar informe en formato Word (DOCX)
def generar_informe_docx(nombre, nivel, fecha, texto_original, texto_corregido, 
                        errores_obj, analisis_contextual, consejo_final):
    doc = Document()
    
    # Estilo del documento
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)
    
    # Título
    doc.add_heading('Informe de corrección textual', 0)
    
    # Información general
    doc.add_heading('Información general', level=1)
    doc.add_paragraph(f'Nombre: {nombre}')
    doc.add_paragraph(f'Nivel: {nivel}')
    doc.add_paragraph(f'Fecha: {fecha}')
    
    # Texto original
    doc.add_heading('Texto original', level=1)
    doc.add_paragraph(texto_original)
    
    # Texto corregido
    doc.add_heading('Texto corregido', level=1)
    doc.add_paragraph(texto_corregido)
    
    # Análisis de errores
    doc.add_heading('Análisis de errores', level=1)
    
    for categoria, errores in errores_obj.items():
        if errores:
            doc.add_heading(categoria, level=2)
            for error in errores:
                p = doc.add_paragraph()
                p.add_run('Fragmento erróneo: ').bold = True
                p.add_run(error.get('fragmento_erroneo', '')).font.color.rgb = RGBColor(255, 0, 0)
                
                p = doc.add_paragraph()
                p.add_run('Corrección: ').bold = True
                p.add_run(error.get('correccion', '')).font.color.rgb = RGBColor(0, 128, 0)
                
                p = doc.add_paragraph()
                p.add_run('Explicación: ').bold = True
                p.add_run(error.get('explicacion', ''))
                
                doc.add_paragraph()  # Espacio
    
    # Análisis contextual
    doc.add_heading('Análisis contextual', level=1)
    
    # Tabla de puntuaciones
    doc.add_heading('Puntuaciones', level=2)
    table = doc.add_table(rows=1, cols=5)
    table.style = 'Table Grid'
    
    # Encabezados
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Aspecto'
    hdr_cells[1].text = 'Coherencia'
    hdr_cells[2].text = 'Cohesión'
    hdr_cells[3].text = 'Registro'
    hdr_cells[4].text = 'Adecuación cultural'
    
    # Datos
    row_cells = table.add_row().cells
    row_cells[0].text = 'Puntuación'
    row_cells[1].text = str(analisis_contextual.get('coherencia', {}).get('puntuacion', 'N/A'))
    row_cells[2].text = str(analisis_contextual.get('cohesion', {}).get('puntuacion', 'N/A'))
    row_cells[3].text = str(analisis_contextual.get('registro_linguistico', {}).get('puntuacion', 'N/A'))
    row_cells[4].text = str(analisis_contextual.get('adecuacion_cultural', {}).get('puntuacion', 'N/A'))
    
    # Consejo final
    doc.add_heading('Consejo final', level=1)
    doc.add_paragraph(consejo_final)
    
    # Generar QR code (simulado)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(f"https://textocorrector.ejemplo.com/informe/{nombre.replace(' ', '')}/{fecha.replace(' ', '_')}")
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Guardar QR como imagen temporal
    qr_buffer = BytesIO()
    img.save(qr_buffer)
    qr_buffer.seek(0)
    
    # Añadir la imagen del QR al documento
    doc.add_heading('Acceso online', level=1)
    doc.add_paragraph('Escanea este código QR para acceder a este informe online:')
    doc.add_picture(qr_buffer, width=Inches(2.0))
    
    # Guardar el documento en memoria
    docx_buffer = BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    
    return docx_buffer

# --- 3. ESTRUCTURA DE LA APLICACIÓN ---
st.title("📝 Textocorrector ELE")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback con análisis contextual avanzado. Creado por el profesor Diego Medina")

# Pestañas principales
tab_corregir, tab_progreso, tab_historial, tab_herramientas = st.tabs(["📝 Corregir texto", "📊 Ver progreso", "📚 Historial", "🛠️ Herramientas"])

# --- PESTAÑA 1: CORREGIR TEXTO ---
with tab_corregir:
    with st.expander("ℹ️ Información sobre el análisis contextual", expanded=False):
        st.markdown("""
    Esta versión mejorada del Textocorrector incluye:
    - **Análisis de coherencia**: Evalúa si las ideas están conectadas de manera lógica y si el texto tiene sentido en su conjunto.
    - **Análisis de cohesión**: Revisa los mecanismos lingüísticos que conectan las diferentes partes del texto.
    - **Evaluación del registro lingüístico**: Determina si el lenguaje usado es apropiado para el contexto y propósito del texto.
    - **Análisis de adecuación cultural**: Identifica si hay expresiones o referencias culturalmente apropiadas o inapropiadas.
    - **Asistente de escritura en tiempo real**: Recibe sugerencias mientras escribes (activable/desactivable).
    
    Las correcciones se adaptan automáticamente al nivel del estudiante.
""")

# Formulario de corrección
with st.form("formulario"):
    nombre = st.text_input("Nombre y apellido:")
    if nombre and " " not in nombre:
        st.warning("Por favor, introduce tanto el nombre como el apellido separados por un espacio.")
    
    nivel = st.selectbox("¿Cuál es tu nivel?", [
        "Nivel principiante (A1-A2)",
        "Nivel intermedio (B1-B2)",
        "Nivel avanzado (C1-C2)"
    ])
    
    # Guardar nivel en formato simplificado para el asistente
    nivel_map = {
        "Nivel principiante (A1-A2)": "principiante",
        "Nivel intermedio (B1-B2)": "intermedio",
        "Nivel avanzado (C1-C2)": "avanzado"
    }
    st.session_state.nivel_estudiante = nivel_map.get(nivel, "intermedio")
    
    idioma = st.selectbox("Selecciona lenguaje para la corrección", ["Español", "Francés", "Inglés"])
    
    col1, col2 = st.columns(2)
    with col1:
        tipo_texto = st.selectbox("Tipo de texto", [
            "General/No especificado",
            "Académico",
            "Profesional/Laboral",
            "Informal/Cotidiano",
            "Creativo/Literario"
        ])
    
    with col2:
        contexto_cultural = st.selectbox("Contexto cultural", [
            "General/Internacional",
            "España",
            "Latinoamérica",
            "Contexto académico",
            "Contexto empresarial"
        ])
    
    # Integrar asistente de escritura en tiempo real
    texto = st.text_area(
        "Escribe tu texto aquí:",
        height=250,
        key="texto_correccion"
    )
    
    info_adicional = st.text_area("Información adicional o contexto (opcional):", height=100)
    
    enviar = st.form_submit_button("Corregir")
    
    # CORREGIR TEXTO CON IA Y JSON ESTRUCTURADO
    if enviar and nombre and texto:
        with st.spinner("Analizando texto y generando corrección contextual..."):
            # Mapeo de niveles para instrucciones más específicas
            nivel_map = {
                "Nivel principiante (A1-A2)": {
                    "descripcion": "principiante (A1-A2)",
                    "enfoque": "Enfócate en estructuras básicas, vocabulario fundamental y errores comunes. Utiliza explicaciones simples y claras. Evita terminología lingüística compleja."
                },
                "Nivel intermedio (B1-B2)": {
                    "descripcion": "intermedio (B1-B2)",
                    "enfoque": "Puedes señalar errores más sutiles de concordancia, uso de tiempos verbales y preposiciones. Puedes usar alguna terminología lingüística básica en las explicaciones."
                },
                "Nivel avanzado (C1-C2)": {
                    "descripcion": "avanzado (C1-C2)",
                    "enfoque": "Céntrate en matices, coloquialismos, registro lingüístico y fluidez. Puedes usar terminología lingüística específica y dar explicaciones más detalladas y técnicas."
                }
            }
            
            nivel_info = nivel_map.get(nivel, nivel_map["Nivel intermedio (B1-B2)"])
            
            # Instrucciones para el modelo de IA con análisis contextual avanzado
            system_message = f"""
Eres Diego, un profesor experto en ELE (Español como Lengua Extranjera) especializado en análisis lingüístico contextual.
Tu objetivo es corregir textos adaptando tu feedback al nivel {nivel_info['descripcion']} del estudiante.
{nivel_info['enfoque']}

Cuando corrijas un texto, DEBES devolver la respuesta únicamente en un JSON válido, sin texto adicional, con la siguiente estructura EXACTA:

{{
  "saludo": "string",                // en {idioma}
  "tipo_texto": "string",            // en {idioma}
  "errores": {{
       "Gramática": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
           // más errores de Gramática (o [] si ninguno)
       ],
       "Léxico": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ],
       "Puntuación": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ],
       "Estructura textual": [
           {{
             "fragmento_erroneo": "string",
             "correccion": "string",
             "explicacion": "string"
           }}
       ]
  }},
  "texto_corregido": "string",       // siempre en español
  "analisis_contextual": {{
       "coherencia": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "cohesion": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "registro_linguistico": {{
           "puntuacion": number,     // del 1 al 10
           "tipo_detectado": "string", // tipo de registro detectado en {idioma}
           "adecuacion": "string",   // evaluación de adecuación en {idioma}
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }},
       "adecuacion_cultural": {{
           "puntuacion": number,     // del 1 al 10
           "comentario": "string",   // en {idioma}
           "elementos_destacables": [  // elementos culturales destacables en {idioma}
               "string",
               "string"
           ],
           "sugerencias": [          // listado de sugerencias en {idioma}
               "string",
               "string"
           ]
       }}
  }},
  "consejo_final": "string",         // en español
  "fin": "Fin de texto corregido."
}}

IMPORTANTE:
- Las explicaciones de los errores deben estar en {idioma}
- Todo el análisis contextual debe estar en {idioma}
- El texto corregido completo SIEMPRE debe estar en español, independientemente del idioma seleccionado
- El consejo final SIEMPRE debe estar en español
- Adapta tus explicaciones y sugerencias al nivel {nivel_info['descripcion']} del estudiante
- Considera el tipo de texto "{tipo_texto}" y el contexto cultural "{contexto_cultural}" en tu análisis

No devuelvas ningún texto extra fuera de este JSON.
"""
            # Mensaje para el usuario con contexto adicional
            user_message = f"""
Texto del alumno:
\"\"\"
{texto}
\"\"\"
Nivel: {nivel}
Nombre del alumno: {nombre}
Idioma de corrección: {idioma}
Tipo de texto: {tipo_texto}
Contexto cultural: {contexto_cultural}
{f"Información adicional: {info_adicional}" if info_adicional else ""}
"""

            try:
                raw_output, data_json = obtener_json_de_ia(system_message, user_message, max_retries=3)

                # Extraer campos del JSON
                saludo = data_json.get("saludo", "")
                tipo_texto_detectado = data_json.get("tipo_texto", "")
                errores_obj = data_json.get("errores", {})
                texto_corregido = data_json.get("texto_corregido", "")
                analisis_contextual = data_json.get("analisis_contextual", {})
                consejo_final = data_json.get("consejo_final", "")
                fin = data_json.get("fin", "")

                # Extraer puntuaciones del análisis contextual
                coherencia = analisis_contextual.get("coherencia", {})
                cohesion = analisis_contextual.get("cohesion", {})
                registro = analisis_contextual.get("registro_linguistico", {})
                adecuacion = analisis_contextual.get("adecuacion_cultural", {})
                
                puntuacion_coherencia = coherencia.get("puntuacion", 0)
                puntuacion_cohesion = cohesion.get("puntuacion", 0)
                puntuacion_registro = registro.get("puntuacion", 0)
                puntuacion_adecuacion = adecuacion.get("puntuacion", 0)

                # --- MOSTRAR RESULTADOS EN LA INTERFAZ ---
                # Mostrar el saludo y presentación directamente sin encabezados
                st.write(saludo)
                
                # Generar texto de presentación en el idioma seleccionado
                if idioma == "Español":
                    presentacion = f"A continuación encontrarás el análisis completo de tu texto. He identificado tu escrito como un texto de tipo **{tipo_texto_detectado.lower()}**. He revisado aspectos gramaticales, léxicos, de puntuación y estructura, además de realizar un análisis de coherencia, cohesión, registro y adecuación cultural. Todas las correcciones están adaptadas a tu nivel {nivel_info['descripcion']}."
                elif idioma == "Francés":
                    presentacion = f"Voici l'analyse complète de ton texte. J'ai identifié ton écrit comme un texte de type **{tipo_texto_detectado.lower()}**. J'ai examiné les aspects grammaticaux, lexicaux, de ponctuation et de structure, en plus de réaliser une analyse de cohérence, cohésion, registre et adaptation culturelle. Toutes les corrections sont adaptées à ton niveau {nivel_info['descripcion']}."
                elif idioma == "Inglés":
                    presentacion = f"Below you will find the complete analysis of your text. I have identified your writing as a **{tipo_texto_detectado.lower()}** type text. I have reviewed grammatical, lexical, punctuation and structural aspects, as well as analyzing coherence, cohesion, register and cultural appropriateness. All corrections are adapted to your {nivel_info['descripcion']} level."
                else:
                    presentacion = f"A continuación encontrarás el análisis completo de tu texto. He identificado tu escrito como un texto de tipo **{tipo_texto_detectado.lower()}**."
                    
                st.markdown(presentacion)
                
                # Errores detectados
                st.subheader("Errores detectados")
                if not any(errores_obj.get(cat, []) for cat in ["Gramática", "Léxico", "Puntuación", "Estructura textual"]):
                    st.success("¡Felicidades! No se han detectado errores significativos.")
                else:
                    for categoria in ["Gramática", "Léxico", "Puntuación", "Estructura textual"]:
                        lista_errores = errores_obj.get(categoria, [])
                        if lista_errores:
                            with st.expander(f"**{categoria}** ({len(lista_errores)} errores)"):
                                for i, err in enumerate(lista_errores, 1):
                                    st.markdown(f"**Error {i}:**")
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.error(f"❌ {err.get('fragmento_erroneo','')}")
                                    with col2:
                                        st.success(f"✅ {err.get('correccion','')}")
                                    st.info(f"💡 {err.get('explicacion','')}")
                                    if i < len(lista_errores):
                                        st.divider()

                # Texto corregido
                st.subheader("Texto corregido completo")
                st.write(texto_corregido)
                
                # --- ANÁLISIS CONTEXTUAL ---
                st.header("Análisis contextual avanzado")
                
                # Crear columnas para las puntuaciones generales
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Coherencia", f"{puntuacion_coherencia}/10")
                with col2:
                    st.metric("Cohesión", f"{puntuacion_cohesion}/10")
                with col3:
                    st.metric("Registro", f"{puntuacion_registro}/10")
                with col4:
                    st.metric("Adecuación cultural", f"{puntuacion_adecuacion}/10")
                
                # Gráfico sencillo para visualizar las puntuaciones
                puntuaciones = [puntuacion_coherencia, puntuacion_cohesion, puntuacion_registro, puntuacion_adecuacion]
                categorias = ["Coherencia", "Cohesión", "Registro", "Ad. Cultural"]
                
                # Calcular el promedio de las puntuaciones
                promedio_contextual = sum(puntuaciones) / len(puntuaciones) if puntuaciones else 0
                
                # Mostrar un progreso general
                st.markdown(f"##### Evaluación global: {promedio_contextual:.1f}/10")
                st.progress(promedio_contextual / 10)
                
                # Detalles de coherencia
                with st.expander("Coherencia textual", expanded=True):
                    st.markdown(f"**Comentario**: {coherencia.get('comentario', '')}")
                    st.markdown("**Sugerencias para mejorar:**")
                    for sug in coherencia.get("sugerencias", []):
                        st.markdown(f"- {sug}")
                
                # Detalles de cohesión
                with st.expander("Cohesión textual", expanded=True):
                    st.markdown(f"**Comentario**: {cohesion.get('comentario', '')}")
                    st.markdown("**Sugerencias para mejorar:**")
                    for sug in cohesion.get("sugerencias", []):
                        st.markdown(f"- {sug}")
                
                # Detalles de registro lingüístico
                with st.expander("Registro lingüístico", expanded=True):
                    st.markdown(f"**Tipo de registro detectado**: {registro.get('tipo_detectado', '')}")
                    st.markdown(f"**Adecuación al contexto**: {registro.get('adecuacion', '')}")
                    st.markdown("**Sugerencias para mejorar:**")
                    for sug in registro.get("sugerencias", []):
                        st.markdown(f"- {sug}")
                
                # Detalles de adecuación cultural
                with st.expander("Adecuación cultural y pragmática", expanded=True):
                    st.markdown(f"**Comentario**: {adecuacion.get('comentario', '')}")
                    if adecuacion.get("elementos_destacables", []):
                        st.markdown("**Elementos culturales destacables:**")
                        for elem in adecuacion.get("elementos_destacables", []):
                            st.markdown(f"- {elem}")
                    st.markdown("**Sugerencias para mejorar:**")
                    for sug in adecuacion.get("sugerencias", []):
                        st.markdown(f"- {sug}")

                # Consejo final
                st.subheader("Consejo final")
                st.info(consejo_final)
                st.write(fin)

                # Guardar en Historial_Correcciones_ELE
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
                corrections_sheet.append_row([nombre, nivel, idioma, fecha, texto, raw_output])
                st.success("✅ Corrección guardada en Historial_Correcciones_ELE.")

                # --- CONTEO DE ERRORES ---
                num_gramatica = len(errores_obj.get("Gramática", []))
                num_lexico = len(errores_obj.get("Léxico", []))
                num_puntuacion = len(errores_obj.get("Puntuación", []))
                num_estructura = len(errores_obj.get("Estructura textual", []))
                total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

                # --- GUARDAR SEGUIMIENTO EN EL DOCUMENTO "Seguimiento" ---
                try:
                    datos_seguimiento = [
                        nombre,
                        nivel,
                        fecha,
                        num_gramatica,
                        num_lexico,
                        num_puntuacion,
                        num_estructura,
                        total_errores,
                        puntuacion_coherencia,
                        puntuacion_cohesion,
                        puntuacion_registro,
                        puntuacion_adecuacion,
                        consejo_final
                    ]
                    
                    # Intenta aprovechar la variable tracking_sheet que definimos al inicio
                    try:
                        tracking_sheet.append_row(datos_seguimiento)
                        st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento.")
                    except NameError:
                        # Si tracking_sheet no está definido, intentamos recuperarlo
                        tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)
                        try:
                            tracking_sheet = tracking_doc.worksheet("Seguimiento")
                        except gspread.exceptions.WorksheetNotFound:
                            tracking_sheet = tracking_doc.add_worksheet(title="Seguimiento", rows=100, cols=14)
                            headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico", 
                                    "Errores Puntuación", "Errores Estructura", "Total Errores", 
                                    "Puntuación Coherencia", "Puntuación Cohesión", "Puntuación Registro", 
                                    "Puntuación Adecuación Cultural", "Consejo Final"]
                            tracking_sheet.append_row(headers)
                        
                        tracking_sheet.append_row(datos_seguimiento)
                        st.success(f"✅ Estadísticas guardadas en hoja de Seguimiento (recuperada).")
                except Exception as e:
                    st.error(f"❌ Error al guardar estadísticas en Seguimiento: {str(e)}")
                    st.info("Detalles del error para depuración:")
                    st.code(str(e))

                # --- GENERAR AUDIO CON ELEVENLABS (Consejo final en español) ---
                st.markdown("**🔊 Consejo leído en voz alta:**")
                with st.spinner("Generando audio con ElevenLabs..."):
                    tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
                    headers = {
                        "xi-api-key": elevenlabs_api_key,
                        "Content-Type": "application/json"
                    }
                    audio_text = consejo_final.replace("Consejo final:", "").strip()
                    data = {
                        "text": audio_text,
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {
                            "stability": 0.3,
                            "similarity_boost": 0.9
                        }
                    }
                    try:
                        response_audio = requests.post(tts_url, headers=headers, json=data)
                        if response_audio.ok:
                            audio_bytes = BytesIO(response_audio.content)
                            st.audio(audio_bytes, format="audio/mpeg")
                        else:
                            st.warning(f"⚠️ No se pudo reproducir el consejo con ElevenLabs. (Status code: {response_audio.status_code})")
                    except Exception as e:
                        st.warning(f"⚠️ Error al generar audio: {e}")

                # --- SECCIONES NUEVAS ---
                
                # 1. Mostrar recomendaciones personalizadas
                mostrar_seccion_recomendaciones(errores_obj, analisis_contextual, nivel, idioma, openai_api_key)
                
                # 2. Opciones de exportación
                st.header("📊 Exportar informe")
                
                # Opciones de exportación en pestañas
                export_tab1, export_tab2, export_tab3 = st.tabs(["📝 Documento Word", "🌐 Documento HTML", "📊 Excel/CSV"])

                with export_tab1:
                    st.write("Exporta este informe como documento Word (DOCX)")
                    
                    # Generar el buffer por adelantado
                    docx_buffer = None
                    try:
                        docx_buffer = generar_informe_docx(
                            nombre, nivel, fecha, texto, texto_corregido,
                            errores_obj, analisis_contextual, consejo_final
                        )
                    except Exception as e:
                        st.error(f"Error al generar el documento Word: {e}")
                    
                    # Si el buffer se generó correctamente, mostrar el botón de descarga
                    if docx_buffer is not None:
                        nombre_archivo = f"informe_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.docx"
                        if st.download_button(
                            label="📥 Descargar documento Word",
                            data=docx_buffer,
                            file_name=nombre_archivo,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="docx_download"
                        ):
                            st.success("✅ Documento Word descargado correctamente.")
                
                with export_tab2:
                    st.write("Exporta este informe como página web (HTML)")
                    
                    # Generar el HTML directamente sin necesidad de un botón adicional
                    html_content = f"""
                    <!DOCTYPE html>
                    <html lang="es">
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>Informe de corrección - {nombre}</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                            h1 {{ color: #2c3e50; }}
                            h2 {{ color: #3498db; margin-top: 30px; }}
                            h3 {{ color: #2980b9; }}
                            .original {{ background-color: #f8f9fa; padding: 15px; border-left: 4px solid #6c757d; }}
                            .corregido {{ background-color: #e7f4e4; padding: 15px; border-left: 4px solid #28a745; }}
                            .error-item {{ margin-bottom: 20px; padding: 10px; background-color: #f1f1f1; }}
                            .fragmento {{ color: #dc3545; }}
                            .correccion {{ color: #28a745; }}
                            .explicacion {{ color: #17a2b8; font-style: italic; }}
                            .puntuaciones {{ width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 20px; }}
                            .puntuaciones th, .puntuaciones td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                            .puntuaciones th {{ background-color: #f2f2f2; }}
                            .consejo {{ background-color: #e7f5fe; padding: 15px; border-left: 4px solid #17a2b8; margin-top: 20px; }}
                            .footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; color: #6c757d; font-size: 0.8em; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>Informe de corrección textual</h1>
                            
                            <section>
                                <h2>Información general</h2>
                                <p><strong>Nombre:</strong> {nombre}</p>
                                <p><strong>Nivel:</strong> {nivel}</p>
                                <p><strong>Fecha:</strong> {fecha}</p>
                            </section>
                            
                            <section>
                                <h2>Texto original</h2>
                                <div class="original">
                                    <p>{texto.replace(chr(10), '<br>')}</p>
                                </div>
                                
                                <h2>Texto corregido</h2>
                                <div class="corregido">
                                    <p>{texto_corregido.replace(chr(10), '<br>')}</p>
                                </div>
                            </section>
                            
                            <section>
                                <h2>Análisis contextual</h2>
                                
                                <h3>Puntuaciones</h3>
                                <table class="puntuaciones">
                                    <tr>
                                        <th>Coherencia</th>
                                        <th>Cohesión</th>
                                        <th>Registro</th>
                                        <th>Adecuación cultural</th>
                                    </tr>
                                    <tr>
                                        <td>{analisis_contextual.get('coherencia', {}).get('puntuacion', 'N/A')}/10</td>
                                        <td>{analisis_contextual.get('cohesion', {}).get('puntuacion', 'N/A')}/10</td>
                                        <td>{analisis_contextual.get('registro_linguistico', {}).get('puntuacion', 'N/A')}/10</td>
                                        <td>{analisis_contextual.get('adecuacion_cultural', {}).get('puntuacion', 'N/A')}/10</td>
                                    </tr>
                                </table>
                            </section>
                            
                            <section>
                                <h2>Consejo final</h2>
                                <div class="consejo">
                                    <p>{consejo_final}</p>
                                </div>
                            </section>
                            
                            <div class="footer">
                                <p>Textocorrector ELE - Informe generado el {fecha} - Todos los derechos reservados</p>
                            </div>
                        </div>
                    </body>
                    </html>
                    """
                    
                    # Convertir a bytes para descargar
                    html_bytes = html_content.encode()
                    
                    # Botón de descarga
                    nombre_archivo = f"informe_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.html"
                    st.download_button(
                        label="📥 Descargar página HTML",
                        data=html_bytes,
                        file_name=nombre_archivo,
                        mime="text/html",
                        key="html_download"
                    )
                    
                    # Opción para previsualizar
                    with st.expander("Previsualizar HTML"):
                        st.markdown(f'<iframe srcdoc="{html_content.replace(chr(34), chr(39))}" width="100%" height="600"></iframe>', unsafe_allow_html=True)
                
                with export_tab3:
                    st.write("Exporta los datos del análisis en formato CSV")
                    
                    # Crear CSV en memoria directamente sin necesidad de un botón adicional
                    csv_buffer = StringIO()
                    
                    # Encabezados
                    csv_buffer.write("Categoría,Dato\n")
                    csv_buffer.write(f"Nombre,{nombre}\n")
                    csv_buffer.write(f"Nivel,{nivel}\n")
                    csv_buffer.write(f"Fecha,{fecha}\n")
                    csv_buffer.write(f"Errores Gramática,{num_gramatica}\n")
                    csv_buffer.write(f"Errores Léxico,{num_lexico}\n")
                    csv_buffer.write(f"Errores Puntuación,{num_puntuacion}\n")
                    csv_buffer.write(f"Errores Estructura,{num_estructura}\n")
                    csv_buffer.write(f"Total Errores,{total_errores}\n")
                    csv_buffer.write(f"Puntuación Coherencia,{puntuacion_coherencia}\n")
                    csv_buffer.write(f"Puntuación Cohesión,{puntuacion_cohesion}\n")
                    csv_buffer.write(f"Puntuación Registro,{puntuacion_registro}\n")
                    csv_buffer.write(f"Puntuación Adecuación Cultural,{puntuacion_adecuacion}\n")
                    
                    csv_bytes = csv_buffer.getvalue().encode()
                    
                    # Botón de descarga
                    nombre_archivo = f"datos_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.csv"
                    st.download_button(
                        label="📥 Descargar CSV",
                        data=csv_bytes,
                        file_name=nombre_archivo,
                        mime="text/csv",
                        key="csv_download"
                    )

            except Exception as e:
                st.error(f"Error al generar la corrección o guardar: {e}")
                import traceback
                st.code(traceback.format_exc())

# --- PESTAÑA 2: VER PROGRESO ---
with tab_progreso:
    st.header("Seguimiento del progreso")
    
    nombre_estudiante = st.text_input("Nombre y apellido del estudiante para ver progreso:", key="nombre_progreso")
    if nombre_estudiante and " " not in nombre_estudiante:
        st.warning("Por favor, introduce tanto el nombre como el apellido separados por un espacio.")
    
    if nombre_estudiante:
        with st.spinner("Cargando datos de progreso..."):
            try:
                df = obtener_historial_estudiante(nombre_estudiante, tracking_sheet)
                if df is not None and not df.empty:
                    mostrar_progreso(df)
                    
                    # Mostrar tabla con historial completo
                    with st.expander("Ver datos completos"):
                        st.dataframe(df)
                    
                    # Verificar si existe la columna Fecha
                    fecha_col = None
                    for col in df.columns:
                        if col.lower() == 'fecha':
                            fecha_col = col
                            break
                    
                    if fecha_col is not None:
                        # Consejo basado en tendencias
                        if len(df) >= 2:
                            st.subheader("Consejo basado en tendencias")
                            
                            # Calcular tendencias simples
                            df[fecha_col] = pd.to_datetime(df[fecha_col])
                            df = df.sort_values(fecha_col)
                            
                            # Extraer primera y última entrada para comparar
                            primera = df.iloc[0]
                            ultima = df.iloc[-1]
                            
                            # Comparar total de errores
                            dif_errores = ultima['Total Errores'] - primera['Total Errores']
                            
                            if dif_errores < 0:
                                st.success(f"¡Felicidades! Has reducido tus errores en {abs(dif_errores)} desde tu primera entrega.")
                            elif dif_errores > 0:
                                st.warning(f"Has aumentado tus errores en {dif_errores} desde tu primera entrega. Revisa las recomendaciones.")
                            else:
                                st.info("El número total de errores se mantiene igual. Sigamos trabajando en las áreas de mejora.")
                            
                            # Identificar área con mayor progreso y área que necesita más trabajo
                            categorias = ['Errores Gramática', 'Errores Léxico', 'Errores Puntuación', 'Errores Estructura']
                            difs = {}
                            for cat in categorias:
                                difs[cat] = ultima[cat] - primera[cat]
                            
                            mejor_area = min(difs.items(), key=lambda x: x[1])[0] if difs else None
                            peor_area = max(difs.items(), key=lambda x: x[1])[0] if difs else None
                            
                            if mejor_area and difs[mejor_area] < 0:
                                st.success(f"Mayor progreso en: {mejor_area.replace('Errores ', '')}")
                            
                            if peor_area and difs[peor_area] > 0:
                                st.warning(f"Área que necesita más trabajo: {peor_area.replace('Errores ', '')}")
                else:
                    st.info(f"No se encontraron datos para '{nombre_estudiante}' en el historial.")
                    
                    # Nuevo código para mostrar nombres disponibles
                    try:
                        todos_datos = tracking_sheet.get_all_records()
                        if todos_datos:
                            columnas = list(todos_datos[0].keys())
                            nombre_col = next((col for col in columnas if col.lower() == 'nombre'), None)
                            
                            if nombre_col:
                                nombres_disponibles = sorted(set(str(row.get(nombre_col, '')).strip() 
                                                             for row in todos_datos if row.get(nombre_col)))
                                
                                if nombres_disponibles:
                                    st.write("Nombres disponibles en el historial:")
                                    nombres_botones = []
                                    
                                    # Dividir en filas de 3 botones
                                    for i in range(0, len(nombres_disponibles), 3):
                                        fila = nombres_disponibles[i:i+3]
                                        cols = st.columns(3)
                                        for j, nombre in enumerate(fila):
                                            if j < len(fila) and cols[j].button(nombre, key=f"btn_{nombre}_{i+j}"):
                                                st.experimental_set_query_params(nombre_seleccionado=nombre)
                                                st.rerun()
                    except Exception as e:
                        st.error(f"Error al listar nombres disponibles: {e}")
            except Exception as e:
                st.error(f"Error al obtener historial: {e}")
                st.info("Detalles para depuración:")
                st.code(str(e))
                     

# --- PESTAÑA 3: HISTORIAL ---
with tab_historial:
    st.header("Historial de correcciones")
    
    try:
        # Obtener todas las correcciones
        correcciones = corrections_sheet.get_all_records()
        
        if correcciones:
            # Convertir a dataframe
            df_correcciones = pd.DataFrame(correcciones)
            
            # Normalizar nombres de columnas para la verificación (convertir a minúsculas)
            df_columns_lower = [col.lower() for col in df_correcciones.columns]
            
            # Filtrar columnas relevantes (verificando de forma más flexible)
            if 'nombre' in df_columns_lower or 'Nombre' in df_correcciones.columns:
                # Determinar los nombres reales de las columnas
                nombre_col = 'Nombre' if 'Nombre' in df_correcciones.columns else 'nombre'
                nivel_col = 'Nivel' if 'Nivel' in df_correcciones.columns else 'nivel'
                fecha_col = 'Fecha' if 'Fecha' in df_correcciones.columns else 'fecha'
                
                # Verificar que todas las columnas existan
                if nombre_col in df_correcciones.columns and nivel_col in df_correcciones.columns and fecha_col in df_correcciones.columns:
                    df_display = df_correcciones[[nombre_col, nivel_col, fecha_col]]
                    
                    # Mostrar tabla de historial
                    st.dataframe(df_display)
                    
                    # Opciones para ver detalles
                    if st.checkbox("Ver detalles de una corrección"):
                        # Extraer nombres únicos
                        nombres = sorted(df_correcciones[nombre_col].unique().tolist())
                        
                        # Selector de nombre
                        nombre_select = st.selectbox("Selecciona un nombre:", nombres)
                        
                        # Filtrar por nombre
                        correcciones_filtradas = df_correcciones[df_correcciones[nombre_col] == nombre_select]
                        
                        # Extraer fechas para este nombre
                        fechas = correcciones_filtradas[fecha_col].tolist()
                        
                        # Selector de fecha
                        fecha_select = st.selectbox("Selecciona una fecha:", fechas)
                        
                        # Mostrar corrección seleccionada
                        correccion = correcciones_filtradas[correcciones_filtradas[fecha_col] == fecha_select].iloc[0]
                        
                        # Mostrar detalles
                        st.subheader(f"Corrección para {nombre_select} ({fecha_select})")
                        
                        # Pestañas para texto original y datos
                        tab_original, tab_datos = st.tabs(["Texto original", "Datos de corrección"])
                        
                        with tab_original:
                            texto_col = 'texto' if 'texto' in df_correcciones.columns else 'Texto'
                            if texto_col in correccion:
                                st.write(correccion.get(texto_col, 'No disponible'))
                            else:
                                st.warning("No se pudo encontrar el texto original.")
                        
                        with tab_datos:
                            try:
                                # Intentar parsear el JSON de la respuesta
                                raw_output_col = 'raw_output' if 'raw_output' in df_correcciones.columns else 'Raw_output'
                                if raw_output_col in correccion:
                                    raw_output = correccion.get(raw_output_col, '{}')
                                    data_json = json.loads(raw_output)
                                    
                                    # Mostrar campos específicos
                                    if 'texto_corregido' in data_json:
                                        st.subheader("Texto corregido")
                                        st.write(data_json['texto_corregido'])
                                    
                                    if 'consejo_final' in data_json:
                                        st.subheader("Consejo final")
                                        st.info(data_json['consejo_final'])
                                else:
                                    st.warning("No se encontraron datos de corrección.")
                            except json.JSONDecodeError:
                                st.warning("No se pudieron cargar los datos de corrección en formato estructurado.")
                                st.code(raw_output[:500] + "...")  # Mostrar parte del texto crudo
                else:
                    st.warning("Algunas columnas necesarias no se encuentran en los datos. Columnas disponibles: " + ", ".join(df_correcciones.columns))
            else:
                st.warning("El formato de los datos no coincide con lo esperado. Columnas disponibles: " + ", ".join(df_correcciones.columns))
        else:
            st.info("No hay correcciones guardadas en el historial.")
    except Exception as e:
        st.error(f"Error al cargar el historial: {e}")
        st.code(str(e))  # Mostrar el error para depuración

# --- PESTAÑA 4: HERRAMIENTAS (NUEVA) ---
with tab_herramientas:
    st.header("🛠️ Herramientas de escritura")
    
    herramienta_tabs = st.tabs(["📝 Editor asistido", "📊 Análisis de complejidad", "📚 Biblioteca de recursos"])
    
    # --- Subpestaña 1: Editor asistido ---
    with herramienta_tabs[0]:
        st.subheader("Editor de texto con asistencia")
        st.markdown("""
           Usa este editor para practicar tu escritura en español con asistencia.
            Escribe tu texto y haz clic en "Verificar texto" para recibir sugerencias.
    """)
        
        # Nivel para editor asistido
        nivel_editor = st.selectbox(
            "Nivel de español:", 
            ["principiante", "intermedio", "avanzado"],
            key="nivel_editor"
        )
        st.session_state.nivel_estudiante = nivel_editor
        
        # Usar el asistente de escritura
        texto_practica = writing_assistant.render_text_editor_with_assistance(
                key="texto_practica",
                 height=350,
                 default_value="Comienza a escribir aquí para practicar tu español...",
                 with_assistant=True
        )
        
        # Botones de acción
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Guardar como borrador"):
                if 'borradores' not in st.session_state:
                    st.session_state.borradores = []
                
                if texto_practica and len(texto_practica.strip()) > 10:
                    from datetime import datetime
                    nuevo_borrador = {
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "texto": texto_practica,
                        "nivel": nivel_editor
                    }
                    st.session_state.borradores.append(nuevo_borrador)
                    st.success("✅ Borrador guardado correctamente.")
                else:
                    st.warning("⚠️ El texto es demasiado corto para guardarlo.")
        
        with col2:
            if st.button("Limpiar editor"):
                st.session_state.texto_practica = ""
                st.experimental_rerun()
        
        # Mostrar borradores guardados
        if 'borradores' in st.session_state and st.session_state.borradores:
            with st.expander("Borradores guardados", expanded=False):
                for i, borrador in enumerate(st.session_state.borradores):
                    st.markdown(f"**Borrador {i+1}** - {borrador['fecha']} (Nivel: {borrador['nivel']})")
                    st.text_area(f"Texto del borrador {i+1}", 
                                value=borrador['texto'], 
                                height=100,
                                key=f"borrador_{i}",
                                disabled=True)
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        if st.button("Cargar", key=f"load_{i}"):
                            st.session_state.texto_practica = borrador['texto']
                            st.experimental_rerun()
                    with col2:
                        if st.button("Eliminar", key=f"delete_{i}"):
                            st.session_state.borradores.pop(i)
                            st.experimental_rerun()
                    st.divider()
    
    # --- Subpestaña 2: Análisis de complejidad ---
    with herramienta_tabs[1]:
        st.subheader("Próximamente: Análisis de complejidad textual")
        st.markdown("""
        Esta herramienta te permitirá analizar la complejidad de tus textos, evaluando:
        
        - Riqueza léxica y variedad de vocabulario
        - Complejidad sintáctica
        - Uso de conectores y elementos cohesivos
        - Adecuación al nivel objetivo
        
        ¡Próximamente disponible!
        """)
    
    # --- Subpestaña 3: Biblioteca de recursos ---
    with herramienta_tabs[2]:
        st.subheader("Próximamente: Biblioteca de recursos")
        st.markdown("""
        Accede a una biblioteca de recursos para mejorar tu escritura:
        
        - Modelos de textos por género y nivel
        - Plantillas para diferentes contextos comunicativos
        - Guías de estructura textual
        - Listas de vocabulario y conectores recomendados
        
        ¡Próximamente disponible!
        """)






