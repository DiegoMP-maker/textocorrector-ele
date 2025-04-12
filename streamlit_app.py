"""
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 1: Importaciones y Configuración Base
==================================================================================

Este artefacto contiene:
1. Todas las importaciones de bibliotecas necesarias
2. Configuración base de la aplicación Streamlit
3. Configuración de logging
4. Definición de la versión de la aplicación
"""

import traceback
import streamlit as st
import json
import gspread
import requests
import re
import pandas as pd
import matplotlib.pyplot as plt
import altair as alt
import time
import io
import base64
import numpy as np
from google.oauth2.service_account import Credentials
from datetime import datetime
from openai import OpenAI
from io import BytesIO, StringIO
from PIL import Image
import qrcode
from docx import Document
from docx.shared import Pt, RGBColor, Inches
import logging
from urllib.parse import urlparse
import uuid

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuración de la página
st.set_page_config(
    page_title="Textocorrector ELE",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Configuración de cache y timeout
st.cache_data.clear()

# Versión de la aplicación
APP_VERSION = "2.1.0"  # Actualizado para la versión reescrita

"""
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 2: Inicialización de Variables y Estados
==================================================================================

Este artefacto contiene:
1. Funciones para inicializar variables de session_state
2. Funciones seguras para acceder y modificar valores del session_state
3. Inicialización del sidebar
"""

# Inicializar variables de session_state si no existen


def init_session_state():
    """
    Inicializa variables de session_state con valores predeterminados seguros
    para evitar KeyError durante la ejecución.
    """
    default_values = {
        "nivel_estudiante": "intermedio",
        "consigna_actual": "",
        "usar_consigna_como_texto": False,
        "texto_correccion_corregir": "",
        "info_adicional_corregir": "",
        "ultima_imagen_url": "",
        "ultima_descripcion": "",
        "ultimo_texto_transcrito": "",
        "tarea_modelo_generada": None,
        "respuesta_modelo_examen": "",
        "inicio_simulacro": None,
        "duracion_simulacro": None,
        "tarea_simulacro": None,
        "simulacro_respuesta_texto": "",
        "request_id": "",
        "usuario_actual": "",
        "correction_result": None,
        "last_correction_time": None,
        "examen_result": None,
        "api_error_count": 0,
        "api_last_error_time": None,
        "circuit_breaker_open": False,
        "ultimo_texto": "",
        "nombre_seleccionado": None,
        "imagen_generada_state": False,
        "imagen_url_state": None,
        "descripcion_state": None,
        "tema_imagen_state": None,
        "descripcion_estudiante_state": "",
        "mostrar_correccion_imagen": False,
        "mostrar_correccion_transcripcion": False,
        "active_tab_index": 0,
        "active_tools_tab_index": 0,
        "tab_navigate_to": None,
        "app_initialized": False
    }

    for key, default_value in default_values.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


# Inicializar session_state
init_session_state()

# Funciones seguras para acceso a session_state


def get_session_var(key, default=None):
    """Obtiene una variable de session_state de forma segura"""
    return st.session_state.get(key, default)


def set_session_var(key, value):
    """Establece una variable en session_state"""
    st.session_state[key] = value


# Generar ID único para esta sesión si no existe
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

# Mensaje de bienvenida en sidebar
st.sidebar.title("📝 Textocorrector ELE")
st.sidebar.info(
    """
    Versión: {0}

    Una herramienta para corrección de textos
    en español con análisis contextual avanzado.

    ID de sesión: {1}
    """.format(APP_VERSION, st.session_state.session_id[:8])
)

"""
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 3: Funciones de Seguridad y Conexión a APIs
==================================================================================

Este artefacto contiene:
1. Funciones para manejo seguro de claves API
2. Implementación del patrón Circuit Breaker para APIs
3. Conexión segura a Google Sheets
4. Configuración segura de clientes API (OpenAI)
5. Funciones de diagnóstico para el estado de conexiones
"""

# --- 1. CONFIGURACIÓN DE CLAVES SEGURAS ---


def get_api_keys():
    """
    Obtiene las claves de API de los secretos de Streamlit con manejo de errores.
    Permite la operación en modo degradado si faltan claves.
    """
    keys = {
        "openai": None,
        "elevenlabs": {"api_key": None, "voice_id": None},
        "google_credentials": None
    }

    try:
        keys["openai"] = st.secrets["OPENAI_API_KEY"]
    except Exception as e:
        logger.warning(f"Error al obtener API Key de OpenAI: {e}")
        st.sidebar.warning(
            "⚠️ API de OpenAI no configurada. Algunas funciones estarán limitadas.")

    try:
        keys["elevenlabs"]["api_key"] = st.secrets["ELEVENLABS_API_KEY"]
        keys["elevenlabs"]["voice_id"] = st.secrets["ELEVENLABS_VOICE_ID"]
    except Exception as e:
        logger.warning(f"Error al obtener configuración de ElevenLabs: {e}")
        st.sidebar.warning(
            "⚠️ API de ElevenLabs no configurada. La función de audio estará deshabilitada.")

    try:
        keys["google_credentials"] = json.loads(
            st.secrets["GOOGLE_CREDENTIALS"])
    except Exception as e:
        logger.warning(f"Error al obtener credenciales de Google: {e}")
        st.sidebar.warning(
            "⚠️ Credenciales de Google no configuradas. El guardado de datos estará deshabilitado.")

    return keys


# Obtener claves de API
api_keys = get_api_keys()

# --- 2. CIRCUIT BREAKER PARA APIS ---


class CircuitBreaker:
    """
    Implementa el patrón Circuit Breaker para APIs externas.
    Previene llamadas repetidas a APIs con fallo.
    """

    def __init__(self, failure_threshold=5, reset_timeout=300):
        self.failure_threshold = failure_threshold  # Número de fallos antes de abrir
        self.reset_timeout = reset_timeout  # Tiempo en segundos antes de reintentar

        # Inicializar contadores para diferentes servicios
        self.services = {
            "openai": {"failures": 0, "last_failure_time": None, "open": False},
            "elevenlabs": {"failures": 0, "last_failure_time": None, "open": False},
            "google_sheets": {"failures": 0, "last_failure_time": None, "open": False}
        }

    def record_failure(self, service_name):
        """Registra un fallo para el servicio especificado"""
        if service_name not in self.services:
            logger.warning(f"Servicio desconocido: {service_name}")
            return

        service = self.services[service_name]
        service["failures"] += 1
        service["last_failure_time"] = time.time()

        if service["failures"] >= self.failure_threshold:
            service["open"] = True
            logger.warning(f"Circuit breaker ABIERTO para {service_name}")

    def record_success(self, service_name):
        """Registra un éxito y restablece contadores para el servicio"""
        if service_name not in self.services:
            return

        service = self.services[service_name]
        service["failures"] = 0
        service["open"] = False

    def can_execute(self, service_name):
        """Determina si se puede ejecutar una llamada al servicio"""
        if service_name not in self.services:
            return True

        service = self.services[service_name]

        # Si el circuit breaker está abierto, verificar si ha pasado el tiempo de reset
        if service["open"]:
            if service["last_failure_time"] is None:
                return True

            elapsed = time.time() - service["last_failure_time"]
            if elapsed > self.reset_timeout:
                # Permitir un reintento
                service["open"] = False
                return True
            else:
                return False

        return True

    def get_status(self):
        """Devuelve el estado actual de todos los servicios"""
        return {name: {"open": info["open"], "failures": info["failures"]}
                for name, info in self.services.items()}


# Inicializar circuit breaker
circuit_breaker = CircuitBreaker()

# --- 3. CONEXIÓN A GOOGLE SHEETS ---


def connect_to_googlesheets():
    """
    Establece conexión con Google Sheets para almacenamiento de datos.
    Retorna un diccionario con los objetos de conexión o None si hay error.
    """
    if api_keys["google_credentials"] is None:
        return None

    if not circuit_breaker.can_execute("google_sheets"):
        st.warning(
            "⚠️ Conexión a Google Sheets temporalmente deshabilitada debido a errores previos.")
        return None

    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_info(
            api_keys["google_credentials"], scopes=scope)
        client_gsheets = gspread.authorize(creds)

        # IDs de los documentos
        CORRECTIONS_DOC_ID = "1GTaS0Bv_VN-wzTq1oiEbDX9_UdlTQXWhC9CLeNHVk_8"
        TRACKING_DOC_ID = "1-OQsMGgWseZ__FyUVh0UtYVOLui_yoTMG0BxxTGPOU8"

        sheets = {}

        # Intentar abrir documentos con manejo de errores para cada uno
        try:
            sheets["corrections"] = client_gsheets.open_by_key(
                CORRECTIONS_DOC_ID).sheet1
            logger.info("Conectado a Historial_Correcciones_ELE")
        except Exception as e:
            logger.error(
                f"Error al conectar con Historial_Correcciones_ELE: {e}")
            sheets["corrections"] = None

        try:
            tracking_doc = client_gsheets.open_by_key(TRACKING_DOC_ID)

            # Verificar si existe la hoja Seguimiento
            try:
                sheets["tracking"] = tracking_doc.worksheet("Seguimiento")
                logger.info("Conectado a hoja Seguimiento")
            except gspread.exceptions.WorksheetNotFound:
                # Crear la hoja si no existe
                sheets["tracking"] = tracking_doc.add_worksheet(
                    title="Seguimiento", rows=100, cols=14)
                # Añadir encabezados a la hoja
                headers = ["Nombre", "Nivel", "Fecha", "Errores Gramática", "Errores Léxico",
                           "Errores Puntuación", "Errores Estructura", "Total Errores",
                           "Puntuación Coherencia", "Puntuación Cohesión", "Puntuación Registro",
                           "Puntuación Adecuación Cultural", "Consejo Final"]
                sheets["tracking"].append_row(headers)
                logger.info("Hoja 'Seguimiento' creada y preparada")
        except Exception as e:
            logger.error(f"Error al conectar con hoja de Seguimiento: {e}")
            sheets["tracking"] = None

        # Verificar si hubo éxito en alguna conexión
        if sheets["corrections"] is not None or sheets["tracking"] is not None:
            circuit_breaker.record_success("google_sheets")
            return sheets
        else:
            circuit_breaker.record_failure("google_sheets")
            return None

    except Exception as e:
        logger.error(f"Error al conectar con Google Sheets: {e}")
        circuit_breaker.record_failure("google_sheets")
        return None


# Establecer conexión con Google Sheets (podría ser None si falla)
sheets_connection = connect_to_googlesheets()

# --- 4. CLIENTE DE OPENAI SEGURO ---


def get_openai_client():
    """
    Crea un cliente de OpenAI con manejo de errores.
    Retorna el cliente o None si no es posible crear la conexión.
    """
    if api_keys["openai"] is None:
        return None

    if not circuit_breaker.can_execute("openai"):
        st.warning(
            "⚠️ Conexión a OpenAI temporalmente deshabilitada debido a errores previos.")
        return None

    try:
        client = OpenAI(api_key=api_keys["openai"])
        circuit_breaker.record_success("openai")
        return client
    except Exception as e:
        logger.error(f"Error al crear cliente OpenAI: {e}")
        circuit_breaker.record_failure("openai")
        return None

# --- 5. UTILIDADES DE DIAGNÓSTICO ---


def show_connection_status():
    """Muestra el estado de conexión de los servicios externos"""
    with st.sidebar.expander("Estado de conexiones", expanded=False):
        status = circuit_breaker.get_status()

        # OpenAI
        if api_keys["openai"] is not None:
            if not status["openai"]["open"]:
                st.sidebar.success("✅ OpenAI: Conectado")
            else:
                st.sidebar.error(
                    f"❌ OpenAI: Desconectado ({status['openai']['failures']} fallos)")
        else:
            st.sidebar.warning("⚠️ OpenAI: No configurado")

        # Google Sheets
        if sheets_connection is not None:
            sheets_status = []
            if sheets_connection["corrections"] is not None:
                sheets_status.append("Historial")
            if sheets_connection["tracking"] is not None:
                sheets_status.append("Seguimiento")

            if sheets_status:
                st.sidebar.success(
                    f"✅ Google Sheets: {', '.join(sheets_status)}")
            else:
                st.sidebar.error("❌ Google Sheets: Error de conexión")
        else:
            if api_keys["google_credentials"] is not None:
                st.sidebar.error("❌ Google Sheets: Error de conexión")
            else:
                st.sidebar.warning("⚠️ Google Sheets: No configurado")

        # ElevenLabs
        if api_keys["elevenlabs"]["api_key"] is not None:
            if not status["elevenlabs"]["open"]:
                st.sidebar.success("✅ ElevenLabs: Conectado")
            else:
                st.sidebar.error(
                    f"❌ ElevenLabs: Desconectado ({status['elevenlabs']['failures']} fallos)")
        else:
            st.sidebar.warning("⚠️ ElevenLabs: No configurado")


# Mostrar estado de conexión en sidebar
show_connection_status()

# --- FUNCIÓN AUXILIAR PARA MANEJO DE EXCEPCIONES ---


def handle_exception(func_name, exception, show_user=True):
    """
    Función de utilidad para manejar excepciones de manera consistente.

    Args:
        func_name: Nombre de la función donde ocurrió el error
        exception: La excepción capturada
        show_user: Si se debe mostrar un mensaje al usuario

    Returns:
        None
    """
    error_msg = f"Error en {func_name}: {str(exception)}"
    logger.error(error_msg)
    logger.error(traceback.format_exc())

    if show_user:
        st.error(f"⚠️ {error_msg}")
        with st.expander("Detalles técnicos", expanded=False):
            st.code(traceback.format_exc())

    return None

# Función para diagnóstico proactivo de problemas


def diagnosticar_aplicacion():
    """Diagnostica problemas comunes en la aplicación"""
    problemas = []

    # Verificar conexión a OpenAI
    if api_keys["openai"] is None:
        problemas.append({
            "tipo": "crítico",
            "mensaje": "API Key de OpenAI no configurada",
            "solucion": "Configura la API Key de OpenAI en los secretos de la aplicación"
        })

    # Verificar conexión a Google Sheets
    if sheets_connection is None:
        problemas.append({
            "tipo": "advertencia",
            "mensaje": "Conexión a Google Sheets no disponible",
            "solucion": "Verifica las credenciales de Google Sheets"
        })

    # Verificar si hay archivos necesarios
    try:
        from docx import Document
    except ImportError:
        problemas.append({
            "tipo": "crítico",
            "mensaje": "Librería python-docx no instalada",
            "solucion": "Instala python-docx con pip install python-docx"
        })

    return problemas


"""
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 4: Funciones Core de Procesamiento
==================================================================================

Este artefacto contiene:
1. Funciones para procesamiento de respuestas API (OpenAI, ElevenLabs)
2. Funciones para procesamiento de JSON
3. Integración core con APIs externas
4. Funciones de procesamiento para corrección y análisis de texto
"""

# --- 1. FUNCIONES DE API DE OPENAI ---


def extract_json_safely(content):
    """
    Extrae contenido JSON de una respuesta con múltiples estrategias.
    Implementa parsing robusto para evitar errores.

    Args:
        content: Contenido de texto que debería contener JSON

    Returns:
        dict: El contenido parseado como JSON o un diccionario con error
    """
    # Si es None o vacío, retornar error inmediatamente
    if not content:
        return {"error": "Contenido vacío, no se puede extraer JSON"}

    # Intento directo
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Limpiar el contenido - eliminar caracteres que puedan causar problemas
        # Esto puede ayudar con el problema "unknown extension ?1 at position 13"
        content_clean = re.sub(r'[^\x20-\x7E]', '', content)

        try:
            return json.loads(content_clean)
        except json.JSONDecodeError:
            pass

        # Búsqueda con regex para JSON completo
        # Regex mejorada para JSON anidado
        json_pattern = r'(\{(?:[^{}]|(?1))*\})'
        match = re.search(json_pattern, content_clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Segunda estrategia: buscar cualquier JSON entre llaves
        simple_pattern = r'\{.*\}'
        match = re.search(simple_pattern, content_clean, re.DOTALL)
        if match:
            try:
                # Intentar limpiar el JSON encontrado
                potential_json = match.group(0)
                # Eliminar comillas mal formadas, escape chars, etc.
                potential_json = re.sub(r'[\r\n\t]', ' ', potential_json)
                return json.loads(potential_json)
            except json.JSONDecodeError:
                pass

    # Si no se pudo extraer, devolver un objeto error
    logger.warning(f"No se pudo extraer JSON de: {content[:100]}...")
    return {"error": "No se pudo extraer JSON válido", "raw_content": content[:500]}


def retry_with_backoff(func, max_retries=3, initial_delay=1):
    """
    Ejecuta una función con reintentos y backoff exponencial.

    Args:
        func: Función a ejecutar
        max_retries: Número máximo de reintentos
        initial_delay: Retraso inicial en segundos

    Returns:
        El resultado de la función o levanta la excepción
    """
    for attempt in range(max_retries):
        try:
            return func()
        except (requests.ConnectionError, requests.Timeout) as e:
            # Errores de red específicos - reintentamos
            if attempt == max_retries - 1:
                raise
            delay = initial_delay * (2 ** attempt)  # Backoff exponencial
            logger.info(
                f"Reintento {attempt+1} en {delay} segundos debido a: {str(e)}")
            time.sleep(delay)
        except Exception as e:
            # Otros errores - no reintentamos
            logger.error(f"Error no recuperable: {str(e)}")
            raise


def obtener_json_de_ia(system_msg, user_msg, model="gpt-4-turbo", max_retries=3):
    """
    Obtiene una respuesta estructurada como JSON de OpenAI con sistema
    de reintentos mejorado y estrategias robustas de extracción.

    Args:
        system_msg: Mensaje del sistema para el prompt
        user_msg: Mensaje del usuario para el prompt
        model: Modelo de OpenAI a utilizar
        max_retries: Número máximo de reintentos

    Returns:
        tuple: (contenido raw original, contenido JSON parseado)
    """
    client = get_openai_client()
    if client is None:
        return None, {"error": "Cliente OpenAI no disponible"}

    if not circuit_breaker.can_execute("openai"):
        return None, {"error": "Servicio OpenAI temporalmente no disponible"}

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]

    def send_request():
        return client.chat.completions.create(
            model=model,
            temperature=0.5,
            response_format={"type": "json_object"},  # Forzar formato JSON
            messages=messages
        )

    try:
        # Usar retry_with_backoff para gestionar reintentos
        response = retry_with_backoff(send_request, max_retries=max_retries)
        raw_output = response.choices[0].message.content

        # Intentar extraer JSON
        data_json = extract_json_safely(raw_output)

        # Si falló la extracción pero podemos reintentar con un mensaje específico
        if "error" in data_json and max_retries > 0:
            # Añadir mensaje solicitando formato JSON específico
            messages.append({
                "role": "user",
                "content": (
                    "Tu respuesta anterior no cumplió el formato JSON requerido. "
                    "Por favor, responde ÚNICAMENTE en JSON válido con la estructura solicitada. "
                    "No incluyas texto extra, backticks, ni marcadores de código fuente."
                )
            })

            # Reintento específico para corrección de formato
            response = retry_with_backoff(
                lambda: client.chat.completions.create(
                    model=model,
                    temperature=0.3,  # Temperatura más baja para formato más preciso
                    response_format={"type": "json_object"},
                    messages=messages
                ),
                max_retries=1
            )

            # Nuevo intento de extracción
            raw_output = response.choices[0].message.content
            data_json = extract_json_safely(raw_output)

        # Marcar como éxito la comunicación con OpenAI
        circuit_breaker.record_success("openai")
        return raw_output, data_json

    except Exception as e:
        logger.error(f"Error en API de OpenAI: {str(e)}")
        circuit_breaker.record_failure("openai")
        return None, {"error": f"Error en API de OpenAI: {str(e)}"}

# --- 2. INTEGRACIÓN CON ELEVENLABS ---


def generar_audio_consejo(consejo_texto):
    """
    Genera un archivo de audio a partir del texto usando ElevenLabs.

    Args:
        consejo_texto: Texto a convertir en audio

    Returns:
        BytesIO: Buffer con el audio generado, o None si ocurre un error
    """
    if not api_keys["elevenlabs"]["api_key"] or not api_keys["elevenlabs"]["voice_id"]:
        logger.warning("Claves de ElevenLabs no configuradas")
        return None

    if not circuit_breaker.can_execute("elevenlabs"):
        logger.warning("ElevenLabs temporalmente no disponible")
        return None

    if not consejo_texto:
        return None

    # Limpiar el texto
    audio_text = consejo_texto.replace("Consejo final:", "").strip()
    if not audio_text:
        return None

    try:
        elevenlabs_api_key = api_keys["elevenlabs"]["api_key"]
        elevenlabs_voice_id = api_keys["elevenlabs"]["voice_id"]

        tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
        headers = {
            "xi-api-key": elevenlabs_api_key,
            "Content-Type": "application/json"
        }
        data = {
            "text": audio_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.3,
                "similarity_boost": 0.9
            }
        }

        # Función para envío de solicitud
        def send_request():
            response = requests.post(
                tts_url, headers=headers, json=data, timeout=15)
            response.raise_for_status()  # Levantar excepción si hay error
            return response

        # Usar sistema de reintentos
        response_audio = retry_with_backoff(send_request, max_retries=2)

        if response_audio.ok:
            audio_bytes = BytesIO(response_audio.content)
            circuit_breaker.record_success("elevenlabs")
            return audio_bytes
        else:
            logger.error(
                f"Error en ElevenLabs API: {response_audio.status_code}")
            circuit_breaker.record_failure("elevenlabs")
            return None

    except Exception as e:
        logger.error(f"Error al generar audio: {str(e)}")
        circuit_breaker.record_failure("elevenlabs")
        return None

