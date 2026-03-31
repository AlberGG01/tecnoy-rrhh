"""
reorganizar_carpetas.py
-----------------------
Reclasifica todos los candidatos de candidates.db en la nueva estructura
de carpetas usando GPT-4o-mini. NO ejecutar sin revisión previa.

NUEVA ESTRUCTURA (bajo TECNOY-Seleccion RRHH/01_ACTIVOS/):
  00_DATA/       Data_Engineer, Data_Analyst, BI, ML_Engineer, AI_Generative
  01_DESARROLLO/ Frontend, Backend, Fullstack, Mobile
  02_INFRAESTRUCTURA/ DevOps, Cloud, SysAdmin, Cybersecurity, Kubernetes_Engineer
  03_FUNCIONAL/  Business_Analyst, Project_Manager_IT, Consultor, Product_Owner
  04_INDUSTRIA/  Ingeniero, Electrico, CAD_Designer
  05_BECARIOS/   Becario_Data, Becario_Desarrollo, Becario_Business

MODO EJECUCION:
  --dry-run   Muestra qué haría sin tocar nada (recomendado primero)
  --execute   Mueve ficheros y actualiza BD (IRREVERSIBLE sin backup)
  --limit N   Procesa solo N candidatos (para prueba)
"""

import argparse
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import json
import os
import shutil
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "candidates.db"
ACTIVOS  = BASE_DIR / "TECNOY-Seleccion RRHH" / "01_ACTIVOS"

load_dotenv(BASE_DIR / ".env")
client = OpenAI()

# ---------------------------------------------------------------------------
# Estructura nueva — usada como contexto para GPT
# ---------------------------------------------------------------------------
ESTRUCTURA = """
00_DATA/
  Data_Engineer_[Tech]_[Seniority]     (Spark, Kafka, dbt, Airflow, Python, BigQuery, Snowflake…)
  Data_Analyst_[Tech]_[Seniority]      (SQL, Power BI, Tableau, Excel, Python…)
  BI_[Tech]_[Seniority]                (Cognos, MicroStrategy, Qlik, SAP BO, OBIEE…)
  ML_Engineer_[Tech]_[Seniority]       (TensorFlow, PyTorch, scikit-learn, MLflow, Kubeflow…)
  AI_Generative_[Tech]_[Seniority]     (LangChain, RAG, GPT, LLM, embeddings, ChromaDB…)

01_DESARROLLO/
  Frontend_[Tech]_[Seniority]          (React, Angular, Vue, TypeScript, HTML/CSS…)
  Backend_[Tech]_[Seniority]           (Java, .NET, Python, Node, Spring, FastAPI…)
  Fullstack_[Tech]_[Seniority]         (React+Node, Angular+Java, Vue+PHP…)
  Mobile_[Tech]_[Seniority]            (iOS, Android, Flutter, React Native…)

02_INFRAESTRUCTURA/
  DevOps_[Tech]_[Seniority]            (CI/CD, Jenkins, GitLab, ArgoCD, Terraform…)
  Cloud_[Tech]_[Seniority]             (AWS, Azure, GCP, multi-cloud…)
  SysAdmin_[Tech]_[Seniority]          (Linux, Windows Server, Active Directory…)
  Cybersecurity_[Seniority]            (pentesting, SOC, SIEM, ISO27001…)
  Kubernetes_Engineer_[Seniority]      (K8s, OpenShift, Helm, service mesh…)

03_FUNCIONAL/
  Business_Analyst_[Sector]            (análisis funcional, requisitos, BPM…)
  Project_Manager_IT_[Seniority]       (PMP, PRINCE2, Scrum Master…)
  Consultor_[Tech]_[Funcion]           (SAP, Salesforce, Oracle ERP, consultoría…)
  Product_Owner_[Seniority]            (backlog, roadmap, stakeholders…)

04_INDUSTRIA/
  Ingeniero_[Especialidad]_[Seniority] (mecánico, industrial, electrónico…)
  Electrico_[Sector]_[Seniority]       (instalaciones, BT/MT, automatización…)
  CAD_Designer_[Seniority]             (AutoCAD, SolidWorks, CATIA…)

05_BECARIOS/
  Becario_Data
  Becario_Desarrollo
  Becario_Business
"""

