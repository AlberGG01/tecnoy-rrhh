# 🚀 Tecnoy HR Search App - Centro de Recursos Humanos

Esta aplicación permite realizar búsquedas inteligentes y rankings de candidatos utilizando los CVs extraídos en el pipeline V2.

## Características principales

1.  **🔍 Búsqueda Híbrida**: Permite buscar por palabras clave (SQLite) y por significado semántico (ChromaDB) simultáneamente.
2.  **🎯 Ranking por Oferta**: Pega una descripción de puesto y la IA encontrará los mejores perfiles usando un sistema de **Reranking con Cross-Encoders**.
3.  **📊 Filtros Avanzados**: Por carpeta de especialidad, nivel de seniority y años de experiencia.
4.  **📑 Acceso a CV**: Botón integrado para abrir el archivo original del candidato.

## Instalación y Uso

1.  **Entorno**: Asegúrate de tener Python 3.9+ instalado.
2.  **Dependencias**: Instala los requisitos necesarios:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuración**: La aplicación requiere una clave de API de OpenAI configurada en las variables de entorno (`OPENAI_API_KEY`).
4.  **Ejecución**: Lanza la aplicación con el siguiente comando:
    ```bash
    streamlit run hr_search_app.py
    ```

## Estructura de Datos
La app lee directamente de:
- `candidates.db`: Base de datos SQLite con metadatos.
- `chroma_db/`: Base de datos vectorial para búsquedas semánticas.
- `logo.png`: Logo corporativo de Tecnoy.

---
**Desarrollado para Tecnoy RRHH V2**