# --- 3. INTEGRACIÓN CON DALL-E ---


def generar_imagen_dalle(tema, nivel):
    """
    Genera una imagen utilizando DALL-E basada en un tema y adaptada al nivel del estudiante.

    Args:
        tema: Tema para la imagen
        nivel: Nivel de español (principiante, intermedio, avanzado)

    Returns:
        tuple: (URL de la imagen generada, descripción de la imagen)
    """
    client = get_openai_client()
    if client is None:
        return None, "API de OpenAI no disponible"

    if not circuit_breaker.can_execute("openai"):
        return None, "Servicio OpenAI temporalmente no disponible"

    # Adaptar la complejidad del prompt según el nivel
    if "principiante" in nivel.lower():
        complejidad = "simple con objetos y personas claramente identificables"
    elif "intermedio" in nivel.lower():
        complejidad = "con detalles moderados y una escena cotidiana con varios elementos"
    else:
        complejidad = "detallada con múltiples elementos, que pueda generar descripciones complejas"

    # Crear el prompt para DALL-E
    prompt = f"Una escena {complejidad} sobre {tema}. La imagen debe ser clara, bien iluminada, y adecuada para describir en español."

    try:
        # Función para envío de solicitud
        def generate_image():
            return client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="standard"
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(generate_image, max_retries=2)

        # Obtener la URL de la imagen
        imagen_url = response.data[0].url

        # Generar una descripción adaptada al nivel
        descripcion_prompt = f"""
        Crea una descripción en español de esta imagen generada para un estudiante de nivel {nivel}.

        La descripción debe:
        1. Ser apropiada para el nivel {nivel}
        2. Utilizar vocabulario y estructuras gramaticales de ese nivel
        3. Incluir entre 3-5 preguntas al final para que el estudiante practique describiendo la imagen

        Tema de la imagen: {tema}
        """

        def generate_description():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": "Eres un profesor de español especializado en crear descripciones y actividades basadas en imágenes."},
                    {"role": "user", "content": descripcion_prompt}
                ],
                temperature=0.7
            )

        descripcion_response = retry_with_backoff(
            generate_description, max_retries=2)
        descripcion = descripcion_response.choices[0].message.content

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return imagen_url, descripcion

    except Exception as e:
        handle_exception("generar_imagen_dalle", e)
        circuit_breaker.record_failure("openai")
        return None, f"Error: {str(e)}"

# --- 4. FUNCIÓN DE OCR PARA TEXTOS MANUSCRITOS ---


def transcribir_imagen_texto(imagen_bytes, idioma="es"):
    """
    Transcribe texto manuscrito de una imagen utilizando la API de OpenAI.
    Versión mejorada con manejo de errores y circuit breaker.

    Args:
        imagen_bytes: Bytes de la imagen a transcribir
        idioma: Código de idioma (es, en, fr)

    Returns:
        str: Texto transcrito o mensaje de error
    """
    client = get_openai_client()
    if client is None:
        return "Error: API de OpenAI no disponible"

    if not circuit_breaker.can_execute("openai"):
        return "Error: Servicio OpenAI temporalmente no disponible"

    try:
        # Codificar la imagen en base64
        encoded_image = base64.b64encode(imagen_bytes).decode('utf-8')

        # Función para envío de solicitud
        def send_ocr_request():
            return client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": f"Eres un sistema de OCR especializado en transcribir texto manuscrito en {idioma}. Tu tarea es extraer con precisión el texto presente en la imagen."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe exactamente el texto manuscrito de esta imagen."},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded_image}"}}
                        ]
                    }
                ],
                max_tokens=1000
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_ocr_request, max_retries=2)

        # Registrar éxito
        circuit_breaker.record_success("openai")

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Error en transcribir_imagen_texto: {str(e)}")
        logger.error(traceback.format_exc())

        circuit_breaker.record_failure("openai")

        return f"Error en la transcripción: {str(e)}"

# --- 5. GUARDADO DE DATOS EN GOOGLE SHEETS ---


def guardar_correccion(nombre, nivel, idioma, texto, resultado_json):
    """
    Guarda los datos de una corrección en Google Sheets.

    Args:
        nombre: Nombre del estudiante
        nivel: Nivel de español
        idioma: Idioma de corrección
        texto: Texto original
        resultado_json: Resultado de la corrección en formato JSON (como string o dict)

    Returns:
        dict: Resultado de la operación
    """
    if sheets_connection is None:
        return {"success": False, "message": "Conexión a Google Sheets no disponible"}

    # Fecha actual para el registro
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Convertir resultado_json a string si es un diccionario
    if isinstance(resultado_json, dict):
        raw_output = json.dumps(resultado_json)
    else:
        raw_output = resultado_json

    result = {
        "success": True,
        "corrections_saved": False,
        "tracking_saved": False,
        "message": ""
    }

    # Guardar en Historial_Correcciones_ELE
    if sheets_connection["corrections"] is not None:
        try:
            sheets_connection["corrections"].append_row(
                [nombre, nivel, idioma, fecha, texto, raw_output]
            )
            result["corrections_saved"] = True
            logger.info(f"Corrección guardada para {nombre}")
        except Exception as e:
            logger.error(
                f"Error al guardar en Historial_Correcciones_ELE: {str(e)}")
            result["message"] += f"Error al guardar historial: {str(e)}. "

    # Guardar en hoja de seguimiento si hay datos de análisis contextual
    if sheets_connection["tracking"] is not None:
        try:
            # Extraer datos del resultado
            if isinstance(resultado_json, str):
                data_json = extract_json_safely(resultado_json)
            else:
                data_json = resultado_json

            # Extraer datos relevantes para seguimiento
            errores = data_json.get("errores", {})
            analisis = data_json.get("analisis_contextual", {})

            # Contar errores por categoría
            num_gramatica = len(errores.get("Gramática", []))
            num_lexico = len(errores.get("Léxico", []))
            num_puntuacion = len(errores.get("Puntuación", []))
            num_estructura = len(errores.get("Estructura textual", []))
            total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

            # Extraer puntuaciones
            coherencia = analisis.get("coherencia", {})
            cohesion = analisis.get("cohesion", {})
            registro = analisis.get("registro_linguistico", {})
            adecuacion = analisis.get("adecuacion_cultural", {})

            puntuacion_coherencia = coherencia.get("puntuacion", 0)
            puntuacion_cohesion = cohesion.get("puntuacion", 0)
            puntuacion_registro = registro.get("puntuacion", 0)
            puntuacion_adecuacion = adecuacion.get("puntuacion", 0)

            # Extraer consejo final
            consejo_final = data_json.get("consejo_final", "")

            # Datos para guardar
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

            # Guardar en hoja de seguimiento
            sheets_connection["tracking"].append_row(datos_seguimiento)
            result["tracking_saved"] = True
            logger.info(f"Estadísticas guardadas para {nombre}")
        except Exception as e:
            logger.error(f"Error al guardar en hoja de Seguimiento: {str(e)}")
            result["message"] += f"Error al guardar estadísticas: {str(e)}."

    # Resultado final
    if result["corrections_saved"] or result["tracking_saved"]:
        result["success"] = True
        if not result["message"]:
            result["message"] = "Datos guardados correctamente."
    else:
        result["success"] = False
        if not result["message"]:
            result["message"] = "No se pudo guardar ningún dato."

    return result


def obtener_historial_estudiante(nombre):
    """
    Obtiene el historial de correcciones y seguimiento para un estudiante específico.

    Args:
        nombre: Nombre del estudiante

    Returns:
        pd.DataFrame o None: DataFrame con historial o None si no hay datos
    """
    if sheets_connection is None or sheets_connection["tracking"] is None:
        logger.warning("No hay conexión con hoja de seguimiento")
        return None

    try:
        # Obtener todos los datos
        todos_datos = sheets_connection["tracking"].get_all_records()

        if not todos_datos:
            return None

        # Crear una versión limpia del nombre buscado
        nombre_buscar = nombre.strip().lower()

        # Buscar en todos los registros con un enfoque más flexible
        datos_estudiante = []
        for row in todos_datos:
            for key, value in row.items():
                # Buscar en cualquier columna que tenga 'nombre'
                if 'nombre' in key.lower() and value:
                    if str(value).strip().lower() == nombre_buscar:
                        datos_estudiante.append(row)
                        break

        # Convertir a DataFrame
        if datos_estudiante:
            df = pd.DataFrame(datos_estudiante)

            # Convertir columnas numéricas explícitamente para evitar errores con PyArrow
            columnas_numericas = [
                'Errores Gramática', 'Errores Léxico', 'Errores Puntuación',
                'Errores Estructura', 'Total Errores', 'Puntuación Coherencia',
                'Puntuación Cohesión', 'Puntuación Registro', 'Puntuación Adecuación Cultural'
            ]

            for col in columnas_numericas:
                if col in df.columns:
                    # Convertir a float de manera segura
                    df[col] = pd.to_numeric(
                        df[col], errors='coerce').fillna(0).astype(float)

            return df

        return None
    except Exception as e:
        logger.error(f"Error en obtener_historial_estudiante: {str(e)}")
        return None

    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 5 - Parte 1: Funciones Utilitarias - Generación de consignas y criterios
==================================================================================

Este artefacto contiene:
1. Funciones para generar consignas de escritura
2. Funciones para obtener criterios de evaluación
3. Funciones para obtener duración de examen
4. Función para extraer título de texto
"""

# --- 1. FUNCIONES DE GENERACIÓN DE CONSIGNAS ---


def generar_consigna_escritura(nivel_actual, tipo_consigna):
    """
    Genera una consigna de escritura adaptada al nivel del estudiante
    y el tipo de texto solicitado.

    Args:
        nivel_actual: Nivel del estudiante (principiante, intermedio, avanzado)
        tipo_consigna: Tipo de texto a generar

    Returns:
        str: Consigna de escritura generada o mensaje de error
    """
    client = get_openai_client()
    if client is None:
        return "No se pudo generar la consigna debido a problemas de conexión."

    if not circuit_breaker.can_execute("openai"):
        return "Servicio temporalmente no disponible. Inténtelo más tarde."

    # Si es aleatorio, seleccionar un tipo
    if tipo_consigna == "Cualquiera (aleatorio)":
        import random
        tipos_disponibles = [
            "Narración", "Correo/Carta formal", "Opinión/Argumentación",
            "Descripción", "Diálogo"
        ]
        tipo_consigna = random.choice(tipos_disponibles)

    # Construir prompt mejorado para OpenAI
    prompt_consigna = f"""
    Eres un profesor experto en la enseñanza de español como lengua extranjera.
    Crea una consigna de escritura adaptada al nivel {nivel_actual} para el tipo de texto: {tipo_consigna}.

    Tu respuesta debe tener este formato exacto:
    1. Un título atractivo y claro
    2. Instrucciones precisas que incluyan:
       - Situación o contexto
       - Tarea específica a realizar
       - Extensión requerida (número de palabras apropiado para el nivel)
       - Elementos que debe incluir el texto

    Adapta la complejidad lingüística y temática al nivel {nivel_actual}:
    - Para niveles principiante: usa vocabulario básico, estructuras simples y temas cotidianos
    - Para niveles intermedio: incluye vocabulario más variado, conectores y temas que requieran opinión
    - Para niveles avanzado: incorpora elementos para expresar matices, argumentación compleja y temas abstractos

    Proporciona solo la consigna, sin explicaciones adicionales ni metacomentarios.
    """

    try:
        def send_request():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.8,
                messages=[
                    {"role": "system", "content": "Eres un profesor de español experto en diseñar actividades de escritura."},
                    {"role": "user", "content": prompt_consigna}
                ]
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_request, max_retries=2)

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return response.choices[0].message.content.strip()

    except Exception as e:
        error_msg = f"Error al generar consigna: {str(e)}"
        logger.error(error_msg)
        circuit_breaker.record_failure("openai")
        return f"No se pudo generar la consigna. Error: {str(e)}"


def obtener_criterios_evaluacion(tipo_examen, nivel_examen):
    """
    Obtiene los criterios de evaluación para un examen y nivel específicos.

    Args:
        tipo_examen: Tipo de examen (DELE, SIELE, etc.)
        nivel_examen: Nivel del examen (A1, A2, etc.)

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

    # Criterios específicos para SIELE
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


def obtener_duracion_examen(tipo_examen, nivel_examen):
    """
    Obtiene la duración en segundos para un simulacro según el tipo y nivel de examen.

    Args:
        tipo_examen: Tipo de examen (DELE, SIELE, etc.)
        nivel_examen: Nivel del examen (A1, A2, etc.)

    Returns:
        int: Duración en segundos
    """
    try:
        # Verificar que los parámetros son válidos
        if tipo_examen is None or nivel_examen is None:
            logger.warning(
                "Parámetros inválidos en obtener_duracion_examen: tipo_examen o nivel_examen es None")
            return 45 * 60  # 45 minutos por defecto

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
            "CELU": {
                "A1": 30 * 60,
                "A2": 35 * 60,
                "B1": 45 * 60,
                "B2": 60 * 60,
                "C1": 75 * 60,
                "C2": 90 * 60
            },
            "DUCLE": {
                "A1": 20 * 60,
                "A2": 25 * 60,
                "B1": 30 * 60,
                "B2": 40 * 60,
                "C1": 50 * 60,
                "C2": 60 * 60
            }
        }

        # Intentar obtener la duración específica
        duracion = duraciones.get(tipo_examen, {}).get(nivel_examen)

        # Si no se encuentra, usar el valor por defecto
        if duracion is None:
            logger.info(
                f"No se encontró duración para {tipo_examen} nivel {nivel_examen}, usando valor por defecto")
            duracion = 45 * 60  # 45 minutos por defecto

        return duracion

    except Exception as e:
        logger.error(f"Error en obtener_duracion_examen: {str(e)}")
        return 45 * 60  # 45 minutos por defecto


def extraer_titulo(texto):
    """
    Extrae el título de una sección de texto.

    Args:
        texto: Texto de la sección

    Returns:
        str: Título extraído
    """
    if not texto:
        return "Contenido sin título"

    lineas = texto.strip().split("\n")
    if lineas and lineas[0]:
        # Eliminar caracteres no deseados que podrían aparecer en un título
        titulo = lineas[0].strip().strip('#').strip('-').strip('*').strip()
        return titulo

    return "Contenido sin título"


"""
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 5 - Parte 2: Funciones Utilitarias - Análisis de complejidad textual
==================================================================================

Este artefacto contiene:
1. Funciones para análisis de complejidad textual
"""


def analizar_complejidad_texto(texto):
    """
    Analiza la complejidad lingüística de un texto en español.

    Args:
        texto: Texto a analizar

    Returns:
        dict: Análisis de complejidad o mensaje de error
    """
    client = get_openai_client()
    if client is None or not texto:
        return {"error": "No se pudo realizar el análisis. Verifique la conexión o el texto."}

    if not circuit_breaker.can_execute("openai"):
        return {"error": "Servicio temporalmente no disponible. Inténtelo más tarde."}

    try:
        # Prompt para análisis de complejidad
        prompt_analisis = f"""
        Analiza la complejidad lingüística del siguiente texto en español.
        Proporciona un análisis detallado que incluya:

        1. Complejidad léxica (variedad de vocabulario, riqueza léxica, palabras poco comunes)
        2. Complejidad sintáctica (longitud de frases, subordinación, tipos de oraciones)
        3. Complejidad textual (coherencia, cohesión, estructura general)
        4. Nivel MCER estimado (A1-C2) con explicación
        5. Índices estadísticos: TTR (type-token ratio), densidad léxica, índice Flesh-Szigriszt (adaptado al español)

        Texto a analizar:
        "{texto}"

        Devuelve el análisis ÚNICAMENTE en formato JSON con la siguiente estructura:
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

        def send_request():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.3,  # Temperatura baja para resultados más precisos
                # Forzar respuesta en JSON
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Eres un experto lingüista y analista textual especializado en complejidad lingüística."},
                    {"role": "user", "content": prompt_analisis}
                ]
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_request, max_retries=2)
        raw_output = response.choices[0].message.content

        # Extraer JSON
        analisis_data = extract_json_safely(raw_output)

        # Verificar si se obtuvo un resultado válido
        if "error" in analisis_data:
            circuit_breaker.record_failure("openai")
            return {"error": "No se pudo procesar el análisis. Formato de respuesta incorrecto."}

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return analisis_data

    except Exception as e:
        handle_exception("analizar_complejidad_texto", e)
        circuit_breaker.record_failure("openai")
        return {"error": f"Error al analizar complejidad: {str(e)}"}
    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 5 - Parte 3: Funciones Utilitarias - Corrección de textos
==================================================================================

Este artefacto contiene:
1. Función principal de corrección de texto
2. Función de corrección de examen
3. Función de corrección de descripción de imagen
4. Función de generación de tareas y ejemplos de examen
"""


