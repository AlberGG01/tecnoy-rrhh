# Lecciones aprendidas

## CRÍTICO: Siempre hacer git push después de cada commit

**Regla:** Después de cada `git commit`, hacer `git push origin main` INMEDIATAMENTE.
**Por qué:** El cliente usa `actualizar.bat` que hace `git fetch + reset --hard origin/main`.
Si los commits no están en GitHub, el cliente descarga la versión antigua y los fixes no llegan.
Esto obliga al cliente a ejecutar comandos manuales en CMD, algo que no debe pasar nunca.
**Cómo aplicar:** Nunca terminar una tarea sin verificar que `git status` diga
"Your branch is up to date with 'origin/main'". El push es parte del commit, no opcional.

## No reescribir scripts que funcionan (actualizar.bat)

**Regla:** Si un script de despliegue funciona en producción, no tocarlo salvo que sea
estrictamente necesario para el objetivo del ticket.
**Por qué:** El commit bcf09bc reescribió actualizar.bat para arreglar otro problema
e introdujo un bug con rutas que contienen paréntesis. El cliente quedó sin poder actualizar.
**Cómo aplicar:** Si hay que modificar actualizar.bat u otros scripts de despliegue,
probar en local con la ruta exacta del cliente (con espacios, paréntesis, etc.) antes de commitear.
