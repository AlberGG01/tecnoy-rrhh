import sqlite3
import chromadb
from pathlib import Path

BASE_DIR = Path("d:/Dev/projects/TECNOY RRHH")
DB_PATH = BASE_DIR / "candidates.db"
CHROMA_DIR = BASE_DIR / "chroma_db"

def clean_database():
    print("Conectando a las bases de datos...")
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    
    # 1. Identificar todos los candidatos cuya carpeta_origen NO empieza por '01_ACTIVOS'
    # Usamos NOT LIKE '01_ACTIVOS%' para coincidir con cualquier subcarpeta dentro de 01_ACTIVOS
    cursor.execute("SELECT id FROM candidatos WHERE carpeta_origen NOT LIKE '01_ACTIVOS%'")
    rows_to_delete = cursor.fetchall()
    ids_to_delete = [str(r[0]) for r in rows_to_delete]
    
    if ids_to_delete:
        print(f"Encontrados {len(ids_to_delete)} perfiles de carpetas antiguas. Borrando...")
        try:
            chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
            collection = chroma.get_collection("candidatos_cv_v2")
            # En Chroma se borra pasando una lista de strings con los IDs
            collection.delete(ids=ids_to_delete)
            print("✔ Borrados de ChromaDB vectorial.")
        except Exception as e:
            print(f"Error borrando de ChromaDB: {e}")
            
        # Borramos de SQLite
        placeholders = ",".join(["?" for _ in ids_to_delete])
        cursor.execute(f"DELETE FROM candidatos WHERE id IN ({placeholders})", ids_to_delete)
        db.commit()
        print("✔ Borrados de la base de datos de SQLite.")
    else:
        print("No hay perfiles antiguos que borrar.")

    # 2. NO tocar carpeta_origen de los que se quedan (eliminada la consulta UPDATE).
    
    db.close()
    print("¡Limpieza terminada de forma segura!")

if __name__ == "__main__":
    clean_database()
