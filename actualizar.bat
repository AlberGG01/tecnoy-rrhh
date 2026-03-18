@echo off
echo Actualizando aplicacion...
git pull origin main
echo Instalando dependencias nuevas...
venv\Scripts\pip install -r requirements.txt -q
echo Actualizacion completada. Reinicia la aplicacion.
pause
