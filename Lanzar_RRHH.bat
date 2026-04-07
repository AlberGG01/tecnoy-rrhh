@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Limpiando cache de Streamlit...
venv\Scripts\python -m streamlit cache clear
echo Iniciando Centro de Recursos Humanos...
venv\Scripts\python -m streamlit run hr_search_app.py
