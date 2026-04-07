@echo off
echo Actualizando aplicacion...
git config --global --add safe.directory "%~dp0"
git -C "%~dp0" pull origin main
echo Instalando dependencias nuevas...
venv\Scripts\pip install -r requirements.txt -q
echo Actualizacion completada. Reinicia la aplicacion.
pause