def corregir_texto(texto, nombre, nivel, idioma, tipo_texto, contexto_cultural, info_adicional=""):
    """
    Realiza una corrección completa de un texto con análisis contextual.

    Args:
        texto: Texto a corregir
        nombre: Nombre del estudiante
        nivel: Nivel del estudiante
        idioma: Idioma de corrección (Español, Francés, Inglés)
        tipo_texto: Tipo de texto
        contexto_cultural: Contexto cultural relevante
        info_adicional: Información adicional o contexto

    Returns:
        dict: Resultado de la corrección o mensaje de error
    """
    try:
        client = get_openai_client()
        if client is None:
            return {"error": "Servicio de corrección no disponible. Verifique la conexión."}

        if not circuit_breaker.can_execute("openai"):
            return {"error": "Servicio temporalmente no disponible. Inténtelo más tarde."}

        # Validar la entrada
        if not texto or not nombre:
            return {"error": "El texto y el nombre son obligatorios."}

        # Mapeo de niveles para instrucciones más específicas
        nivel_map_instrucciones = {
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

        # Usar nivel intermedio como fallback
        nivel_info = nivel_map_instrucciones.get(
            nivel, nivel_map_instrucciones["Nivel intermedio (B1-B2)"])

        # Instrucciones para el modelo de IA con análisis contextual avanzado
        system_message = f'''
Eres Diego, un profesor experto en ELE (Español como Lengua Extranjera) especializado en análisis lingüístico contextual.
Tu objetivo es corregir textos adaptando tu feedback al nivel {nivel_info["descripcion"]} del estudiante.
{nivel_info["enfoque"]}

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
- Adapta tus explicaciones y sugerencias al nivel {nivel_info["descripcion"]} del estudiante
- Considera el tipo de texto "{tipo_texto}" y el contexto cultural "{contexto_cultural}" en tu análisis

No devuelvas ningún texto extra fuera de este JSON.
'''

        # Mensaje para el usuario con contexto adicional
        user_message = f'''
Texto del alumno:
"""
{texto}
"""
Nivel: {nivel}
Nombre del alumno: {nombre}
Idioma de corrección: {idioma}
Tipo de texto: {tipo_texto}
Contexto cultural: {contexto_cultural}
{f"Información adicional: {info_adicional}" if info_adicional else ""}
'''

        try:
            # Enviar solicitud a OpenAI
            raw_output, data_json = obtener_json_de_ia(
                system_message, user_message, model="gpt-4-turbo", max_retries=3)

            # Verificar si hay error en la respuesta
            if raw_output is None or "error" in data_json:
                error_msg = data_json.get(
                    "error", "Error desconocido en el procesamiento")
                logger.error(f"Error en corrección: {error_msg}")
                return {"error": error_msg}

            # Registrar éxito
            circuit_breaker.record_success("openai")

            # Guardar corrección si hay conexión a Google Sheets
            if sheets_connection is not None:
                resultado_guardado = guardar_correccion(
                    nombre, nivel, idioma, texto, raw_output)
                if not resultado_guardado["success"]:
                    logger.warning(
                        f"No se pudo guardar la corrección: {resultado_guardado['message']}")

            # Guardar el texto para posible uso futuro
            set_session_var("ultimo_texto", texto)

            # Devolver resultado
            return data_json

        except Exception as e:
            error_msg = f"Error al corregir texto: {str(e)}"
            logger.error(error_msg)
            circuit_breaker.record_failure("openai")
            return {"error": error_msg}

    except Exception as e:
        handle_exception("corregir_texto", e)
        return {"error": f"Error al corregir texto: {str(e)}"}


def corregir_examen(texto, tipo_examen, nivel_examen, tiempo_usado=None):
    """
    Corrige un texto de examen específico.

    Args:
        texto: Texto a corregir
        tipo_examen: Tipo de examen
        nivel_examen: Nivel del examen
        tiempo_usado: Tiempo usado (opcional)

    Returns:
        dict: Resultado de la corrección
    """
    if not texto or not texto.strip():
        return {"error": "El texto está vacío. Por favor, escribe una respuesta."}

    # Guardar para futura referencia
    set_session_var("ultimo_texto", texto)

    # Obtener datos necesarios
    nombre = get_session_var("usuario_actual", "Usuario")

    # Mapear nivel del examen al formato de nivel de la aplicación
    nivel_map = {
        "A1": "Nivel principiante (A1-A2)",
        "A2": "Nivel principiante (A1-A2)",
        "B1": "Nivel intermedio (B1-B2)",
        "B2": "Nivel intermedio (B1-B2)",
        "C1": "Nivel avanzado (C1-C2)",
        "C2": "Nivel avanzado (C1-C2)"
    }
    nivel = nivel_map.get(nivel_examen, "Nivel intermedio (B1-B2)")

    # Construir información adicional
    info_adicional = f"Examen {tipo_examen} nivel {nivel_examen}"
    if tiempo_usado:
        info_adicional += f" (Tiempo usado: {tiempo_usado})"

    # Llamar a la función de corrección
    resultado = corregir_texto(
        texto, nombre, nivel, "Español", "Académico",
        "Contexto académico", info_adicional
    )

    # Guardar resultado
    set_session_var("correction_result", resultado)
    set_session_var("last_correction_time", datetime.now().isoformat())
    set_session_var("examen_result", resultado)

    return resultado


def corregir_descripcion_imagen(descripcion, tema_imagen, nivel):
    """
    Corrige una descripción de imagen.

    Args:
        descripcion: Texto de la descripción
        tema_imagen: Tema de la imagen
        nivel: Nivel del estudiante

    Returns:
        dict: Resultado de la corrección
    """
    if not descripcion or not descripcion.strip():
        return {"error": "La descripción está vacía. Por favor, escribe una descripción."}

    # Guardar para futura referencia
    set_session_var("ultimo_texto", descripcion)

    # Obtener datos necesarios
    nombre = get_session_var("usuario_actual", "Usuario")

    # Información adicional
    info_adicional = f"Descripción de imagen sobre '{tema_imagen}'"

    # Llamar a la función de corrección
    resultado = corregir_texto(
        descripcion, nombre, nivel, "Español", "Descriptivo",
        "General/Internacional", info_adicional
    )

    # Guardar resultado
    set_session_var("correction_result", resultado)
    set_session_var("last_correction_time", datetime.now().isoformat())

    return resultado


def generar_tarea_examen(tipo_examen, nivel_examen):
    """
    Genera una tarea de expresión escrita para un examen específico.

    Args:
        tipo_examen: Tipo de examen (DELE, SIELE, etc.)
        nivel_examen: Nivel del examen (A1, A2, etc.)

    Returns:
        str: Tarea generada para el examen
    """
    client = get_openai_client()
    if client is None:
        return "No se pudo generar la tarea. Servicio no disponible."

    if not circuit_breaker.can_execute("openai"):
        return "Servicio temporalmente no disponible. Inténtelo más tarde."

    try:
        # Prompt para generación de tarea
        prompt_tarea = f"""
        Crea una tarea de expresión escrita para el examen {tipo_examen} de nivel {nivel_examen}.
        La tarea debe incluir:
        1. Instrucciones claras y precisas
        2. Contexto o situación comunicativa
        3. Número de palabras requerido
        4. Aspectos que se evaluarán

        El formato debe ser idéntico al que aparece en los exámenes oficiales {tipo_examen}.
        La tarea debe ser apropiada para el nivel {nivel_examen}, siguiendo los estándares oficiales.
        """

        def send_request():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.7,
                messages=[
                    {"role": "system", "content": "Eres un experto en exámenes oficiales de español como lengua extranjera."},
                    {"role": "user", "content": prompt_tarea}
                ]
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_request, max_retries=2)

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return response.choices[0].message.content

    except Exception as e:
        error_msg = f"Error al generar tarea de examen: {str(e)}"
        logger.error(error_msg)
        circuit_breaker.record_failure("openai")
        return f"No se pudo generar la tarea. Error: {str(e)}"


def generar_ejemplos_evaluados(tipo_examen, nivel_examen):
    """
    Genera ejemplos de textos evaluados para un examen específico.

    Args:
        tipo_examen: Tipo de examen (DELE, SIELE, etc.)
        nivel_examen: Nivel del examen (A1, A2, etc.)

    Returns:
        str: Ejemplos de textos evaluados
    """
    client = get_openai_client()
    if client is None:
        return "No se pudieron generar ejemplos. Servicio no disponible."

    if not circuit_breaker.can_execute("openai"):
        return "Servicio temporalmente no disponible. Inténtelo más tarde."

    try:
        # Prompt para generación de ejemplos
        prompt_ejemplos = f"""
        Genera un ejemplo de texto de un estudiante para el examen {tipo_examen} nivel {nivel_examen},
        junto con una evaluación detallada usando los criterios oficiales.
        Muestra:
        1. La tarea solicitada
        2. El texto del estudiante (con algunos errores típicos de ese nivel)
        3. Evaluación punto por punto según los criterios oficiales
        4. Puntuación desglosada y comentarios
        """

        def send_request():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.7,
                messages=[
                    {"role": "system", "content": "Eres un evaluador experto de exámenes oficiales de español."},
                    {"role": "user", "content": prompt_ejemplos}
                ]
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_request, max_retries=2)

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return response.choices[0].message.content

    except Exception as e:
        error_msg = f"Error al generar ejemplos evaluados: {str(e)}"
        logger.error(error_msg)
        circuit_breaker.record_failure("openai")
        return f"No se pudieron generar ejemplos. Error: {str(e)}"
    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 6: Componentes Reutilizables de UI Básicos
==================================================================================

Este artefacto contiene:
1. Componentes básicos de UI reutilizables
2. Utilidades de interfaz
3. Mensajes estandarizados
4. Indicadores de progreso
5. Diálogos de confirmación
"""

# --- 1. COMPONENTES DE UI REUTILIZABLES ---


def ui_header():
    """Muestra el encabezado principal de la aplicación."""
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("📝 Textocorrector ELE")
        st.markdown(
            "Corrección de textos en español con análisis contextual avanzado.")

    with col2:
        # Mostrar indicador de versión
        st.markdown(f"""
        <div style="background-color:#f0f2f6;padding:8px;border-radius:5px;margin-top:20px;text-align:center">
            <small>v{APP_VERSION}</small>
        </div>
        """, unsafe_allow_html=True)


def ui_user_info_form(form_key="form_user_info"):
    """
    Formulario para obtener información básica del usuario, con mejor validación.

    Args:
        form_key: Clave única para el formulario

    Returns:
        dict: Datos del usuario (nombre, nivel)
    """
    with st.form(key=form_key):
        col1, col2 = st.columns(2)

        with col1:
            nombre = st.text_input(
                "Nombre y apellido:",
                value=get_session_var("usuario_actual", ""),
                help="Por favor, introduce tu nombre (y apellido opcional)."
            )

        with col2:
            nivel = st.selectbox(
                "¿Cuál es tu nivel?",
                [
                    "Nivel principiante (A1-A2)",
                    "Nivel intermedio (B1-B2)",
                    "Nivel avanzado (C1-C2)"
                ],
                index=["principiante", "intermedio", "avanzado"].index(
                    get_session_var("nivel_estudiante", "intermedio")
                )
            )

        submit = st.form_submit_button("Guardar", use_container_width=True)

        if submit:
            # SOLUCIÓN: Validación de nombre mejorada
            if not nombre.strip():
                st.warning("Por favor, introduce al menos tu nombre.")
                return None

            # Guardar en session_state
            set_session_var("usuario_actual", nombre)

            # Guardar nivel en formato simplificado
            nivel_map = {
                "Nivel principiante (A1-A2)": "principiante",
                "Nivel intermedio (B1-B2)": "intermedio",
                "Nivel avanzado (C1-C2)": "avanzado"
            }
            set_session_var("nivel_estudiante",
                            nivel_map.get(nivel, "intermedio"))

            return {"nombre": nombre, "nivel": nivel}

        return None


def ui_idioma_correcciones_tipo():
    """
    Componente para seleccionar idioma de correcciones y tipo de texto.

    Returns:
        dict: Opciones seleccionadas
    """
    col1, col2, col3 = st.columns(3)

    with col1:
        idioma = st.selectbox(
            "Idioma de corrección",
            ["Español", "Inglés", "Francés"],
            help="Idioma en el que recibirás las explicaciones y análisis."
        )

    with col2:
        tipo_texto = st.selectbox(
            "Tipo de texto",
            [
                "General/No especificado",
                "Académico",
                "Profesional/Laboral",
                "Informal/Cotidiano",
                "Creativo/Literario"
            ],
            help="Tipo de texto que estás escribiendo."
        )

    with col3:
        contexto_cultural = st.selectbox(
            "Contexto cultural",
            [
                "General/Internacional",
                "España",
                "Latinoamérica",
                "Contexto académico",
                "Contexto empresarial"
            ],
            help="Contexto cultural relevante para tu texto."
        )

    return {
        "idioma": idioma,
        "tipo_texto": tipo_texto,
        "contexto_cultural": contexto_cultural
    }


def ui_examen_options():
    """
    Componente para seleccionar opciones de examen.

    Returns:
        dict: Opciones de examen seleccionadas
    """
    col1, col2 = st.columns(2)

    with col1:
        tipo_examen = st.selectbox(
            "Examen oficial:",
            ["DELE", "SIELE", "CELU", "DUCLE"],
            help="Selecciona el tipo de examen para el que quieres prepararte."
        )

    with col2:
        nivel_examen = st.selectbox(
            "Nivel:",
            ["A1", "A2", "B1", "B2", "C1", "C2"],
            help="Nivel del examen."
        )

    return {
        "tipo_examen": tipo_examen,
        "nivel_examen": nivel_examen
    }


def ui_loading_spinner(text="Procesando..."):
    """
    Spinner de carga con texto personalizable.

    Args:
        text: Texto a mostrar durante la carga

    Returns:
        st.spinner: Objeto spinner de Streamlit
    """
    return st.spinner(text)


def ui_empty_placeholder():
    """
    Crea un placeholder vacío para contenido dinámico.

    Returns:
        st.empty: Objeto empty de Streamlit
    """
    return st.empty()


def ui_countdown_timer(total_seconds, start_time=None):
    """
    Muestra un temporizador de cuenta regresiva.

    Args:
        total_seconds: Tiempo total en segundos
        start_time: Tiempo de inicio (None = ahora)

    Returns:
        dict: Estado del temporizador
    """
    # Manejar el caso donde total_seconds es None
    if total_seconds is None:
        total_seconds = 0  # Usar 0 como valor por defecto

    if start_time is None:
        start_time = time.time()

    # Calcular tiempo transcurrido
    tiempo_transcurrido = time.time() - start_time
    tiempo_restante_segundos = max(0, total_seconds - tiempo_transcurrido)

    # Formatear tiempo restante
    minutos = int(tiempo_restante_segundos // 60)
    segundos = int(tiempo_restante_segundos % 60)
    tiempo_formateado = f"{minutos:02d}:{segundos:02d}"

    # Calcular porcentaje (evitar división por cero)
    if total_seconds > 0:
        porcentaje = 1 - (tiempo_restante_segundos / total_seconds)
    else:
        porcentaje = 1  # Si no hay tiempo total, consideramos que está completo

    porcentaje = max(0, min(1, porcentaje))  # Asegurar entre 0 y 1

    # Determinar color según tiempo restante
    if tiempo_restante_segundos > total_seconds * 0.5:  # Más del 50% restante
        color = "normal"  # Verde/Normal
    elif tiempo_restante_segundos > total_seconds * 0.25:  # Entre 25% y 50%
        color = "warning"  # Amarillo/Advertencia
    else:  # Menos del 25%
        color = "error"  # Rojo/Error

    return {
        "tiempo_restante": tiempo_restante_segundos,
        "tiempo_formateado": tiempo_formateado,
        "porcentaje": porcentaje,
        "color": color,
        "terminado": tiempo_restante_segundos <= 0
    }

# --- 2. UTILIDADES DE INTERFAZ ---


def ui_error_message(error_msg, show_details=True):
    """
    Muestra un mensaje de error formateado.

    Args:
        error_msg: Mensaje de error
        show_details: Mostrar detalles adicionales
    """
    st.error(f"⚠️ {error_msg}")

    if show_details:
        with st.expander("Ver detalles del error"):
            st.code(traceback.format_exc())
            st.info(
                "Si el problema persiste, contacta con el administrador del sistema.")


def ui_success_message(msg):
    """
    Muestra un mensaje de éxito formateado.

    Args:
        msg: Mensaje de éxito
    """
    st.success(f"✅ {msg}")


def ui_info_message(msg):
    """
    Muestra un mensaje informativo formateado.

    Args:
        msg: Mensaje informativo
    """
    st.info(f"ℹ️ {msg}")


def ui_warning_message(msg):
    """
    Muestra un mensaje de advertencia formateado.

    Args:
        msg: Mensaje de advertencia
    """
    st.warning(f"⚠️ {msg}")


def ui_show_progress(title, value, max_value=100, style="progress"):
    """
    Muestra una barra de progreso con diferentes estilos.

    Args:
        title: Título del progreso
        value: Valor actual
        max_value: Valor máximo
        style: Estilo (progress/metric/percent)
    """
    if style == "progress":
        st.markdown(f"#### {title}")
        st.progress(value / max_value)
    elif style == "metric":
        st.metric(title, f"{value}/{max_value}")
    elif style == "percent":
        percent = (value / max_value) * 100
        st.metric(title, f"{percent:.0f}%")
    else:
        st.markdown(f"**{title}:** {value}/{max_value}")


def ui_confirm_dialog(title, message, ok_button="Confirmar", cancel_button="Cancelar"):
    """
    Muestra un diálogo de confirmación.

    Args:
        title: Título del diálogo
        message: Mensaje del diálogo
        ok_button: Texto del botón de confirmación
        cancel_button: Texto del botón de cancelación

    Returns:
        bool: True si se confirma, False si se cancela
    """
    st.markdown(f"### {title}")
    st.markdown(message)

    col1, col2 = st.columns(2)
    with col1:
        cancel = st.button(cancel_button, key=f"cancel_{hash(title)}")
    with col2:
        confirm = st.button(ok_button, key=f"confirm_{hash(title)}")

    if confirm:
        return True

    if cancel:
        return False

    return None  # No se ha tomado decisión


def ui_tooltip(text, tooltip):
    """
    Muestra un texto con tooltip al pasar el ratón.

    Args:
        text: Texto a mostrar
        tooltip: Texto del tooltip
    """
    st.markdown(f"""
    <span title="{tooltip}" style="border-bottom: 1px dotted #000; cursor: help;">
        {text}
    </span>
    """, unsafe_allow_html=True)


def ui_feedback_form():
    """
    Muestra un formulario de feedback para el usuario.

    Returns:
        dict: Datos del feedback o None si no se envía
    """
    with st.expander("📝 Danos tu opinión", expanded=False):
        with st.form(key="feedback_form"):
            st.markdown("### Nos gustaría conocer tu opinión")

            rating = st.slider(
                "¿Cómo valorarías la utilidad de esta herramienta?",
                min_value=1,
                max_value=5,
                value=4,
                help="1 = Poco útil, 5 = Muy útil"
            )

            feedback_text = st.text_area(
                "Comentarios o sugerencias:",
                height=100,
                help="¿Qué podríamos mejorar?"
            )

            submit = st.form_submit_button("Enviar feedback")

            if submit:
                # En una implementación real, aquí se enviaría el feedback a una base de datos
                ui_success_message("¡Gracias por tu feedback!")
                return {
                    "rating": rating,
                    "feedback": feedback_text,
                    "timestamp": datetime.now().isoformat()
                }

            return None
        """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 7: Generación de Informes
