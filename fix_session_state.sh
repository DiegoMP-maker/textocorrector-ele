#!/bin/bash
# Script para corregir el error de session_state en streamlit_app.py

set -e  # Detener en caso de error

echo "=== SOLUCIÓN PARA EL ERROR DE SESSION_STATE EN STREAMLIT ==="
echo "Este script reemplazará la implementación problemática con una versión corregida."

# Verificar que existe el archivo
if [ ! -f "streamlit_app.py" ]; then
    echo "❌ Error: No se encuentra el archivo streamlit_app.py"
    echo "Asegúrate de ejecutar este script desde el directorio raíz del proyecto"
    exit 1
fi

# Hacer copia de seguridad
BACKUP_FILE="streamlit_app.py.bak.session_state.$(date +%Y%m%d%H%M%S)"
echo "📦 Creando copia de seguridad en $BACKUP_FILE"
cp streamlit_app.py "$BACKUP_FILE"
echo "✅ Copia de seguridad creada"

# Crear archivo temporal con la nueva implementación
echo "✏️ Creando nueva implementación de ui_export_options_rediseñado..."
TEMP_FILE=$(mktemp)

cat > "$TEMP_FILE" << 'EOF'
def ui_export_options_rediseñado(data):
    """
    Implementación rediseñada que evita modificar session_state después de instanciar widgets.
    Esta versión soluciona el error: "st.session_state.select_docx cannot be modified after
    the widget with key select_docx is instantiated."
    
    Args:
        data: Resultados de la corrección
    """
    st.header("📊 Exportar informe")

    # Verificación básica de datos
    if not isinstance(data, dict):
        st.warning("⚠️ No hay datos suficientes para exportar.")
        return

    # Extraer datos para la exportación
    nombre = get_session_var("usuario_actual", "Usuario")
    nivel = get_session_var("nivel_estudiante", "intermedio")
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    texto_original = get_session_var("ultimo_texto", "")
    texto_corregido = data.get("texto_corregido", "")
    errores_obj = data.get("errores", {})
    analisis_contextual = data.get("analisis_contextual", {})
    consejo_final = data.get("consejo_final", "")
    
    # Clave única para esta instancia (evita conflictos si se llama varias veces)
    instance_key = hash(str(data)[:100]) if isinstance(data, dict) else hash(str(time.time()))
    
    # PASO 1: Inicialización de estado (solo si no existe)
    for fmt in ["docx", "html", "csv"]:
        if f"select_{fmt}_{instance_key}" not in st.session_state:
            st.session_state[f"select_{fmt}_{instance_key}"] = fmt == "docx"  # Por defecto, Word seleccionado
    
    # Variable para controlar si mostrar resultados o no
    if f"show_exports_{instance_key}" not in st.session_state:
        st.session_state[f"show_exports_{instance_key}"] = False
    
    # PASO 2: Selección del formato de exportación
    st.write("Selecciona el formato en el que deseas exportar el informe:")
    
    # Columnas para selección - Simplificado para evitar modificar st.session_state después
    formato_cols = st.columns(3)
    with formato_cols[0]:
        word_selected = st.checkbox(
            "Documento Word (DOCX)", 
            key=f"select_docx_{instance_key}"
        )
    with formato_cols[1]:
        html_selected = st.checkbox(
            "Página web (HTML)", 
            key=f"select_html_{instance_key}"
        )
    with formato_cols[2]:
        csv_selected = st.checkbox(
            "Datos CSV", 
            key=f"select_csv_{instance_key}"
        )
    
    # PASO 3: Botón para preparar informes
    if st.button("Preparar informes seleccionados", key=f"prepare_exports_{instance_key}"):
        if not (word_selected or html_selected or csv_selected):
            st.warning("Por favor, selecciona al menos un formato para exportar.")
        else:
            # Activar la bandera para mostrar resultados
            st.session_state[f"show_exports_{instance_key}"] = True
            st.rerun()
    
    # PASO 4: Mostrar resultados si se activó la bandera
    if st.session_state[f"show_exports_{instance_key}"]:
        # Contenedor para los informes generados
        with st.container():
            st.subheader("Informes generados:")
            
            # Generar Word si está seleccionado
            if word_selected:
                word_container = st.container()
                with word_container:
                    st.write("**Documento Word (DOCX)**")
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
                                key=f"docx_download_{instance_key}"
                            )
                            st.success("✅ Documento Word generado correctamente")
                        else:
                            st.error("❌ No se pudo generar el documento Word")
                
                st.divider()
            
            # Generar HTML si está seleccionado
            if html_selected:
                html_container = st.container()
                with html_container:
                    st.write("**Página Web (HTML)**")
                    with st.spinner("Generando HTML..."):
                        html_content = generar_informe_html(
                            nombre, nivel, fecha, texto_original, texto_corregido,
                            analisis_contextual, consejo_final
                        )
                        
                        if html_content:
                            html_bytes = html_content.encode()
                            nombre_archivo = f"informe_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.html"
                            
                            st.download_button(
                                label="📥 Descargar página HTML",
                                data=html_bytes,
                                file_name=nombre_archivo,
                                mime="text/html",
                                key=f"html_download_{instance_key}"
                            )
                            st.success("✅ Documento HTML generado correctamente")
                            
                            # Vista previa
                            with st.expander("Previsualizar HTML", expanded=False):
                                sanitized_html = html_content.replace('"', '&quot;')
                                st.markdown(
                                    f'<iframe srcdoc="{sanitized_html}" width="100%" height="600" style="border: 1px solid #ddd; border-radius: 5px;"></iframe>',
                                    unsafe_allow_html=True
                                )
                        else:
                            st.error("❌ No se pudo generar el documento HTML")
                
                st.divider()
            
            # Generar CSV si está seleccionado
            if csv_selected:
                csv_container = st.container()
                with csv_container:
                    st.write("**Datos CSV**")
                    with st.spinner("Generando CSV..."):
                        csv_buffer = generar_csv_analisis(
                            nombre, nivel, fecha, data
                        )
                        
                        if csv_buffer:
                            nombre_archivo = f"datos_{nombre.replace(' ', '_')}_{fecha.replace(':', '_').replace(' ', '_')}.csv"
                            st.download_button(
                                label="📥 Descargar CSV",
                                data=csv_buffer,
                                file_name=nombre_archivo,
                                mime="text/csv",
                                key=f"csv_download_{instance_key}"
                            )
                            st.success("✅ Archivo CSV generado correctamente")
                        else:
                            st.error("❌ No se pudo generar el archivo CSV")
            
            # Botón para ocultar los resultados
            if st.button("Ocultar resultados", key=f"hide_results_{instance_key}"):
                st.session_state[f"show_exports_{instance_key}"] = False
                st.rerun()
