import streamlit as st
import sqlite3
import pandas as pd
import chromadb
import json
import os
import re
import io
import sys
import subprocess
import datetime
from pathlib import Path
from openai import OpenAI
from sentence_transformers import CrossEncoder
import torch
from dotenv import load_dotenv
import cv_exporter  # Exportador a Master File Corporativo

_APP_DIR = Path(__file__).parent.resolve()
load_dotenv(_APP_DIR / ".env")
BASE_DIR = os.getenv("BASE_DIR", str(_APP_DIR))

import chromadb.utils.embedding_functions as embedding_functions
# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Centro de Recursos Humanos | Tecnoy",
    page_icon="🚀",
    layout="wide",
)

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .stApp {{
        background-color: #F5F5F5;
    }}
    .main-header {{
        color: #1A1A1A;
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 1rem;
    }}
    .candidato-card {{
        background-color: #FFFFFF;
        padding: 1.5rem;
        border-radius: 8px;
        border-left: 4px solid #E8500A;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }}
    .candidato-header {{
        color: #1A1A1A;
        font-size: 1.25rem;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .seniority-badge {{
        background-color: #E8500A22;
        color: #E8500A;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 600;
    }}
    .skill-match {{
        background-color: #E8500A;
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        margin-right: 4px;
        font-size: 0.8rem;
    }}
    .skill-missing {{
        background-color: #E0E0E0;
        color: #666666;
        padding: 2px 6px;
        border-radius: 4px;
        margin-right: 4px;
        font-size: 0.8rem;
    }}
    .match-score {{
        font-size: 2rem;
        font-weight: 800;
        color: #E8500A;
    }}
    .stButton>button {{
        background-color: #E8500A;
        color: white;
        border-radius: 6px;
        border: none;
        padding: 0.5rem 1rem;
    }}
    .stButton>button:hover {{
        background-color: #1A1A1A;
        color: white;
    }}
    .medal {{
        font-size: 1.5rem;
        margin-right: 0.5rem;
    }}
    </style>
""", unsafe_allow_html=True)

# --- CLIENTES Y RECURSOS ---
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect(str(_APP_DIR / "candidates.db"), check_same_thread=False)
    return conn

def get_chroma_client():
    client = chromadb.PersistentClient(path=str(_APP_DIR / "chroma_db"))
    return client

@st.cache_resource
def load_reranker():
    return CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

client_openai = OpenAI()

# --- DICCIONARIO DE SINÓNIMOS DE SKILLS ---
SKILL_SYNONYMS = {
    'pwc': ['powercenter', 'power center'],
    'powercenter': ['pwc', 'power center'],
    'k8s': ['kubernetes'],
    'kubernetes': ['k8s'],
    'js': ['javascript'],
    'javascript': ['js'],
    'aws': ['amazon web services', 'amazon cloud'],
    'gcp': ['google cloud platform', 'google cloud'],
    'ts': ['typescript'],
    'typescript': ['ts'],
    'vb.net': ['visual basic .net', 'vbnet'],
    'reactjs': ['react.js', 'react'],
    'nodejs': ['node.js', 'node'],
    'vuejs': ['vue.js', 'vue'],
    't-sql': ['tsql', 'transact-sql'],
    'pl/sql': ['plsql'],
    'ms sql': ['sql server', 'mssql'],
    '.net': ['dotnet'],
    'net core': ['dotnet core']
}

def expand_skill_variants(skill_str):
    """Devuelve una lista con el skill original y todos sus sinónimos conocidos."""
    s = skill_str.strip().lower()
    variants = [s]
    # Comprobar si coincide exactamente con el diccionario
    if s in SKILL_SYNONYMS:
        variants.extend(SKILL_SYNONYMS[s])
    # Opcional: si contiene el acrónimo rodeado de espacios o al final/principio
    # Pero para no complicar en exceso el algoritmo y generar falsos positivos, usamos mach exacto.
    for key, syn_list in SKILL_SYNONYMS.items():
        if key in s.split():  # si la palabra exacta "pwc" está dentro del string del candidato
            variants.extend(syn_list)
    return list(set(variants))

# --- FUNCIONES DE SOPORTE ---
def format_list(val):
    if not val: return []
    try:
        items = json.loads(val)
        if isinstance(items, list): return items
        return [val]
    except:
        return [val]

def format_fecha_ingreso(fecha_str):
    """Devuelve HTML con la fecha de ingreso coloreada según antigüedad."""
    if not fecha_str or str(fecha_str).lower() in ('null', 'none', ''):
        return ""
    try:
        from datetime import date
        ingreso = date.fromisoformat(str(fecha_str)[:10])
        hoy = date.today()
        años = (hoy - ingreso).days / 365.25
        fecha_fmt = ingreso.strftime("%d/%m/%Y")
        if años > 5:
            return f'<span style="color:#CC0000;font-weight:600;">📅 Ingresado: {fecha_fmt} ⚠️ Perfil antiguo</span>'
        elif años > 2:
            return f'<span style="color:#E8500A;font-weight:600;">📅 Ingresado: {fecha_fmt} ⚠️</span>'
        else:
            return f'<span style="color:#555555;">📅 Ingresado: {fecha_fmt}</span>'
    except Exception:
        return ""


def get_folders():
    base = _APP_DIR / "TECNOY-Seleccion RRHH" / "01_ACTIVOS"
    if not base.exists(): return []
    folders = []
    for p in base.rglob('*'):
        if p.is_dir() and not p.name.startswith('_'):
            folders.append(str(p.relative_to(base.parent).as_posix()))
    return sorted(list(set(folders)))

def folder_filter_mask(series, folders):
    """Acepta carpeta_origen aunque esté almacenada como nombre corto o como ruta completa.
    Cubre la inconsistencia histórica de la DB (pipeline antiguo vs actual).
    """
    folder_last = {f.split('/')[-1] for f in folders}
    return series.isin(folders) | series.isin(folder_last) | series.apply(
        lambda c: any(c == f.split('/')[-1] for f in folders) if c else False
    )

def generate_excel_download(df, is_ranking=False):
    export_df = pd.DataFrame()
    export_df['Nombre'] = df['nombre']
    export_df['Título profesional'] = df['titulo_profesional']
    export_df['Nivel seniority'] = df['nivel_seniority']
    export_df['Años de experiencia'] = df['años_experiencia_total']
    export_df['Email'] = df['email']
    export_df['Teléfono'] = df['telefono']
    export_df['Skills técnicas'] = df['skills_tecnicas'].apply(lambda x: ", ".join(format_list(x)) if isinstance(x, str) else "")
    export_df['LinkedIn'] = df['linkedin']
    export_df['Carpeta/Especialidad'] = df['carpeta_origen']
    
    if is_ranking:
        export_df['% Match'] = df['match_percent']
        export_df['Skills coincidentes'] = df['matched_skills'].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False, sheet_name='Candidatos')
        
        # Auto-ajustar ancho de columnas
        worksheet = writer.sheets['Candidatos']
        for i, col in enumerate(export_df.columns):
            # Encontrar la longitud máxima de datos en la columna
            max_len = max(export_df[col].astype(str).map(len).max(), len(str(col))) + 2
            # Limitar a un ancho razonable (ej. máx 60 caracteres)
            if max_len > 60: max_len = 60
            
            # Obtener la letra de la columna para openpyxl
            import openpyxl
            col_letter = openpyxl.utils.get_column_letter(i + 1)
            worksheet.column_dimensions[col_letter].width = max_len
    
    return buffer.getvalue()

# --- LÓGICA DE BÚSQUEDA ---
def hybrid_search(query, folders, seniorities, min_experience):
    db = get_db_connection()
    chroma = get_chroma_client()
    
    collection = chroma.get_collection("candidatos_cv_v2")
    
    # 1. Sqlite Keyword Search
    sql = "SELECT id, nombre, email, telefono, linkedin, carpeta_origen, archivo_origen, ruta_completa, nivel_seniority, años_experiencia_total, skills_tecnicas, resumen_profesional, fecha_ingreso FROM candidatos WHERE 1=1"
    params = []
    
    if query:
        # Simple text search over skills and summary
        sql += " AND (skills_tecnicas LIKE ? OR resumen_profesional LIKE ? OR nombre LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])
    
    if folders:
        placeholders = ",".join(["?" for _ in folders])
        sql += f" AND carpeta_origen IN ({placeholders})"
        params.extend(folders)
        
    if seniorities:
        placeholders = ",".join(["?" for _ in seniorities])
        sql += f" AND LOWER(nivel_seniority) IN ({placeholders})"
        params.extend([s.lower() for s in seniorities])
        
    sql += " AND años_experiencia_total >= ?"
    params.append(min_experience)
    
    df_sql = pd.read_sql_query(sql, db, params=params)
    
    # 2. ChromaDB Semantic Search
    results_chroma = []
    if query:
        emb_resp = client_openai.embeddings.create(
            input=[query],
            model="text-embedding-3-small"
        )
        query_embedding = emb_resp.data[0].embedding
        
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=100
        )
        if response['ids']:
            ids = [int(i) for i in response['ids'][0]]
            results_chroma = ids
            
    # Combine (Union of IDs)
    sql_ids = set(df_sql['id'].tolist())
    chroma_ids = set(results_chroma)
    
    # If query exists, we might want to prioritize intersection or union?
    # User said "Combina ambos resultados eliminando duplicados".
    combined_ids = sql_ids.union(chroma_ids) if query else sql_ids
    
    if not combined_ids:
        return pd.DataFrame()
        
    # Get final detaills for intersection/union
    placeholders = ",".join(["?" for _ in combined_ids])
    final_sql = f"SELECT * FROM candidatos WHERE id IN ({placeholders})"
    df_final = pd.read_sql_query(final_sql, db, params=list(combined_ids))
    
    # Re-apply filters to Chroma results that might not have matched the SQL where
    if folders:
        df_final = df_final[folder_filter_mask(df_final['carpeta_origen'], folders)]
    if seniorities:
        df_final = df_final[df_final['nivel_seniority'].str.lower().isin([s.lower() for s in seniorities])]
    df_final = df_final[df_final['años_experiencia_total'] >= min_experience]

    return df_final

def ranking_by_offer(offer_text, folders, seniorities, min_experience, n_show):
    chroma = get_chroma_client()
    collection = chroma.get_collection("candidatos_cv_v2")
    reranker = load_reranker()
    db = get_db_connection()
    
    # 0. Extraer keywords + detectar idioma + traducir si inglés (una sola llamada gpt-4o-mini)
    extract_prompt = (
        "Analiza esta oferta de trabajo y devuelve un JSON con exactamente estas claves:\n"
        "- \"lang\": idioma de la oferta (\"es\" o \"en\")\n"
        "- \"keywords_orig\": tecnologías, herramientas y lenguajes clave separados por comas. "
        "Si hay acrónimos con nombres alternativos (ej. PWC→PowerCenter, K8s→Kubernetes) inclúyelos también.\n"
        "- \"keywords_es\": si lang=\"en\", los mismos términos traducidos/adaptados al español; "
        "si lang=\"es\", idéntico a keywords_orig.\n"
        "Devuelve SOLO el JSON, sin markdown.\n"
        f"Oferta:\n{offer_text}"
    )
    keyword_resp = client_openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": extract_prompt}],
        temperature=0
    )
    raw = keyword_resp.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
        offer_lang = parsed.get("lang", "es")
        offer_skills_str = parsed.get("keywords_orig", "")
        keywords_es_str = parsed.get("keywords_es", offer_skills_str)
    except Exception:
        offer_lang = "es"
        offer_skills_str = raw
        keywords_es_str = raw

    offer_skills = [s.strip().lower() for s in offer_skills_str.split(',') if s.strip()]
    enriched_offer_text = offer_text + "\n\nPalabras clave técnicas requeridas extras: " + offer_skills_str

    # 1. Semantic retrieval — dual query si la oferta está en inglés
    is_english = offer_lang == "en" and keywords_es_str != offer_skills_str
    if is_english:
        # Dos embeddings en una sola llamada a la API (batch nativo)
        emb_resp = client_openai.embeddings.create(
            input=[enriched_offer_text, keywords_es_str],
            model="text-embedding-3-small"
        )
        emb_en = emb_resp.data[0].embedding
        emb_es = emb_resp.data[1].embedding
        # Una sola llamada a ChromaDB con ambos embeddings (100 por query → hasta 200 únicos)
        response = collection.query(
            query_embeddings=[emb_en, emb_es],
            n_results=100
        )
        if not response['ids'] or not response['ids'][0]:
            return []
        # Combinar y deduplicar: resultados EN primero, luego los nuevos de ES
        seen: dict = {}
        for i, id_ in enumerate(response['ids'][0]):
            if id_ not in seen:
                seen[id_] = response['documents'][0][i]
        for i, id_ in enumerate(response['ids'][1]):
            if id_ not in seen:
                seen[id_] = response['documents'][1][i]
        candidate_ids = [int(i) for i in seen.keys()]
        documents = list(seen.values())
    else:
        emb_resp = client_openai.embeddings.create(
            input=[enriched_offer_text],
            model="text-embedding-3-small"
        )
        response = collection.query(
            query_embeddings=[emb_resp.data[0].embedding],
            n_results=200
        )
        if not response['ids'] or not response['ids'][0]:
            return []
        candidate_ids = [int(i) for i in response['ids'][0]]
        documents = response['documents'][0]

    _dbg_log = _APP_DIR / "logs" / "debug_ranking.txt"
    def _dbg(msg):
        with open(_dbg_log, "a", encoding="utf-8") as _f:
            _f.write(msg + "\n")

    _dbg(f"[DEBUG] IDs ChromaDB top 10: {candidate_ids[:10]}")

    # 2. Get details and filter
    placeholders = ",".join(["?" for _ in candidate_ids])
    df = pd.read_sql_query(f"SELECT * FROM candidatos WHERE id IN ({placeholders})", db, params=candidate_ids)

    _dbg(f"[DEBUG] Candidatos en df: {len(df)}")
    _dbg(f"[DEBUG] 5143 en df: {5143 in df['id'].values}")
    if 5143 in df['id'].values:
        row5143 = df[df['id'] == 5143].iloc[0]
        _dbg(f"[DEBUG] carpeta_origen de 5143: {repr(row5143['carpeta_origen'])}")
    _dbg(f"[DEBUG] folders filtro: {folders}")

    if folders:
        df = df[folder_filter_mask(df['carpeta_origen'], folders)]
    if seniorities:
        df = df[df['nivel_seniority'].str.lower().isin([s.lower() for s in seniorities])]
    df = df[df['años_experiencia_total'] >= min_experience]

    # Filter out empty names
    df = df[df['nombre'].notna()]
    df = df[df['nombre'].str.strip() != '']
    df = df[df['nombre'].str.lower() != 'null']

    _dbg(f"[DEBUG] Candidatos tras filtros: {len(df)}")
    _dbg(f"[DEBUG] 5143 tras filtros: {5143 in df['id'].values}")

    if df.empty:
        return []

    # 3. Reranking
    passages = []
    for _, row in df.iterrows():
        # Build passage for reranker
        passages.append(f"Candidate: {row['nombre']}. Seniority: {row['nivel_seniority']}. Skills: {row['skills_tecnicas']}. Summary: {row['resumen_profesional']}")

    pairs = [[offer_text, p] for p in passages]
    scores = reranker.predict(pairs)

    df['rerank_score'] = scores
    df = df.sort_values(by='rerank_score', ascending=False)

    _dbg(f"[DEBUG] 5143 en ranking final: {5143 in df['id'].values}")
    
    # Extract experience required from offer
    exp_prompt = f"Busca en esta oferta de trabajo los años mínimos de experiencia requeridos. Devuelve SOLO un número entero (ejemplo: si dice 'Más de 5 años' devuelve 5, si dice 'cinco años' devuelve 5). Si no se especifica experiencia, devuelve 0.\nOferta:\n{offer_text}"
    exp_resp = client_openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": exp_prompt}],
        temperature=0
    )
    try:
        # Busca el primer número en la respuesta (por si acaso GPT añade texto)
        found_nums = re.findall(r'\d+', exp_resp.choices[0].message.content)
        offer_exp_req = int(found_nums[0]) if found_nums else 0
    except:
        offer_exp_req = min_experience
    if offer_exp_req == 0:
        offer_exp_req = min_experience
        
    # 4. Keyword and Experience Match calculation
    # (Las variantes en 'offer_skills' ya fueron extraídas al principio para enriquecer el vector de ChromaDB)
    
    def calculate_match_details(row_skills_str):
        if not offer_skills: 
            return 0, [], offer_skills
        candidate_skills = [s.strip().lower() for s in format_list(row_skills_str)]
        matched_list = []
        missing_list = []
        for req in offer_skills:
            req_variants = expand_skill_variants(req)
            matched = False
            for cs in candidate_skills:
                cs_variants = expand_skill_variants(cs)
                # Solo emparejar si coinciden exactamente (usando las variantes del diccionario)
                # O si cv está dentro de rv PERO como palabra entera para evitar ("R" dentro de "Servicenow")
                for rv in req_variants:
                    for cv in cs_variants:
                        if cv == rv:
                            matched = True
                            break
                        # Si es un substring pero largo y delimitado por espacios para evitar fallos (ej. "React" dentro de "React Native")
                        elif len(cv) > 2 and len(rv) > 2:
                            import re
                            # Comprobar si cv es una palabra independiente dentro de rv
                            if re.search(r'\b' + re.escape(cv) + r'\b', rv) or re.search(r'\b' + re.escape(rv) + r'\b', cv):
                                # Evitar que Java matchee JavaScript
                                if not (cv == 'java' and rv == 'javascript') and not (cv == 'javascript' and rv == 'java'):
                                    matched = True
                                    break
                    if matched:
                        break
            
            if matched:
                matched_list.append(req)
            else:
                missing_list.append(req)
        pct = (len(matched_list) / len(offer_skills)) * 100 if offer_skills else 0
        return pct, matched_list, missing_list
        
    match_data = df['skills_tecnicas'].apply(calculate_match_details)
    df['keyword_match_pct'] = [d[0] for d in match_data]
    df['matched_skills'] = [d[1] for d in match_data]
    df['missing_skills'] = [d[2] for d in match_data]
    df['total_offer_skills'] = len(offer_skills)
    
    # Experience per skill bonus
    def calc_skill_exp_bonus(row):
        bonus = 0
        exp_dict = {}
        try:
            val = row['años_experiencia_por_skill']
            if val and str(val).lower() != 'null':
                exp_dict = json.loads(val)
        except:
            pass
            
        matched = row.get('matched_skills', [])
        req_years = offer_exp_req if offer_exp_req > 0 else 1 # default 1 year if not specified
        
        skill_exp_texts = []
        for ms in matched:
            # Find if this skill is in the dict
            for k, v in exp_dict.items():
                if ms in k.lower() or k.lower() in ms:
                    try:
                        years = float(v)
                        if years >= req_years:
                            bonus += 5
                        skill_exp_texts.append(f"{k.title()}: {int(years)} años")
                        break
                    except:
                        pass
        return bonus, " | ".join(skill_exp_texts)
        
    skill_exp_data = df.apply(calc_skill_exp_bonus, axis=1)
    df['skill_exp_bonus'] = [d[0] for d in skill_exp_data]
    df['skill_exp_text'] = [d[1] for d in skill_exp_data]
    
    # Senior title bonus logic
    def calc_senior_bonus(row):
        title = str(row['titulo_profesional']).lower()
        if row['años_experiencia_total'] >= 15:
            if any(req in title for req in offer_skills):
                return 5
        return 0
    df['senior_title_bonus'] = df.apply(calc_senior_bonus, axis=1)
    
    # Calculate Experience Score
    def calc_exp_score(cand_exp):
        if offer_exp_req == 0:
            return 100
        if cand_exp >= offer_exp_req:
            return 100
        ratio = cand_exp / offer_exp_req
        if ratio >= 0.5:
            return ratio * 100
        else:
            return ratio * 50 # Penalize heavily if < 50%
            
    df['exp_score_pct'] = df['años_experiencia_total'].apply(calc_exp_score)
    df['offer_exp_req'] = offer_exp_req
    
    # Combine: 50% keyword match + 35% semantic score + 15% experience + Bonuses
    df['base_match'] = (df['keyword_match_pct'] * 0.50) + \
                       (df['rerank_score'].apply(lambda x: min(100, max(0, 50 + x*10))) * 0.35) + \
                       (df['exp_score_pct'] * 0.15) + \
                       df['skill_exp_bonus'] + df['senior_title_bonus']
                       
    # Apply Seniority Bonus/Penalty
    def apply_seniority_modifier(row):
        score = row['base_match']
        sen = str(row['nivel_seniority']).lower()
        if 'senior' in sen or 'lead' in sen:
            score += 10
        elif 'junior' in sen or 'becario' in sen:
            score -= 10
            
        # Penalizar a los Falsos Juniors (perfiles con excesiva experiencia que no aceptarían un salario junior)
        # Si el usuario filtra por Junior explícitamente y el candidato tiene > 3 años, lo hundimos en el ranking
        is_searching_junior = seniorities and any('junior' in s.lower() or 'becario' in s.lower() for s in seniorities)
        if is_searching_junior and row['años_experiencia_total'] > 3:
            score -= 40
            
        return max(0, min(100, score)) # Cap between 0 and 100
        
    df['match_percent'] = df.apply(apply_seniority_modifier, axis=1)
    df['match_percent'] = df['match_percent'].astype(int)
    
    df = df.sort_values(by='match_percent', ascending=False)
    
    # Deduplicate by candidate name (keeping the one with highest match_percent)
    _dbg(f"[DEBUG] 5143 antes de dedup: {5143 in df['id'].values}")
    if 5143 in df['id'].values:
        _pos = df['id'].tolist().index(5143)
        _dbg(f"[DEBUG] posicion de 5143 antes de dedup: {_pos + 1}/{len(df)}")
    df = df.drop_duplicates(subset=['nombre'], keep='first')
    _dbg(f"[DEBUG] 5143 tras dedup: {5143 in df['id'].values}")
    _dbg(f"[DEBUG] n_show={n_show}, total={len(df)}")
    return df.head(n_show)

# --- UI SIDEBAR --- (REMOVIDO)
# Se han eliminado los filtros globales para integrarlos en la pestaña específica.

# --- UI MAIN ---
col1, col2 = st.columns([1, 5])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=150)
with col2:
    st.markdown('<h1 class="main-header" style="margin-top: 10px;">Centro de Recursos Humanos Tecnoy</h1>', unsafe_allow_html=True)

st.markdown("### Filtros Globales de Búsqueda")

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    sel_folders = st.multiselect("Especialidad / Carpeta", options=get_folders())
with col_f2:
    sel_seniority = st.multiselect("Nivel Seniority", options=["becario", "junior", "mid", "senior", "lead"])
with col_f3:
    min_exp = st.slider("Años experiencia mínimos", 0, 20, 0)

col_f4, col_f5 = st.columns([1, 2])
with col_f4:
    _antiguedad_opts = {"Todos": 0, "Máx. 1 año": 1, "Máx. 2 años": 2, "Máx. 5 años": 5}
    _antiguedad_label = st.selectbox("Antigüedad máxima del CV", options=list(_antiguedad_opts.keys()))
    max_antiguedad = _antiguedad_opts[_antiguedad_label]
    
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["🔍 Búsqueda por palabras clave", "📋 Ranking por Oferta", "📄 Generar MK File", "⚙️ Mantenimiento"])

with tab1:
    
    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input("Escribe tecnologías o habilidades...", placeholder="Ej: Java, Spring Boot, React")
    with col2:
        st.write("##")
        search_btn = st.button("BUSCAR 🚀")
        
    if search_btn:
        with st.spinner("Buscando candidatos..."):
            st.session_state['keyword_results'] = hybrid_search(search_query, sel_folders, sel_seniority, min_exp)
            
    if 'keyword_results' in st.session_state:
        results = st.session_state['keyword_results']
        if max_antiguedad > 0 and 'fecha_ingreso' in results.columns:
            from datetime import date as _date
            cutoff = _date.today().replace(year=_date.today().year - max_antiguedad).isoformat()
            results = results[results['fecha_ingreso'].fillna('9999-12-31') >= cutoff]
        if results.empty:
            st.info("No se han encontrado candidatos con esos criterios. Prueba a ampliar los filtros.")
        else:
            st.write(f"Se han encontrado **{len(results)}** candidatos.")
            
            excel_data = generate_excel_download(results, is_ranking=False)
            filename = f"Informe_Candidatos_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
            st.download_button(
                label="📥 Descargar Informe de Candidatos",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            for _, row in results.iterrows():
                skills = format_list(row['skills_tecnicas'])
                
                # Usar la ruta absoluta exacta alojada en la BD para evitar problemas con subcarpetas
                app_dir = Path(__file__).parent
                ruta_cv = app_dir / str(row['ruta_completa'])
                url_cv = f"file:///{str(ruta_cv).replace(chr(92), '/')}"
                
                with st.container():
                    st.markdown(f"""
                        <div class="candidato-card">
                            <div class="candidato-header">
                                <span>{row['nombre']}</span>
                                <span class="seniority-badge">{row['nivel_seniority'].upper() if row['nivel_seniority'] else 'N/D'}</span>
                            </div>
                            <div style="color: #666666; margin-bottom: 0.5rem;">
                                <b>{row['años_experiencia_total']} años de experiencia</b> | {row['titulo_profesional'] or ''}
                            </div>
                            <div style="margin-bottom: 0.5rem;">
                                {" ".join([f'<span class="skill-match">{s}</span>' if search_query.lower() in s.lower() else f'<span class="skill-missing">{s}</span>' for s in skills[:15]])}
                            </div>
                            <div style="font-size: 0.9rem; color: #2D2D2D; margin-bottom: 0.4rem;">
                                📍 <b>Carpeta:</b> {row['carpeta_origen']} | 📧 {row['email'] or 'N/D'} | 📞 {row['telefono'] or 'N/D'}
                            </div>
                            <div style="font-size: 0.85rem; margin-bottom: 1rem;">
                                {format_fecha_ingreso(row.get('fecha_ingreso'))}
                            </div>
                    """, unsafe_allow_html=True)

                    if st.button(f"📄 Abrir PDF/Word Original", key=f"btn_kw_{row['id']}"):
                        try: os.startfile(str(ruta_cv))
                        except Exception as e: st.error(f"Error abriendo documento local: {e}")
                            
                    st.markdown("</div>", unsafe_allow_html=True)

with tab2:
    offer_desc = st.text_area("Pega aquí la descripción completa de la oferta", height=200, placeholder="Buscamos un desarrollador Java con 5 años de experiencia...")
    n_results = st.slider("Número de candidatos a mostrar", 10, 50, 30)
    rank_btn = st.button("BUSCAR CANDIDATOS POR MATCH 🎯")
    
    if rank_btn and offer_desc:
        if len(offer_desc.strip()) < 15:
            st.error("El texto es demasiado corto. Por favor introduce al menos tecnologías o un título de puesto.")
        else:
            is_valid = True
            with st.spinner("Validando la oferta..."):
                val_prompt = f"Valida si el siguiente texto es una descripción de oferta de trabajo o una lista de características/tecnologías válidas para buscar perfiles. Devuelve 'SI' si es válido (ej. contiene un rol, tecnologías o requisitos). Devuelve 'NO' si es código fuente, spam o algo sin sentido.\nTexto:\n{offer_desc[:2000]}"
                try:
                    val_resp = client_openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": val_prompt}],
                        temperature=0
                    )
                    val_content = val_resp.choices[0].message.content.strip().upper()
                    is_valid = val_content.startswith("SI") or val_content.startswith("SÍ")
                except:
                    is_valid = True
            
            if not is_valid:
                st.error("El texto no parece una oferta de trabajo o una lista de tecnologías válida. Por favor, introduce más detalles o características del puesto.")
            else:
                with st.spinner("Calculando ranking semántico..."):
                    # Pasamos los filtros globales a la IA (si el usuario los deja vacíos, la IA usa sus propias reglas)
                    st.session_state['ranking_results'] = ranking_by_offer(offer_desc, sel_folders, sel_seniority, min_exp, n_results)

    if 'ranking_results' in st.session_state:
        ranking = st.session_state['ranking_results']
        if max_antiguedad > 0 and 'fecha_ingreso' in ranking.columns:
            from datetime import date as _date
            cutoff = _date.today().replace(year=_date.today().year - max_antiguedad).isoformat()
            ranking = ranking[ranking['fecha_ingreso'].fillna('9999-12-31') >= cutoff]
        if len(ranking) == 0:
            st.warning("No hay candidatos que coincidan con la oferta y los filtros aplicados.")
        else:
            excel_data = generate_excel_download(ranking, is_ranking=True)
            filename = f"Informe_Candidatos_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
            st.download_button(
                label="📥 Descargar Informe de Candidatos",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            for idx, (_, row) in enumerate(ranking.iterrows()):
                # Simple match logic for UI
                match_percent = row.get('match_percent', 0)
                medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else ""
                
                matched_html = " ".join([f'<span class="skill-match">{s.title()}</span>' for s in row.get('matched_skills', [])])
                missing_html = " ".join([f'<span class="skill-missing">{s.title()}</span>' for s in row.get('missing_skills', [])])
                skills_desc = f"<b>{len(row.get('matched_skills', []))}/{row.get('total_offer_skills', 0)} skills coincidentes:</b><br>{matched_html} {missing_html}"
                
                if row.get('skill_exp_text'):
                    skills_desc += f"<br><span style='font-size: 0.85rem; color: #666666;'><i>Experiencia extraída: {row['skill_exp_text']}</i></span>"
                
                # Usar la ruta absoluta exacta alojada en la BD para evitar problemas con subcarpetas
                app_dir = Path(__file__).parent
                ruta_cv = app_dir / str(row['ruta_completa'])
                url_cv = f"file:///{str(ruta_cv).replace(chr(92), '/')}"
                
                with st.container():
                    st.markdown(f"""
                        <div class="candidato-card">
                            <div class="candidato-header">
                                <span><span class="medal">{medal}</span>#{idx+1} {row['nombre']}</span>
                                <span class="match-score">{match_percent}%</span>
                            </div>
                            <div style="margin-bottom: 1rem;">
                                <div style="height: 8px; width: 100%; background-color: #E0E0E0; border-radius: 4px;">
                                    <div style="height: 100%; width: {match_percent}%; background-color: #E8500A; border-radius: 4px;"></div>
                                </div>
                            </div>
                            <div style="margin-bottom: 0.5rem;">
                                {skills_desc}
                            </div>
                            <p style="font-size: 0.95rem; color: #2D2D2D;"><i>{row['resumen_profesional'][:300]}...</i></p>
                            <div style="margin-bottom: 0.5rem; color: {'#E8500A' if row['años_experiencia_total'] < row.get('offer_exp_req', 0) else '#2D2D2D'}; font-weight: 500;">
                                <b>Seniority:</b> {row['nivel_seniority']} | <b>Experiencia:</b> {row['años_experiencia_total']} años (Requerida: {row.get('offer_exp_req', 0)} años)
                            </div>
                            <div style="font-size: 0.9rem; color: #2D2D2D; margin-top: 0.5rem; margin-bottom: 0.4rem;">
                                {" | ".join(filter(None, [
                                    f"🔗 <a href='{row['linkedin']}' target='_blank'>LinkedIn</a>" if row.get('linkedin') and str(row.get('linkedin')).lower() not in ['null', 'n/d', 'none'] else "",
                                    f"📧 {row['email']}" if row.get('email') and str(row.get('email')).lower() not in ['null', 'n/d', 'none'] else "",
                                    f"📞 {row['telefono']}" if row.get('telefono') and str(row.get('telefono')).lower() not in ['null', 'n/d', 'none'] else "",
                                    f"📍 {row['carpeta_origen']}"
                                ]))}
                            </div>
                            <div style="font-size: 0.85rem; margin-bottom: 1rem;">
                                {format_fecha_ingreso(row.get('fecha_ingreso'))}
                            </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"📄 Abrir PDF/Word Original", key=f"btn_rank_{row['id']}"):
                        try: os.startfile(str(ruta_cv))
                        except Exception as e: st.error(f"Error abriendo documento local: {e}")
                            
                    st.markdown("</div>", unsafe_allow_html=True)
                            
with tab3:
    st.markdown("### Generador Automático de Master Files")
    
    modo_gen = st.radio("Elige el modo de procesamiento:", ["📄 Un solo currículum (Carga manual)", "📁 Procesamiento Masivo (Carpeta local)"], horizontal=True)

    if modo_gen == "📄 Un solo currículum (Carga manual)":
        st.write("Sube o arrastra aquí cualquier currículum (PDF o Word) para automatizar la extracción estructurada gracias a la Inteligencia Artificial de OpenAI y maquetarlo al vuelo sobre la plantilla oficial de la empresa.")
        
        uploaded_cv = st.file_uploader("Arrastra aquí o pulsa para buscar en el ordenador", type=["pdf", "docx", "doc"])
        
        if uploaded_cv is not None:
            if st.button("🚀 Extraer Datos y Generar MK File", type="primary"):
                with st.spinner("Leyendo original, extrayendo historial (IA) y maquetando Master File corporativo (aprox 5-10 segs)..."):
                    file_bytes = uploaded_cv.read()
                    filename = uploaded_cv.name
                    
                    raw_text = cv_exporter.extract_text_from_bytes(file_bytes, filename)
                    
                    if raw_text == "ERROR_UNSUPPORTED_DOC":
                        st.error("El formato antiguo `.doc` de Word de 1997-2003 no está soportado por el extractor automático. Por favor, abre el documento en Word y guárdalo como archivo `.docx` o expórtalo a PDF antes de subirlo.")
                    elif raw_text.startswith("ERROR_CRASH:"):
                        st.error(f"Error interno grave al intentar leer el archivo: {raw_text.replace('ERROR_CRASH:', '')}")
                    elif raw_text.strip():
                        parsed_json = cv_exporter.parse_cv_to_corporate_json(raw_text)
                        if parsed_json:
                            # Extraer nombre directamente del parseo hecho por la IA y forzar Capitalización (Ej Carlos Galache Urda)
                            cand_name = parsed_json.get('nombre_candidato') or 'Candidato Desconocido'
                            safe_name = cand_name.title().replace(' ', '_')
                            out_filename = f"MKF_{safe_name}.docx"
                            
                            docx_bytes = cv_exporter.generate_corporate_cv_docx(None, parsed_json)
                            
                            # Crear el directorio base si no existe DENTRO de TECNOY-Seleccion RRHH
                            mk_dir = Path(__file__).parent / "TECNOY-Seleccion RRHH" / "MK File Tecnoy"
                            mk_dir.mkdir(exist_ok=True, parents=True)
                            
                            out_path = mk_dir / out_filename
                            
                            # Logic para no sobreescribir archivos existentes y crear versiones (1), (2)...
                            base_name, extension = os.path.splitext(out_filename)
                            counter = 1
                            while out_path.exists():
                                out_filename = f"{base_name} ({counter}){extension}"
                                out_path = mk_dir / out_filename
                                counter += 1
                            
                            # Guardar en disco duro de forma local (silencioso para el usuario)
                            try:
                                with open(out_path, "wb") as f:
                                    f.write(docx_bytes.getbuffer())
                                st.success(f"✅ ¡Master File generado con éxito! Guardado automáticamente en la carpeta local: `{mk_dir.name}/{out_filename}`")
                                
                                # Opcional manual download
                                st.download_button(
                                    label="📥 (Opcional) Descargar también copia por el navegador",
                                    data=docx_bytes,
                                    file_name=out_filename,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                )
                            except PermissionError:
                                st.error(f"❌ No se ha podido guardar automáticamente porque el archivo `{out_filename}` ya lo tienes abierto en Microsoft Word u otro programa. Por favor, ciérralo e inténtalo de nuevo, o usa el botón de descarga manual de abajo.")
                                st.download_button(
                                    label="📥 Forzar descarga por navegador",
                                    data=docx_bytes,
                                    file_name=out_filename,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                )
                            except Exception as e:
                                st.error(f"Error inesperado guardando el archivo en el disco: {e}")
                        else:
                            st.error("La IA no pudo estructurar el CV. El archivo original podría estar dañado o vacío.")
                    else:
                        st.error("No se pudo extraer texto puro del documento original. Puede que sea un PDF de imágenes escaneadas sin capas de texto.")
    else:
        st.write("Indica la ruta completa a una carpeta en tu ordenador. Se procesarán todos los PDFs y Words que contenga y se guardarán en una subcarpeta nueva.")
        
        # Uso de tkinter para abrir dialog de carpeta nativo
        col_btn, col_txt = st.columns([1, 3])
        with col_btn:
            if st.button("📂 Examinar Carpeta..."):
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.wm_attributes('-topmost', 1)
                folder_sel = filedialog.askdirectory(master=root)
                root.destroy()
                if folder_sel:
                    st.session_state['batch_folder_path'] = folder_sel
                    
        current_folder = st.session_state.get('batch_folder_path', '')
        
        with col_txt:
            folder_path = st.text_input("Ruta de la carpeta:", value=current_folder, placeholder="C:\\ruta\\a\\tu\\carpeta")
            # Actualizamos de vuelta el text input a la sesión
            if folder_path != current_folder:
                st.session_state['batch_folder_path'] = folder_path
                
        if st.button("🚀 Procesar Carpeta Completa", type="primary"):
            if not folder_path or not os.path.isdir(folder_path):
                st.error("La ruta introducida no es válida o no existe. Por favor, introduce una ruta a una carpeta válida de tu ordenador.")
            else:
                folder_p = Path(folder_path)
                out_dir = folder_p / "Convertidos Tecnoy"
                
                # Buscar archivos a convertir
                valid_extensions = {'.pdf', '.docx', '.doc'}
                files_to_process = [f for f in folder_p.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions]
                
                if not files_to_process:
                    st.warning("No se han encontrado archivos PDF, DOCX o DOC en la carpeta indicada.")
                else:
                    out_dir.mkdir(exist_ok=True, parents=True)
                    st.write(f"Iniciando el procesamiento de {len(files_to_process)} currículums. Esto puede llevar unos minutos...")
                    
                    progress_bar = st.progress(0, text="Preparando procesamiento...")
                    success_count = 0
                    errors = []
                    
                    for i, file_p in enumerate(files_to_process):
                        filename = file_p.name
                        progress_bar.progress(i / len(files_to_process), text=f"Convirtiendo ({i+1}/{len(files_to_process)}): {filename} ...")
                        
                        try:
                            file_bytes = file_p.read_bytes()
                            raw_text = cv_exporter.extract_text_from_bytes(file_bytes, filename)
                            
                            if raw_text == "ERROR_UNSUPPORTED_DOC":
                                errors.append(f"**{filename}**: Formato antiguo `.doc` no soportado.")
                            elif raw_text.startswith("ERROR_CRASH:"):
                                errors.append(f"**{filename}**: Error grave - {raw_text.replace('ERROR_CRASH:', '')}")
                            elif raw_text.strip():
                                parsed_json = cv_exporter.parse_cv_to_corporate_json(raw_text)
                                if parsed_json:
                                    cand_name = parsed_json.get('nombre_candidato') or 'Candidato Desconocido'
                                    safe_name = cand_name.title().replace(' ', '_')
                                    out_filename = f"MKF_{safe_name}.docx"
                                    
                                    docx_bytes = cv_exporter.generate_corporate_cv_docx(None, parsed_json)
                                    
                                    out_path = out_dir / out_filename
                                    base_name, extension = os.path.splitext(out_filename)
                                    counter = 1
                                    while out_path.exists():
                                        out_filename = f"{base_name} ({counter}){extension}"
                                        out_path = out_dir / out_filename
                                        counter += 1
                                        
                                    with open(out_path, "wb") as f:
                                        f.write(docx_bytes.getbuffer())
                                    
                                    success_count += 1
                                else:
                                    errors.append(f"**{filename}**: La IA no pudo estructurar correctamente el CV.")
                            else:
                                errors.append(f"**{filename}**: No se pudo extraer texto (quizás sea PDF escaneado).")
                        except Exception as e:
                            errors.append(f"**{filename}**: Excepción inesperada - {e}")
                            
                    # Finalizar UI
                    progress_bar.progress(1.0, text="¡Procesamiento masivo finalizado!")
                    
                    st.success(f"✅ **Se han convertido y maquetado con éxito {success_count} currículums.**")
                    st.info(f"📂 Puedes encontrarlos en: `{out_dir}`")
                    
                    if errors:
                        st.warning(f"Se omitieron o fallaron {len(errors)} archivos:")
                        for err in errors:
                            st.write(f"- {err}")

with tab4:
    st.markdown("### ⚙️ Mantenimiento del Sistema")
    st.markdown("---")

    _app_dir = Path(__file__).parent

    # --- Calcular datos comunes usados en ambas columnas ---
    _nuevos_dir = _app_dir / "NUEVOS_INGRESOS"
    _valid_exts = {'.pdf', '.docx', '.doc'}
    _pending_files = sorted(
        [f for f in _nuevos_dir.rglob("*") if f.is_file() and f.suffix.lower() in _valid_exts],
        key=lambda f: f.name
    ) if _nuevos_dir.exists() else []

    col_proc, col_stats = st.columns([1, 1], gap="large")

    # ── Columna izquierda: Procesar nuevos CVs ───────────────────────────────
    with col_proc:
        st.markdown("#### 🔄 Procesar Nuevos CVs Manualmente")

        if _pending_files:
            st.warning(f"📥 **{len(_pending_files)} CV(s)** pendientes en NUEVOS_INGRESOS")
            with st.expander("Ver archivos pendientes"):
                for pf in _pending_files[:20]:
                    st.write(f"• {pf.name}")
                if len(_pending_files) > 20:
                    st.write(f"… y {len(_pending_files) - 20} más")
        else:
            st.success("✅ No hay CVs pendientes en NUEVOS_INGRESOS.")

        if st.button("🔄 Procesar NUEVOS_INGRESOS ahora", type="primary", key="btn_batch"):
            _db_conn = get_db_connection()
            _count_before = pd.read_sql_query("SELECT COUNT(*) as n FROM candidatos", _db_conn).iloc[0]['n']

            # Buscar el python del venv; si no existe usar el python actual
            _python_exe = _app_dir / "venv" / "Scripts" / "python.exe"
            if not _python_exe.exists():
                _python_exe = Path(sys.executable)
            _batch_script = _app_dir / "batch_weekly.py"

            _log_output = ""
            with st.spinner(f"Procesando {len(_pending_files)} CV(s)… (puede tardar varios minutos)"):
                try:
                    _proc = subprocess.run(
                        [str(_python_exe), str(_batch_script)],
                        cwd=str(_app_dir),
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=900
                    )
                    _log_output = _proc.stdout or ""
                    if _proc.stderr:
                        _log_output += "\n--- ERRORES ---\n" + _proc.stderr
                except subprocess.TimeoutExpired:
                    _log_output = "[!] Tiempo límite superado (15 min). Revisa los logs manualmente."
                except Exception as _e:
                    _log_output = f"[!] Error lanzando batch_weekly.py: {_e}"

            # Recontar tras el proceso (la conexión cacheada puede necesitar un cursor fresco)
            _count_after = pd.read_sql_query("SELECT COUNT(*) as n FROM candidatos", _db_conn).iloc[0]['n']
            _nuevos = _count_after - _count_before

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("CVs encontrados", len(_pending_files))
            col_b.metric("Candidatos antes", _count_before)
            col_c.metric("Candidatos ahora", _count_after, delta=f"+{_nuevos}" if _nuevos > 0 else str(_nuevos))

            st.text_area("📋 Log del procesamiento:", value=_log_output, height=300)

    # ── Columna derecha: Estadísticas ────────────────────────────────────────
    with col_stats:
        st.markdown("#### 📊 Estadísticas del Sistema")

        _db_conn = get_db_connection()

        # Total candidatos
        _total = pd.read_sql_query("SELECT COUNT(*) as n FROM candidatos", _db_conn).iloc[0]['n']
        st.metric("Total candidatos en base de datos", _total)

        st.markdown("")

        # Distribución por carpeta/especialidad
        _df_dist = pd.read_sql_query(
            """SELECT carpeta_origen AS Especialidad,
                      COUNT(*) AS Candidatos
               FROM candidatos
               GROUP BY carpeta_origen
               ORDER BY Candidatos DESC""",
            _db_conn
        )
        st.markdown("**Distribución por especialidad:**")
        st.dataframe(_df_dist, use_container_width=True, hide_index=True)

        st.markdown("")

        # Fecha del último procesamiento batch (por el log más reciente)
        _logs_dir = _app_dir / "logs"
        _last_batch_str = "Sin registros"
        if _logs_dir.exists():
            _log_files = sorted(_logs_dir.glob("Informe_Batch_*.txt"), reverse=True)
            if _log_files:
                # El nombre tiene formato Informe_Batch_YYYYMMDD_HHMMSS.txt
                _raw = _log_files[0].stem.replace("Informe_Batch_", "")
                try:
                    _dt = datetime.datetime.strptime(_raw, "%Y%m%d_%H%M%S")
                    _last_batch_str = _dt.strftime("%d/%m/%Y a las %H:%M")
                except Exception:
                    _last_batch_str = _raw

        col_x, col_y = st.columns(2)
        col_x.markdown(f"**Último batch:**  \n`{_last_batch_str}`")
        col_y.markdown(f"**CVs pendientes:**  \n`{len(_pending_files)} archivo(s)`")

# --- FOOTER ---
st.markdown("---")
st.markdown("<div style='text-align: center; color: #666666;'>© 2026 Centro de Recursos Humanos Tecnoy | Inteligencia Artificial Aplicada</div>", unsafe_allow_html=True)