==================================================================================

Este artefacto contiene las funciones para generar informes en diferentes formatos:
1. Generación de informes DOCX
2. Generación de informes HTML
3. Generación de informes CSV
"""

# --- 1. GENERACIÓN DE INFORME DOCX (FUNCIÓN CORREGIDA) ---


def generar_informe_docx(nombre, nivel, fecha, texto_original, texto_corregido, errores_obj, analisis_contextual, consejo_final):
    """
    Genera un informe de corrección en formato Word (DOCX).
    Versión optimizada con mejor manejo de errores y validación.

    Args:
        nombre: Nombre del estudiante
        nivel: Nivel del estudiante
        fecha: Fecha de la corrección
        texto_original: Texto original del estudiante
        texto_corregido: Texto con correcciones
        errores_obj: Objeto con errores detectados
        analisis_contextual: Objeto con análisis contextual
        consejo_final: Consejo final para el estudiante

    Returns:
        BytesIO: Buffer con el documento generado
    """
    try:
        # Crear el documento desde cero
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

        # SOLUCIÓN: Simplificar verificación de errores
        if isinstance(errores_obj, dict):
            for categoria, errores in errores_obj.items():
                if isinstance(errores, list) and errores:
                    doc.add_heading(categoria, level=2)
                    for i, err in enumerate(errores, 1):
                        if not isinstance(err, dict):
                            continue

                        p = doc.add_paragraph()
                        fragmento = err.get('fragmento_erroneo', '')
                        if fragmento:
                            run = p.add_run('Fragmento erróneo: ')
                            run.bold = True
                            run = p.add_run(fragmento)
                            run.font.color.rgb = RGBColor(255, 0, 0)

                        correccion = err.get('correccion', '')
                        if correccion:
                            p = doc.add_paragraph()
                            run = p.add_run('Corrección: ')
                            run.bold = True
                            run = p.add_run(correccion)
                            run.font.color.rgb = RGBColor(0, 128, 0)

                        explicacion = err.get('explicacion', '')
                        if explicacion:
                            p = doc.add_paragraph()
                            run = p.add_run('Explicación: ')
                            run.bold = True
                            p.add_run(explicacion)

                        doc.add_paragraph()  # Espacio
        else:
            doc.add_paragraph("No se detectaron errores significativos.")

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

        # SOLUCIÓN: Simplificar verificación de análisis contextual
        # Datos
        row_cells = table.add_row().cells
        row_cells[0].text = 'Puntuación'

        # Manejar valores de manera más simple
        coherencia = analisis_contextual.get('coherencia', {}) if isinstance(
            analisis_contextual, dict) else {}
        cohesion = analisis_contextual.get('cohesion', {}) if isinstance(
            analisis_contextual, dict) else {}
        registro = analisis_contextual.get('registro_linguistico', {}) if isinstance(
            analisis_contextual, dict) else {}
        adecuacion = analisis_contextual.get('adecuacion_cultural', {}) if isinstance(
            analisis_contextual, dict) else {}

        row_cells[1].text = str(coherencia.get('puntuacion', 'N/A'))
        row_cells[2].text = str(cohesion.get('puntuacion', 'N/A'))
        row_cells[3].text = str(registro.get('puntuacion', 'N/A'))
        row_cells[4].text = str(adecuacion.get('puntuacion', 'N/A'))

        # Añadir comentarios del análisis contextual
        if coherencia:
            doc.add_heading('Coherencia textual', level=3)
            doc.add_paragraph(coherencia.get('comentario', 'No disponible'))

        if cohesion:
            doc.add_heading('Cohesión textual', level=3)
            doc.add_paragraph(cohesion.get('comentario', 'No disponible'))

        if registro:
            doc.add_heading('Registro lingüístico', level=3)
            doc.add_paragraph(
                f"Tipo detectado: {registro.get('tipo_detectado', 'No especificado')}")
            doc.add_paragraph(registro.get('adecuacion', 'No disponible'))

        if adecuacion:
            doc.add_heading('Adecuación cultural', level=3)
            doc.add_paragraph(adecuacion.get('comentario', 'No disponible'))

        # Consejo final
        doc.add_heading('Consejo final', level=1)
        doc.add_paragraph(consejo_final or "No disponible")

        # SOLUCIÓN: Simplificar generación del QR
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )

            # Generar un ID único para el informe
            informe_id = f"{nombre.replace(' ', '')}_{fecha.replace(' ', '_').replace(':', '-')}"
            qr_data = f"textocorrector://informe/{informe_id}"
            qr.add_data(qr_data)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")

            # Guardar QR como imagen temporal
            qr_buffer = BytesIO()
            img.save(qr_buffer)
            qr_buffer.seek(0)

            # Añadir la imagen del QR al documento
            doc.add_heading('Acceso online', level=1)
            doc.add_paragraph(
                'Escanea este código QR para acceder a este informe online:')

            # Añadir la imagen
            doc.add_picture(qr_buffer, width=Inches(2.0))

            # Cerrar el buffer del QR
            qr_buffer.close()
        except Exception as qr_error:
            # Si hay error con el QR, simplemente seguimos sin él
            doc.add_heading('Acceso online', level=1)
            doc.add_paragraph('Código QR no disponible en este momento.')

        # SOLUCIÓN: Guardar el documento simplificado
        docx_buffer = BytesIO()
        doc.save(docx_buffer)
        docx_buffer.seek(0)

        return docx_buffer

    except Exception as e:
        # Si hay un error general, hacemos un log y devolvemos None
        logger.error(f"Error al generar informe DOCX: {str(e)}")
        logger.error(traceback.format_exc())
        return None

# --- 2. GENERACIÓN DE INFORME HTML (FUNCIÓN CORREGIDA) ---


def generar_informe_html(nombre, nivel, fecha, texto_original, texto_corregido, analisis_contextual, consejo_final):
    """
    Genera un informe de corrección en formato HTML.
    Versión optimizada con mejor manejo de valores nulos y formato.

    Args:
        nombre: Nombre del estudiante
        nivel: Nivel del estudiante
        fecha: Fecha de la corrección
        texto_original: Texto original del estudiante
        texto_corregido: Texto con correcciones
        analisis_contextual: Objeto con análisis contextual
        consejo_final: Consejo final para el estudiante

    Returns:
        str: Contenido HTML del informe
    """
    try:
        # SOLUCIÓN: Simplificar verificación de entradas
        # Usar valores seguros por defecto de manera más directa
        nombre = nombre or "Estudiante"
        nivel = nivel or "No especificado"
        fecha = fecha or datetime.now().strftime("%Y-%m-%d %H:%M")
        texto_original = texto_original or "No disponible"
        texto_corregido = texto_corregido or "No disponible"
        consejo_final = consejo_final or "No disponible"
        app_version = APP_VERSION

        # Función para sanitizar HTML
        def sanitize_html(text):
            if not text:
                return ""
            # Reemplazar caracteres problemáticos
            sanitized = text.replace("<", "&lt;").replace(">", "&gt;")
            # Convertir saltos de línea en <br>
            sanitized = sanitized.replace("\n", "<br>")
            return sanitized

        # Sanitizar textos
        texto_original_safe = sanitize_html(texto_original)
        texto_corregido_safe = sanitize_html(texto_corregido)
        consejo_final_safe = sanitize_html(consejo_final)

        # SOLUCIÓN: Simplificar verificación de análisis contextual
        analisis_contextual = analisis_contextual if isinstance(
            analisis_contextual, dict) else {}

        # Extraer datos de análisis contextual con manejo seguro
        coherencia = analisis_contextual.get('coherencia', {})
        cohesion = analisis_contextual.get('cohesion', {})
        registro = analisis_contextual.get('registro_linguistico', {})
        adecuacion = analisis_contextual.get('adecuacion_cultural', {})

        puntuacion_coherencia = coherencia.get('puntuacion', 'N/A')
        puntuacion_cohesion = cohesion.get('puntuacion', 'N/A')
        puntuacion_registro = registro.get('puntuacion', 'N/A')
        puntuacion_adecuacion = adecuacion.get('puntuacion', 'N/A')

        # Crear HTML con estructura mejorada
        html_content = f'''
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Informe de corrección - {nombre}</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    line-height: 1.6; 
                    margin: 0;
                    padding: 20px;
                    color: #333;
                }}
                .container {{ 
                    max-width: 800px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                    background-color: #fff;
                    border-radius: 5px;
                }}
                h1 {{ 
                    color: #2c3e50; 
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2 {{ 
                    color: #3498db; 
                    margin-top: 30px; 
                    border-left: 4px solid #3498db;
                    padding-left: 10px;
                }}
                h3 {{ 
                    color: #2980b9; 
                    margin-top: 20px;
                }}
                .original {{ 
                    background-color: #f8f9fa; 
                    padding: 15px; 
                    border-left: 4px solid #6c757d; 
                    white-space: pre-wrap;
                    margin: 15px 0;
                    border-radius: 4px;
                }}
                .corregido {{ 
                    background-color: #e7f4e4; 
                    padding: 15px; 
                    border-left: 4px solid #28a745; 
                    white-space: pre-wrap;
                    margin: 15px 0;
                    border-radius: 4px;
                }}
                .puntuaciones {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                    margin: 20px 0;
                }}
                .puntuaciones th, .puntuaciones td {{ 
                    border: 1px solid #ddd; 
                    padding: 10px; 
                    text-align: center;
                }}
                .puntuaciones th {{ 
                    background-color: #f2f2f2; 
                    font-weight: bold;
                }}
                .consejo {{ 
                    background-color: #e7f5fe; 
                    padding: 15px; 
                    border-left: 4px solid #17a2b8; 
                    margin: 20px 0;
                    border-radius: 4px;
                }}
                .footer {{ 
                    margin-top: 50px; 
                    padding-top: 20px; 
                    border-top: 1px solid #ddd; 
                    color: #6c757d; 
                    font-size: 0.8em;
                    text-align: center;
                }}
                @media print {{
                    body {{ background-color: #fff; }}
                    .container {{ box-shadow: none; }}
                    a {{ text-decoration: none; color: #000; }}
                }}
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
                        {texto_original_safe}
                    </div>

                    <h2>Texto corregido</h2>
                    <div class="corregido">
                        {texto_corregido_safe}
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
                            <td>{puntuacion_coherencia}/10</td>
                            <td>{puntuacion_cohesion}/10</td>
                            <td>{puntuacion_registro}/10</td>
                            <td>{puntuacion_adecuacion}/10</td>
                        </tr>
                    </table>
                    
                    <h3>Coherencia textual</h3>
                    <p>{sanitize_html(coherencia.get('comentario', 'No disponible'))}</p>
                    
                    <h3>Cohesión textual</h3>
                    <p>{sanitize_html(cohesion.get('comentario', 'No disponible'))}</p>
                    
                    <h3>Registro lingüístico</h3>
                    <p><strong>Tipo detectado:</strong> {sanitize_html(registro.get('tipo_detectado', 'No especificado'))}</p>
                    <p>{sanitize_html(registro.get('adecuacion', 'No disponible'))}</p>
                    
                    <h3>Adecuación cultural</h3>
                    <p>{sanitize_html(adecuacion.get('comentario', 'No disponible'))}</p>
                </section>

                <section>
                    <h2>Consejo final</h2>
                    <div class="consejo">
                        <p>{consejo_final_safe}</p>
                    </div>
                </section>

                <div class="footer">
                    <p>Textocorrector ELE - Informe generado el {fecha} - Versión {app_version}</p>
                    <p>Este informe fue generado automáticamente por la aplicación Textocorrector ELE</p>
                </div>
            </div>
        </body>
        </html>
        '''

        return html_content

    except Exception as e:
        logger.error(f"Error al generar informe HTML: {str(e)}")
        logger.error(traceback.format_exc())

        # Crear HTML básico de error
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>Error en informe</title></head>
        <body>
            <h1>Error al generar informe</h1>
            <p>Se produjo un error al generar el informe. Por favor, inténtelo de nuevo.</p>
        </body>
        </html>
        '''

# --- 3. GENERACIÓN DE INFORME CSV ---


def generar_csv_analisis(nombre, nivel, fecha, datos_analisis):
    """
    Genera un archivo CSV con los datos de análisis de una corrección.
    Versión mejorada con mejor manejo de errores y formato consistente.

    Args:
        nombre: Nombre del estudiante
        nivel: Nivel del estudiante
        fecha: Fecha de la corrección
        datos_analisis: Diccionario con datos de análisis

    Returns:
        BytesIO: Buffer con el CSV generado
    """
    try:
        # Asegurar que tenemos datos válidos
        nombre = nombre or "Estudiante"
        nivel = nivel or "No especificado"
        fecha = fecha or datetime.now().strftime("%Y-%m-%d %H:%M")

        # Verificar que datos_analisis es un diccionario
        if not isinstance(datos_analisis, dict):
            datos_analisis = {}

        # Extraer datos con manejo seguro
        errores = datos_analisis.get("errores", {}) or {}
        analisis_contextual = datos_analisis.get(
            "analisis_contextual", {}) or {}

        # Contar errores por categoría con validación
        num_gramatica = len(errores.get("Gramática", [])) if isinstance(
            errores.get("Gramática"), list) else 0
        num_lexico = len(errores.get("Léxico", [])) if isinstance(
            errores.get("Léxico"), list) else 0
        num_puntuacion = len(errores.get("Puntuación", [])) if isinstance(
            errores.get("Puntuación"), list) else 0
        num_estructura = len(errores.get("Estructura textual", [])) if isinstance(
            errores.get("Estructura textual"), list) else 0
        total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

        # Extraer puntuaciones con validación
        coherencia = analisis_contextual.get("coherencia", {}) or {}
        cohesion = analisis_contextual.get("cohesion", {}) or {}
        registro = analisis_contextual.get("registro_linguistico", {}) or {}
        adecuacion = analisis_contextual.get("adecuacion_cultural", {}) or {}

        # Convertir a valores numéricos o 0 si no están disponibles
        def safe_numeric(val, default=0):
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        coherencia_punt = safe_numeric(coherencia.get("puntuacion"))
        cohesion_punt = safe_numeric(cohesion.get("puntuacion"))
        registro_punt = safe_numeric(registro.get("puntuacion"))
        adecuacion_punt = safe_numeric(adecuacion.get("puntuacion"))

        # Extraer consejo final
        consejo_final = datos_analisis.get("consejo_final", "")
        # Limitar a 100 caracteres para el CSV
        consejo_resumen = consejo_final[:100] + "..." if consejo_final and len(
            consejo_final) > 100 else consejo_final

        # Crear CSV en memoria
        csv_buffer = StringIO()

        # Encabezados
        csv_buffer.write("Categoría,Dato\n")

        # Datos básicos
        csv_buffer.write(f"Nombre,{nombre}\n")
        csv_buffer.write(f"Nivel,{nivel}\n")
        csv_buffer.write(f"Fecha,{fecha}\n")

        # Datos de errores
        csv_buffer.write(f"Errores Gramática,{num_gramatica}\n")
        csv_buffer.write(f"Errores Léxico,{num_lexico}\n")
        csv_buffer.write(f"Errores Puntuación,{num_puntuacion}\n")
        csv_buffer.write(f"Errores Estructura,{num_estructura}\n")
        csv_buffer.write(f"Total Errores,{total_errores}\n")

        # Datos de análisis contextual
        csv_buffer.write(f"Puntuación Coherencia,{coherencia_punt}\n")
        csv_buffer.write(f"Puntuación Cohesión,{cohesion_punt}\n")
        csv_buffer.write(f"Puntuación Registro,{registro_punt}\n")
        csv_buffer.write(f"Puntuación Adecuación Cultural,{adecuacion_punt}\n")

        # Datos adicionales (sin incluir texto completo)
        csv_buffer.write(
            f"Tipo Registro,{registro.get('tipo_detectado', 'No especificado')}\n")
        csv_buffer.write(f"Consejo Final (Resumen),{consejo_resumen}\n")

        # Convertir a bytes
        csv_bytes = csv_buffer.getvalue().encode(
            'utf-8-sig')  # Usar UTF-8 con BOM para Excel

        # Crear buffer de bytes
        bytes_buffer = BytesIO(csv_bytes)
        bytes_buffer.seek(0)  # Importante: posicionar al inicio del buffer

        return bytes_buffer

    except Exception as e:
        logger.error(f"Error al generar CSV: {str(e)}")
        logger.error(traceback.format_exc())

        # Crear CSV básico con mensaje de error
        csv_buffer = StringIO()
        csv_buffer.write("Error,Mensaje\n")
        csv_buffer.write(f"Error al generar CSV,{str(e)}\n")

        return BytesIO(csv_buffer.getvalue().encode('utf-8-sig'))
    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 8: Visualización de Resultados y Componentes UI Avanzados
==================================================================================

Este artefacto contiene:
1. Funciones para mostrar los resultados de corrección
2. Funciones para exportar informes (UI)
3. Componentes de UI avanzados
"""

# --- 1. VISUALIZACIÓN DE RESULTADOS DE CORRECCIÓN ---


