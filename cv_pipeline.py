import os
import re
import json
import sqlite3
import base64
import time
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import chromadb
from docx import Document
from openai import OpenAI
from dotenv import load_dotenv

# Load API Key from .env located next to this script
BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- CONFIGURATION ---
TARGET_DIR = BASE_DIR / "CURRICULUMS"
DB_PATH = BASE_DIR / "candidates.db"
CHROMA_DIR = BASE_DIR / "chroma_db"
PROGRESS_FILE = BASE_DIR / "progress.json"

# GPT Models
MODEL_MINI = "gpt-4o-mini"
MODEL_VISION = "gpt-4o"

# V2 Prompt
SYSTEM_PROMPT = """Eres un extractor de datos de currículums experto. 
Analiza el CV y devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:

{
  "tipo_documento": "cv_personal | ficha_tecnoy",
  "nombre": "",
  "email": "",
  "telefono": "",
  "linkedin": "",
  "github": "",
  "portfolio_web": "",
  "ubicacion": {
    "ciudad": "",
    "provincia": "",
    "pais": ""
  },
  "titulo_profesional": "",
  "resumen_profesional": "",
  "nivel_seniority": "becario | junior | mid | senior | lead | manager | null",
  "años_experiencia_total": 0,
  "años_experiencia_por_skill": {
    "nombre_skill": 0
  },
  "instruccion_critica_antiolvido": "Dime que te has cerciorado de incluir MongoDB, O365, SAP, PWC, Kafka, PowerCenter, PLCs, Azure si aparecen. No resumas JAMÁS las habilidades técnicas, cópialas del texto original.",
  "skills_tecnicas": [],
  "skills_blandas": [],
  "certificaciones": [
    {
      "nombre": "",
      "entidad": "",
      "año": 0,
      "vigente": true
    }
  ],
  "idiomas": [
    {
      "idioma": "",
      "nivel": "básico | intermedio | avanzado | nativo | null",
      "certificacion": ""
    }
  ],
  "educacion": [
    {
      "titulo": "",
      "especialidad": "",
      "centro": "",
      "año_fin": 0,
      "nivel": "FP | grado | máster | doctorado | curso | certificación | null"
    }
  ],
  "experiencia_laboral": [
    {
      "empresa": "",
      "cargo": "",
      "fecha_inicio": "",
      "fecha_fin": "",
      "años": 0,
      "sector": "",
      "tecnologias_usadas": [],
      "descripcion_breve": ""
    }
  ],
  "sector_experiencia": [],
  "tipo_contrato_preferido": "indefinido | temporal | freelance | practicas | indiferente | null",
  "logros_destacados": [],
  "puntos_fuertes": [],
  "nivel_extraccion": 0,
  "confianza_extraccion": "alta | media | baja"
}

Reglas de extracción:
- Si un campo no existe, usa null o []
- años_experiencia_total: suma total estimada en años
- años_experiencia_por_skill: estima los años que ha usado cada tecnología basándote en las fechas de los proyectos
- skills_tecnicas: Extrae ABSOLUTAMENTE TODAS las tecnologías, herramientas, bases de datos (ej. MongoDB), frameworks, nubes y METODOLOGÍAS DE TRABAJO (ej. Scrum, Agile, Kanban, ITIL) en el texto y proyectos. NO RESUMAS. Sé extremadamente exhaustivo.
- nivel_seniority: deducirlo de años de experiencia y cargos
- resumen_profesional: máximo 3 líneas relevantes
- logros_destacados: proyectos importantes, equipos liderados, sistemas construidos desde cero, mejoras
- puntos_fuertes: dedúcelos del CV aunque no estén explícitos
- tipo_documento ficha_tecnoy: si tiene logo TECNOY o estructura de Niveles de intervención / Áreas de dominio
- email y telefono: BUSCA Y EXTRAE SIEMPRE estos campos del documento si es cv_personal, incluso si el formato es extraño (ej. +34, espacios). NO pongas null a menos que de verdad no existan.
- Para fichas Tecnoy: email, teléfono, linkedin y github = null
- NO incluyas carnet de conducir, vehículo, ni datos no IT
- Los strings "null" conviértelos siempre a null real de Python"""

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS candidatos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tipo_documento TEXT,
      nombre TEXT,
      email TEXT,
      telefono TEXT,
      linkedin TEXT,
      github TEXT,
      portfolio_web TEXT,
      ubicacion TEXT, -- JSON
      titulo_profesional TEXT,
      resumen_profesional TEXT,
      nivel_seniority TEXT,
      años_experiencia_total INTEGER,
      años_experiencia_por_skill TEXT, -- JSON
      skills_tecnicas TEXT, -- JSON
      skills_blandas TEXT, -- JSON
      certificaciones TEXT, -- JSON
      idiomas TEXT, -- JSON
      educacion TEXT, -- JSON
      experiencia_laboral TEXT, -- JSON
      sector_experiencia TEXT, -- JSON
      tipo_contrato_preferido TEXT,
      logros_destacados TEXT, -- JSON
      puntos_fuertes TEXT, -- JSON
      nivel_extraccion INTEGER,
      confianza_extraccion TEXT,
      carpeta_origen TEXT,
      archivo_origen TEXT,
      ruta_completa TEXT,
      fecha_indexacion TEXT
    )''')
    conn.commit()
    return conn

def get_chroma_collection():
    client_chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client_chroma.get_or_create_collection(
        name="candidatos_cv_v2",
        metadata={"hnsw:space": "cosine"}
    )
    return collection

# --- CLEANING LOGIC ---
def clean_value(val):
    if isinstance(val, str):
        if val.lower().strip() in ["null", "none", "n/a", ""]:
            return None
    elif val is None:
        return None
    return val

def sanitize_json(data):
    if isinstance(data, dict):
        return {k: sanitize_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_json(v) for v in data]
    else:
        return clean_value(data)

# --- HELPER FUNCTIONS ---
def is_valid_file(file_path: Path):
    name = file_path.name.lower()
    ext = file_path.suffix.lower()
    
    if "kpsheet" in name or "kp sheet" in name: return False
    if "_signed" in name or "oferta de incorporación" in name: return False
    if name == "thumbs.db": return False
    if file_path.stat().st_size < 5120: return False # 5KB
    if "onedrive_1_2-7-2025.zip" in name: return False
    
    allowed_exts = ['.pdf', '.docx', '.doc']
    if ext not in allowed_exts: return False
    
    return True

def extract_raw_text_pdf(pdf_path):
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception:
        pass
    return text

def check_coherence(text):
    if not text: return False
    words = text.split()
    if len(words) < 50: return False
    
    short_words = [w for w in words if len(w) <= 2]
    if (len(short_words) / len(words)) > 0.4: return False
    
    prefix = text[:100]
    if re.search(r'[^\x00-\x7F]{5,}', prefix): return False
    
    return True

def pdf_to_base64_images(pdf_path):
    images = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            images.append(base64.b64encode(img_data).decode('utf-8'))
        doc.close()
    except:
        pass
    return images

def docx_to_text(path):
    try:
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except:
        return ""

def process_single_file_with_cost(file_path: Path):
    ext = file_path.suffix.lower()
    name = file_path.name
    level = 1
    extracted_text = ""
    is_vision = False
    cost = 0.0
    
    if ext == '.pdf':
        extracted_text = extract_raw_text_pdf(file_path)
        if not extracted_text.strip():
            is_vision = True  # Nivel 3: Sin texto absoluto, requiere Visión
            level = 3
        elif not check_coherence(extracted_text):
            is_vision = False # Nivel 2: Texto "sucio" (columnas), probamos con Mini para ahorrar
            level = 2
        else:
            is_vision = False # Nivel 1: Texto limpio
            level = 1
    elif ext == '.docx':
        extracted_text = docx_to_text(file_path)
        level = 1 if len(extracted_text.split()) >= 50 else 2
    elif ext == '.doc':
        level = 2

    try:
        # SOLO usamos Visión si es Nivel 3 (Escaneo real sin texto)
        if is_vision and level == 3 and ext == '.pdf':
            images = pdf_to_base64_images(file_path)
            content = [{"type": "text", "text": "Extrae los datos de este CV según el esquema JSON solicitado."}]
            if level == 3: content[0]["text"] += " Es un escaneo, usa tu OCR interno."
            
            for img_b64 in images[:5]:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                })
            
            response = client.chat.completions.create(
                model=MODEL_VISION,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                response_format={"type": "json_object"}
            )
            cost = (response.usage.prompt_tokens * 5.0 / 1000000) + (response.usage.completion_tokens * 15.0 / 1000000)
        else:
            if ext == '.doc':
                with open(file_path, 'rb') as f:
                    bin_data = f.read()
                    extracted_text = "".join([chr(c) if 31 < c < 127 else " " for c in bin_data])
                    extracted_text = re.sub(r'\s+', ' ', extracted_text)[:5000]

            response = client.chat.completions.create(
                model=MODEL_MINI,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Archivo: {name}\nContenido:\n{extracted_text[:12000]}"}
                ],
                response_format={"type": "json_object"}
            )
            cost = (response.usage.prompt_tokens * 0.15 / 1000000) + (response.usage.completion_tokens * 0.60 / 1000000)
        
        extracted_data = json.loads(response.choices[0].message.content)
        extracted_data = sanitize_json(extracted_data)
        extracted_data["nivel_extraccion"] = level
        return extracted_data, extracted_text, cost
    except Exception as e:
        return {"error": str(e)}, "", 0.0

def save_to_db(data, raw_text, file_path, conn, collection):
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO candidatos (
            tipo_documento, nombre, email, telefono, linkedin, github, portfolio_web,
            ubicacion, titulo_profesional, resumen_profesional, nivel_seniority,
            años_experiencia_total, años_experiencia_por_skill, skills_tecnicas,
            skills_blandas, certificaciones, idiomas, educacion, experiencia_laboral,
            sector_experiencia, tipo_contrato_preferido, logros_destacados,
            puntos_fuertes, nivel_extraccion, confianza_extraccion, carpeta_origen,
            archivo_origen, ruta_completa, fecha_indexacion
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            data.get("tipo_documento"), data.get("nombre"), data.get("email"),
            data.get("telefono"), data.get("linkedin"), data.get("github"), data.get("portfolio_web"),
            json.dumps(data.get("ubicacion")), data.get("titulo_profesional"),
            data.get("resumen_profesional"), data.get("nivel_seniority"),
            data.get("años_experiencia_total"), json.dumps(data.get("años_experiencia_por_skill")),
            json.dumps(data.get("skills_tecnicas")), json.dumps(data.get("skills_blandas")),
            json.dumps(data.get("certificaciones")), json.dumps(data.get("idiomas")),
            json.dumps(data.get("educacion")), json.dumps(data.get("experiencia_laboral")),
            json.dumps(data.get("sector_experiencia")), data.get("tipo_contrato_preferido"),
            json.dumps(data.get("logros_destacados")), json.dumps(data.get("puntos_fuertes")),
            data.get("nivel_extraccion"), data.get("confianza_extraccion"),
            str(file_path.parent.name), file_path.name, str(file_path),
            datetime.now().isoformat()
        ))
        row_id = c.lastrowid
        conn.commit()
        
        doc_text = raw_text if raw_text else json.dumps(data)
        
        # OpenAI embedding
        emb_resp = client.embeddings.create(
            input=[doc_text[:8191]],
            model="text-embedding-3-small"
        )
        embedding = emb_resp.data[0].embedding
        
        collection.add(
            documents=[doc_text],
            embeddings=[embedding],
            metadatas=[{
                "sqlite_id": int(row_id), 
                "nombre": str(data.get("nombre") or "Desconocido"), 
                "archivo": str(file_path.name)
            }],
            ids=[str(row_id)]
        )
        return True
    except Exception as e:
        print(f"Error saving to DB: {e}")
        return False

# --- BATCH PROCESSING ---
def get_all_valid_files():
    valid_files = []
    for p in TARGET_DIR.rglob("*"):
        if p.is_file() and is_valid_file(p):
            valid_files.append(p)
    return valid_files

def get_processed_files(conn):
    c = conn.cursor()
    c.execute("SELECT ruta_completa FROM candidatos")
    return {row[0] for row in c.fetchall()}

def update_progress(processed, pending, errors, cost):
    prog = {
        "archivos_procesados": processed,
        "archivos_pendientes": pending,
        "errores": errors,
        "coste_acumulado_estimado": cost
    }
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(prog, f, indent=2)

def run_full_process(batch_size=50):
    conn = init_db()
    collection = get_chroma_collection()
    all_files = get_all_valid_files()
    processed_paths = get_processed_files(conn)
    pending_files = [f for f in all_files if str(f) not in processed_paths]
    
    total_to_process = len(pending_files)
    processed_count = 0
    
    # Load initial cost and errors from progress.json if exists
    total_cost = 0.0
    errors_count = 0
    if PROGRESS_FILE.exists():
        for _ in range(3): # Retry 3 times
            try:
                with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                    old_prog = json.load(f)
                    total_cost = old_prog.get("coste_acumulado_estimado", 0.0)
                    errors_count = old_prog.get("errores", 0)
                break
            except:
                time.sleep(1)
    
    # Stats for the batch summary
    batch_stats = {1: 0, 2: 0, 3: 0}
    
    print(f"\n--- INICIANDO PROCESAMIENTO TOTAL (V2) ---")
    print(f"Pendientes: {total_to_process} | Coste inicial: ${total_cost:.4f}\n")
    
    for i in range(0, total_to_process, batch_size):
        batch = pending_files[i:i+batch_size]
        print(f"\n>> Procesando lote {i//batch_size + 1} ({len(batch)} archivos)...")
        
        batch_errors = 0
        for file_path in batch:
            try:
                data, text, cost = process_single_file_with_cost(file_path)
                if "error" in data:
                    print(f"  [ERROR] {file_path.name}: {data['error']}")
                    batch_errors += 1
                else:
                    total_cost += cost
                    lvl = data.get("nivel_extraccion", 1)
                    batch_stats[lvl] = batch_stats.get(lvl, 0) + 1
                    print(f"  [OK] {file_path.name} (Lvl {lvl}) - Cost: ${cost:.5f}")
                    save_to_db(data, text, file_path, conn, collection)
            except Exception as e:
                print(f"  [CRITICAL ERROR] {file_path.name}: {e}")
                batch_errors += 1
            
            processed_count += 1
            update_progress(len(processed_paths) + processed_count, 
                            total_to_process - processed_count, 
                            errors_count + batch_errors, 
                            total_cost)
        
        errors_count += batch_errors
        print(f"\n--- RESUMEN LOTE {i//batch_size + 1} ---")
        print(f"Nivel 1: {batch_stats[1]} | Nivel 2: {batch_stats[2]} | Nivel 3: {batch_stats[3]}")
        print(f"Errores en este lote: {batch_errors}")
        print(f"Coste acumulado: ${total_cost:.4f}")
        # Reset batch stats for next batch print
        batch_stats = {1: 0, 2: 0, 3: 0}

    conn.close()

def run_test_sample():
    test_paths = [
        Path("TECNOY-Seleccion RRHH/00_ADMIN/Z-CVS ANTIGUOS/CV-europass.pdf"), 
        Path("TECNOY-Seleccion RRHH/00_ADMIN/Z-CVS ANTIGUOS/InfoJobs -  Angeles García Muñiz CV.pdf"),
        Path("TECNOY-Seleccion RRHH/02_CANDIDATOS_EN_PROCESO/TECNOY CANDIDATOS/JAVA/MKF Tecnoy - Consultor Java - Edgar Gabaldon.pdf"),
        Path("TECNOY-Seleccion RRHH/00_ADMIN/CV ANTIGUOS/CV_OscarCaniveHuguet (002).docx"),
        Path("TECNOY-Seleccion RRHH/01_ACTIVOS/00_DATA/big data python/CV Miguel Ivan Martinez Romero.doc")
    ]
    conn = init_db()
    collection = get_chroma_collection()
    results = []
    print("\n--- PRUEBA V2 SCHEMA ---\n")
    for rel_p in test_paths:
        p = BASE_DIR / rel_p
        if not p.exists(): continue
        print(f"Procesando: {p.name}...")
        data, text, cost = process_single_file_with_cost(p)
        results.append({"file": p.name, "result": data})
        save_to_db(data, text, p, conn, collection)
    print("\n--- RESULTADOS PRUEBA V2 ---\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        run_full_process()
    else:
        run_test_sample()
