import streamlit as st
import json
import gspread
import requests
import re
import pandas as pd
import matplotlib.pyplot as plt
import altair as alt
import time
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

# Función para extraer título de sección del plan de estudio
def extraer_titulo(texto):
    """
    Extrae el título de una sección del plan de estudio.
    
    Args:
        texto (str): Texto de la sección
        
    Returns:
        str: Título extraído
    """
    lineas = texto.strip().split("\n")
    if lineas and lineas[0]:
        return lineas[0].strip()
    return "Contenido sin título"

# Función para obtener duración de examen
def obtener_duracion_examen(tipo_examen, nivel_examen):
    """
    Obtiene la duración en segundos para un simulacro según el tipo y nivel de examen.
    
    Args:
        tipo_examen (str): Tipo de examen (DELE, SIELE, etc.)
        nivel_examen (str): Nivel del examen (A1, A2, etc.)
        
    Returns:
        int: Duración en segundos
    """
    # Mapeo de duraciones según examen y nivel
    duraciones = {
        "DELE": {
            "A1": 25 * 60,  # 25 minutos
            "A2": 30 * 60,
            "B1": 40 * 60,
            "B2": 60 * 60,
            "C1": 80 * 60,
            "C2": 90 * 60
        },
        "SIELE": {
            "A1": 20 * 60,
            "A2": 25 * 60,
            "B1": 35 * 60,
            "B2": 50 * 60,
            "C1": 70 * 60,
            "C2": 80 * 60
        },
        # Otros exámenes
    }
    
    return duraciones.get(tipo_examen, {}).get(nivel_examen, 45 * 60)  # Default: 45 minutos

# Función para obtener criterios de evaluación
def obtener_criterios_evaluacion(tipo_examen, nivel_examen):
    """
    Obtiene los criterios de evaluación para un examen y nivel específicos.
    
    Args:
        tipo_examen (str): Tipo de examen (DELE, SIELE, etc.)
        nivel_examen (str): Nivel del examen (A1, A2, etc.)
        
    Returns:
        str: Criterios de evaluación en formato markdown
    """
    # Criterios genéricos por defecto
    criterios_default = """
    ## Criterios de evaluación genéricos

    ### Adecuación al contexto
    - Ajuste a la tarea solicitada
    - Adecuación al registro requerido
    - Cumplimiento del propósito comunicativo

    ### Coherencia y cohesión
    - Organización lógica de las ideas
    - Uso adecuado de conectores
    - Desarrollo temático apropiado

    ### Corrección gramatical
    - Uso adecuado de estructuras gramaticales
    - Control de tiempos verbales
    - Concordancia nominal y verbal

    ### Riqueza léxica
    - Variedad y precisión del vocabulario
    - Uso apropiado de expresiones idiomáticas
    - Evitar repeticiones innecesarias
    """
    
    # Criterios específicos para DELE
    if tipo_examen == "DELE":
        if nivel_examen in ["A1", "A2"]:
            return """
            ## Criterios de evaluación DELE A1-A2
            
            ### Adecuación al contexto (25%)
            - Cumple con la tarea solicitada
            - Se ajusta a la extensión requerida
            - Emplea el registro adecuado (formal/informal)
            
            ### Coherencia textual (25%)
            - Las ideas están organizadas con lógica
            - Usa conectores básicos (y, pero, porque)
            - Información relevante y comprensible
            
            ### Corrección gramatical (25%)
            - Uso correcto de estructuras básicas
            - Control de presente y pasados simples
            - Concordancia nominal y verbal básica
            
            ### Alcance y control léxico (25%)
            - Vocabulario básico suficiente
            - Ortografía de palabras frecuentes
            - Expresiones memorizadas adecuadas
            """
        elif nivel_examen in ["B1", "B2"]:
            return """
            ## Criterios de evaluación DELE B1-B2
            
            ### Adecuación a la tarea (20%)
            - Cumple los puntos requeridos en la tarea
            - Se ajusta a la extensión y formato
            - Registro adecuado al destinatario y propósito
            
            ### Coherencia y cohesión (20%)
            - Progresión temática clara
            - Uso variado de conectores y marcadores
            - Estructura textual apropiada al género
            
            ### Corrección gramatical (30%)
            - Estructuras variadas con pocos errores
            - Buen control de tiempos y modos verbales
            - Uso adecuado de subordinación
            
            ### Alcance y control léxico (30%)
            - Vocabulario preciso y variado
            - Pocas confusiones o imprecisiones léxicas
            - Ortografía y puntuación generalmente correctas
            """
        else:  # C1-C2
            return """
            ## Criterios de evaluación DELE C1-C2
            
            ### Adecuación a la tarea (20%)
            - Desarrollo completo y matizado de todos los puntos
            - Formato y extensión perfectamente ajustados
            - Registro sofisticado y perfectamente adaptado
            
            ### Coherencia y cohesión (20%)
            - Estructura textual compleja y elaborada
            - Amplia variedad de mecanismos de cohesión
            - Desarrollo argumentativo sofisticado
            
            ### Corrección gramatical (30%)
            - Uso preciso y flexible de estructuras complejas
            - Control de aspectos sutiles de la gramática
            - Errores escasos y poco significativos
            
            ### Alcance y control léxico (30%)
            - Vocabulario amplio, preciso y natural
            - Uso adecuado de expresiones idiomáticas
            - Pleno control de matices y connotaciones
            """
    
    # Criterios específicos para SIELE (simplificados)
    elif tipo_examen == "SIELE":
        return """
        ## Criterios de evaluación SIELE
        
        ### Coherencia textual (25%)
        - Organización lógica del contenido
        - Desarrollo adecuado de las ideas
        - Uso de conectores apropiados al nivel
        
        ### Corrección lingüística (25%)
        - Control gramatical según el nivel
        - Precisión léxica adecuada
        - Ortografía y puntuación
        
        ### Adecuación al contexto (25%)
        - Cumplimiento de la tarea solicitada
        - Registro apropiado a la situación
        - Longitud del texto según lo requerido
        
        ### Alcance lingüístico (25%)
        - Variedad de recursos gramaticales
        - Riqueza de vocabulario
        - Complejidad apropiada al nivel
        """
    
    # Por defecto, devolvemos criterios genéricos
    return criterios_default