def ui_show_correction_results(result, show_export=True):
    """
    Muestra los resultados de una corrección de texto.

    Args:
        result: Resultados de la corrección
        show_export: Mostrar opciones de exportación
    """
    if "error" in result:
        st.error(f"Error en la corrección: {result['error']}")
        return

    # Extraer campos del JSON
    saludo = result.get("saludo", "")
    tipo_texto_detectado = result.get("tipo_texto", "")
    errores_obj = result.get("errores", {})
    texto_corregido = result.get("texto_corregido", "")
    analisis_contextual = result.get("analisis_contextual", {})
    consejo_final = result.get("consejo_final", "")
    fin = result.get("fin", "")

    # Extraer puntuaciones del análisis contextual
    coherencia = analisis_contextual.get("coherencia", {})
    cohesion = analisis_contextual.get("cohesion", {})
    registro = analisis_contextual.get("registro_linguistico", {})
    adecuacion = analisis_contextual.get("adecuacion_cultural", {})

    puntuacion_coherencia = coherencia.get("puntuacion", 0)
    puntuacion_cohesion = cohesion.get("puntuacion", 0)
    puntuacion_registro = registro.get("puntuacion", 0)
    puntuacion_adecuacion = adecuacion.get("puntuacion", 0)

    # --- CONTEO DE ERRORES ---
    num_gramatica = len(errores_obj.get("Gramática", []))
    num_lexico = len(errores_obj.get("Léxico", []))
    num_puntuacion = len(errores_obj.get("Puntuación", []))
    num_estructura = len(errores_obj.get("Estructura textual", []))
    total_errores = num_gramatica + num_lexico + num_puntuacion + num_estructura

    # --- MOSTRAR RESULTADOS EN LA INTERFAZ ---
    # Mostrar el saludo directamente
    st.write(saludo)

    # Mostrar tipo de texto detectado con contextualización
    st.info(
        f"He identificado tu escrito como un texto de tipo **{tipo_texto_detectado.lower()}**.")

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
                            st.error(f"❌ {err.get('fragmento_erroneo', '')}")
                        with col2:
                            st.success(f"✅ {err.get('correccion', '')}")
                        st.info(f"💡 {err.get('explicacion', '')}")
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
    puntuaciones = [puntuacion_coherencia, puntuacion_cohesion,
                    puntuacion_registro, puntuacion_adecuacion]
    categorias = ["Coherencia", "Cohesión", "Registro", "Ad. Cultural"]

    # Calcular el promedio de las puntuaciones
    promedio_contextual = sum(puntuaciones) / \
        len(puntuaciones) if puntuaciones else 0

    # Mostrar un progreso general
    st.markdown(f"##### Evaluación global: {promedio_contextual:.1f}/10")
    st.progress(promedio_contextual / 10)

    # Detalles de coherencia
    with st.expander("Coherencia textual", expanded=True):
        st.markdown(f"**Comentario**: {coherencia.get('comentario', '')}")
        sugerencias = coherencia.get("sugerencias", [])
        if sugerencias:
            st.markdown("**Sugerencias para mejorar:**")
            for sug in sugerencias:
                st.markdown(f"- {sug}")

    # Detalles de cohesión
    with st.expander("Cohesión textual", expanded=True):
        st.markdown(f"**Comentario**: {cohesion.get('comentario', '')}")
        sugerencias = cohesion.get("sugerencias", [])
        if sugerencias:
            st.markdown("**Sugerencias para mejorar:**")
            for sug in sugerencias:
                st.markdown(f"- {sug}")

    # Detalles de registro lingüístico
    with st.expander("Registro lingüístico", expanded=True):
        st.markdown(
            f"**Tipo de registro detectado**: {registro.get('tipo_detectado', '')}")
        st.markdown(
            f"**Adecuación al contexto**: {registro.get('adecuacion', '')}")
        sugerencias = registro.get("sugerencias", [])
        if sugerencias:
            st.markdown("**Sugerencias para mejorar:**")
            for sug in sugerencias:
                st.markdown(f"- {sug}")

    # Detalles de adecuación cultural
    with st.expander("Adecuación cultural y pragmática", expanded=True):
        st.markdown(f"**Comentario**: {adecuacion.get('comentario', '')}")
        elementos = adecuacion.get("elementos_destacables", [])
        if elementos:
            st.markdown("**Elementos culturales destacables:**")
            for elem in elementos:
                st.markdown(f"- {elem}")
        sugerencias = adecuacion.get("sugerencias", [])
        if sugerencias:
            st.markdown("**Sugerencias para mejorar:**")
            for sug in sugerencias:
                st.markdown(f"- {sug}")

    # Consejo final
    st.subheader("Consejo final")
    st.info(consejo_final)
    st.write(fin)

    # --- GENERAR AUDIO CON ELEVENLABS (Consejo final en español) ---
    if consejo_final:
        st.markdown("**🔊 Consejo leído en voz alta:**")
        with st.spinner("Generando audio con ElevenLabs..."):
            audio_bytes = generar_audio_consejo(consejo_final)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mpeg")
            else:
                st.warning("⚠️ No se pudo generar el audio del consejo.")

    # --- MOSTRAR RECOMENDACIONES PERSONALIZADAS ---
    ui_show_recommendations(errores_obj, analisis_contextual, get_session_var(
        "nivel_estudiante", "intermedio"), "Spanish")

    # --- OPCIONES DE EXPORTACIÓN ---
    if show_export:
        ui_export_options(result)

# --- 2. MOSTRAR RECOMENDACIONES ---


# Base de datos simplificada de recursos por niveles y categorías
RECURSOS_DB = {
    "A1-A2": {
        "Gramática": [
            {"título": "Presente de indicativo", "tipo": "Ficha",
                "url": "https://www.profedeele.es/gramatica/presente-indicativo/", "nivel": "A1"},
            {"título": "Los artículos en español", "tipo": "Vídeo",
                "url": "https://www.youtube.com/watch?v=example1", "nivel": "A1"},
            {"título": "Ser y estar", "tipo": "Ejercicios",
                "url": "https://aprenderespanol.org/ejercicios/ser-estar", "nivel": "A2"},
            {"título": "Pretérito indefinido", "tipo": "Explicación",
                "url": "https://www.cervantes.es/gramatica/indefinido", "nivel": "A2"}
        ],
        "Léxico": [
            {"título": "Vocabulario básico", "tipo": "Ficha",
                "url": "https://www.spanishdict.com/vocabulario-basico", "nivel": "A1"},
            {"título": "Alimentos y comidas", "tipo": "Tarjetas",
                "url": "https://quizlet.com/es/alimentos", "nivel": "A1"},
            {"título": "La ciudad", "tipo": "Podcast",
                "url": "https://spanishpod101.com/la-ciudad", "nivel": "A2"}
        ],
        "Cohesión": [
            {"título": "Conectores básicos", "tipo": "Guía",
                "url": "https://www.lingolia.com/es/conectores-basicos", "nivel": "A2"},
            {"título": "Organizar ideas", "tipo": "Ejercicios",
                "url": "https://www.todo-claro.com/organizacion", "nivel": "A2"}
        ],
        "Registro": [
            {"título": "Saludos formales e informales", "tipo": "Vídeo",
                "url": "https://www.youtube.com/watch?v=example2", "nivel": "A1"},
            {"título": "Peticiones corteses", "tipo": "Diálogos",
                "url": "https://www.lingoda.com/es/cortesia", "nivel": "A2"}
        ]
    },
    "B1-B2": {
        "Gramática": [
            {"título": "Subjuntivo presente", "tipo": "Guía",
                "url": "https://www.profedeele.es/subjuntivo-presente/", "nivel": "B1"},
            {"título": "Estilo indirecto", "tipo": "Ejercicios",
                "url": "https://www.cervantes.es/estilo-indirecto", "nivel": "B2"}
        ],
        "Léxico": [
            {"título": "Expresiones idiomáticas", "tipo": "Podcast",
                "url": "https://spanishpod101.com/expresiones", "nivel": "B1"},
            {"título": "Vocabulario académico", "tipo": "Glosario",
                "url": "https://cvc.cervantes.es/vocabulario-academico", "nivel": "B2"}
        ],
        "Cohesión": [
            {"título": "Marcadores discursivos", "tipo": "Guía",
                "url": "https://www.cervantes.es/marcadores", "nivel": "B1"},
            {"título": "Conectores argumentativos", "tipo": "Ejercicios",
                "url": "https://www.todo-claro.com/conectores", "nivel": "B2"}
        ],
        "Registro": [
            {"título": "Lenguaje formal e informal", "tipo": "Curso",
             "url": "https://www.coursera.org/spanish-registers", "nivel": "B1"},
            {"título": "Comunicación profesional", "tipo": "Ejemplos",
                "url": "https://www.cervantes.es/comunicacion-profesional", "nivel": "B2"}
        ]
    },
    "C1-C2": {
        "Gramática": [
            {"título": "Construcciones pasivas", "tipo": "Análisis",
                "url": "https://www.profedeele.es/pasivas-avanzadas/", "nivel": "C1"},
            {"título": "Subordinadas complejas", "tipo": "Guía",
                "url": "https://www.cervantes.es/subordinadas", "nivel": "C2"}
        ],
        "Léxico": [
            {"título": "Lenguaje académico", "tipo": "Corpus",
                "url": "https://www.rae.es/corpus-academico", "nivel": "C1"},
            {"título": "Variantes dialectales", "tipo": "Curso",
                "url": "https://www.coursera.org/variantes-espanol", "nivel": "C2"}
        ],
        "Cohesión": [
            {"título": "Estructura textual avanzada", "tipo": "Manual",
                "url": "https://www.uned.es/estructura-textual", "nivel": "C1"},
            {"título": "Análisis del discurso", "tipo": "Investigación",
                "url": "https://cvc.cervantes.es/analisis-discurso", "nivel": "C2"}
        ],
        "Registro": [
            {"título": "Pragmática intercultural", "tipo": "Seminario",
                "url": "https://www.cervantes.es/pragmatica", "nivel": "C1"},
            {"título": "Lenguaje literario", "tipo": "Análisis",
                "url": "https://www.rae.es/lenguaje-literario", "nivel": "C2"}
        ]
    }
}


def ui_show_recommendations(errores_obj, analisis_contextual, nivel, idioma):
    """
    Muestra recomendaciones personalizadas basadas en el análisis.

    Args:
        errores_obj: Objeto con errores detectados
        analisis_contextual: Objeto con análisis contextual
        nivel: Nivel del estudiante
        idioma: Idioma de las instrucciones
    """
    st.header("📚 Recomendaciones personalizadas")

    # Pestañas para diferentes tipos de recomendaciones
    tab1, tab2 = st.tabs(
        ["📖 Recursos recomendados", "✏️ Ejercicios personalizados"])

    with tab1:
        recursos = obtener_recursos_recomendados(
            errores_obj, analisis_contextual, nivel)

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
                errores_obj, analisis_contextual, nivel, idioma)

            ejercicios = ejercicios_data.get("ejercicios", [])

            for i, ejercicio in enumerate(ejercicios):
                # Usar st.expander para el ejercicio principal
                with st.expander(f"{ejercicio.get('titulo', f'Ejercicio {i+1}')}"):
                    # Crear pestañas para ejercicio y solución
                    ejercicio_tab, solucion_tab = st.tabs(
                        ["Ejercicio", "Solución"])

                    with ejercicio_tab:
                        st.markdown(
                            f"**{ejercicio.get('tipo', 'Actividad')}**")
                        st.markdown(
                            f"*Instrucciones:* {ejercicio.get('instrucciones', '')}")
                        st.markdown("---")
                        st.markdown(ejercicio.get('contenido', ''))

                    with solucion_tab:
                        st.markdown(f"#### Solución del ejercicio:")
                        st.markdown(ejercicio.get('solucion', ''))


def obtener_recursos_recomendados(errores_obj, analisis_contextual, nivel):
    """
    Obtiene recursos recomendados basados en los errores y análisis del estudiante.

    Args:
        errores_obj: Objeto con errores detectados
        analisis_contextual: Objeto con análisis contextual
        nivel: Nivel del estudiante

    Returns:
        list: Lista de recursos recomendados
    """
    recursos_recomendados = []

    try:
        # Verificar entradas
        if not isinstance(errores_obj, dict):
            errores_obj = {}
        if not isinstance(analisis_contextual, dict):
            analisis_contextual = {}

        # Determinar el nivel para buscar recursos
        if "principiante" in nivel.lower():
            nivel_db = "A1-A2"
        elif "intermedio" in nivel.lower():
            nivel_db = "B1-B2"
        else:
            nivel_db = "C1-C2"

        # Verificar errores gramaticales
        if len(errores_obj.get("Gramática", [])) > 0:
            recursos_gramatica = RECURSOS_DB.get(
                nivel_db, {}).get("Gramática", [])
            if recursos_gramatica:
                recursos_recomendados.extend(recursos_gramatica[:2])

        # Verificar errores léxicos
        if len(errores_obj.get("Léxico", [])) > 0:
            recursos_lexico = RECURSOS_DB.get(nivel_db, {}).get("Léxico", [])
            if recursos_lexico:
                recursos_recomendados.extend(recursos_lexico[:2])

        # Verificar problemas de cohesión
        if analisis_contextual.get("cohesion", {}).get("puntuacion", 10) < 7:
            recursos_cohesion = RECURSOS_DB.get(
                nivel_db, {}).get("Cohesión", [])
            if recursos_cohesion:
                recursos_recomendados.extend(recursos_cohesion[:1])

        # Verificar problemas de registro
        if analisis_contextual.get("registro_linguistico", {}).get("puntuacion", 10) < 7:
            recursos_registro = RECURSOS_DB.get(
                nivel_db, {}).get("Registro", [])
            if recursos_registro:
                recursos_recomendados.extend(recursos_registro[:1])

    except Exception as e:
        logger.error(f"Error al obtener recursos: {str(e)}")

    return recursos_recomendados

# --- 3. UI PARA EXPORTACIÓN DE RESULTADOS (FUNCIÓN CORREGIDA) ---


def ui_export_options(data):
    """
    Muestra opciones para exportar los resultados de la corrección.
    Versión optimizada que evita usar botones dentro de formularios.

    Args:
        data: Resultados de la corrección
    """
    st.header("📊 Exportar informe")

    # Verificación básica de datos
    if not isinstance(data, dict):
        st.warning("⚠️ No hay datos suficientes para exportar.")
        return

    # Extraer datos para la exportación con manejo seguro
    nombre = get_session_var("usuario_actual", "Usuario")
    nivel = get_session_var("nivel_estudiante", "intermedio")
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    texto_original = get_session_var("ultimo_texto", "")
    texto_corregido = data.get("texto_corregido", "")
    errores_obj = data.get("errores", {})
    analisis_contextual = data.get("analisis_contextual", {})
    consejo_final = data.get("consejo_final", "")

    # Opciones de exportación en pestañas
    export_tab1, export_tab2, export_tab3 = st.tabs(
        ["📝 Documento Word", "🌐 Documento HTML", "📊 Excel/CSV"]
    )

    with export_tab1:
        st.write("Exporta este informe como documento Word (DOCX)")

        # SOLUCIÓN: Usar st.button directamente (no dentro de un form)
        if st.button("Generar documento Word", key="gen_docx"):
            with st.spinner("Generando documento Word..."):
                docx_buffer = generar_informe_docx(
                    nombre, nivel, fecha, texto_original, texto_corregido,
                    errores_obj, analisis_contextual, consejo_final
                )

                if docx_buffer:
                    nombre_archivo = f"informe_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.docx"
                    st.download_button(
                        label="📥 Descargar documento Word",
                        data=docx_buffer,
                        file_name=nombre_archivo,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="docx_download_corregir"
                    )
                    st.success("✅ Documento generado correctamente")
                else:
                    st.error(
                        "No se pudo generar el documento Word. Inténtalo de nuevo.")

    with export_tab2:
        st.write("Exporta este informe como página web (HTML)")

        # SOLUCIÓN: Usar st.button directamente (no dentro de un form)
        if st.button("Generar documento HTML", key="gen_html"):
            with st.spinner("Generando HTML..."):
                html_content = generar_informe_html(
                    nombre, nivel, fecha, texto_original, texto_corregido,
                    analisis_contextual, consejo_final
                )

                if html_content:
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
                    st.success("✅ HTML generado correctamente")

                    # Opción para previsualizar
                    with st.expander("Previsualizar HTML"):
                        # Sanitizar de manera segura para la previsualización
                        sanitized_html = html_content.replace('"', '&quot;')
                        st.markdown(
                            f'<iframe srcdoc="{sanitized_html}" width="100%" height="600" style="border: 1px solid #ddd; border-radius: 5px;"></iframe>',
                            unsafe_allow_html=True
                        )
                else:
                    st.error("No se pudo generar el HTML. Inténtalo de nuevo.")

    with export_tab3:
        st.write("Exporta los datos del análisis en formato CSV")

        # SOLUCIÓN: Usar st.button directamente (no dentro de un form)
        if st.button("Generar CSV", key="gen_csv"):
            with st.spinner("Generando CSV..."):
                csv_buffer = generar_csv_analisis(
                    nombre, nivel, fecha, data
                )

                if csv_buffer:
                    # Botón de descarga
                    nombre_archivo = f"datos_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.csv"
                    st.download_button(
                        label="📥 Descargar CSV",
                        data=csv_buffer,
                        file_name=nombre_archivo,
                        mime="text/csv",
                        key="csv_download_corregir"
                    )
                    st.success("✅ CSV generado correctamente")
                else:
                    st.error("No se pudo generar el CSV. Inténtalo de nuevo.")

                    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 9: Transcripción de Texto Manuscrito
==================================================================================

