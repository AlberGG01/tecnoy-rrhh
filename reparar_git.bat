@echo off
echo Reparando permisos de Git...
git config --global --add safe.directory "%~dp0"
echo Listo. Ahora ejecuta actualizar.bat
pause