# ---------------------------------------------------------------------------
# GPT call
# ---------------------------------------------------------------------------
def clasificar_candidato(nombre, titulo, skills, seniority):
    """Devuelve (categoria_padre, subcarpeta_nombre) según la estructura nueva."""
    prompt = f"""Eres un clasificador de CVs de IT. Dada la informacion de un candidato,
determina en que subcarpeta de la nueva estructura debe ir.

ESTRUCTURA:
{ESTRUCTURA}

CANDIDATO:
- Nombre: {nombre}
- Titulo profesional: {titulo or 'N/D'}
- Seniority: {seniority or 'N/D'}
- Skills tecnicas: {skills or 'N/D'}

REGLAS OBLIGATORIAS (aplica en orden de prioridad):

1. DESARROLLO (01_DESARROLLO): Si el candidato tiene como skills PRINCIPALES cualquiera de:
   Java, Python (desarrollo), Node.js, PHP, .NET, C#, Spring, Hibernate, FastAPI, Flask,
   React, Angular, Vue, TypeScript, Swift, Kotlin, Flutter.
   → Subcarpeta: Backend_[Tech]_[Seniority], Frontend_[Tech]_[Seniority] o Fullstack_[Tech]_[Seniority]
   NUNCA mandes un desarrollador Java/Python/Node a 02_INFRAESTRUCTURA.

2. DATA (00_DATA): Si skills principales incluyen Spark, Hadoop, BigQuery, Snowflake, dbt,
   Airflow, Kafka, ETL, Power BI, Tableau, Cognos, scikit-learn, TensorFlow, PyTorch, LangChain.
   → Data_Engineer, Data_Analyst, BI, ML_Engineer o AI_Generative segun corresponda.

3. DEVOPS/INFRA (02_INFRAESTRUCTURA):
   - DevOps SOLO si Docker, Kubernetes, CI/CD, Terraform, Ansible, Jenkins son skills PRINCIPALES.
   - SysAdmin SOLO si el perfil es administracion de sistemas: Linux admin, Windows Server,
     Active Directory, VMware, administracion de servidores. NO desarrollo en Linux.
   - Kubernetes_Engineer si Kubernetes/OpenShift es el rol central.

4. BECARIOS (05_BECARIOS): Si seniority es becario o nivel muy junior sin experiencia real.
   → Becario_Data, Becario_Desarrollo o Becario_Business segun el area.

5. FUNCIONAL (03_FUNCIONAL): Perfiles no tecnicos: BA, PM, Scrum Master, consultores ERP.

6. INDUSTRIA (04_INDUSTRIA): Ingenieros no IT, electricos, CAD, mecanicos.

FORMATO ESTRICTO DE SUBCARPETA: Rol_Tech_Seniority
REGLAS DE FORMATO (OBLIGATORIAS):
- SIEMPRE tres segmentos separados por guion bajo: Rol_Tech_Seniority
- NUNCA juntes palabras sin guion bajo (MAL: SQLjunior, SQLsenior / BIEN: SQL_junior, SQL_senior)
- NUNCA: Data_Analyst_SQLjunior / SIEMPRE: Data_Analyst_SQL_junior
- NUNCA: Backend_JavaSpringsenior / SIEMPRE: Backend_Java_Spring_senior
- Rol: una palabra (Backend, Frontend, Data_Analyst, Data_Engineer, ML_Engineer, DevOps, SysAdmin...)
- Tech: una o dos palabras en PascalCase separadas por guion bajo (Java, Java_Spring, Python_Spark, Power_BI)
- Seniority: junior / mid / senior / lead / becario (siempre en minusculas, siempre con guion bajo antes)

EJEMPLOS CORRECTOS (sigue este patron exacto):
- Java + Spring     → {{"categoria": "01_DESARROLLO",       "subcarpeta": "Backend_Java_Spring_senior"}}
- Java basico       → {{"categoria": "01_DESARROLLO",       "subcarpeta": "Backend_Java_junior"}}
- React + TS        → {{"categoria": "01_DESARROLLO",       "subcarpeta": "Frontend_React_TS_mid"}}
- Python + Spark    → {{"categoria": "00_DATA",             "subcarpeta": "Data_Engineer_Python_Spark_senior"}}
- SQL + Power BI    → {{"categoria": "00_DATA",             "subcarpeta": "Data_Analyst_SQL_junior"}}
- SQL senior        → {{"categoria": "00_DATA",             "subcarpeta": "Data_Analyst_SQL_senior"}}
- Kubernetes + K8s  → {{"categoria": "02_INFRAESTRUCTURA",  "subcarpeta": "DevOps_Kubernetes_senior"}}
- Linux + WinServer → {{"categoria": "02_INFRAESTRUCTURA",  "subcarpeta": "SysAdmin_Linux_mid"}}
- Power BI          → {{"categoria": "00_DATA",             "subcarpeta": "Data_Analyst_Power_BI_mid"}}
- Becario datos     → {{"categoria": "05_BECARIOS",         "subcarpeta": "Becario_Data"}}

Responde UNICAMENTE con JSON valido:
{{"categoria": "01_DESARROLLO", "subcarpeta": "Backend_Java_Spring_senior"}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=80,
        response_format={"type": "json_object"}
    )
    result = json.loads(resp.choices[0].message.content)
    return result["categoria"], result["subcarpeta"]


# ---------------------------------------------------------------------------
# Resolución de ruta física del CV
# ---------------------------------------------------------------------------
def resolver_ruta(ruta_completa):
    """Devuelve Path absoluto al fichero, sea ruta relativa o absoluta en DB."""
    p = Path(ruta_completa)
    if p.is_absolute():
        return p if p.exists() else None
    # Ruta relativa: intentar con BASE_DIR
    candidato = BASE_DIR / p
    if candidato.exists():
        return candidato
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Reorganizar carpetas de candidatos")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Mostrar plan sin ejecutar (por defecto)")
    parser.add_argument("--execute", action="store_true",
                        help="Ejecutar cambios reales (mover ficheros + actualizar BD)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Procesar solo N candidatos (0 = todos)")
    args = parser.parse_args()

    dry_run = not args.execute
    mode_label = "DRY-RUN" if dry_run else "EJECUTANDO"

    print("=" * 65)
    print(f"  REORGANIZADOR DE CARPETAS — {mode_label}")
    print("=" * 65)
    if dry_run:
        print("  MODO SEGURO: no se moverá ningún fichero.")
        print("  Para aplicar cambios: python reorganizar_carpetas.py --execute")
    else:
        confirm = input("\n  [!] ATENCION: esto movera ficheros y actualizara la BD.\n"
                        "  ¿Continuar? (escribe SI para confirmar): ").strip()
        if confirm != "SI":
            print("Cancelado.")
            sys.exit(0)
    print()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = "SELECT id, nombre, titulo_profesional, skills_tecnicas, nivel_seniority, ruta_completa, carpeta_origen FROM candidatos ORDER BY id"
    c.execute(query)
    rows = c.fetchall()

    if args.limit:
        rows = rows[:args.limit]

    total       = len(rows)
    movidos     = 0
    errores     = 0
    sin_fichero = 0
    ya_ok       = 0
    nuevas_carpetas = set()

    print(f"Candidatos a procesar: {total}\n")

    for i, row in enumerate(rows, 1):
        cid        = row["id"]
        nombre     = row["nombre"] or "Desconocido"
        titulo     = row["titulo_profesional"]
        skills_raw = row["skills_tecnicas"]
        seniority  = row["nivel_seniority"]
        ruta_db    = row["ruta_completa"]
        carpeta_actual = row["carpeta_origen"]

        # Parsear skills
        try:
            skills_list = json.loads(skills_raw) if skills_raw else []
            skills = ", ".join(skills_list[:20]) if isinstance(skills_list, list) else str(skills_raw)
        except Exception:
            skills = str(skills_raw or "")

        print(f"[{i:4d}/{total}] {nombre[:45]:<45}", end=" ", flush=True)

        # Clasificar con GPT
        try:
            categoria, subcarpeta = clasificar_candidato(nombre, titulo, skills, seniority)
        except Exception as e:
            print(f"[ERR] GPT error: {e}")
            errores += 1
            continue

        nueva_carpeta_origen = f"01_ACTIVOS/{categoria}/{subcarpeta}"
        nueva_ruta_dir = ACTIVOS / categoria / subcarpeta

        # Resolver fichero físico
        fichero = resolver_ruta(ruta_db) if ruta_db else None
        if fichero is None:
            print(f"[!]  sin fichero -> {categoria}/{subcarpeta}")
            sin_fichero += 1
            # Actualizar solo la carpeta en BD aunque no haya fichero
            if not dry_run:
                c.execute("UPDATE candidatos SET carpeta_origen=? WHERE id=?",
                          (nueva_carpeta_origen, cid))
            continue

        nombre_fichero = fichero.name
        nueva_ruta_fichero = nueva_ruta_dir / nombre_fichero

        # ¿Ya está en el destino correcto?
        if fichero == nueva_ruta_fichero:
            print(f"[OK] ya en destino correcto")
            ya_ok += 1
            continue

        print(f"->  {categoria}/{subcarpeta}")

        if not dry_run:
            try:
                nueva_ruta_dir.mkdir(parents=True, exist_ok=True)
                nuevas_carpetas.add(str(nueva_ruta_dir))
                shutil.move(str(fichero), str(nueva_ruta_fichero))
                nueva_ruta_str = str(nueva_ruta_fichero.relative_to(BASE_DIR))
                c.execute(
                    "UPDATE candidatos SET carpeta_origen=?, ruta_completa=? WHERE id=?",
                    (nueva_carpeta_origen, nueva_ruta_str, cid)
                )
                movidos += 1
            except Exception as e:
                print(f"     [ERR] Error moviendo: {e}")
                errores += 1
        else:
            # En dry-run registramos carpetas que se crearían
            if not nueva_ruta_dir.exists():
                nuevas_carpetas.add(str(nueva_ruta_dir))
            movidos += 1  # "movería"

    if not dry_run:
        conn.commit()
    conn.close()

    # Resumen
    print()
    print("=" * 65)
    print(f"  RESUMEN {'(DRY-RUN — nada ejecutado)' if dry_run else '(CAMBIOS APLICADOS)'}")
    print("=" * 65)
    print(f"  Total procesados : {total}")
    print(f"  {'Moverían' if dry_run else 'Movidos'}         : {movidos}")
    print(f"  Ya en destino    : {ya_ok}")
    print(f"  Sin fichero      : {sin_fichero}")
    print(f"  Errores          : {errores}")
    if nuevas_carpetas:
        print(f"\n  Carpetas {'que se crearían' if dry_run else 'creadas'} ({len(nuevas_carpetas)}):")
        for nc in sorted(nuevas_carpetas):
            rel = Path(nc).relative_to(ACTIVOS) if Path(nc).is_relative_to(ACTIVOS) else nc
            print(f"    + {rel}")
    print()


if __name__ == "__main__":
    main()