Este artefacto contiene las funciones corregidas para la transcripción de texto manuscrito:
1. Visualización de texto manuscrito
2. Herramienta de texto manuscrito
"""

# --- 1. VISUALIZACIÓN DE TEXTO MANUSCRITO (FUNCIÓN CORREGIDA) ---


def visualizar_texto_manuscrito():
    """
    Función corregida para visualizar y corregir texto transcrito de imágenes.
    Soluciona problemas de flujo entre transcripción y corrección.
    """
    st.subheader("Corrección de texto manuscrito transcrito")

    # Verificar si hay texto transcrito para corregir
    texto_transcrito = get_session_var("ultimo_texto_transcrito", "")
    if not texto_transcrito:
        st.info("No hay texto transcrito para corregir.")
        # Botón para volver a la herramienta de transcripción
        if st.button("Volver a transcripción", key="volver_transcripcion"):
            set_session_var("mostrar_correccion_transcripcion", False)
            st.rerun()
        return

    # Mostrar texto transcrito
    texto_transcrito_editable = st.text_area(
        "Texto transcrito (puedes editarlo si hay errores):",
        value=texto_transcrito,
        height=200,
        key="texto_transcrito_editable"
    )

    # Opciones de corrección
    options = ui_idioma_correcciones_tipo()

    # SOLUCIÓN: Crear un formulario en lugar de un botón simple
    # Esto evita problemas de estado y reinicios innecesarios
    with st.form(key="form_correccion_transcripcion"):
        st.write("Ajusta las opciones y haz clic en 'Corregir texto' para continuar.")

        # Botón de envío del formulario
        submit_correccion = st.form_submit_button(
            "Corregir texto", use_container_width=True)

    # Botones fuera del formulario
    col1, col2 = st.columns(2)

    with col1:
        # Botón para cancelar y volver
        if st.button("Cancelar y volver", key="cancelar_correccion_transcripcion"):
            set_session_var("mostrar_correccion_transcripcion", False)
            st.rerun()

    with col2:
        # Botón para enviar a la pestaña principal de corrección
        if st.button("Enviar a pestaña principal", key="enviar_a_principal"):
            # Guardar el texto para usarlo en la pestaña principal
            set_session_var("texto_correccion_corregir",
                            texto_transcrito_editable)
            set_session_var("mostrar_correccion_transcripcion", False)
            # Navegar a la pestaña de corrección
            st.session_state.tab_navigate_to = 0  # Índice de la pestaña "Corregir texto"
            # Recargar la página
            st.rerun()

    # Procesar la corrección cuando se envía el formulario
    if submit_correccion:
        if not texto_transcrito_editable.strip():
            st.warning(
                "El texto está vacío. Por favor, asegúrate de que hay contenido para corregir.")
        else:
            # Guardar para futura referencia
            set_session_var("ultimo_texto", texto_transcrito_editable)

            with st.spinner("Analizando texto transcrito..."):
                # Obtener datos necesarios
                nombre = get_session_var("usuario_actual", "Usuario")
                nivel = get_session_var("nivel_estudiante", "intermedio")

                # Llamar a la función de corrección directamente
                resultado = corregir_texto(
                    texto_transcrito_editable, nombre, nivel, options["idioma"],
                    options["tipo_texto"], options["contexto_cultural"],
                    "Texto transcrito de imagen manuscrita"
                )

                # Guardar resultado
                set_session_var("correction_result", resultado)
                set_session_var("last_correction_time",
                                datetime.now().isoformat())

                # Mostrar resultados sin recargar la página
                if "error" not in resultado:
                    # Mostrar los resultados primero
                    ui_show_correction_results(resultado)

                    # Añadir el botón para volver después
                    if st.button("Volver a transcripción", key="volver_despues_correccion"):
                        set_session_var(
                            "mostrar_correccion_transcripcion", False)
                        st.rerun()
                else:
                    st.error(f"Error en la corrección: {resultado['error']}")

# --- 2. HERRAMIENTA DE TEXTO MANUSCRITO (FUNCIÓN CORREGIDA) ---


def herramienta_texto_manuscrito():
    """
    Implementación optimizada de la herramienta de transcripción de textos manuscritos.
    Soluciona problemas de flujo entre transcripción y corrección.
    """
    st.subheader("✍️ Transcripción de textos manuscritos")
    st.markdown("""
    Esta herramienta te permite subir imágenes de textos manuscritos para transcribirlos
    automáticamente y luego enviarlos a corrección.
    """)

    # SOLUCIÓN: Verificar si estamos en modo de corrección de transcripción y usar un estado más robusto
    mostrar_correccion = get_session_var(
        "mostrar_correccion_transcripcion", False)
    if mostrar_correccion:
        # Redireccionamos al componente de visualización
        visualizar_texto_manuscrito()
        return

    # Selección de idioma para la transcripción
    idioma_manuscrito = st.selectbox(
        "Idioma del texto manuscrito:",
        ["Español", "Francés", "Inglés"],
        key="idioma_manuscrito"
    )

    # Mapeo de idiomas para la API
    idioma_map = {
        "Español": "es",
        "Francés": "fr",
        "Inglés": "en"
    }

    # Subida de imagen
    imagen_manuscrito = st.file_uploader(
        "Sube una imagen de tu texto manuscrito (JPG, PNG):",
        type=["jpg", "jpeg", "png"],
        key="imagen_manuscrito"
    )

    if imagen_manuscrito is not None:
        # Mostrar la imagen subida
        try:
            imagen = Image.open(imagen_manuscrito)
            # CORREGIDO: Reemplazo de use_column_width por use_container_width
            st.image(imagen, caption="Imagen subida", use_container_width=True)
        except Exception as e:
            st.error(f"Error al procesar la imagen: {str(e)}")
            return

        # SOLUCIÓN: Usar un formulario para la transcripción para evitar problemas de estado
        with st.form(key="form_transcribir_manuscrito"):
            st.write("Haz clic en el botón para transcribir el texto de la imagen.")
            submit_transcribir = st.form_submit_button(
                "Transcribir texto", use_container_width=True)

        if submit_transcribir:
            with st.spinner("Transcribiendo texto manuscrito..."):
                try:
                    # Leer bytes de la imagen
                    imagen_bytes = imagen_manuscrito.getvalue()

                    # Obtener código de idioma
                    codigo_idioma = idioma_map.get(idioma_manuscrito, "es")

                    # Transcribir la imagen
                    texto_transcrito = transcribir_imagen_texto(
                        imagen_bytes, codigo_idioma
                    )

                    if texto_transcrito and not texto_transcrito.startswith("Error"):
                        # Mostrar el texto transcrito
                        st.success("✅ Texto transcrito correctamente")

                        with st.expander("Texto transcrito", expanded=True):
                            st.write(texto_transcrito)

                            # Guardar en session_state de forma segura
                            set_session_var(
                                "ultimo_texto_transcrito", texto_transcrito)

                        # SOLUCIÓN: Añadir opciones para usar el texto transcrito
                        col1, col2 = st.columns(2)
                        with col1:
                            # Opción 1: Corregir directamente
                            if st.button("Corregir texto transcrito", key="btn_corregir_texto_transcrito"):
                                # Activar la bandera que mostrará la vista de corrección
                                set_session_var(
                                    "mostrar_correccion_transcripcion", True)
                                # Asegurar que estamos en la pestaña correcta para la próxima vez
                                st.session_state.active_tab_index = 4  # Índice de Herramientas complementarias
                                st.session_state.active_tools_tab_index = 3  # Índice de Texto manuscrito
                                # Recargar la página
                                st.rerun()
                        with col2:
                            # SOLUCIÓN NUEVA: Copiar a la pestaña principal de corrección
                            if st.button("Enviar a pestaña de corrección", key="btn_enviar_a_correccion"):
                                # Guardar el texto transcrito para usarlo en la pestaña principal
                                set_session_var(
                                    "texto_correccion_corregir", texto_transcrito)
                                # Navegar a la pestaña de corrección
                                st.session_state.tab_navigate_to = 0  # Índice de la pestaña "Corregir texto"
                                # Recargar la página
                                st.rerun()
                    else:
                        st.error(
                            texto_transcrito or "No se pudo transcribir el texto. Por favor, verifica que la imagen sea clara y contiene texto manuscrito legible.")

                except Exception as e:
                    st.error(f"Error durante la transcripción: {str(e)}")
                    logger.error(
                        f"Error en herramienta_texto_manuscrito: {str(e)}")
                    logger.error(traceback.format_exc())

                    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 10: Generación de Ejercicios Personalizados
==================================================================================

Este artefacto contiene la función para generar ejercicios personalizados según
las necesidades identificadas en la corrección.
"""


def generar_ejercicios_personalizado(errores_obj, analisis_contextual, nivel, idioma):
    """
    Genera ejercicios personalizados basados en los errores y análisis del estudiante.

    Args:
        errores_obj: Objeto con errores detectados
        analisis_contextual: Objeto con análisis contextual
        nivel: Nivel del estudiante
        idioma: Idioma de las instrucciones

    Returns:
        dict: Datos de ejercicios generados
    """
    client = get_openai_client()
    if client is None:
        return {"ejercicios": [{"titulo": "Servicio no disponible",
                                "tipo": "Error",
                                "instrucciones": "El servicio de generación de ejercicios no está disponible en este momento.",
                                "contenido": "Inténtelo más tarde.",
                                "solucion": "N/A"}]}

    if not circuit_breaker.can_execute("openai"):
        return {"ejercicios": [{"titulo": "Servicio temporalmente no disponible",
                                "tipo": "Error",
                                "instrucciones": "El servicio está temporalmente deshabilitado debido a errores previos.",
                                "contenido": "Inténtelo más tarde.",
                                "solucion": "N/A"}]}

    try:
        # Verificar entradas
        if not isinstance(errores_obj, dict):
            errores_obj = {}
        if not isinstance(analisis_contextual, dict):
            analisis_contextual = {}

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
        if "principiante" in nivel.lower():
            nivel_prompt = "A1-A2"
        elif "intermedio" in nivel.lower():
            nivel_prompt = "B1-B2"
        else:
            nivel_prompt = "C1-C2"

        # Obtener ejemplos de errores (con manejo seguro)
        ejemplos_gramatica = ", ".join([e.get('fragmento_erroneo', '')
                                       for e in errores_gramatica[:2]]) if errores_gramatica else ""
        ejemplos_lexico = ", ".join([e.get('fragmento_erroneo', '')
                                    for e in errores_lexico[:2]]) if errores_lexico else ""

        # Construir prompt para OpenAI
        prompt_ejercicios = f"""
        Basándote en los errores y análisis contextual de un estudiante de español de nivel {nivel_prompt},
        crea 3 ejercicios personalizados que le ayuden a mejorar. El estudiante tiene:
        
        - Errores gramaticales: {len(errores_gramatica)} {f"(ejemplos: {ejemplos_gramatica})" if ejemplos_gramatica else ""}
        - Errores léxicos: {len(errores_lexico)} {f"(ejemplos: {ejemplos_lexico})" if ejemplos_lexico else ""}
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
            }}
          ]
        }}
        """

        # Idioma para las instrucciones
        if idioma != "Español":
            prompt_ejercicios += f"\nTraduce las instrucciones y el título al {idioma}, pero mantén el contenido del ejercicio en español."

        def send_request():
            return client.chat.completions.create(
                model="gpt-4-turbo",
                temperature=0.7,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": "Eres un experto profesor de ELE especializado en crear ejercicios personalizados."},
                          {"role": "user", "content": prompt_ejercicios}]
            )

        # Usar sistema de reintentos
        response = retry_with_backoff(send_request, max_retries=2)
        raw_output = response.choices[0].message.content

        # Extraer JSON
        ejercicios_data = extract_json_safely(raw_output)

        # Verificar si se obtuvo un resultado válido
        if "error" in ejercicios_data:
            logger.warning(
                f"Error al extraer JSON de ejercicios: {ejercicios_data['error']}")
            return {"ejercicios": [{"titulo": "Ejercicio de repaso",
                                   "tipo": "Ejercicio de práctica",
                                    "instrucciones": "Revisa los elementos más problemáticos en tu texto",
                                    "contenido": "Contenido genérico de práctica",
                                    "solucion": "Consulta con tu profesor"}]}

        # Registrar éxito
        circuit_breaker.record_success("openai")
        return ejercicios_data

    except Exception as e:
        handle_exception("generar_ejercicios_personalizado", e)
        circuit_breaker.record_failure("openai")
        return {"ejercicios": [{"titulo": "Error en la generación",
                                "tipo": "Error controlado",
                                "instrucciones": "No se pudieron generar ejercicios personalizados",
                                "contenido": f"Error: {str(e)}",
                                "solucion": "Intenta de nuevo más tarde"}]}

        """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 11: Generación de Plan de Estudio Personalizado
==================================================================================

Este artefacto contiene la función para generar un plan de estudio personalizado
basado en el historial del estudiante.
"""


def generar_plan_estudio_personalizado(nombre, nivel, datos_historial):
    """
    Genera un plan de estudio personalizado basado en el historial del estudiante.

    Args:
        nombre: Nombre del estudiante
        nivel: Nivel del estudiante
        datos_historial: DataFrame con historial de correcciones

    Returns:
        dict: Plan de estudio generado
    """
    client = get_openai_client()
    if client is None:
        return {"error": "Servicio no disponible", "plan": None}

    if not circuit_breaker.can_execute("openai"):
        return {"error": "Servicio temporalmente no disponible", "plan": None}

    if datos_historial is None or datos_historial.empty:
        return {"error": "No hay suficientes datos para generar un plan personalizado", "plan": None}

    try:
        # Extraer estadísticas básicas
        if 'Errores Gramática' in datos_historial.columns and 'Errores Léxico' in datos_historial.columns:
            # Calcular promedios
            promedio_gramatica = datos_historial['Errores Gramática'].mean()
            promedio_lexico = datos_historial['Errores Léxico'].mean()

            # Verificar columnas de análisis contextual
            coherencia_promedio = datos_historial['Puntuación Coherencia'].mean(
            ) if 'Puntuación Coherencia' in datos_historial.columns else 5
            cohesion_promedio = datos_historial['Puntuación Cohesión'].mean(
            ) if 'Puntuación Cohesión' in datos_historial.columns else 5

            # Extraer nivel del último registro
            if 'Nivel' in datos_historial.columns:
                nivel_actual = datos_historial.iloc[-1]['Nivel']
            else:
                nivel_actual = nivel

            # Verificar consejos finales para extraer temas recurrentes
            temas_recurrentes = []
            if 'Consejo Final' in datos_historial.columns:
                # Aquí podríamos implementar un análisis más sofisticado de los consejos
                temas_recurrentes = ["conjugación verbal",
                                     "uso de preposiciones", "concordancia"]

            # Construir contexto para la IA
            errores_frecuentes = (
                f"Promedio de errores gramaticales: {promedio_gramatica:.1f}, "
                f"Promedio de errores léxicos: {promedio_lexico:.1f}. "
                f"Puntuación en coherencia: {coherencia_promedio:.1f}/10, "
                f"Puntuación en cohesión: {cohesion_promedio:.1f}/10. "
                f"Temas recurrentes: {', '.join(temas_recurrentes)}."
            )

            # Prompt para la IA
            prompt_plan = f"""
            Crea un plan de estudio personalizado para un estudiante de español llamado {nombre} de nivel {nivel_actual}
            con los siguientes errores frecuentes: {errores_frecuentes}

            Organiza el plan por semanas (4 semanas) con objetivos claros, actividades concretas y recursos recomendados.
            Para cada semana, incluye:

            1. Objetivos específicos
            2. Temas gramaticales a trabajar
            3. Vocabulario a practicar
            4. 1-2 actividades concretas
            5. Recursos o materiales recomendados

            Adapta todo el contenido al nivel del estudiante y sus necesidades específicas.
            """

            def send_request():
                return client.chat.completions.create(
                    model="gpt-4-turbo",
                    temperature=0.7,
                    messages=[
                        {"role": "system", "content": "Eres un experto en diseño curricular ELE que crea planes de estudio personalizados."},
                        {"role": "user", "content": prompt_plan}
                    ]
                )

            # Usar sistema de reintentos
            response = retry_with_backoff(send_request, max_retries=2)
            plan_estudio = response.choices[0].message.content

            # Registrar éxito
            circuit_breaker.record_success("openai")

            # Dividir el plan por semanas
            semanas = plan_estudio.split("Semana")

            # Procesar el resultado
            plan_procesado = {
                "completo": plan_estudio,
                "semanas": []
            }

            # Ignorar el elemento vacío al inicio
            for i, semana in enumerate(semanas[1:], 1):
                titulo_semana = extraer_titulo(semana)
                contenido_semana = semana.strip()
                plan_procesado["semanas"].append({
                    "numero": i,
                    "titulo": titulo_semana,
                    "contenido": contenido_semana
                })

            return {"error": None, "plan": plan_procesado}

        else:
            return {"error": "No se encontraron columnas necesarias en los datos", "plan": None}

    except Exception as e:
        handle_exception("generar_plan_estudio_personalizado", e)
        circuit_breaker.record_failure("openai")
        return {"error": f"Error al generar plan de estudio: {str(e)}", "plan": None}


def crear_grafico_radar(valores, categorias):
    """
    Crea un gráfico de radar para visualizar habilidades contextuales.

    Args:
        valores: Lista de valores numéricos
        categorias: Lista de nombres de categorías

    Returns:
        matplotlib.figure.Figure: Figura con el gráfico
    """
    try:
        # Verificar entradas
        if not isinstance(valores, list) or not isinstance(categorias, list):
            logger.error("Valores o categorías no son listas")
            return None

        if len(valores) != len(categorias) or len(valores) == 0:
            logger.error(
                f"Longitud incorrecta: valores={len(valores)}, categorias={len(categorias)}")
            return None

        # Convertir valores a tipo numérico
        valores_num = []
        for val in valores:
            try:
                valores_num.append(float(val))
            except (ValueError, TypeError):
                valores_num.append(0.0)

        # Crear figura
        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))

        # Número de categorías
        N = len(categorias)

        # Ángulos para cada eje
        angulos = [n / float(N) * 2 * 3.14159 for n in range(N)]
        angulos += angulos[:1]  # Cerrar el círculo

        # Añadir los valores, repitiendo el primero
        valores_radar = valores_num + [valores_num[0]]

        # Dibujar los ejes
        plt.xticks(angulos[:-1], categorias)

        # Dibujar el polígono
        ax.plot(angulos, valores_radar)
        ax.fill(angulos, valores_radar, alpha=0.1)

        # Ajustar escala
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_ylim(0, 10)

        plt.title("Habilidades contextuales")

        return fig

    except Exception as e:
        logger.error(f"Error al crear gráfico radar: {str(e)}")
        return None


