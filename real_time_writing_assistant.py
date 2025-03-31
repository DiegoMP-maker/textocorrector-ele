import streamlit as st
import json
import re
import time
from openai import OpenAI

class RealTimeWritingAssistant:
    """
    Clase para implementar un asistente de escritura en tiempo real
    similar a Grammarly pero enfocado en español como lengua extranjera.
    """
    def __init__(self, api_key, debounce_time=1.0):
        """
        Inicializa el asistente de escritura en tiempo real.
        
        :param api_key: Clave API de OpenAI
        :param debounce_time: Tiempo en segundos para esperar antes de hacer una solicitud
        """
        self.client = OpenAI(api_key=api_key)
        self.debounce_time = debounce_time
        self.last_text = ""
        self.last_check_time = 0
        self.suggestions_cache = {}
        
    def get_text_with_highlighting(self, text, nivel="intermedio"):
        """
        Analiza el texto y retorna sugerencias en tiempo real con formato para highlighting
        
        :param text: Texto a analizar
        :param nivel: Nivel del estudiante (principiante, intermedio, avanzado)
        :return: Diccionario con texto analizado, sugerencias y errores detectados
        """
        # Si el texto es muy corto o no ha cambiado, no hacer nada
        if len(text.strip()) < 15 or text == self.last_text:
            return None
        
        # Control de debounce para no hacer demasiadas llamadas a la API
        current_time = time.time()
        if current_time - self.last_check_time < self.debounce_time:
            return None
            
        self.last_check_time = current_time
        self.last_text = text
        
        # Verificar si ya tenemos sugerencias en caché para este texto
        if text in self.suggestions_cache:
            return self.suggestions_cache[text]
        
        try:
            # Prompt para el análisis en tiempo real (optimizado para respuestas rápidas)
            system_prompt = f"""
            Eres un asistente de escritura en tiempo real para estudiantes de español.
            Identifica rápidamente errores y mejoras potenciales en el texto que se está escribiendo.
            
            - Adapta tu análisis al nivel {nivel} del estudiante
            - Enfócate solo en los errores más importantes o patrones recurrentes
            - Sé conciso en las sugerencias
            
            Responde ÚNICAMENTE en formato JSON con esta estructura:
            {{
              "errores": [
                {{
                  "fragmento": "texto con error",
                  "sugerencia": "texto corregido",
                  "tipo": "tipo de error",
                  "explicacion": "explicación breve"
                }}
              ],
              "patrones": [
                {{
                  "patron": "descripción del patrón recurrente",
                  "sugerencia": "cómo mejorar"
                }}
              ],
              "vocabulario": [
                {{
                  "palabra": "palabra que podría mejorarse",
                  "alternativas": ["alternativa1", "alternativa2"]
                }}
              ]
            }}
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # Usar modelo más rápido para tiempo real
                temperature=0.3,
                max_tokens=500,  # Limitar tokens para respuestas rápidas
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ]
            )
            
            # Extraer y parsear respuesta JSON
            try:
                response_text = response.choices[0].message.content
                # Buscar JSON en la respuesta
                json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    feedback_data = json.loads(json_str)
                    
                    # Guardar en caché para futuras consultas
                    self.suggestions_cache[text] = feedback_data
                    return feedback_data
                    
            except Exception as e:
                print(f"Error al parsear respuesta: {e}")
                return None
                
        except Exception as e:
            print(f"Error en la API: {e}")
            return None
        
        return None

    def render_text_editor_with_assistance(self, key="writing_area", height=250, default_value=""):
        """
        Renderiza un editor de texto con asistencia en tiempo real.
        
        :param key: Clave para el widget
        :param height: Altura del editor
        :param default_value: Valor por defecto para el editor
        :return: El texto ingresado
        """
        # Comprobar si existe la configuración del asistente en session_state
        if 'writing_assistant_enabled' not in st.session_state:
            st.session_state.writing_assistant_enabled = False
        
        # Obtener el nivel del estudiante
        nivel = "intermedio"  # Valor por defecto
        if 'nivel_estudiante' in st.session_state:
            nivel = st.session_state.nivel_estudiante
        
        # Control para activar/desactivar el asistente
        enable_assistant = st.checkbox("Activar asistente de escritura en tiempo real", 
                                      value=st.session_state.writing_assistant_enabled,
                                      key=f"toggle_writing_assistant_{key}")
        
        # Guardar estado del checkbox
        st.session_state.writing_assistant_enabled = enable_assistant
        
        # Verificar si hay un valor previo en session_state
        if key not in st.session_state:
            st.session_state[key] = default_value
        
        # Área de texto
        text = st.text_area("Escribe tu texto aquí:", 
                           height=height, 
                           key=key,
                           value=st.session_state[key])
        
        # Actualizar session_state con el nuevo valor
        st.session_state[key] = text
        
        # Mostrar sugerencias solo si el asistente está activado
        if enable_assistant and text:
            with st.spinner("Analizando texto..."):
                feedback = self.get_text_with_highlighting(text, nivel)
                
                if feedback:
                    # Contenedor para sugerencias
                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        
                        # Contador de sugerencias
                        total_sugerencias = (
                            len(feedback.get("errores", [])) + 
                            len(feedback.get("patrones", [])) + 
                            len(feedback.get("vocabulario", []))
                        )
                        
                        with col1:
                            st.markdown(f"### Sugerencias ({total_sugerencias})")
                        
                        with col2:
                            st.markdown('<div style="text-align: right; font-size: 0.8em; color: #555;">Asistente activo</div>', 
                                        unsafe_allow_html=True)
                        
                        # Mostrar errores detectados
                        if feedback.get("errores", []):
                            with st.expander("Correcciones sugeridas", expanded=True):
                                for i, error in enumerate(feedback["errores"]):
                                    st.markdown(f"**{error['tipo']}**: ")
                                    col1, col2 = st.columns([1, 1])
                                    with col1:
                                        st.error(f"{error['fragmento']}")
                                    with col2:
                                        st.success(f"{error['sugerencia']}")
                                    st.info(f"💡 {error['explicacion']}")
                                    if i < len(feedback["errores"]) - 1:
                                        st.divider()
                        
                        # Mostrar patrones recurrentes
                        if feedback.get("patrones", []):
                            with st.expander("Patrones recurrentes", expanded=False):
                                for patron in feedback["patrones"]:
                                    st.markdown(f"**{patron['patron']}**")
                                    st.info(f"✏️ {patron['sugerencia']}")
                                    st.divider()
                        
                        # Mostrar sugerencias de vocabulario
                        if feedback.get("vocabulario", []):
                            with st.expander("Mejoras de vocabulario", expanded=False):
                                for vocab in feedback["vocabulario"]:
                                    st.markdown(f"**{vocab['palabra']}** → *{', '.join(vocab['alternativas'])}*")
                                    
        return text

# Para probar de forma independiente
if __name__ == "__main__":
    st.title("Prueba del Asistente de Escritura")
    
    # Ejemplo de uso con una clave API ficticia
    assistant = RealTimeWritingAssistant("tu-api-key")
    
    st.session_state.nivel_estudiante = st.selectbox(
        "Nivel de español:", 
        ["principiante", "intermedio", "avanzado"]
    )
    
    texto = assistant.render_text_editor_with_assistance(
        key="demo_writing",
        height=300,
        default_value="Escribe algo en español para probar el asistente..."
    )