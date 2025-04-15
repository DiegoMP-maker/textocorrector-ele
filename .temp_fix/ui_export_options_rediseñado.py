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