def mostrar_progreso(df):
    """
    Crea gráficos de progreso a partir de un DataFrame con historial de correcciones.

    Args:
        df: DataFrame con historial de correcciones

    Returns:
        dict: Diccionario con gráficos generados (altair)
    """
    resultado = {
        "errores_totales": None,
        "tipos_error": None,
        "radar": None,
        "fecha_col": None
    }

    if df is None or df.empty:
        logger.warning("DataFrame vacío o nulo")
        return resultado

    try:
        # Verificar si existe la columna Fecha
        fecha_col = None
        # Buscar la columna de fecha de manera flexible
        for col in df.columns:
            if 'fecha' in col.lower().strip():
                fecha_col = col
                break

        if fecha_col is None:
            logger.error("No se encontró la columna 'Fecha' en los datos")
            return resultado

        resultado["fecha_col"] = fecha_col

        # Asegurarse de que la columna Fecha está en formato datetime
        try:
            df[fecha_col] = pd.to_datetime(df[fecha_col], errors='coerce')
            df = df.sort_values(fecha_col)
        except Exception as e:
            logger.error(f"Error al convertir fechas: {str(e)}")
            return resultado

        # Verificar que Total Errores es numérico
        if 'Total Errores' in df.columns:
            # Convertir a numérico de manera segura
            df['Total Errores'] = pd.to_numeric(
                df['Total Errores'], errors='coerce').fillna(0)

            # Crear un gráfico con Altair para total de errores
            # Convertir a formato largo para Altair
            source = pd.DataFrame({
                'Fecha': df[fecha_col],
                'Total Errores': df['Total Errores'],
                'Nivel': df.get('Nivel', 'No especificado')
            })

            chart_errores = alt.Chart(source).mark_line(point=True).encode(
                x=alt.X('Fecha:T', title='Fecha'),
                y=alt.Y('Total Errores:Q', title='Total Errores'),
                tooltip=['Fecha:T', 'Total Errores:Q', 'Nivel:N']
            ).properties(
                title='Evolución de errores totales a lo largo del tiempo'
            ).interactive()

            resultado["errores_totales"] = chart_errores

        # Gráfico de tipos de errores
        columnas_errores = [
            'Errores Gramática', 'Errores Léxico', 'Errores Puntuación',
            'Errores Estructura'
        ]

        # Encontrar las columnas que realmente existen en el DataFrame
        columnas_errores_existentes = [
            col for col in columnas_errores if col in df.columns]

        if columnas_errores_existentes:
            # Convertir columnas a numérico
            for col in columnas_errores_existentes:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            # Crear DataFrame en formato largo para Altair
            tipos_error_data = []
            for idx, row in df.iterrows():
                for col in columnas_errores_existentes:
                    tipos_error_data.append({
                        'Fecha': row[fecha_col],
                        'Tipo de Error': col,
                        'Cantidad': row[col]
                    })

            tipos_error_df = pd.DataFrame(tipos_error_data)

            chart_tipos = alt.Chart(tipos_error_df).mark_line(point=True).encode(
                x=alt.X('Fecha:T', title='Fecha'),
                y=alt.Y('Cantidad:Q', title='Cantidad'),
                color=alt.Color('Tipo de Error:N', title='Tipo de Error'),
                tooltip=['Fecha:T', 'Tipo de Error:N', 'Cantidad:Q']
            ).properties(
                title='Evolución por tipo de error'
            ).interactive()

            resultado["tipos_error"] = chart_tipos

        # Datos para el gráfico de radar (última entrada)
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

            fig_radar = crear_grafico_radar(valores, categorias)
            resultado["radar"] = fig_radar

        return resultado

    except Exception as e:
        logger.error(f"Error al mostrar progreso: {str(e)}")
        return resultado
    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 12: Aplicación Principal
==================================================================================

