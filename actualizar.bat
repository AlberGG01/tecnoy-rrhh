@echo off
pushd "%~dp0"
echo Actualizando aplicacion...
git config --global --add safe.directory "%CD%"
git fetch origin
git reset --hard origin/main
echo Instalando dependencias nuevas...

REM Crear directorio temporal corto para evitar error de rutas largas en OneDrive
if not exist "C:\Temp" mkdir "C:\Temp"
set TEMP=C:\Temp
set TMP=C:\Temp

venv\Scripts\pip install -r requirements.txt -q --no-cache-dir
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo AVISO: pip reporto un error al instalar dependencias.
    echo Esto puede ocurrir por rutas largas en OneDrive. Intentando continuar...
    echo Si la aplicacion no arranca, contacta con el administrador.
    echo.
)
echo Actualizacion completada. Reinicia la aplicacion.
popd
pause
