@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Iniciando Centro de Recursos Humanos...
streamlit run hr_search_app.py
