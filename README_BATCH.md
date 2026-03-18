# 🚀 Automatización Semanal de Currículums (HR)

Esta carpeta está configurada para procesar automáticamente los nuevos currículums que recibes cada semana, leerlos, extraer sus datos utilizando Inteligencia Artificial, clasificarlos en su especialidad correspondiente y añadirlos directamente a la base de datos de búsquedas.

## 📝 Instrucciones de Uso (Para Recursos Humanos)

El proceso es 100% automático, solo tienes que seguir **un único paso**:

1. **Suelta los nuevos CVs** (formatos `.pdf`, `.docx` o `.doc`) dentro de la carpeta `NUEVOS_INGRESOS`.
2. **¡Ya está! No tienes que tocar ni hacer nada más.**

### ⏱️ ¿Cuándo se procesan los CVs?
El sistema informático de tu PC está configurado para despertar silenciosamente **todos los lunes a las 8:00 AM**. 
Si en ese preciso momento hay currículums esperando en la carpeta `NUEVOS_INGRESOS`, el programa:
- Leerá su texto con IA.
- Detectará su nombre, habilidades y años de experiencia.
- Los guardará en el buscador de candidatos inteligente que usáis diariamente.
- Los reubicará automáticamente sacándolos de `NUEVOS_INGRESOS` y metiéndolos en su subcarpeta correcta dentro del directorio `01_ACTIVOS` (Por ejemplo: `01_ACTIVOS/01_DESARROLLO/java j2ee/`).

> 💡 **Nota Inteligente:** Si por las prisas metes en la carpeta un documento administrativo por error (un contrato firmado, una LOPD, un DNI, etc.), no te preocupes. La IA del programa lo detectará, sabrá que no es un currículum válido, lo descartará automáticamente y no envenenará la base de datos.

---

## 🛠️ Instalación Inicial (Solo la primera vez en un ordenador nuevo)

Esta automatización está ya programada, pero si alguna vez mueves todo este proyecto de Inteligencia Artificial a un Ordenador Nuevo, necesitas decirle a ese nuevo Windows que trabaje los lunes por ti. Para hacerlo:

1. Ve a la raíz de esta carpeta.
2. Haz **click derecho** sobre el archivo de engranajes llamado `setup_task_scheduler.bat`
3. Pulsa la opción **Ejecutar como administrador**.
4. Se abrirá una ventanita confirmando que la tarea ha sido creada con éxito. Pulsa cualquier tecla y se cerrará.
5. ¡Listo! Ya no tendrás que volver a hacer esto nunca más. Funciona internamente.

### 📋 ¿Dónde veo si funcionó correctamente?
Si un lunes quieres comprobar qué ha metido el robot en tu base de datos o si ha fallado algo, simplemente entra a la carpeta `logs/`. 
Allí encontrarás un archivo de texto por cada ejecución titulado `Informe_Batch_...` con un resumen claro de exactamente qué ocurrió ese lunes (cuántos CVs extrajo, cuáles descartó y el coste).
