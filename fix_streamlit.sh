#!/bin/bash

# Este script modifica streamlit_app.py para solucionar el problema de botones dentro de formularios

# 1. Crear una copia de seguridad del archivo original
echo "Creando copia de seguridad..."
cp streamlit_app.py streamlit_app.py.backup

# 2. Buscar y reemplazar la función ui_export_options con ui_export_options_tabs
echo "Modificando la implementación de ui_export_options..."

# Buscar el inicio de la función ui_export_options
FUNCTION_START=$(grep -n "def ui_export_options" streamlit_app.py | cut -d':' -f1)

# Buscar el fin aproximado de la función (inicio de una nueva función def)
NEXT_FUNCTION=$(tail -n +$FUNCTION_START streamlit_app.py | grep -n "^def " | head -n 1 | cut -d':' -f1)
FUNCTION_END=$((FUNCTION_START + NEXT_FUNCTION - 1))

# Guardar líneas antes de la función
head -n $((FUNCTION_START - 1)) streamlit_app.py > streamlit_app.py.temp

# Añadir la nueva implementación
cat << 'EOF' >> streamlit_app.py.temp
def ui_export_options_tabs(data):
    """
    Versión alternativa que utiliza pestañas en lugar de formularios para la exportación.
    Esto garantiza que no haya botones anidados en formularios.

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

    # Usar pestañas para separar completamente los formatos
    export_tab1, export_tab2, export_tab3 = st.tabs(
        ["📝 Documento Word", "🌐 Documento HTML", "📊 Excel/CSV"]
    )

    # Pestaña para documento Word
    with export_tab1:
        st.write("Exporta este informe como documento Word (DOCX)")
        
        # Botón para generar Word - SIN usar formulario
        if st.button("Generar documento Word", key="gen_docx_tab"):
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
                        key="docx_download_tab"
                    )
                    st.success("✅ Documento generado correctamente")
                else:
                    st.error("No se pudo generar el documento Word. Inténtalo de nuevo.")

    # Pestaña para HTML
    with export_tab2:
        st.write("Exporta este informe como página web (HTML)")
        
        # Botón para generar HTML - SIN usar formulario
        if st.button("Generar documento HTML", key="gen_html_tab"):
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
                        key="html_download_tab"
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

    # Pestaña para CSV
    with export_tab3:
        st.write("Exporta los datos del análisis en formato CSV")
        
        # Botón para generar CSV - SIN usar formulario
        if st.button("Generar CSV", key="gen_csv_tab"):
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
                        key="csv_download_tab"
                    )
                    st.success("✅ CSV generado correctamente")
                else:
                    st.error("No se pudo generar el CSV. Inténtalo de nuevo.")
EOF

# Añadir las líneas después de la función original
tail -n +$FUNCTION_END streamlit_app.py >> streamlit_app.py.temp

# 3. Modificar la llamada a ui_export_options en ui_show_correction_results
echo "Actualizando la llamada a la función de exportación..."
sed -i 's/ui_export_options(result)/ui_export_options_tabs(result)/g' streamlit_app.py.temp

# 4. Reemplazar el archivo original con el modificado
mv streamlit_app.py.temp streamlit_app.py

echo "Cambios implementados con éxito. El archivo original se ha guardado como streamlit_app.py.backup"