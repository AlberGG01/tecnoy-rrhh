@echo off
pushd "%~dp0"
echo Actualizando aplicacion...
git config --global --add safe.directory "%CD%"
git fetch origin
git reset --hard origin/main
echo Instalando dependencias nuevas...
venv\Scripts\pip install -r requirements.txt -q
echo Actualizacion completada. Reinicia la aplicacion.
popd
pause