EOF

# Buscar la función ui_export_options_rediseñado en el archivo original
echo "🔍 Buscando la función ui_export_options_rediseñado en el archivo original..."
START_LINE=$(grep -n "def ui_export_options_rediseñado" streamlit_app.py | head -1 | cut -d':' -f1)

if [ -z "$START_LINE" ]; then
    echo "❌ Error: No se encontró la función ui_export_options_rediseñado en el archivo"
    echo "Abortando la operación."
    rm "$TEMP_FILE"
    exit 1
fi

echo "✅ Función encontrada en la línea $START_LINE"

# Encontrar el final de la función
echo "🔍 Buscando el final de la función..."
# Buscar la siguiente línea que comienza con 'def ' después de START_LINE
END_LINE=$(tail -n +$((START_LINE + 1)) streamlit_app.py | grep -n "^def " | head -1 | cut -d':' -f1)

# Si END_LINE está vacío, significa que no hay más funciones después
if [ -z "$END_LINE" ]; then
    # En este caso, usamos el final del archivo
    END_LINE=$(wc -l < streamlit_app.py)
else
    # Si encontramos otra función, ajustamos END_LINE para que apunte a la línea justo antes de la siguiente función
    END_LINE=$((START_LINE + END_LINE - 1))
fi

echo "✅ Final de la función encontrado en la línea $END_LINE"

# Ahora reemplazamos la función
echo "🔄 Reemplazando la función en el archivo..."

# Crear un archivo temporal con el contenido antes de la función
head -n $((START_LINE - 1)) streamlit_app.py > streamlit_app.py.temp

# Añadir la nueva implementación
cat "$TEMP_FILE" >> streamlit_app.py.temp

# Añadir el resto del archivo después de la función original
tail -n +$((END_LINE + 1)) streamlit_app.py >> streamlit_app.py.temp

# Reemplazar el archivo original con el temporal
mv streamlit_app.py.temp streamlit_app.py

# Eliminar el archivo temporal
rm "$TEMP_FILE"

echo "✅ ¡Operación completada con éxito!"
echo "La función ui_export_options_rediseñado ha sido reemplazada con la nueva implementación"
echo "Esta solución evita modificar session_state después de instanciar widgets, resolviendo el error"
echo ""
echo "Si necesitas restaurar la versión anterior, puedes usar: cp \"$BACKUP_FILE\" streamlit_app.py"
echo ""
echo "Ahora puedes ejecutar tu aplicación con: streamlit run streamlit_app.py"