# --- 3. ESTRUCTURA DE LA APLICACIÓN ---
st.title("📝 Textocorrector ELE")
st.markdown("Corrige tus textos escritos y guarda automáticamente el feedback con análisis contextual avanzado. Creado por el profesor Diego Medina")

# Pestañas principales - ESTRUCTURA REORGANIZADA
tab_corregir, tab_progreso, tab_historial, tab_examenes, tab_herramientas = st.tabs([
    "📝 Corregir texto", 
    "📊 Ver progreso", 
    "📚 Historial", 
    "🎓 Preparación para exámenes",
    "🔧 Herramientas complementarias"
])

# --- PESTAÑA 1: CORREGIR TEXTO (Con generador de consignas integrado) ---
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

    # Formulario de corrección con clave única
    with st.form(key="formulario_corregir"):
        nombre = st.text_input("Nombre y apellido:", key="nombre_corregir")
        if nombre and " " not in nombre:
            st.warning("Por favor, introduce tanto el nombre como el apellido separados por un espacio.")
        
        nivel = st.selectbox("¿Cuál es tu nivel?", [
            "Nivel principiante (A1-A2)",
            "Nivel intermedio (B1-B2)",
            "Nivel avanzado (C1-C2)"
        ], key="nivel_corregir")
        
        # Guardar nivel en formato simplificado para el asistente
        nivel_map = {
            "Nivel principiante (A1-A2)": "principiante",
            "Nivel intermedio (B1-B2)": "intermedio",
            "Nivel avanzado (C1-C2)": "avanzado"
        }
        st.session_state.nivel_estudiante = nivel_map.get(nivel, "intermedio")
        
        # NUEVO: Generador de consignas integrado
        with st.expander("¿No sabes qué escribir? Yo te ayudo...", expanded=False):
            tipo_consigna = st.selectbox(
                "Tipo de texto a escribir:",
                [
                    "Cualquiera (aleatorio)",
                    "Narración",
                    "Correo/Carta formal",
                    "Opinión/Argumentación",
                    "Descripción",
                    "Diálogo"
                ],
                key="tipo_consigna_corregir"
            )
            
            if st.button("Generar consigna de escritura", key="generar_consigna"):
                with st.spinner("Generando consigna adaptada a tu nivel..."):
                    # Determinar el nivel para la IA
                    nivel_actual = nivel_map.get(nivel, "intermedio")
                    
                    # Construir prompt para OpenAI
                    prompt_consigna = f"""
                    Genera una consigna de escritura breve para un estudiante de español de nivel {nivel_actual}.
                    """
                    
                    if tipo_consigna != "Cualquiera (aleatorio)":
                        prompt_consigna += f" La consigna debe ser para escribir un texto de tipo: {tipo_consigna}."
                        
                    # Añadir contexto según nivel
                    if nivel_actual == "principiante":
                        prompt_consigna += " Debe ser muy sencilla, con vocabulario básico, usando presente y pasado simple principalmente."
                    elif nivel_actual == "intermedio":
                        prompt_consigna += " Debe tener complejidad moderada, permitiendo usar diversos tiempos verbales y expresar opiniones."
                    else:
                        prompt_consigna += " Debe ser desafiante, permitiendo argumentación compleja, uso de expresiones idiomáticas y matices."
                    
                    prompt_consigna += " La consigna debe ser motivadora y creativa, similar a las de los exámenes DELE o SIELE."
                    
                    # Llamar a la API
                    client = OpenAI(api_key=openai_api_key)
                    response = client.chat.completions.create(
                        model="gpt-4-turbo",
                        temperature=0.8,
                        messages=[
                            {"role": "system", "content": "Eres un profesor de español experto en diseñar actividades de escritura."},
                            {"role": "user", "content": prompt_consigna}
                        ]
                    )
                    
                    # Obtener resultado
                    consigna_generada = response.choices[0].message.content.strip()
                    
                    # Guardar en session_state para usarlo en el formulario
                    st.session_state.consigna_actual = consigna_generada
                
                # Mostrar la consigna generada
                st.success("✨ Consigna generada:")
                st.info(st.session_state.consigna_actual)
                
                # Opcional: botón para usar esta consigna
                if st.button("Usar esta consigna como contexto", key="usar_consigna"):
                    # Setear el texto de información adicional
                    st.session_state.info_adicional_corregir = f"Consigna: {st.session_state.consigna_actual}"
                    st.rerun()  # Recargar para actualizar el formulario
        
        # Continúa el formulario original
        idioma = st.selectbox("Selecciona lenguaje para la corrección", ["Español", "Francés", "Inglés"], key="idioma_corregir")
        
        col1, col2 = st.columns(2)
        with col1:
            tipo_texto = st.selectbox("Tipo de texto", [
                "General/No especificado",
                "Académico",
                "Profesional/Laboral",
                "Informal/Cotidiano",
                "Creativo/Literario"
            ], key="tipo_texto_corregir")
        
        with col2:
            contexto_cultural = st.selectbox("Contexto cultural", [
                "General/Internacional",
                "España",
                "Latinoamérica",
                "Contexto académico",
                "Contexto empresarial"
            ], key="contexto_cultural_corregir")
        
        # Texto inicial con contenido de la consigna si está disponible
        texto_inicial = ""
        if "info_adicional_corregir" in st.session_state and "consigna_actual" in st.session_state:
            texto_inicial = f"[Instrucción: {st.session_state.consigna_actual}]\n\n"
        
        # Área de texto para la corrección
        texto = st.text_area(
            "Escribe tu texto aquí:",
            value=texto_inicial,
            height=250,
            key="texto_correccion_corregir"
        )
        
        info_adicional = st.text_area("Información adicional o contexto (opcional):", height=100, key="info_adicional_corregir")
        
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
                                key="docx_download_corregir"
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
                            key="html_download_corregir"
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
                            key="csv_download_corregir"
                        )

                except Exception as e:
                    st.error(f"Error al generar la corrección o guardar: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    # --- PESTAÑA 2: VER PROGRESO ---
with tab_progreso:
    st.header("Seguimiento del progreso")
    
    # Subtabs para diferentes vistas de progreso
    subtab_estadisticas, subtab_plan_estudio = st.tabs([
        "Estadísticas", "Plan de estudio personalizado"
    ])
    
    with subtab_estadisticas:
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
                                                if j < len(fila) and cols[j].button(nombre, key=f"btn_progreso_{nombre}_{i+j}"):
                                                    st.experimental_set_query_params(nombre_seleccionado=nombre)
                                                    st.rerun()
                        except Exception as e:
                            st.error(f"Error al listar nombres disponibles: {e}")
                except Exception as e:
                    st.error(f"Error al obtener historial: {e}")
                    st.info("Detalles para depuración:")
                    st.code(str(e))
    
    # NUEVO: Plan de estudio personalizado
    with subtab_plan_estudio:
        st.header("📚 Plan de estudio personalizado")
        
        nombre_estudiante_plan = st.text_input("Nombre y apellido:", key="nombre_plan_estudio")
        
        if nombre_estudiante_plan and " " not in nombre_estudiante_plan:
            st.warning("Por favor, introduce tanto el nombre como el apellido separados por un espacio.")
        
        if nombre_estudiante_plan:
            with st.spinner("Analizando tu historial de errores y generando plan personalizado..."):
                # Obtener historial del estudiante
                df = obtener_historial_estudiante(nombre_estudiante_plan, tracking_sheet)
                
                if df is not None and not df.empty:
                    # Analizar patrones de error frecuentes
                    # Suponemos que tenemos estas columnas en el df
                    if 'Errores Gramática' in df.columns and 'Errores Léxico' in df.columns:
                        # Extraer estadísticas básicas
                        promedio_gramatica = df['Errores Gramática'].mean()
                        promedio_lexico = df['Errores Léxico'].mean()
                        
                        # Verificar si tenemos las columnas contextuales
                        coherencia_promedio = df['Puntuación Coherencia'].mean() if 'Puntuación Coherencia' in df.columns else 5
                        cohesion_promedio = df['Puntuación Cohesión'].mean() if 'Puntuación Cohesión' in df.columns else 5
                        
                        # Extraer nivel del último registro
                        if 'Nivel' in df.columns:
                            nivel_actual = df.iloc[-1]['Nivel']
                        else:
                            nivel_actual = "intermedio"
                        
                        # Verificar si tenemos consejos finales para extraer temas recurrentes
                        temas_recurrentes = []
                        if 'Consejo Final' in df.columns:
                            # Aquí podríamos implementar un análisis más sofisticado de los consejos
                            temas_recurrentes = ["conjugación verbal", "uso de preposiciones", "concordancia"]
                        
                        # Construir contexto para la IA
                        errores_frecuentes = (
                            f"Promedio de errores gramaticales: {promedio_gramatica:.1f}, "
                            f"Promedio de errores léxicos: {promedio_lexico:.1f}. "
                            f"Puntuación en coherencia: {coherencia_promedio:.1f}/10, "
                            f"Puntuación en cohesión: {cohesion_promedio:.1f}/10. "
                            f"Temas recurrentes: {', '.join(temas_recurrentes)}."
                        )
                        
                        # Generar plan de estudio con IA
                        client = OpenAI(api_key=openai_api_key)
                        
                        response = client.chat.completions.create(
                            model="gpt-4-turbo",
                            temperature=0.7,
                            messages=[
                                {"role": "system", "content": "Eres un experto en diseño curricular ELE que crea planes de estudio personalizados."},
                                {"role": "user", "content": f"Crea un plan de estudio personalizado para un estudiante de nivel {nivel_actual} con los siguientes errores frecuentes: {errores_frecuentes} Organiza el plan por semanas (4 semanas) con objetivos claros, actividades concretas y recursos recomendados."}
                            ]
                        )
                        
                        plan_estudio = response.choices[0].message.content
                        
                        # Mostrar el plan en pestañas organizadas por semanas
                        semanas = plan_estudio.split("Semana")  # Podría necesitar ajustes según el formato de salida
                        
                        st.markdown("### Tu plan de estudio personalizado")
                        st.markdown("Basado en tu historial de errores, hemos creado este plan de estudio de 4 semanas para ayudarte a mejorar tus habilidades:")
                        
                        for i, semana in enumerate(semanas[1:], 1):  # Ignorar el elemento vacío al inicio
                            titulo_semana = extraer_titulo(semana)
                            with st.expander(f"Semana {i}: {titulo_semana}"):
                                st.markdown(semana)
                                
                                # Generar ejercicios específicos para esta parte
                                if st.button(f"Generar ejercicios para Semana {i}", key=f"ejercicios_semana_{i}"):
                                    with st.spinner("Creando ejercicios personalizados..."):
                                        prompt_ejercicios = f"Crea 2 ejercicios breves para practicar los temas de la semana {i} del plan: {semana[:300]}... Los ejercicios deben ser específicos para un estudiante de nivel {nivel_actual}."
                                        
                                        response_ej = client.chat.completions.create(
                                            model="gpt-4-turbo",
                                            temperature=0.7,
                                            messages=[
                                                {"role": "system", "content": "Eres un profesor de español especializado en crear actividades didácticas."},
                                                {"role": "user", "content": prompt_ejercicios}
                                            ]
                                        )
                                        
                                        ejercicios = response_ej.choices[0].message.content
                                        st.markdown("#### Ejercicios recomendados")
                                        st.markdown(ejercicios)
                    else:
                        st.warning("No se encontraron columnas de errores en los datos. El análisis no puede ser completo.")
                else:
                    st.info("No tenemos suficientes datos para generar un plan personalizado. Realiza al menos 3 correcciones de texto para activar esta función.")

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
                    if st.checkbox("Ver detalles de una corrección", key="checkbox_historial"):
                        # Extraer nombres únicos
                        nombres = sorted(df_correcciones[nombre_col].unique().tolist())
                        
                        # Selector de nombre
                        nombre_select = st.selectbox("Selecciona un nombre:", nombres, key="nombre_select_historial")
                        
                        # Filtrar por nombre
                        correcciones_filtradas = df_correcciones[df_correcciones[nombre_col] == nombre_select]
                        
                        # Extraer fechas para este nombre
                        fechas = correcciones_filtradas[fecha_col].tolist()
                        
                        # Selector de fecha
                        fecha_select = st.selectbox("Selecciona una fecha:", fechas, key="fecha_select_historial")
                        
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

# --- PESTAÑA 4: PREPARACIÓN PARA EXÁMENES (NUEVA) ---
with tab_examenes:
    st.header("🎓 Preparación para exámenes oficiales")
    
    # Selector de examen y nivel
    col1, col2 = st.columns(2)
    with col1:
        tipo_examen = st.selectbox(
            "Examen oficial:",
            ["DELE", "SIELE", "CELU", "DUCLE"],
            key="tipo_examen"
        )
    
    with col2:
        nivel_examen = st.selectbox(
            "Nivel:",
            ["A1", "A2", "B1", "B2", "C1", "C2"],
            key="nivel_examen"
        )
    
    # Pestañas para las diferentes funcionalidades
    tabs_examen = st.tabs(["Modelo de examen", "Simulacro cronometrado", "Criterios de evaluación"])
    
    with tabs_examen[0]:
        st.subheader("Modelo de prueba escrita")
        st.markdown("""
        Aquí encontrarás un modelo de tarea de expresión escrita similar a la que encontrarás en el examen.
        Practica sin límite de tiempo y recibe correcciones detalladas.
        """)
        
        if st.button("Generar tarea de examen", key="generar_tarea_examen"):
            # Generar tarea específica para el examen y nivel seleccionados
            with st.spinner("Generando tarea oficial..."):
                client = OpenAI(api_key=openai_api_key)
                
                prompt_tarea = f"""
                Crea una tarea de expresión escrita para el examen {tipo_examen} de nivel {nivel_examen}.
                La tarea debe incluir:
                1. Instrucciones claras y precisas
                2. Contexto o situación comunicativa
                3. Número de palabras requerido
                4. Aspectos que se evaluarán
                
                El formato debe ser idéntico al que aparece en los exámenes oficiales {tipo_examen}.
                """
                
                response = client.chat.completions.create(
                    model="gpt-4-turbo",
                    temperature=0.7,
                    messages=[
                        {"role": "system", "content": "Eres un experto en exámenes oficiales de español como lengua extranjera."},
                        {"role": "user", "content": prompt_tarea}
                    ]
                )
                
                tarea_generada = response.choices[0].message.content
                
                # Mostrar la tarea
                st.success("✅ Tarea generada correctamente")
                st.markdown(tarea_generada)
                
                # Opción para usar esta tarea en la sección de corrección
                if st.button("Usar esta tarea para practicar", key="usar_tarea_examen"):
                    # Guardar en session_state para usarlo en el formulario de corrección
                    st.session_state.info_adicional_corregir = f"Tarea {tipo_examen} {nivel_examen}: {tarea_generada}"
                    # Redirigir a la pestaña de corrección (experimental)
                    st.write("Redirigiendo a la pestaña de corrección...")
                    st.script_runner.script_request("click_element", {"selector": "button[data-baseweb='tab'][title='📝 Corregir texto']"})
    
    with tabs_examen[1]:
        st.subheader("Simulacro cronometrado")
        st.markdown("""
        Pon a prueba tus habilidades bajo las condiciones reales del examen.
        Esta prueba está cronometrada según los tiempos oficiales.
        """)
        
        tiempo_restante = st.empty()
        
        if "inicio_simulacro" not in st.session_state:
            if st.button("Iniciar simulacro", key="iniciar_simulacro"):
                # Configurar el temporizador
                st.session_state.inicio_simulacro = time.time()
                st.session_state.duracion_simulacro = obtener_duracion_examen(tipo_examen, nivel_examen)
                st.rerun()
        else:
            # Calcular tiempo transcurrido
            tiempo_transcurrido = time.time() - st.session_state.inicio_simulacro
            tiempo_restante_segundos = max(0, st.session_state.duracion_simulacro - tiempo_transcurrido)
            
            # Formatear tiempo restante
            minutos = int(tiempo_restante_segundos // 60)
            segundos = int(tiempo_restante_segundos % 60)
            
            # Mostrar temporizador
            tiempo_restante.warning(f"⏱️ Tiempo restante: {minutos:02d}:{segundos:02d}")
            
            # Generar tarea para el simulacro si no existe
            if "tarea_simulacro" not in st.session_state:
                with st.spinner("Generando tarea para el simulacro..."):
                    client = OpenAI(api_key=openai_api_key)
                    
                    prompt_tarea = f"""
                    Crea una tarea de expresión escrita para el examen {tipo_examen} de nivel {nivel_examen}.
                    La tarea debe ser concisa e incluir:
                    1. Instrucciones claras
                    2. Contexto comunicativo
                    3. Extensión requerida
                    """
                    
                    response = client.chat.completions.create(
                        model="gpt-4-turbo",
                        temperature=0.7,
                        messages=[
                            {"role": "system", "content": "Eres un experto en exámenes oficiales de español."},
                            {"role": "user", "content": prompt_tarea}
                        ]
                    )
                    
                    st.session_state.tarea_simulacro = response.choices[0].message.content
            
            # Mostrar la tarea
            st.markdown("### Tarea:")
            st.markdown(st.session_state.tarea_simulacro)
            
            # Área de texto para respuesta
            simulacro_respuesta = st.text_area(
                "Tu respuesta:",
                height=300,
                key="simulacro_respuesta"
            )
            
            # Opciones para finalizar o reiniciar
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Finalizar simulacro", key="finalizar_simulacro"):
                    # Limpiar variables del simulacro
                    tiempo_final = time.time() - st.session_state.inicio_simulacro
                    minutos_usados = int(tiempo_final // 60)
                    segundos_usados = int(tiempo_final % 60)
                    
                    st.session_state.tiempo_usado = f"{minutos_usados:02d}:{segundos_usados:02d}"
                    st.session_state.respuesta_final = simulacro_respuesta
                    
                    # Limpiar variables de control
                    del st.session_state.inicio_simulacro
                    del st.session_state.duracion_simulacro
                    
                    st.success(f"Simulacro completado en {st.session_state.tiempo_usado}")
                    st.rerun()
            
            with col2:
                if st.button("Reiniciar simulacro", key="reiniciar_simulacro"):
                    # Limpiar todas las variables del simulacro
                    for key in ["inicio_simulacro", "duracion_simulacro", "tarea_simulacro"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()
            
            # Verificar si se acabó el tiempo
            if tiempo_restante_segundos <= 0:
                st.error("⏰ ¡Tiempo agotado! Finaliza tu respuesta y envíala.")
            
            # Mostrar la respuesta final si existe
            if "respuesta_final" in st.session_state:
                st.subheader("Tu respuesta final:")
                st.write(f"Tiempo utilizado: {st.session_state.tiempo_usado}")
                st.write(st.session_state.respuesta_final)
                
                # Opción para corregir
                if st.button("Enviar para corrección", key="corregir_simulacro"):
                    st.session_state.texto_correccion_corregir = st.session_state.respuesta_final
                    st.session_state.info_adicional_corregir = f"Simulacro {tipo_examen} {nivel_examen}: {st.session_state.tarea_simulacro}"
                    # Redirigir a pestaña de corrección (experimental)
                    st.write("Redirigiendo a la pestaña de corrección...")
                    st.script_runner.script_request("click_element", {"selector": "button[data-baseweb='tab'][title='📝 Corregir texto']"})
    
    with tabs_examen[2]:
        st.subheader("Criterios de evaluación")
        st.markdown("""
        Conocer cómo se evalúa tu texto es fundamental para prepararte adecuadamente.
        Aquí encontrarás las rúbricas oficiales y ejemplos de textos evaluados.
        """)
        
        # Mostrar los criterios específicos según el examen seleccionado
        criterios = obtener_criterios_evaluacion(tipo_examen, nivel_examen)
        st.markdown(criterios)
        
        # Opción para ver ejemplos evaluados
        if st.button("Ver ejemplos de textos evaluados", key="ver_ejemplos_evaluados"):
            with st.spinner("Generando ejemplos..."):
                client = OpenAI(api_key=openai_api_key)
                
                prompt_ejemplos = f"""
                Genera un ejemplo de texto de un estudiante para el examen {tipo_examen} nivel {nivel_examen}, 
                junto con una evaluación detallada usando los criterios oficiales.
                Muestra: 
                1. La tarea solicitada
                2. El texto del estudiante (con algunos errores típicos)
                3. Evaluación punto por punto según los criterios
                4. Puntuación desglosada y comentarios
                """
                
                response = client.chat.completions.create(
                    model="gpt-4-turbo",
                    temperature=0.7,
                    messages=[
                        {"role": "system", "content": "Eres un evaluador experto de exámenes oficiales de español."},
                        {"role": "user", "content": prompt_ejemplos}
                    ]
                )
                
                ejemplos = response.choices[0].message.content
                st.markdown(ejemplos)

    # --- PESTAÑA 5: HERRAMIENTAS COMPLEMENTARIAS (RENOMBRADA) ---
with tab_herramientas:
    st.header("🔧 Herramientas complementarias")
    
    # Rediseño: Ahora solo contiene herramientas verdaderamente complementarias
    subtab_complejidad, subtab_recursos = st.tabs([
        "Análisis de complejidad", "Biblioteca de recursos"
    ])
    
    # --- Subpestaña 1: Análisis de complejidad ---
    with subtab_complejidad:
        st.subheader("Análisis de complejidad textual")
        st.markdown("""
        Esta herramienta analiza la complejidad léxica, sintáctica y estructural de tu texto 
        para ayudarte a entender tu nivel actual y cómo mejorar.
        """)
        
        # Código para el análisis de complejidad
        texto_analisis = st.text_area(
            "Ingresa el texto a analizar:",
            height=200,
            key="texto_analisis"
        )
        
        if st.button("Analizar complejidad", key="analizar_complejidad") and texto_analisis.strip():
            with st.spinner("Analizando la complejidad de tu texto..."):
                # Llamada a la API para analizar complejidad
                client = OpenAI(api_key=openai_api_key)
                
                prompt_analisis = f"""
                Analiza la complejidad lingüística del siguiente texto en español. 
                Proporciona un análisis detallado que incluya:
                
                1. Complejidad léxica (variedad de vocabulario, riqueza léxica, palabras poco comunes)
                2. Complejidad sintáctica (longitud de frases, subordinación, tipos de oraciones)
                3. Complejidad textual (coherencia, cohesión, estructura general)
                4. Nivel MCER estimado (A1-C2) con explicación
                5. Índices estadísticos: TTR (type-token ratio), densidad léxica, índice Flesh-Szigriszt (adaptado al español)
                
                Texto a analizar:
                "{texto_analisis}"
                
                Devuelve el análisis en formato JSON con la siguiente estructura:
                {{
                  "complejidad_lexica": {{
                    "nivel": "string",
                    "descripcion": "string",
                    "palabras_destacadas": ["string1", "string2"]
                  }},
                  "complejidad_sintactica": {{
                    "nivel": "string",
                    "descripcion": "string",
                    "estructuras_destacadas": ["string1", "string2"]
                  }},
                  "complejidad_textual": {{
                    "nivel": "string",
                    "descripcion": "string"
                  }},
                  "nivel_mcer": {{
                    "nivel": "string",
                    "justificacion": "string"
                  }},
                  "indices": {{
                    "ttr": number,
                    "densidad_lexica": number,
                    "szigriszt": number,
                    "interpretacion": "string"
                  }},
                  "recomendaciones": ["string1", "string2"]
                }}
                """
                
                response = client.chat.completions.create(
                    model="gpt-4-turbo",
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": "Eres un experto lingüista y analista textual especializado en complejidad lingüística."},
                        {"role": "user", "content": prompt_analisis}
                    ]
                )
                
                try:
                    # Extraer JSON de la respuesta
                    content = response.choices[0].message.content
                    match = re.search(r"\{.*\}", content, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                        analisis_data = json.loads(json_str)
                        
                        # Mostrar resultados
                        st.subheader("Resultados del análisis")
                        
                        # Nivel MCER estimado
                        nivel_mcer = analisis_data.get("nivel_mcer", {})
                        st.info(f"📊 **Nivel MCER estimado: {nivel_mcer.get('nivel', 'No disponible')}**")
                        st.write(nivel_mcer.get("justificacion", ""))
                        
                        # Métricas principales en columnas
                        indices = analisis_data.get("indices", {})
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("TTR", f"{indices.get('ttr', 0):.2f}")
                            st.caption("Ratio tipo/token - variedad léxica")
                        with col2:
                            st.metric("Densidad léxica", f"{indices.get('densidad_lexica', 0):.2f}")
                            st.caption("Proporción palabras contenido/total")
                        with col3:
                            st.metric("Índice Szigriszt", f"{indices.get('szigriszt', 0):.1f}")
                            st.caption("Legibilidad (70-80: estándar)")
                        
                        # Interpretación general
                        st.markdown(f"**Interpretación general**: {indices.get('interpretacion', '')}")
                        
                        # Detalles por áreas
                        tabs = st.tabs(["Léxico", "Sintaxis", "Textual"])
                        
                        with tabs[0]:
                            lex = analisis_data.get("complejidad_lexica", {})
                            st.markdown(f"**Nivel de complejidad léxica**: {lex.get('nivel', '')}")
                            st.write(lex.get("descripcion", ""))
                            
                            palabras = lex.get("palabras_destacadas", [])
                            if palabras:
                                st.markdown("**Palabras destacadas:**")
                                st.write(", ".join(palabras))
                        
                        with tabs[1]:
                            sint = analisis_data.get("complejidad_sintactica", {})
                            st.markdown(f"**Nivel de complejidad sintáctica**: {sint.get('nivel', '')}")
                            st.write(sint.get("descripcion", ""))
                            
                            estructuras = sint.get("estructuras_destacadas", [])
                            if estructuras:
                                st.markdown("**Estructuras destacadas:**")
                                for est in estructuras:
                                    st.markdown(f"- {est}")
                        
                        with tabs[2]:
                            text = analisis_data.get("complejidad_textual", {})
                            st.markdown(f"**Nivel de complejidad textual**: {text.get('nivel', '')}")
                            st.write(text.get("descripcion", ""))
                        
                        # Recomendaciones
                        recomendaciones = analisis_data.get("recomendaciones", [])
                        if recomendaciones:
                            with st.expander("Recomendaciones para mejorar", expanded=True):
                                for rec in recomendaciones:
                                    st.markdown(f"- {rec}")
                    else:
                        st.error("No se pudo extraer el análisis en formato estructurado. Mostrando respuesta cruda.")
                        st.write(content)
                except Exception as e:
                    st.error(f"Error al procesar el análisis: {str(e)}")
                    st.code(content)  # Mostrar respuesta cruda para depuración
    
    # --- Subpestaña 2: Biblioteca de recursos ---
    with subtab_recursos:
        st.subheader("Biblioteca de recursos")
        st.markdown("""
        Accede a recursos didácticos para mejorar tu español, 
        organizados por nivel y categoría gramatical.
        """)
        
        # Organización de recursos en categorías
        col1, col2 = st.columns(2)
        
        with col1:
            categoria = st.selectbox(
                "Categoría:",
                [
                    "Gramática", "Vocabulario", "Expresiones", 
                    "Ortografía", "Conectores", "Cultura"
                ],
                key="categoria_recursos"
            )
        
        with col2:
            nivel_recursos = st.selectbox(
                "Nivel:",
                ["A1", "A2", "B1", "B2", "C1", "C2", "Todos los niveles"],
                key="nivel_recursos"
            )
        
        # Mapear al nivel en la base de datos
        if nivel_recursos in ["A1", "A2"]:
            nivel_db = "A1-A2"
        elif nivel_recursos in ["B1", "B2"]:
            nivel_db = "B1-B2"
        elif nivel_recursos in ["C1", "C2"]:
            nivel_db = "C1-C2"
        else:
            nivel_db = None  # Todos los niveles
        
        # Generar recursos basados en la selección
        if st.button("Buscar recursos", key="buscar_recursos"):
            recursos_mostrados = []
            
            # Buscar en la base de datos estática
            if nivel_db:
                # Filtramos por nivel específico
                nivel_recursos_db = RECURSOS_DB.get(nivel_db, {})
                for cat, recursos in nivel_recursos_db.items():
                    if categoria.lower() in cat.lower() or "todos" in categoria.lower():
                        recursos_mostrados.extend(recursos)
            else:
                # Mostrar todos los niveles
                for nivel, categorias in RECURSOS_DB.items():
                    for cat, recursos in categorias.items():
                        if categoria.lower() in cat.lower() or "todos" in categoria.lower():
                            recursos_mostrados.extend(recursos)
            
            # Si no hay recursos en la base de datos, generar con IA
            if not recursos_mostrados:
                with st.spinner("Generando recomendaciones de recursos..."):
                    # Llamar a la API para generar recursos
                    client = OpenAI(api_key=openai_api_key)
                    
                    nivel_str = nivel_recursos if nivel_recursos != "Todos los niveles" else "todos los niveles"
                    
                    prompt_recursos = f"""
                    Genera una lista de 5 recursos didácticos reales y relevantes para estudiantes de español 
                    de nivel {nivel_str} enfocados en {categoria}.
                    
                    Cada recurso debe incluir:
                    1. Título descriptivo
                    2. Tipo de recurso (libro, página web, app, podcast, vídeo, etc.)
                    3. URL real (o editorial en caso de libros)
                    4. Breve descripción de su contenido y utilidad
                    5. Nivel específico (si aplica)
                    
                    Devuelve SOLO la información en formato JSON con la estructura:
                    {{
                      "recursos": [
                        {{
                          "titulo": "string",
                          "tipo": "string",
                          "url": "string",
                          "descripcion": "string",
                          "nivel": "string"
                        }}
                      ]
                    }}
                    """
                    
                    response = client.chat.completions.create(
                        model="gpt-4-turbo",
                        temperature=0.5,
                        messages=[
                            {"role": "system", "content": "Eres un especialista en recursos didácticos para aprendizaje de español como lengua extranjera."},
                            {"role": "user", "content": prompt_recursos}
                        ]
                    )
                    
                    try:
                        # Extraer JSON
                        content = response.choices[0].message.content
                        match = re.search(r"\{.*\}", content, re.DOTALL)
                        if match:
                            json_str = match.group(0)
                            recursos_data = json.loads(json_str)
                            recursos_ia = recursos_data.get("recursos", [])
                            
                            # Convertir al formato de nuestros recursos
                            for recurso in recursos_ia:
                                recursos_mostrados.append({
                                    "título": recurso.get("titulo", ""),
                                    "tipo": recurso.get("tipo", ""),
                                    "url": recurso.get("url", ""),
                                    "nivel": recurso.get("nivel", "")
                                })
                    except Exception as e:
                        st.error(f"Error al generar recursos: {str(e)}")
            
            # Mostrar los recursos
            if recursos_mostrados:
                st.subheader(f"Recursos de {categoria} para nivel {nivel_recursos}")
                
                for i, recurso in enumerate(recursos_mostrados):
                    with st.expander(f"{i+1}. {recurso.get('título', '')} ({recurso.get('nivel', '')})", expanded=i==0):
                        st.markdown(f"**Tipo:** {recurso.get('tipo', '')}")
                        st.markdown(f"**URL:** [{recurso.get('url', '').split('/')[-1]}]({recurso.get('url', '')})")
                        if "descripcion" in recurso:
                            st.markdown(f"**Descripción:** {recurso.get('descripcion', '')}")
            else:
                st.info(f"No se encontraron recursos para {categoria} de nivel {nivel_recursos}. Intenta con otra combinación.")

        
