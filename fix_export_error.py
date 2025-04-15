#!/usr/bin/env python3
import re
import os

# Verificar que el archivo existe
if not os.path.exists('streamlit_app.py'):
    print("Error: No se encuentra el archivo streamlit_app.py")
    exit(1)

# Leer el archivo actual
with open('streamlit_app.py', 'r', encoding='utf-8') as f:
    original_content = f.read()

# Crear copia de seguridad
with open('streamlit_app.py.export-backup', 'w', encoding='utf-8') as f:
    f.write(original_content)
print("✓ Backup creado: streamlit_app.py.export-backup")

# Buscar y eliminar las líneas de form en las tres pestañas
modified_content = original_content

# Para export_tab1 (documento Word)
modified_content = re.sub(
    r'with export_tab1:.*?with st\.form\(key="form_export_docx"\):',
    r'with export_tab1:\n        st.write("Exporta este informe como documento Word (DOCX)")\n',
    modified_content, flags=re.DOTALL
)
modified_content = re.sub(
    r'submit_docx = st\.form_submit_button\(.*?\)',
    r'if st.button("Generar documento Word", key="gen_docx")',
    modified_content, flags=re.DOTALL
)

# Para export_tab2 (HTML)
modified_content = re.sub(
    r'with export_tab2:.*?with st\.form\(key="form_export_html"\):',
    r'with export_tab2:\n        st.write("Exporta este informe como página web (HTML)")\n',
    modified_content, flags=re.DOTALL
)
modified_content = re.sub(
    r'submit_html = st\.form_submit_button\(.*?\)',
    r'if st.button("Generar documento HTML", key="gen_html")',
    modified_content, flags=re.DOTALL
)

# Para export_tab3 (CSV)
modified_content = re.sub(
    r'with export_tab3:.*?with st\.form\(key="form_export_csv"\):',
    r'with export_tab3:\n        st.write("Exporta los datos del análisis en formato CSV")\n',
    modified_content, flags=re.DOTALL
)
modified_content = re.sub(
    r'submit_csv = st\.form_submit_button\(.*?\)',
    r'if st.button("Generar CSV", key="gen_csv")',
    modified_content, flags=re.DOTALL
)

# Guardar los cambios
with open('streamlit_app.py', 'w', encoding='utf-8') as f:
    f.write(modified_content)

print("✓ Corrección aplicada con éxito")
print("Ejecuta la aplicación con: streamlit run streamlit_app.py")