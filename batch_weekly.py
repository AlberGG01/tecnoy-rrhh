import sqlite3
import chromadb
import json
import shutil
import os
import sys
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
    client,
    extract_raw_text_pdf,
    docx_to_text,
    save_to_db,
    init_db
)

# Configuración de rutas relativas
SOURCE_DIR = BASE_DIR / "NUEVOS_INGRESOS"
ACTIVOS_DIR = BASE_DIR / "TECNOY-Seleccion RRHH" / "01_ACTIVOS"
DUPLICADOS_DIR = BASE_DIR / "DUPLICADOS"
DB_PATH = BASE_DIR / "candidates.db"
CHROMA_DIR = BASE_DIR / "chroma_db"
LOG_DIR = BASE_DIR / "logs"

# Asegurar que los directorios existen
SOURCE_DIR.mkdir(parents=True, exist_ok=True)
ACTIVOS_DIR.mkdir(parents=True, exist_ok=True)
DUPLICADOS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def extract_text(file_path: Path):
    ext = file_path.suffix.lower()
    if ext == '.pdf':
        return extract_raw_text_pdf(file_path)
    elif ext in ['.docx', '.doc']:
        return docx_to_text(str(file_path))
    return ""

def is_real_cv(text, filename=""):
    # Bypass GPT: ficheros MKF/Tecnoy son siempre CVs validos por nombre
    name_lower = filename.lower()
    if name_lower.startswith(("mk", "mkf")) or "tecnoy" in name_lower:
        return True

    if not text or len(text.strip()) < 50:
        return False

    val_prompt = (
        "Determina si el siguiente documento es un Curriculum Vitae (CV) real de un candidato "
        "a un puesto de trabajo. "
        "IMPORTANTE: Los documentos cuyo nombre empiece por 'MK', 'MKF' o que contengan 'Tecnoy' "
        "son fichas corporativas de candidatos y DEBEN considerarse CVs validos, NO documentos administrativos. "
        "Devuelve SOLO 'SI' si es un curriculum, perfil profesional o ficha corporativa de candidato valida. "
        "Devuelve SOLO 'NO' si es un documento puramente administrativo (contrato, formulario LOPD, "
        "oferta de servicios empresariales, documento legal, etc) que no describe la experiencia de una persona.\n\n"
        f"Texto extraido (parcial):\n{text[:3000]}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": val_prompt}],
            temperature=0
        )
        return resp.choices[0].message.content.strip().upper().startswith("SI")
    except Exception as e:
        return False

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
        
        log_print(f"Iniciando procesamiento de {len(files_to_check)} archivos encontrados...\n")
        
        # 3. Procesar archivos
        for file_path in files_to_check:
            filename = file_path.name
            
            if filename in indexed_files:
                stats["ya_indexados"] += 1
                try:
                    # Mover el archivo a la carpeta principal para limpiar NUEVOS_INGRESOS
                    # aunque ya estuviera indexado (para no procesarlo en el futuro)
                    trash_path = ACTIVOS_DIR / filename
                    shutil.move(str(file_path), str(trash_path))
                    log_print(f"[{filename}] YA INDEXADO -> Movido a 01_ACTIVOS (sin carpeta skill)")
                except Exception as e:
                    log_print(f"[{filename}] YA INDEXADO -> Error al limpiar la ruta: {e}")
                continue
                
            log_print(f"[{filename}] Analizando nuevo candidato...")
            text = extract_text(file_path)
            
            if not is_real_cv(text, filename):
                log_print(f"  [DESCARTADO] No parece un CV real (documento administrativo).")
                stats["administrativos_ignorados"] += 1
                try:
                    trash_path = ACTIVOS_DIR / filename
                    shutil.move(str(file_path), str(trash_path))
                except: pass
                continue

            stats["cvs_reales"] += 1
            log_print("  [CV] Es un CV real. Extrayendo datos con IA...")

            try:
                data, extracted_text, cost = process_single_file_with_cost(file_path)
            except Exception as e:
                log_print(f"  [ERROR] Error critico en pipeline: {e}")
                stats["fallos_extraccion"] += 1
                continue

            if "error" not in data:
                extracted_name = clean_name(data.get('nombre', ''))
                extracted_email = data.get('email', '')

                # Comprobar duplicado por nombre o email antes de insertar
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
                    log_print(f"  [DUPLICADO] Candidato ya existe en la BD (por {existing.get('razon')}): {existing.get('nombre')}")
                    log_print(f"[DUPLICADO_JSON] {dup_info}")
                    # Mover el archivo a DUPLICADOS para revisión manual
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

                log_print(f"  [->] Moviendo a: 01_ACTIVOS/{folder_str}/{new_filename}")

                try:
                    shutil.move(str(file_path), str(target_path))
                    insert_into_db(data, extracted_text, DB_PATH, CHROMA_DIR, str(target_path), folder_str, new_filename)
                    log_print(f"  [OK] Indexado y vectorizado correctamente. (Costo: ${cost:.5f})")
                    stats["nuevos_anadidos"] += 1
                    indexed_files.add(filename)
                except Exception as e:
                    log_print(f"  [ERROR] Error al mover o indexar: {e}")
                    stats["fallos_extraccion"] += 1
            else:
                log_print(f"  [ERROR] Fallo en IA: {data['error']}")
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

if __name__ == "__main__":
    main()
