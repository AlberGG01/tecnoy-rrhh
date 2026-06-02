import sqlite3
import chromadb
import json
import shutil
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

# Forzar UTF-8 en stdout para evitar UnicodeEncodeError en consolas cp1252 de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Añadir el directorio base al path para poder importar módulos locales
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# Importaciones locales
from cv_pipeline import (
    process_single_file_with_cost,
    save_to_db,
    init_db
)

# Configuración de rutas relativas
SOURCE_DIR = BASE_DIR / "NUEVOS_INGRESOS"
ACTIVOS_DIR = BASE_DIR / "TECNOY-Seleccion RRHH" / "01_ACTIVOS"
DUPLICADOS_DIR = BASE_DIR / "DUPLICADOS"
NO_CV_DIR = SOURCE_DIR / "NO_ES_CV"
DB_PATH = BASE_DIR / "candidates.db"
CHROMA_DIR = BASE_DIR / "chroma_db"
LOG_DIR = BASE_DIR / "logs"

# Asegurar que los directorios existen
SOURCE_DIR.mkdir(parents=True, exist_ok=True)
ACTIVOS_DIR.mkdir(parents=True, exist_ok=True)
DUPLICADOS_DIR.mkdir(parents=True, exist_ok=True)
NO_CV_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_proposed_folder(skills, seniority):
    if not skills: return "00_VARIOS"
    main_skill = skills[0] if isinstance(skills, list) else str(skills).split(",")[0]
    sen = str(seniority).replace(" ","_").capitalize() if seniority and str(seniority).lower() != 'null' else "Unknown"
    import re
    safe_skill = re.sub(r'[^a-zA-Z0-9_\-]', '', str(main_skill).replace(" ", "_"))
    return f"{safe_skill}_{sen}"

def get_new_filename(original, name):
    ext = Path(original).suffix
    if not name or str(name).lower() == 'null': return original
    safe_name = str(name).replace(" ", "_").upper()
    return f"{safe_name}{ext}"

def insert_into_db(data, raw_text, db_path, chroma_dir, target_path, folder_str, new_filename):
    conn = init_db()  # garantiza schema actualizado + WAL mode
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection("candidatos_cv_v2")
    save_to_db(data, raw_text, Path(target_path), conn, collection)
    conn.close()

def clean_name(name):
    import re
    if not name or name.lower() == 'null': return None
    return re.sub(r'\s+', ' ', name).strip()

def filename_suggests_cv(filename):
    """True si el nombre del archivo indica claramente que es un CV (override de seguridad)."""
    import re
    name = filename.lower()
    # Palabras que indican explícitamente que es un CV
    if re.search(r'\b(cv|curriculum|resume|curriculo)\b', name):
        return True
    # Adobe Scan / CamScanner → documentos escaneados que el jefe mete a mano = asumir CV
    if re.search(r'\b(adobe.?scan|camscanner|scan\b)', name):
        return True
    return False