Este artefacto contiene:
1. Implementación de pestañas principales
2. Función main y punto de entrada de la aplicación
"""

# --- IMPLEMENTACIÓN DE PESTAÑAS PRINCIPALES ---


def tab_corregir():
    """Implementación de la pestaña de corrección de texto."""
    # Limpiar variables de simulacro si venimos de otra pestaña
    if "inicio_simulacro" in st.session_state:
        set_session_var("inicio_simulacro", None)
    if "duracion_simulacro" in st.session_state:
        set_session_var("duracion_simulacro", None)
    if "tarea_simulacro" in st.session_state:
        set_session_var("tarea_simulacro", None)

    st.header("📝 Corrección de texto")

    with st.expander("ℹ️ Información sobre el análisis contextual", expanded=False):
        st.markdown("""
        Esta versión mejorada del Textocorrector incluye:
        - **Análisis de coherencia**: Evalúa si las ideas están conectadas de manera lógica y si el texto tiene sentido en su conjunto.
        - **Análisis de cohesión**: Revisa los mecanismos lingüísticos que conectan las diferentes partes del texto.
        - **Evaluación del registro lingüístico**: Determina si el lenguaje usado es apropiado para el contexto y propósito del texto.
        - **Análisis de adecuación cultural**: Identifica si hay expresiones o referencias culturalmente apropiadas o inapropiadas.

        Las correcciones se adaptan automáticamente al nivel del estudiante.
        """)

    # Obtener datos del usuario - usando key única para este formulario
    user_data = ui_user_info_form(form_key="form_user_info_corregir")

    # El resto del código permanece igual...
    if not user_data:
        if "usuario_actual" not in st.session_state or not st.session_state.usuario_actual:
            st.info("👆 Por favor, introduce tu nombre y nivel para comenzar.")
            return

    # GENERADOR DE CONSIGNAS
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
                nivel_actual = get_session_var(
                    "nivel_estudiante", "intermedio")

                # Generar la consigna
                consigna_generada = generar_consigna_escritura(
                    nivel_actual, tipo_consigna)

                # Guardar en session_state
                set_session_var("consigna_actual", consigna_generada)

            # Mostrar la consigna generada
            if "consigna_actual" in st.session_state and st.session_state.consigna_actual:
                st.success("✨ Consigna generada:")
                st.info(st.session_state.consigna_actual)

                # Opción para usar esta consigna
                if st.button("Usar esta consigna como contexto", key="usar_consigna"):
                    set_session_var("info_adicional_corregir",
                                    f"Consigna: {st.session_state.consigna_actual}")
                    set_session_var("usar_consigna_como_texto", True)
                    st.rerun()  # Recargar para actualizar el formulario

    # FORMULARIO DE CORRECCIÓN
    with st.form(key="formulario_corregir"):
        # Opciones de corrección
        options = ui_idioma_correcciones_tipo()

        # Texto inicial con contenido de la consigna si está disponible
        texto_inicial = ""
        if get_session_var("usar_consigna_como_texto", False) and "consigna_actual" in st.session_state:
            texto_inicial = f"[Instrucción: {st.session_state.consigna_actual}]\n\n"
            # Reset para no añadirlo cada vez
            set_session_var("usar_consigna_como_texto", False)

        # Área de texto para la corrección
        texto = st.text_area(
            "Escribe tu texto aquí:",
            value=texto_inicial,
            height=250,
            key="texto_correccion_corregir"
        )

        info_adicional = st.text_area(
            "Información adicional o contexto (opcional):",
            value=get_session_var("info_adicional_corregir", ""),
            height=100,
            key="info_adicional_widget_key"  # Clave diferente para el widget
        )

        # Guardar sin conflicto (dentro del formulario, pero fuera de la definición del widget)
        set_session_var("info_adicional_corregir", info_adicional)

        # Botón de envío
        enviar = st.form_submit_button("Corregir", use_container_width=True)

        # PROCESAMIENTO DEL FORMULARIO (dentro del form, será ejecutado solo cuando se envíe)
        if enviar:
            if not texto.strip():
                st.warning("Por favor, escribe un texto para corregir.")
            else:
                # Guardar el texto para posible uso futuro
                set_session_var("ultimo_texto", texto)

                with st.spinner("Analizando texto y generando corrección contextual..."):
                    # Obtener los datos del usuario
                    nombre = get_session_var("usuario_actual", "")
                    nivel = user_data.get("nivel") if user_data else get_session_var(
                        "nivel_estudiante", "intermedio")

                    # Obtener las opciones seleccionadas
                    idioma = options.get("idioma", "Español")
                    tipo_texto = options.get(
                        "tipo_texto", "General/No especificado")
                    contexto_cultural = options.get(
                        "contexto_cultural", "General/Internacional")

                    # Llamar a la función de corrección
                    resultado = corregir_texto(
                        texto, nombre, nivel, idioma,
                        tipo_texto, contexto_cultural, info_adicional
                    )

                    # Guardar el resultado para futuras referencias
                    set_session_var("correction_result", resultado)
                    set_session_var(
                        "last_correction_time", datetime.now().isoformat())

                    # Mostrar el resultado
                    if "error" in resultado:
                        st.error(
                            f"Error en la corrección: {resultado['error']}")
                    else:
                        ui_show_correction_results(resultado)


def tab_progreso():
    """Implementación mejorada de la pestaña de progreso con manejo adecuado de tipos de datos."""
    st.header("📊 Tu progreso")

    # Obtener datos del usuario
    user_data = ui_user_info_form(form_key="form_user_info_progreso")

    if not user_data and "usuario_actual" not in st.session_state:
        st.info("Por favor, introduce tu información para ver tu progreso.")
        return

    # Nombre del estudiante actual
    nombre_estudiante = get_session_var("usuario_actual")

    # Mostrar resumen general
    st.subheader("Resumen de tu progreso")
    with st.container():
        # Intentar obtener historial
        historial = obtener_historial_estudiante(nombre_estudiante)

        if historial is None or historial.empty:
            st.warning(
                "No hay datos de progreso disponibles. Realiza algunas correcciones primero.")
            return

        # SOLUCIÓN MEJORADA: Verificación exhaustiva de columnas y manejo robusto de tipos
        try:
            # Mostrar información del historial de forma segura
            ultima_entrada = historial.iloc[-1]
            num_correcciones = len(historial)
            
            # Buscar la columna de fecha de manera más exhaustiva
            fecha_col = None
            posibles_columnas_fecha = ['Fecha', 'fecha', 'FECHA', 'Date', 'date']
            
            # Intenta encontrar una columna exacta primero
            for col_name in posibles_columnas_fecha:
                if col_name in historial.columns:
                    fecha_col = col_name
                    break
            
            # Si no encuentra, busca de manera menos estricta
            if fecha_col is None:
                for col in historial.columns:
                    if any(fecha_str in col.lower() for fecha_str in ['fecha', 'date', 'time']):
                        fecha_col = col
                        break
            
            # Si aún no encontramos, usamos la primera columna como fallback
            if fecha_col is None and len(historial.columns) > 0:
                fecha_col = historial.columns[0]
                logger.warning(f"No se encontró columna de fecha. Usando {fecha_col} como sustituto")
            
            # Obtener valores de fecha de forma segura
            if fecha_col is not None:
                # Intentar convertir a datetime si es necesario
                try:
                    historial[fecha_col] = pd.to_datetime(historial[fecha_col], errors='coerce')
                except:
                    pass  # Si falla, seguimos con la columna tal cual
                
                # CORRECCIÓN: Convertir los valores Timestamp a string para evitar errores en st.metric
                if len(historial) > 0:
                    fecha_primera_raw = historial.iloc[0][fecha_col]
                    fecha_ultima_raw = ultima_entrada[fecha_col]
                    
                    # Convertir a string si son objetos Timestamp
                    if hasattr(fecha_primera_raw, 'strftime'):
                        fecha_primera = fecha_primera_raw.strftime('%Y-%m-%d %H:%M')
                    else:
                        fecha_primera = str(fecha_primera_raw)
                        
                    if hasattr(fecha_ultima_raw, 'strftime'):
                        fecha_ultima = fecha_ultima_raw.strftime('%Y-%m-%d %H:%M')
                    else:
                        fecha_ultima = str(fecha_ultima_raw)
                else:
                    fecha_primera = "No disponible"
                    fecha_ultima = "No disponible"
            else:
                fecha_primera = "No disponible"
                fecha_ultima = "No disponible"
            
            # Mostrar stats básicos
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Correcciones realizadas", num_correcciones)
            with col2:
                st.metric("Primera corrección", fecha_primera)
            with col3:
                st.metric("Última corrección", fecha_ultima)
            with col4:
                nivel_actual = get_session_var("nivel_estudiante", "intermedio")
                nivel_map = {
                    "principiante": "A1-A2",
                    "intermedio": "B1-B2",
                    "avanzado": "C1-C2"
                }
                st.metric("Nivel actual", nivel_map.get(nivel_actual, nivel_actual))

            # Mostrar gráficos de progreso
            st.subheader("Gráficos de progreso")

            # Obtener gráficos
            graficos = mostrar_progreso(historial)

            if graficos["errores_totales"] is not None:
                # Pestaña para gráficos
                grafico_tab1, grafico_tab2, grafico_tab3 = st.tabs(
                    ["Errores totales", "Tipos de errores", "Habilidades"])

                with grafico_tab1:
                    st.altair_chart(graficos["errores_totales"],
                                    use_container_width=True)

                with grafico_tab2:
                    if graficos["tipos_error"] is not None:
                        st.altair_chart(graficos["tipos_error"],
                                        use_container_width=True)
                    else:
                        st.info("No hay datos suficientes para mostrar errores por tipo.")

                with grafico_tab3:
                    if graficos["radar"] is not None:
                        st.pyplot(graficos["radar"])
                    else:
                        st.info(
                            "No hay datos suficientes para mostrar el gráfico de habilidades contextuales.")
            else:
                st.warning("No hay suficientes datos para generar gráficos.")

            # Mostrar últimos consejos de manera más robusta
            consejo_col = None
            for posible_col in ['Consejo Final', 'Consejo final', 'consejo', 'Consejo']:
                if posible_col in historial.columns:
                    consejo_col = posible_col
                    break
                    
            if consejo_col:
                st.subheader("Últimos consejos recibidos")
                
                # Crear una copia para evitar modificar el original
                try:
                    # Mostrar consejos sin ordenar para evitar errores
                    if len(historial) > 0:
                        consejos_mostrados = 0
                        # Comenzamos desde el final para mostrar los más recientes primero
                        for i in range(len(historial)-1, max(-1, len(historial)-4), -1):
                            consejo = historial.iloc[i][consejo_col]
                            if isinstance(consejo, (str)) and consejo.strip():
                                st.info(f"**Consejo {consejos_mostrados+1}**: {consejo}")
                                consejos_mostrados += 1
                                if consejos_mostrados >= 3:  # Mostrar máximo 3 consejos
                                    break
                except Exception as e:
                    logger.error(f"Error al mostrar consejos: {str(e)}")
                    st.info("Hay consejos disponibles, pero no se pueden mostrar correctamente.")
            else:
                st.info("No hay consejos disponibles en el historial.")

            # Generar plan de estudio personalizado
            st.subheader("Plan de estudio personalizado")
            if st.button("Generar plan de estudio", key="generar_plan"):
                with st.spinner("Analizando tu historial y generando plan de estudio..."):
                    plan_result = generar_plan_estudio_personalizado(
                        nombre_estudiante, nivel_actual, historial)

                    if "error" in plan_result and plan_result["error"]:
                        st.error(
                            f"No se pudo generar el plan de estudio: {plan_result['error']}")
                    else:
                        plan = plan_result.get("plan", {})
                        if plan and "semanas" in plan:
                            st.success(
                                "¡Plan de estudio generado! Revisa cada semana a continuación:")

                            # Mostrar plan por semanas
                            for semana in plan["semanas"]:
                                with st.expander(f"Semana {semana['numero']}: {semana['titulo']}"):
                                    st.markdown(semana["contenido"])
                        else:
                            st.warning(
                                "No se pudo generar un plan de estudio detallado. Intenta realizar más correcciones.")
        
        except Exception as e:
            st.error(f"Ocurrió un error al mostrar el progreso: {str(e)}")
            logger.error(f"Error en tab_progreso: {str(e)}")
            logger.error(traceback.format_exc())
            st.info("Por favor, continúa realizando correcciones para generar datos de progreso.")


def tab_examen():
    """Implementación de la pestaña de preparación para exámenes."""
    st.header("🎓 Preparación para exámenes")

    # Obtener datos del usuario
    user_data = ui_user_info_form(form_key="form_user_info_examen")

    if not user_data and "usuario_actual" not in st.session_state:
        st.info(
            "Por favor, introduce tu información para iniciar la preparación para exámenes.")
        return

    # Nombre del estudiante actual
    nombre_estudiante = get_session_var("usuario_actual")

    # Opciones de examen
    options = ui_examen_options()

    # Información sobre el examen y criterios
    with st.expander(f"ℹ️ Sobre el examen {options['tipo_examen']} nivel {options['nivel_examen']}", expanded=False):
        st.markdown(
            f"### Examen {options['tipo_examen']} nivel {options['nivel_examen']}")

        # Mostrar criterios de evaluación
        criterios = obtener_criterios_evaluacion(
            options["tipo_examen"], options["nivel_examen"])
        st.markdown(criterios)

    # Dos pestañas: "Simulacro de examen" y "Ejemplos evaluados"
    sim_tab, ejemplos_tab = st.tabs(
        ["🧪 Simulacro de examen", "📑 Ejemplos evaluados"])

    with sim_tab:
        st.markdown(
            "### Simulacro de expresión escrita")
        st.markdown(
            "Realiza un simulacro de expresión escrita con tiempo controlado.")

        # Comprobar si hay un simulacro activo
        inicio_simulacro = get_session_var("inicio_simulacro", None)
        duracion_simulacro = get_session_var("duracion_simulacro", None)
        tarea_simulacro = get_session_var("tarea_simulacro", None)

        if inicio_simulacro is None or duracion_simulacro is None or tarea_simulacro is None:
            # No hay simulacro activo, mostrar opciones para iniciar
            with st.form(key="form_iniciar_simulacro"):
                st.write(
                    "Haz clic en el botón para generar una tarea de examen y comenzar el simulacro.")
                tiempo_personalizado = st.slider(
                    "Tiempo para el simulacro (minutos):", min_value=10, max_value=120, value=45)
                submit_iniciar = st.form_submit_button(
                    "Iniciar simulacro", use_container_width=True)

                if submit_iniciar:
                    # Generar una tarea de expresión escrita
                    with st.spinner("Generando tarea de examen..."):
                        # Obtener la duración y la tarea para el nivel y tipo seleccionado
                        duracion_examen = obtener_duracion_examen(
                            options["tipo_examen"], options["nivel_examen"])
                        if tiempo_personalizado:
                            duracion_examen = tiempo_personalizado * 60  # Convertir minutos a segundos

                        tarea_examen = generar_tarea_examen(
                            options["tipo_examen"], options["nivel_examen"])

                        # Guardar datos del simulacro
                        set_session_var("inicio_simulacro", time.time())
                        set_session_var("duracion_simulacro", duracion_examen)
                        set_session_var("tarea_simulacro", tarea_examen)

                        # Recargar para mostrar el simulacro
                        st.rerun()

        else:
            # Hay un simulacro activo, mostrar tarea y temporizador
            st.markdown("### Tarea de expresión escrita")
            st.markdown(tarea_simulacro)

            # Temporizador
            timer_state = ui_countdown_timer(
                duracion_simulacro, inicio_simulacro)
            tiempo_formateado = timer_state["tiempo_formateado"]
            porcentaje = timer_state["porcentaje"]
            color = timer_state["color"]
            terminado = timer_state["terminado"]

            # Mostrar tiempo restante
            if color == "normal":
                st.success(f"⏱️ Tiempo restante: {tiempo_formateado}")
            elif color == "warning":
                st.warning(f"⏱️ Tiempo restante: {tiempo_formateado}")
            else:
                st.error(f"⏱️ Tiempo restante: {tiempo_formateado}")

            # Barra de progreso
            st.progress(porcentaje)

            # Formulario para la respuesta
            with st.form(key="form_simulacro_respuesta"):
                respuesta = st.text_area(
                    "Tu respuesta:",
                    value=get_session_var("simulacro_respuesta_texto", ""),
                    height=300,
                    key="simulacro_respuesta_texto"
                )

                col1, col2 = st.columns(2)
                with col1:
                    submit_finalizar = st.form_submit_button(
                        "Finalizar y corregir", use_container_width=True)
                with col2:
                    submit_cancelar = st.form_submit_button(
                        "Cancelar simulacro", use_container_width=True)

            # Opción para finalizar manualmente incluso si el tiempo no ha acabado
            if submit_finalizar:
                if not respuesta.strip():
                    st.warning(
                        "Por favor, escribe tu respuesta antes de finalizar.")
                else:
                    # Calcular tiempo usado
                    tiempo_usado = time.time() - inicio_simulacro
                    minutos_usados = int(tiempo_usado // 60)
                    segundos_usados = int(tiempo_usado % 60)
                    tiempo_usado_str = f"{minutos_usados}m {segundos_usados}s"

                    # Corregir la respuesta
                    with st.spinner("Analizando tu respuesta..."):
                        resultado = corregir_examen(
                            respuesta,
                            options["tipo_examen"],
                            options["nivel_examen"],
                            tiempo_usado_str
                        )

                        # Limpiar datos del simulacro
                        set_session_var("inicio_simulacro", None)
                        set_session_var("duracion_simulacro", None)
                        set_session_var("tarea_simulacro", None)
                        set_session_var("simulacro_respuesta_texto", "")

                        # Mostrar resultados de la corrección
                        st.success(
                            f"✅ Simulacro completado. Tiempo usado: {tiempo_usado_str}")

                        # Mostrar el resultado
                        if "error" in resultado:
                            st.error(
                                f"Error en la corrección: {resultado['error']}")
                        else:
                            ui_show_correction_results(resultado)

            # Opción para cancelar el simulacro
            if submit_cancelar:
                st.warning("Simulacro cancelado.")
                # Limpiar datos del simulacro
                set_session_var("inicio_simulacro", None)
                set_session_var("duracion_simulacro", None)
                set_session_var("tarea_simulacro", None)
                set_session_var("simulacro_respuesta_texto", "")
                st.rerun()

            # Si el tiempo ha terminado y no se ha enviado, mostrar advertencia
            if terminado and not submit_finalizar and not submit_cancelar:
                st.error(
                    "⏰ ¡Tiempo terminado! Por favor, finaliza tu respuesta.")

    with ejemplos_tab:
        st.markdown("### Ejemplos de respuestas evaluadas")
        st.markdown(
            "A continuación se muestran ejemplos de respuestas de estudiantes con su evaluación correspondiente.")

        if st.button("Generar ejemplos", key="generar_ejemplos"):
            with st.spinner("Generando ejemplos de respuestas evaluadas..."):
                ejemplos = generar_ejemplos_evaluados(
                    options["tipo_examen"], options["nivel_examen"])
                st.markdown(ejemplos)


def tab_herramientas():
    """Implementación de la pestaña de herramientas complementarias."""
    st.header("🧰 Herramientas complementarias")

    # Pestañas para diferentes tipos de herramientas
    tools_tabs = st.tabs([
        "📊 Análisis de complejidad",
        "📚 Recursos didácticos",
        "🖼️ Descripción de imágenes",
        "✍️ Texto manuscrito"
    ])

    # Actualizar el índice de la pestaña activa (para navegación entre tabs)
    if "active_tools_tab_index" in st.session_state:
        tabs_index = get_session_var("active_tools_tab_index")
        for i, tab in enumerate(tools_tabs):
            if i == tabs_index:
                tab.active = True

    # 1. Herramienta de análisis de complejidad
    with tools_tabs[0]:
        herramienta_analisis_complejidad()

    # 2. Herramienta de recursos didácticos
    with tools_tabs[1]:
        herramienta_recursos_didacticos()

    # 3. Herramienta de descripción de imágenes
    with tools_tabs[2]:
        herramienta_descripcion_imagenes()

    # 4. Herramienta de texto manuscrito
    with tools_tabs[3]:
        herramienta_texto_manuscrito()


def herramienta_analisis_complejidad():
    """Herramienta para análisis de complejidad textual."""
    st.subheader("📊 Análisis de complejidad textual")
    st.markdown(
        "Esta herramienta analiza la complejidad lingüística de un texto y proporciona información sobre su nivel.")

    with st.form(key="form_analisis_complejidad"):
        texto = st.text_area(
            "Introduce el texto a analizar:",
            height=200,
            placeholder="Pega aquí el texto que quieres analizar..."
        )
        submit_analizar = st.form_submit_button(
            "Analizar complejidad", use_container_width=True)

    if submit_analizar:
        if not texto.strip():
            st.warning("Por favor, introduce un texto para analizar.")
        else:
            with st.spinner("Analizando complejidad textual..."):
                resultado_analisis = analizar_complejidad_texto(texto)

                if "error" in resultado_analisis:
                    st.error(
                        f"Error al analizar la complejidad: {resultado_analisis['error']}")
                else:
                    # Mostrar resultados del análisis
                    st.success("Análisis completado. Resultados:")

                    # Nivel MCER
                    nivel_mcer = resultado_analisis.get("nivel_mcer", {})
                    st.subheader("📌 Nivel MCER estimado")
                    st.info(
                        f"**{nivel_mcer.get('nivel', 'No disponible')}** - {nivel_mcer.get('justificacion', '')}")

                    # Crear pestañas para los diferentes aspectos del análisis
                    complejidad_tab1, complejidad_tab2, complejidad_tab3, complejidad_tab4 = st.tabs([
                        "Léxico", "Sintaxis", "Estructura", "Índices"
                    ])

                    # Complejidad léxica
                    with complejidad_tab1:
                        lexico = resultado_analisis.get(
                            "complejidad_lexica", {})
                        st.markdown(
                            f"### Complejidad léxica: {lexico.get('nivel', 'No disponible')}")
                        st.markdown(lexico.get("descripcion", ""))

                        # Palabras destacadas
                        if "palabras_destacadas" in lexico and lexico["palabras_destacadas"]:
                            st.markdown("##### Palabras destacadas:")
                            cols = st.columns(min(3, len(
                                lexico["palabras_destacadas"])))
                            for i, palabra in enumerate(lexico["palabras_destacadas"]):
                                cols[i % 3].markdown(f"- _{palabra}_")

                    # Complejidad sintáctica
                    with complejidad_tab2:
                        sintaxis = resultado_analisis.get(
                            "complejidad_sintactica", {})
                        st.markdown(
                            f"### Complejidad sintáctica: {sintaxis.get('nivel', 'No disponible')}")
                        st.markdown(sintaxis.get("descripcion", ""))

                        # Estructuras destacadas
                        if "estructuras_destacadas" in sintaxis and sintaxis["estructuras_destacadas"]:
                            st.markdown("##### Estructuras destacadas:")
                            for estructura in sintaxis["estructuras_destacadas"]:
                                st.markdown(f"- _{estructura}_")

                    # Complejidad textual
                    with complejidad_tab3:
                        textual = resultado_analisis.get(
                            "complejidad_textual", {})
                        st.markdown(
                            f"### Estructura textual: {textual.get('nivel', 'No disponible')}")
                        st.markdown(textual.get("descripcion", ""))

                    # Índices estadísticos
                    with complejidad_tab4:
                        indices = resultado_analisis.get("indices", {})
                        st.markdown("### Índices lingüísticos")

                        # Crear métricas para índices
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            ttr = indices.get("ttr", 0)
                            st.metric("TTR (Type-Token Ratio)",
                                      f"{ttr:.3f}" if isinstance(ttr, (int, float)) else "N/A")

                        with col2:
                            densidad = indices.get("densidad_lexica", 0)
                            st.metric("Densidad léxica",
                                      f"{densidad:.3f}" if isinstance(densidad, (int, float)) else "N/A")

                        with col3:
                            szigriszt = indices.get("szigriszt", 0)
                            st.metric("Índice Szigriszt",
                                      f"{szigriszt:.1f}" if isinstance(szigriszt, (int, float)) else "N/A")

                        # Interpretación
                        st.markdown("##### Interpretación:")
                        st.markdown(indices.get("interpretacion", ""))

                    # Recomendaciones finales
                    if "recomendaciones" in resultado_analisis and resultado_analisis["recomendaciones"]:
                        st.subheader("📝 Recomendaciones")
                        for rec in resultado_analisis["recomendaciones"]:
                            st.markdown(f"- {rec}")


def herramienta_recursos_didacticos():
    """Herramienta para acceder a recursos didácticos."""
    st.subheader("📚 Recursos didácticos")

    # Filtro de recursos
    st.markdown("Selecciona los filtros para encontrar recursos:")

    col1, col2, col3 = st.columns(3)
    with col1:
        nivel_filtro = st.selectbox(
            "Nivel:",
            ["Todos", "A1-A2", "B1-B2", "C1-C2"],
            key="nivel_filtro_recursos"
        )
    with col2:
        categoria_filtro = st.selectbox(
            "Categoría:",
            ["Todos", "Gramática", "Léxico", "Cohesión", "Registro"],
            key="categoria_filtro_recursos"
        )
    with col3:
        tipo_filtro = st.selectbox(
            "Tipo de recurso:",
            ["Todos", "Guía", "Ejercicios", "Vídeo", "Ficha", "Curso", "Podcast"],
            key="tipo_filtro_recursos"
        )

    # Filtrar recursos según los criterios seleccionados
    recursos_filtrados = []
    for nivel, categorias in RECURSOS_DB.items():
        if nivel_filtro == "Todos" or nivel == nivel_filtro:
            for categoria, recursos in categorias.items():
                if categoria_filtro == "Todos" or categoria == categoria_filtro:
                    for recurso in recursos:
                        if tipo_filtro == "Todos" or recurso["tipo"] == tipo_filtro:
                            recursos_filtrados.append(
                                {**recurso, "categoria": categoria, "nivel_grupo": nivel})

    # Mostrar resultados
    st.markdown(f"Se encontraron **{len(recursos_filtrados)}** recursos:")

    # Agrupar por nivel
    if recursos_filtrados:
        for nivel in ["A1-A2", "B1-B2", "C1-C2"]:
            recursos_nivel = [
                r for r in recursos_filtrados if r["nivel_grupo"] == nivel]
            if recursos_nivel:
                with st.expander(f"Nivel {nivel} ({len(recursos_nivel)} recursos)"):
                    for i, recurso in enumerate(recursos_nivel):
                        st.markdown(
                            f"**{recurso['título']}** - {recurso['tipo']} - Nivel {recurso['nivel']}")
                        st.markdown(
                            f"*Categoría: {recurso['categoria']}*")
                        st.markdown(
                            f"[Acceder al recurso]({recurso['url']})")
                        if i < len(recursos_nivel) - 1:
                            st.divider()
    else:
        st.info("No se encontraron recursos con los filtros seleccionados.")

    # Botón para sugerir recursos personalizados
    st.markdown("---")
    st.markdown("¿No encuentras lo que necesitas?")
    if st.button("Sugerir recursos personalizados"):
        # Esta función podría implementarse para generar recursos personalizados
        # con alguna API como OpenAI basado en criterios específicos
        st.info("Función en desarrollo. Próximamente disponible.")


def herramienta_descripcion_imagenes():
    """Herramienta para generar y describir imágenes."""
    st.subheader("🖼️ Descripción de imágenes")
    st.markdown(
        "Esta herramienta te permite generar o subir imágenes y practicar describiéndolas en español.")

    # Verificar si estamos en modo de corrección
    mostrar_correccion = get_session_var("mostrar_correccion_imagen", False)
    if mostrar_correccion:
        # Obtener datos de la imagen
        imagen_url = get_session_var("imagen_url_state", None)
        descripcion = get_session_var("descripcion_state", None)
        tema_imagen = get_session_var("tema_imagen_state", None)
        descripcion_estudiante = get_session_var(
            "descripcion_estudiante_state", "")

        if not imagen_url or not descripcion:
            st.error("No hay datos de imagen para corregir.")
            if st.button("Volver", key="volver_descripcion_error"):
                set_session_var("mostrar_correccion_imagen", False)
                st.rerun()
            return

        # Mostrar la imagen
        st.image(imagen_url, caption=f"Imagen sobre: {tema_imagen}")

        # Mostrar descripción
        with st.expander("Ver descripción de referencia", expanded=False):
            st.markdown(descripcion)

        # Formulario para la descripción del estudiante
        with st.form(key="form_correccion_descripcion"):
            descripcion_estudiante = st.text_area(
                "Tu descripción:",
                value=descripcion_estudiante,
                height=200,
                placeholder="Escribe aquí tu descripción de la imagen..."
            )
            submit_correccion = st.form_submit_button(
                "Corregir descripción", use_container_width=True)

        if st.button("Volver", key="volver_descripcion"):
            set_session_var("mostrar_correccion_imagen", False)
            set_session_var("descripcion_estudiante_state", "")
            st.rerun()

        if submit_correccion:
            if not descripcion_estudiante.strip():
                st.warning(
                    "Por favor, escribe una descripción antes de corregir.")
            else:
                set_session_var(
                    "descripcion_estudiante_state", descripcion_estudiante)

                with st.spinner("Analizando tu descripción..."):
                    # Obtener datos necesarios
                    nombre = get_session_var("usuario_actual", "Usuario")
                    nivel = get_session_var("nivel_estudiante", "intermedio")

                    # Llamar a la función de corrección
                    resultado = corregir_descripcion_imagen(
                        descripcion_estudiante, tema_imagen, nivel)

                    # Mostrar el resultado
                    if "error" in resultado:
                        st.error(
                            f"Error en la corrección: {resultado['error']}")
                    else:
                        ui_show_correction_results(resultado)

    else:
        # Pestañas para las opciones de imágenes
        imagen_tab1, imagen_tab2 = st.tabs(
            ["🎨 Generar imagen", "📷 Subir imagen"])

        with imagen_tab1:
            st.markdown(
                "Genera una imagen para describir, adaptada a tu nivel de español.")

            # Opciones para la generación
            with st.form(key="form_generar_imagen"):
                tema_imagen = st.text_input(
                    "Tema de la imagen:",
                    placeholder="Ej: Una fiesta de cumpleaños, Un día en la playa, etc."
                )
                nivel = st.selectbox(
                    "Nivel de complejidad:",
                    ["principiante", "intermedio", "avanzado"],
                    index=["principiante", "intermedio", "avanzado"].index(
                        get_session_var("nivel_estudiante", "intermedio")
                    )
                )
                submit_generar = st.form_submit_button(
                    "Generar imagen", use_container_width=True)

            if submit_generar:
                if not tema_imagen.strip():
                    st.warning("Por favor, introduce un tema para la imagen.")
                else:
                    with st.spinner("Generando imagen con DALL-E..."):
                        imagen_url, descripcion = generar_imagen_dalle(
                            tema_imagen, nivel)

                        if imagen_url:
                            # Guardar datos en session state
                            set_session_var("imagen_generada_state", True)
                            set_session_var("imagen_url_state", imagen_url)
                            set_session_var("descripcion_state", descripcion)
                            set_session_var("tema_imagen_state", tema_imagen)

                            # Mostrar la imagen generada
                            st.image(imagen_url, caption=f"Imagen sobre: {tema_imagen}",
                                     use_column_width=True)

                            # Mostrar la descripción
                            with st.expander("Descripción de la imagen", expanded=True):
                                st.markdown(descripcion)

                            # Botón para empezar a describir
                            if st.button("Practicar descripción de esta imagen", key="practicar_descripcion"):
                                set_session_var(
                                    "mostrar_correccion_imagen", True)
                                st.rerun()
                        else:
                            st.error(
                                "Error al generar la imagen. Por favor, intenta de nuevo.")

        with imagen_tab2:
            st.markdown("Sube tu propia imagen para practicar describiéndola.")
            st.warning(
                "Esta función está en desarrollo y será implementada próximamente.")


def main():
    """Función principal que configura la interfaz y el flujo de la aplicación."""
    # Mostrar diagnósticos del sistema si es necesario
    problemas = diagnosticar_aplicacion()
    if problemas:
        with st.sidebar.expander("⚠️ Diagnóstico del sistema", expanded=len([p for p in problemas if p["tipo"] == "crítico"]) > 0):
            for problema in problemas:
                if problema["tipo"] == "crítico":
                    st.error(f"❌ {problema['mensaje']}")
                elif problema["tipo"] == "advertencia":
                    st.warning(f"⚠️ {problema['mensaje']}")
                st.info(f"💡 Solución: {problema['solucion']}")

    # Mostrar cabecera de la aplicación
    ui_header()

    # Verificar si se ha inicializado la aplicación
    if not get_session_var("app_initialized", False):
        # Reflejar que ya está inicializada la app
        set_session_var("app_initialized", True)

    # Tabs principales
    tab_names = ["📝 Corregir texto", "📊 Tu progreso",
                 "🎓 Exámenes oficiales", "🧰 Herramientas"]
    tabs = st.tabs(tab_names)

    # Configurar la navegación entre tabs
    if "tab_navigate_to" in st.session_state and st.session_state.tab_navigate_to is not None:
        target_tab = st.session_state.tab_navigate_to
        for i, tab in enumerate(tabs):
            if i == target_tab:
                tab.active = True
        # Limpiar la navegación
        st.session_state.tab_navigate_to = None

    # Actualizar el índice de la pestaña activa
    for i, tab in enumerate(tabs):
        if tab.active:
            set_session_var("active_tab_index", i)

    # Implementación de pestañas
    with tabs[0]:
        tab_corregir()

    with tabs[1]:
        tab_progreso()

    with tabs[2]:
        tab_examen()

    with tabs[3]:
        tab_herramientas()

    # Mostrar formulario de feedback al final
    ui_feedback_form()

    # Pie de página
    st.markdown("""
    <div style="margin-top:50px;text-align:center;color:#888;font-size:0.8em;">
        Textocorrector ELE © 2023-2025 - v{0}<br>
        Desarrollado con 💙 para estudiantes de español
    </div>
    """.format(APP_VERSION), unsafe_allow_html=True)


# Punto de entrada de la aplicación
if __name__ == "__main__":
    main()

    """
TEXTOCORRECTOR ELE - APLICACIÓN DE CORRECCIÓN DE TEXTOS EN ESPAÑOL CON ANÁLISIS CONTEXTUAL
==================================================================================
Artefacto 13: Implementación Herramientas Complementarias Faltantes
==================================================================================

Este artefacto complementa la implementación con las funciones de herramientas
que quedaron pendientes en el artefacto 12.
"""

# Caché mejorado para reducir llamadas a la API


@st.cache_data(ttl=3600, show_spinner=False)
def cached_obtener_json_de_ia(system_msg_hash, user_msg_hash, model="gpt-4-turbo"):
    """Versión con caché de obtener_json_de_ia para reducir llamadas a la API"""
    # Usamos hashes en lugar de los mensajes completos como parámetros para evitar problemas de cache
    # Convertimos los hashes de vuelta a los mensajes originales desde session_state
    system_msg = st.session_state.get(f"system_msg_{system_msg_hash}", "")
    user_msg = st.session_state.get(f"user_msg_{user_msg_hash}", "")

    if not system_msg or not user_msg:
        return None, {"error": "Mensajes no encontrados en cache"}

    return obtener_json_de_ia(system_msg, user_msg, model)
