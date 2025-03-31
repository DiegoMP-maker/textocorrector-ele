import streamlit as st
import json
import re
import time
from openai import OpenAI

class RealTimeWritingAssistant:
    def __init__(self, api_key, debounce_time=0.5):  # Reducido a 0.5 segundos
        self.client = OpenAI(api_key=api_key)
        self.debounce_time = debounce_time
        self.last_text = ""
        self.last_check_time = 0
        self.suggestions_cache = {}
        
    def get_text_with_highlighting(self, text, nivel="intermedio"):
        # Reducir el número mínimo de caracteres a 10
        if len(text.strip()) < 10:  
            return None
        
        # Verificar si ha pasado suficiente tiempo desde la última verificación
        current_time = time.time()
        if current_time - self.last_check_time < self.debounce_time:
            return None
            
        # Si el texto no ha cambiado, usar la versión en caché
        if text == self.last_text and text in self.suggestions_cache:
            return self.suggestions_cache[text]
            
        # Actualizar tiempo y texto de la última verificación
        self.last_check_time = current_time
        self.last_text = text
        
        # Verificar si ya tenemos este texto en caché
        if text in self.suggestions_cache:
            return self.suggestions_cache[text]
        
        try:
            system_prompt = f"""
            Eres un asistente de escritura en tiempo real para estudiantes de español.
            Identifica rápidamente errores y mejoras potenciales en el texto que se está escribiendo.
            
            - Adapta tu análisis al nivel {nivel} del estudiante
            - Enfócate solo en los errores más importantes o patrones recurrentes
            - Sé conciso en las sugerencias
            - Analiza incluso textos cortos o incompletos, dando sugerencias inmediatas
            
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
            
            # Configurar para respuesta rápida
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                temperature=0.3,
                max_tokens=300,  # Reducido para respuestas más rápidas
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ]
            )
            
            try:
                response_text = response.choices[0].message.content
                json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    feedback_data = json.loads(json_str)
                    
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
        # Inicializar session_state si es necesario
        if key not in st.session_state:
            st.session_state[key] = default_value

        if 'writing_assistant_enabled' not in st.session_state:
            st.session_state.writing_assistant_enabled = False
        
        nivel = st.session_state.get('nivel_estudiante', "intermedio")
        
        # Checkbox para activar/desactivar el asistente
        enable_assistant = st.checkbox(
            "Activar asistente de escritura en tiempo real", 
            value=st.session_state.writing_assistant_enabled,
            key=f"toggle_writing_assistant_{key}"
        )
        
        st.session_state.writing_assistant_enabled = enable_assistant
        
        # Mostrar una nota para informar al usuario
        if enable_assistant:
            st.caption("El asistente analizará tu texto mientras escribes. Escribe al menos 10 caracteres para activarlo.")
        
        # Obtener el valor actual antes de renderizar el widget
        current_value = st.session_state[key]
        
        # Renderizar el text_area
        text = st.text_area(
            "Escribe tu texto aquí:", 
            height=height, 
            key=key,
            value=current_value,
            on_change=self._text_changed,  # Registrar cambio
            args=(key,)  # Pasar el key como argumento
        )
        
        # Mostrar el estado de "analizando" para hacerlo más interactivo
        analyzing_key = f"analyzing_{key}"
        if analyzing_key not in st.session_state:
            st.session_state[analyzing_key] = False
        
        if enable_assistant and text:
            # Un contenedor para mostrar feedback
            feedback_container = st.container()
            
            with feedback_container:
                # Decidir si mostrar indicador de análisis o resultados
                if st.session_state.get(analyzing_key, False):
                    with st.spinner("Analizando texto..."):
                        # Aquí simularíamos el análisis
                        pass
                
                # Obtener feedback
                feedback = self.get_text_with_highlighting(text, nivel)
                
                # Ya no estamos analizando
                st.session_state[analyzing_key] = False
                
                if feedback:
                    total_sugerencias = (
                        len(feedback.get("errores", [])) + 
                        len(feedback.get("patrones", [])) + 
                        len(feedback.get("vocabulario", []))
                    )
                    
                    if total_sugerencias > 0:
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.markdown(f"### Sugerencias ({total_sugerencias})")
                        
                        with col2:
                            st.markdown('<div style="text-align: right; font-size: 0.8em; color: #555;">Asistente activo</div>', 
                                        unsafe_allow_html=True)
                        
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
                        
                        if feedback.get("patrones", []):
                            with st.expander("Patrones recurrentes", expanded=False):
                                for patron in feedback["patrones"]:
                                    st.markdown(f"**{patron['patron']}**")
                                    st.info(f"✏️ {patron['sugerencia']}")
                                    st.divider()
                        
                        if feedback.get("vocabulario", []):
                            with st.expander("Mejoras de vocabulario", expanded=False):
                                for vocab in feedback["vocabulario"]:
                                    st.markdown(f"**{vocab['palabra']}** → *{', '.join(vocab['alternativas'])}*")
                    else:
                        st.caption("No se han detectado errores o sugerencias.")
    
        return text
    
    def _text_changed(self, key):
        """Callback cuando el texto cambia"""
        # Marcar que estamos analizando
        analyzing_key = f"analyzing_{key}"
        st.session_state[analyzing_key] = True

if __name__ == "__main__":
    st.title("Prueba del Asistente de Escritura")
    
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