def check_duplicate(nombre, email):
    """Busca en la BD si ya existe un candidato con el mismo nombre o email.
    Devuelve (True, dict_existente) o (False, None)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        c = conn.cursor()
        if nombre:
            nombre_norm = ' '.join(nombre.strip().lower().split())
            c.execute(
                "SELECT id, nombre, archivo_origen, ruta_completa FROM candidatos "
                "WHERE LOWER(TRIM(nombre)) = ? LIMIT 1",
                (nombre_norm,)
            )
            row = c.fetchone()
            if row:
                conn.close()
                return True, {"id": row[0], "nombre": row[1],
                              "archivo_origen": row[2], "ruta_completa": row[3],
                              "razon": "nombre"}
        if email and str(email).lower() not in ('null', 'none', ''):
            c.execute(
                "SELECT id, nombre, archivo_origen, ruta_completa FROM candidatos "
                "WHERE LOWER(TRIM(email)) = ? LIMIT 1",
                (email.strip().lower(),)
            )
            row = c.fetchone()
            if row:
                conn.close()
                return True, {"id": row[0], "nombre": row[1],
                              "archivo_origen": row[2], "ruta_completa": row[3],
                              "razon": "email"}
        conn.close()
    except Exception:
        pass
    return False, None

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"Informe_Batch_{timestamp}.txt"
    
    # 1. Buscar archivos en NUEVOS_INGRESOS
    valid_extensions = {".pdf", ".docx", ".doc"}
    files_to_check = []
    
    for root, _, files in os.walk(SOURCE_DIR):
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in valid_extensions and not file_path.name.startswith("~"):
                files_to_check.append(file_path)
                
    # Si no hay archivos, terminamos silenciosamente anotando en el log
    if not files_to_check:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No se encontraron nuevos CVs en la carpeta NUEVOS_INGRESOS.\n")
            f.write("Ejecucion terminada sin acciones.\n")
        return

    # Preparar el archivo de log para la ejecución
    with open(log_file, "w", encoding="utf-8") as log:
        def log_print(msg):
            print(msg)
            log.write(msg + "\n")
            
        log_print(f"==================================================")
        log_print(f" REPORT DE BATCH SEMANAL - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_print(f"==================================================\n")
            
        # 2. Conectar a SQLite para obviar los ya indexados
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT archivo_origen FROM candidatos")
            indexed_files = {row[0] for row in cursor.fetchall()}
            conn.close()
        except sqlite3.OperationalError:
            indexed_files = set()
            log_print("Aviso: No se pudo conectar a SQLite, se asumirá que ningún archivo está indexado.")

        stats = {
            "archivos_encontrados": len(files_to_check),
            "ya_indexados": 0,
            "cvs_reales": 0,
            "administrativos_ignorados": 0,
            "nuevos_anadidos": 0,
            "duplicados": 0,
            "fallos_extraccion": 0
        }
        no_cv_files = []  # nombres de archivos movidos a NO_ES_CV

        # Separar ya-indexados de nuevos
        already_indexed = [fp for fp in files_to_check if fp.name in indexed_files]
        to_process = [fp for fp in files_to_check if fp.name not in indexed_files]

        # Limpiar ya-indexados rápido (sin IA)
        for file_path in already_indexed:
            filename = file_path.name
            stats["ya_indexados"] += 1
            try:
                shutil.move(str(file_path), str(ACTIVOS_DIR / filename))
                log_print(f"[{filename}] YA INDEXADO -> Movido a 01_ACTIVOS")
            except Exception as e:
                log_print(f"[{filename}] YA INDEXADO -> Error al limpiar: {e}")

        if not to_process:
            log_print("No hay archivos nuevos que procesar.")
        else:
            # Número de workers: tantos como núcleos, máximo 8, mínimo 1
            max_workers = min(8, os.cpu_count() or 2, len(to_process))
            log_print(f"Iniciando extraccion paralela de {len(to_process)} archivo(s) con {max_workers} workers...\n")

            # Lock para log thread-safe durante la fase paralela
            log_lock = threading.Lock()
            def safe_log(msg):
                with log_lock:
                    log_print(msg)

            # 3a. Fase paralela: extraccion (Docling + GPT) — la parte lenta
            extraction_results = {}  # file_path -> (data, text, cost) | Exception

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(process_single_file_with_cost, fp): fp
                    for fp in to_process
                }
                for future in as_completed(future_to_file):
                    fp = future_to_file[future]
                    try:
                        data, text, cost = future.result()
                        extraction_results[fp] = (data, text, cost)
                        words = len(text.split()) if text else 0
                        safe_log(f"[{fp.name}] Extraido: {words} palabras (costo: ${cost:.5f})")
                    except Exception as e:
                        extraction_results[fp] = e
                        safe_log(f"[{fp.name}] [ERROR] Error en pipeline: {e}")

            log_print("")

            # 3b. Fase serial: clasificar, mover archivos e insertar en BD
            for file_path in to_process:
                filename = file_path.name
                result = extraction_results.get(file_path)

                if isinstance(result, Exception) or result is None:
                    log_print(f"[{filename}] [ERROR] Fallo en extraccion — se omite.")
                    stats["fallos_extraccion"] += 1
                    continue

                data, extracted_text, cost = result

                if "error" in data:
                    log_print(f"[{filename}] [ERROR] Fallo en IA: {data['error']}")
                    stats["fallos_extraccion"] += 1
                    continue

                if data.get("tipo_documento") == "documento_administrativo":
                    if filename_suggests_cv(filename):
                        log_print(f"[{filename}] [OVERRIDE] IA dijo doc. administrativo pero nombre contiene 'cv/curriculum' — procesando como CV.")
                    else:
                        stats["administrativos_ignorados"] += 1
                        try:
                            shutil.move(str(file_path), str(NO_CV_DIR / filename))
                            no_cv_files.append(filename)
                            log_print(f"[{filename}] [DESCARTADO] No es un CV — movido a NUEVOS_INGRESOS/NO_ES_CV/")
                        except Exception as e:
                            log_print(f"[{filename}] [DESCARTADO] Error al mover a NO_ES_CV: {e}")
                        continue

                stats["cvs_reales"] += 1
                extracted_name = clean_name(data.get('nombre', ''))
                extracted_email = data.get('email', '')

                is_dup, existing = check_duplicate(extracted_name, extracted_email)
                if is_dup:
                    stats["duplicados"] += 1
                    dup_info = json.dumps({
                        "nuevo_archivo": filename,
                        "candidato_nombre": extracted_name or "Desconocido",
                        "existente_archivo": existing.get("archivo_origen", ""),
                        "existente_ruta": existing.get("ruta_completa", ""),
                        "existente_nombre": existing.get("nombre", ""),
                        "razon": existing.get("razon", "nombre")
                    }, ensure_ascii=False)
                    log_print(f"[{filename}] [DUPLICADO] Ya existe en BD (por {existing.get('razon')}): {existing.get('nombre')}")
                    log_print(f"[DUPLICADO_JSON] {dup_info}")
                    try:
                        shutil.move(str(file_path), str(DUPLICADOS_DIR / filename))
                    except Exception:
                        pass
                    continue

                new_filename = get_new_filename(filename, extracted_name)
                skills = data.get('skills_tecnicas', [])
                seniority = data.get('nivel_seniority', '')
                folder_str = get_proposed_folder(skills, seniority)
                target_folder = ACTIVOS_DIR / folder_str
                target_folder.mkdir(parents=True, exist_ok=True)
                target_path = target_folder / new_filename

                log_print(f"[{filename}] [->] Moviendo a: 01_ACTIVOS/{folder_str}/{new_filename}")
                try:
                    shutil.move(str(file_path), str(target_path))
                    insert_into_db(data, extracted_text, DB_PATH, CHROMA_DIR, str(target_path), folder_str, new_filename)
                    log_print(f"[{filename}] [OK] Indexado y vectorizado. (Costo: ${cost:.5f})")
                    stats["nuevos_anadidos"] += 1
                    indexed_files.add(filename)
                except PermissionError:
                    log_print(f"[{filename}] [BLOQUEADO] El archivo esta abierto en Word o OneDrive lo esta sincronizando. Cierralo y vuelve a lanzar el batch.")
                    stats["fallos_extraccion"] += 1
                except Exception as e:
                    log_print(f"[{filename}] [ERROR] Error al mover o indexar: {e}")
                    stats["fallos_extraccion"] += 1
                
        # 4. Resumen final en log
        log_print(f"\n==================================================")
        log_print(f" RESUMEN FINAL")
        log_print(f"==================================================")
        log_print(f"Archivos encontrados (pdf/doc/docx):  {stats['archivos_encontrados']}")
        log_print(f"Archivos pre-existentes ignorados:    {stats['ya_indexados']}")
        log_print(f"Documentos administrativos ignorados: {stats['administrativos_ignorados']}")
        log_print(f"Currículums reales identificados:     {stats['cvs_reales']}")
        log_print(f"Nuevos CVs extraídos e indexados:     {stats['nuevos_anadidos']}")
        log_print(f"Duplicados detectados (no añadidos):  {stats['duplicados']}")
        log_print(f"Fallos de extracción/indexación:      {stats['fallos_extraccion']}")
        log_print(f"==================================================\n")
        if no_cv_files:
            log_print(f"AVISO: {len(no_cv_files)} archivo(s) detectados como NO currículum han sido")
            log_print(f"       movidos a la carpeta: NUEVOS_INGRESOS/NO_ES_CV/")
            log_print(f"       Revísalos manualmente por si se han colado por error:")
            for fn in no_cv_files:
                log_print(f"         - {fn}")
            log_print(f"")

if __name__ == "__main__":
    main()
