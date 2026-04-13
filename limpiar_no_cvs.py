"""
limpiar_no_cvs.py
-----------------
Detecta y elimina de la BD + ChromaDB todos los registros cuyo fichero
no es un CV real (facturas, hojas de coste, contratos, expectativas
salariales, etc.).

Los ficheros no-CV se mueven a la carpeta BASURA/ para revisión manual.

MODO DE EJECUCIÓN:
  --dry-run    Muestra qué eliminaría sin tocar nada (por defecto)
  --execute    Ejecuta la limpieza real (IRREVERSIBLE sin backup)
  --limit N    Procesa solo N candidatos (para prueba)
"""

import argparse
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import shutil
import sqlite3
from pathlib import Path

import fitz
import chromadb
from docx import Document as DocxDocument
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR  = Path(__file__).parent
DB_PATH   = BASE_DIR / "candidates.db"
CHROMA_DIR = BASE_DIR / "chroma_db"
BASURA_DIR = BASE_DIR / "BASURA"

load_dotenv(BASE_DIR / ".env")
client = OpenAI()


# ---------------------------------------------------------------------------
# Extracción de texto
# ---------------------------------------------------------------------------
def extract_text(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            doc = fitz.open(str(file_path))
            text = "".join(page.get_text() for page in doc)
            doc.close()
            return text
        elif ext == ".docx":
            doc = DocxDocument(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext == ".doc":
            with open(file_path, "rb") as f:
                raw = f.read()
            return "".join(chr(b) if 31 < b < 127 else " " for b in raw)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------
def clasificar(nombre_archivo: str, texto: str) -> tuple[bool, str]:
    """Devuelve (es_cv, motivo).
    es_cv=True → mantener | es_cv=False → eliminar."""

    nombre_lower = nombre_archivo.lower()

    # Siempre válidos por nombre
    if nombre_lower.startswith(("mk", "mkf")) or "tecnoy" in nombre_lower:
        return True, "ficha_tecnoy_por_nombre"

    # Sin texto legible → dudoso pero no eliminamos sin certeza
    if not texto or len(texto.strip()) < 80:
        return True, "texto_insuficiente_mantener"

    # Heurística rápida: palabras clave de documentos administrativos
    texto_low = texto[:2000].lower()
    keywords_no_cv = [
        "tarifa estimada", "estimación horas facturables", "profit sharing",
        "factura nº", "número de factura", "base imponible", "iva incluido",
        "facturación", "importe total", "forma de pago", "número de pedido",
        "contrato de servicios", "objeto del contrato", "cláusula",
        "lopd", "protección de datos", "política de privacidad",
        "oferta económica", "presupuesto nº", "cotización nº",
        "salario bruto mensual", "seguridad social empresa", "coste anual",
    ]
    for kw in keywords_no_cv:
        if kw in texto_low:
            return False, f"heuristica: '{kw}'"

    # GPT para casos no resueltos por heurística
    prompt = (
        "Determina si el siguiente documento es un Curriculum Vitae (CV) "
        "o ficha de perfil profesional de un candidato.\n"
        "Devuelve SOLO 'SI' si es un CV o perfil profesional válido.\n"
        "Devuelve SOLO 'NO' si es: factura, contrato, hoja de costes, "
        "formulario administrativo, presupuesto, expectativas salariales "
        "u otro documento que NO describe la experiencia laboral de una persona.\n\n"
        f"Nombre de archivo: {nombre_archivo}\n"
        f"Texto (parcial):\n{texto[:3000]}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        es_cv = resp.choices[0].message.content.strip().upper().startswith("SI")
        return es_cv, "gpt" if es_cv else "gpt: no es CV"
    except Exception as e:
        return True, f"error_gpt_mantener: {e}"


# ---------------------------------------------------------------------------
# Resolución de ruta física
# ---------------------------------------------------------------------------
def resolver_ruta(ruta_completa: str) -> Path | None:
    if not ruta_completa:
        return None
    p = Path(ruta_completa)
    if p.is_absolute():
        return p if p.exists() else None
    rel = BASE_DIR / p
    return rel if rel.exists() else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    dry_run = not args.execute

    BASURA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(f"  LIMPIEZA DE NO-CVs — {'DRY-RUN' if dry_run else 'EJECUTANDO'}")
    print("=" * 65)
    if dry_run:
        print("  MODO SEGURO: no se eliminará nada.")
        print("  Para aplicar: python limpiar_no_cvs.py --execute")
    else:
        confirm = input(
            "\n  [!] ATENCIÓN: esto eliminará registros de la BD y moverá ficheros.\n"
            "  ¿Continuar? (escribe SI para confirmar): "
        ).strip()
        if confirm != "SI":
            print("Cancelado.")
            sys.exit(0)
    print()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT id, nombre, archivo_origen, ruta_completa FROM candidatos ORDER BY id"
    )
    rows = c.fetchall()
    if args.limit:
        rows = rows[: args.limit]

    total = len(rows)
    eliminados = 0
    sin_fichero = 0
    mantenidos = 0
    errores = 0
    ids_eliminar = []

    print(f"Candidatos a analizar: {total}\n")

    for i, row in enumerate(rows, 1):
        cid = row["id"]
        nombre = row["nombre"] or "Desconocido"
        archivo = row["archivo_origen"] or ""
        ruta_db = row["ruta_completa"] or ""

        print(f"[{i:4d}/{total}] {nombre[:50]:<50}", end=" ", flush=True)

        fichero = resolver_ruta(ruta_db)
        if fichero is None:
            # Intentar buscar por nombre en 01_ACTIVOS
            if archivo:
                activos = BASE_DIR / "TECNOY-Seleccion RRHH" / "01_ACTIVOS"
                found = list(activos.rglob(archivo)) if activos.exists() else []
                if found:
                    fichero = found[0]

        if fichero is None:
            print(f"[SIN FICHERO] {archivo}")
            sin_fichero += 1
            mantenidos += 1
            continue

        texto = extract_text(fichero)
        es_cv, motivo = clasificar(archivo, texto)

        if es_cv:
            print(f"[OK] {motivo}")
            mantenidos += 1
        else:
            print(f"[NO-CV] {motivo} → {archivo}")
            eliminados += 1
            ids_eliminar.append(str(cid))

            if not dry_run:
                # Mover fichero a BASURA
                try:
                    dest = BASURA_DIR / fichero.name
                    # Evitar colisión de nombres
                    if dest.exists():
                        dest = BASURA_DIR / f"{cid}_{fichero.name}"
                    shutil.move(str(fichero), str(dest))
                except Exception as e:
                    print(f"     [ERR] No se pudo mover fichero: {e}")
                    errores += 1

    # Eliminar de BD y Chroma
    if not dry_run and ids_eliminar:
        try:
            chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
            collection = chroma.get_collection("candidatos_cv_v2")
            collection.delete(ids=ids_eliminar)
            print(f"\n✔ {len(ids_eliminar)} eliminados de ChromaDB.")
        except Exception as e:
            print(f"\n[ERR] ChromaDB: {e}")

        placeholders = ",".join(["?"] * len(ids_eliminar))
        conn.execute(
            f"DELETE FROM candidatos WHERE id IN ({placeholders})", ids_eliminar
        )
        conn.commit()
        print(f"✔ {len(ids_eliminar)} eliminados de SQLite.")

    conn.close()

    print()
    print("=" * 65)
    print(f"  RESUMEN {'(DRY-RUN)' if dry_run else '(CAMBIOS APLICADOS)'}")
    print("=" * 65)
    print(f"  Total analizados   : {total}")
    print(f"  CVs válidos        : {mantenidos}")
    print(f"  No-CVs {'detectados' if dry_run else 'eliminados'}   : {eliminados}")
    print(f"  Sin fichero        : {sin_fichero}")
    print(f"  Errores            : {errores}")
    if dry_run and ids_eliminar:
        print(f"\n  IDs que se eliminarían: {', '.join(ids_eliminar[:20])}"
              + (" ..." if len(ids_eliminar) > 20 else ""))
    print()


if __name__ == "__main__":
    main()
