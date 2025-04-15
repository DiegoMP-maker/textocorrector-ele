#!/bin/bash
# Script para implementar la solución al problema de botones en formularios

set -e  # Parar en caso de error

echo "==== Solución al problema st.button() en st.form() ===="
echo "Iniciando script de implementación automática..."

# Directorio actual
WORKDIR=$(pwd)
APP_FILE="$WORKDIR/streamlit_app.py"
BACKUP_FILE="$WORKDIR/streamlit_app.py.bak.$(date +%Y%m%d%H%M%S)"
TEMP_DIR="$WORKDIR/.temp_fix"
NEW_APP_FILE="$TEMP_DIR/app_final.py"

# Verificar que el archivo existe
if [ ! -f "$APP_FILE" ]; then
  echo "❌ Error: No se encuentra el archivo streamlit_app.py"
  echo "Asegúrate de ejecutar este script desde el directorio raíz del proyecto"
  exit 1
fi

# Crear directorio temporal si no existe
echo "🔧 Creando directorio temporal..."
mkdir -p "$TEMP_DIR"

# Hacer backup del archivo original
echo "📦 Creando copia de seguridad en $BACKUP_FILE"
cp "$APP_FILE" "$BACKUP_FILE"
echo "✅ Copia de seguridad creada"

# Crear archivo temporal con la función ui_export_options_rediseñado
echo "✏️ Creando nueva función ui_export_options_rediseñado..."
cat > "$TEMP_DIR/ui_export_options_rediseñado.py" << 'EOF'
def ui_export_options_rediseñado(data):
    """
    Versión completamente rediseñada del sistema de exportación usando un enfoque 
    de flujo secuencial sin formularios anidados.
    
    Esta implementación evita por completo el problema de botones en formularios 
    mediante un diseño que separa la selección del formato y la generación del archivo.

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

    # PASO 1: Selección del formato de exportación
    st.write("Selecciona el formato en el que deseas exportar el informe:")
    
    formato_cols = st.columns(3)
    with formato_cols[0]:
        word_selected = st.checkbox("Documento Word (DOCX)", key="select_docx", value=True)
    with formato_cols[1]:
        html_selected = st.checkbox("Página web (HTML)", key="select_html")
    with formato_cols[2]:
        csv_selected = st.checkbox("Datos CSV", key="select_csv")
    
    # PASO 2: Generación de informes según selección
    if st.button("Preparar informes seleccionados", key="prepare_exports"):
        if not (word_selected or html_selected or csv_selected):
            st.warning("Por favor, selecciona al menos un formato para exportar.")
            return
            
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
                                key="docx_download_final"
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
                                key="html_download_final"
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
                                key="csv_download_final"
                            )
                            st.success("✅ Archivo CSV generado correctamente")
                        else:
                            st.error("❌ No se pudo generar el archivo CSV")
EOF
echo "✅ Nueva función creada"

# Buscar la función ui_show_correction_results y modificarla para usar ui_export_options_rediseñado
echo "🔍 Localizando referencias a ui_export_options_tabs..."

# Crear el patrón de búsqueda y reemplazo
SEARCH_PATTERN="ui_export_options_tabs(result)"
REPLACE_PATTERN="ui_export_options_rediseñado(result)"

# Verificar que el patrón existe en el archivo
if ! grep -q "$SEARCH_PATTERN" "$APP_FILE"; then
  echo "⚠️ Advertencia: No se encontró el patrón exacto '$SEARCH_PATTERN'"
  echo "Intentando buscar patrones similares..."
  
  # Buscar patrones similares
  if grep -q "ui_export_options_tabs" "$APP_FILE"; then
    echo "✅ Se encontró una referencia a ui_export_options_tabs"
    SEARCH_PATTERN="ui_export_options_tabs"
    REPLACE_PATTERN="ui_export_options_rediseñado"
  else
    echo "❌ Error: No se encontró ninguna referencia a ui_export_options_tabs"
    echo "Abortando script. Por favor, realiza los cambios manualmente."
    exit 1
  fi
fi

# Crear un archivo temporal con el reemplazo
echo "🔄 Reemplazando referencias a ui_export_options_tabs..."
sed "s/$SEARCH_PATTERN/$REPLACE_PATTERN/g" "$APP_FILE" > "$TEMP_DIR/app_modified.py"

# Verificar que el reemplazo se realizó correctamente
if ! grep -q "$REPLACE_PATTERN" "$TEMP_DIR/app_modified.py"; then
  echo "❌ Error: El reemplazo no se realizó correctamente"
  echo "Abortando script. Por favor, realiza los cambios manualmente."
  exit 1
fi

echo "✅ Referencias reemplazadas correctamente"

# Buscar la posición para añadir la nueva función ui_export_options_rediseñado
echo "🔍 Buscando la posición para añadir la nueva función..."

# Buscar el bloque de la función ui_export_options_tabs
START_LINE=$(grep -n "def ui_export_options_tabs" "$TEMP_DIR/app_modified.py" | cut -d':' -f1)
if [ -z "$START_LINE" ]; then
  echo "❌ Error: No se encontró la función ui_export_options_tabs"
  echo "Intentando encontrar un lugar adecuado..."
  
  # Estrategia alternativa: buscar la función ui_show_correction_results
  START_LINE=$(grep -n "def ui_show_correction_results" "$TEMP_DIR/app_modified.py" | cut -d':' -f1)
  
  if [ -z "$START_LINE" ]; then
    echo "❌ Error: No se pudo encontrar un lugar adecuado para añadir la función"
    echo "Abortando script. Por favor, realiza los cambios manualmente."
    exit 1
  fi
  
  echo "✅ Se utilizará la línea después de ui_show_correction_results"
  # Encontrar el final de ui_show_correction_results
  END_LINE=$((START_LINE + 1))
  while read -r line; do
    if [[ "$line" =~ ^def\ [a-zA-Z_][a-zA-Z0-9_]*\( ]]; then
      break
    fi
    END_LINE=$((END_LINE + 1))
  done < <(tail -n +$((START_LINE + 1)) "$TEMP_DIR/app_modified.py")
else
  echo "✅ Función ui_export_options_tabs encontrada en la línea $START_LINE"
  
  # Encontrar el final de la función ui_export_options_tabs
  END_LINE=$((START_LINE + 1))
  while read -r line; do
    if [[ "$line" =~ ^def\ [a-zA-Z_][a-zA-Z0-9_]*\( ]]; then
      break
    fi
    END_LINE=$((END_LINE + 1))
  done < <(tail -n +$((START_LINE + 1)) "$TEMP_DIR/app_modified.py")
fi

echo "✅ Posición para añadir la nueva función identificada"

# Crear el archivo final con la nueva función añadida
echo "🔄 Añadiendo la nueva función..."

# Copiar desde el inicio hasta el punto de inserción
head -n $END_LINE "$TEMP_DIR/app_modified.py" > "$NEW_APP_FILE"

# Añadir la nueva función ui_export_options_rediseñado
echo "" >> "$NEW_APP_FILE"  # Añadir línea en blanco
cat "$TEMP_DIR/ui_export_options_rediseñado.py" >> "$NEW_APP_FILE"
echo "" >> "$NEW_APP_FILE"  # Añadir línea en blanco

# Añadir el resto del archivo
tail -n +$((END_LINE + 1)) "$TEMP_DIR/app_modified.py" >> "$NEW_APP_FILE"

# Verificar que la nueva función se añadió correctamente
if ! grep -q "def ui_export_options_rediseñado" "$NEW_APP_FILE"; then
  echo "❌ Error: La nueva función no se añadió correctamente"
  echo "Abortando script. Por favor, realiza los cambios manualmente."
  exit 1
fi

echo "✅ Nueva función añadida correctamente"

# Reemplazar el archivo original con el nuevo
echo "🔄 Reemplazando el archivo original..."
cp "$NEW_APP_FILE" "$APP_FILE"

echo "✅ Archivo original reemplazado correctamente"
echo ""
echo "✨ ¡Solución implementada con éxito!"
echo ""
echo "📋 Resumen de acciones realizadas:"
echo "  - Se creó una copia de seguridad en: $BACKUP_FILE"
echo "  - Se añadió la nueva función ui_export_options_rediseñado"
echo "  - Se reemplazaron las referencias a ui_export_options_tabs"
echo ""
echo "🧪 Ahora puedes probar la aplicación para verificar que el error ha sido solucionado."
echo "Si encuentras algún problema, puedes restaurar la copia de seguridad con:"
echo "  cp \"$BACKUP_FILE\" \"$APP_FILE\""
echo ""
echo "Para limpiar los archivos temporales, ejecuta:"
echo "  rm -rf \"$TEMP_DIR\""
echo ""
echo "¡Gracias por utilizar este script de solución automatizada!"
