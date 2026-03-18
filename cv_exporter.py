import os
import json
import base64
import io
import fitz  # PyMuPDF
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.resolve() / ".env")
client_openai = OpenAI()

def extract_text_from_file(file_path: str) -> str:
    ext = file_path.lower()
    text = ""
    if ext.endswith(".pdf"):
        try:
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()
        except: pass
    elif ext.endswith(".docx") or ext.endswith(".doc"):
        try:
            doc = Document(file_path)
            paragraphs_text = "\n".join([p.text for p in doc.paragraphs])
            tables_text = "\n".join([p.text for table in doc.tables for row in table.rows for cell in row.cells for p in cell.paragraphs])
            text = paragraphs_text + "\n" + tables_text
        except: pass
    return text

def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extract raw text directly from an in-memory byte stream, bypassing the disk."""
    ext = filename.lower()
    text = ""
    try:
        if ext.endswith(".pdf"):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                text += page.get_text()
            doc.close()
        elif ext.endswith(".docx"):
            doc = Document(io.BytesIO(file_bytes))
            paragraphs_text = "\n".join([p.text for p in doc.paragraphs])
            tables_text = "\n".join([p.text for table in doc.tables for row in table.rows for cell in row.cells for p in cell.paragraphs])
            text = paragraphs_text + "\n" + tables_text
        elif ext.endswith(".doc"):
            return "ERROR_UNSUPPORTED_DOC"
    except Exception as e:
        print(f"Error extracting memory file: {e}")
        return f"ERROR_CRASH: {str(e)}"
    return text

def parse_cv_to_corporate_json(raw_text: str):
    """
    Given the raw text of a candidate CV, ask OpenAI to extract all
    relevant historical fields strictly matching the corporate MF format.
    """
    prompt = f"""
INSTRUCCIÓN CRÍTICA Y OBLIGATORIA:
Eres un experto analista de recursos humanos. Dada la siguiente extracción en texto plano de un Curriculum Vitae, debes extraer y organizar rígidamente la información en un objeto JSON puro.

MUY IMPORTANTE SOBRE "conocimientos_especificos":
Lee TODO el historial de proyectos del candidato. Extrae ABSOLUTAMENTE TODAS las tecnologías, herramientas, lenguajes, frameworks, bases de datos y sistemas que se mencionen en CUALQUIERA de sus trabajos o proyectos.
NO RESUMAS. Todo lo que encuentres (ej. Java, Spring, O365, Azure, SAP, Jira, SQL, Python, Active Directory, Windows Server, etc.) DEBE ser clasificado e incluido obligatoriamente dentro del objeto "conocimientos_especificos" al principio del JSON. Si no lo haces, el currículum quedará inválido.

Tu salida debe ser ÚNICAMENTE un JSON válido (sin marcas de markdown de código, ni ```json, solo el JSON raw).

Estructura JSON exacta requerida:
{{
  "nombre_candidato": "Nombre completo de la persona dueña del currículum",
  "titulo_profesional": "Su titular profesional principal basado en su experiencia y nombre de puesto más senior. Ej. Analista Programador Java",
  "niveles_intervencion": ["lista", "de", "viñetas", "de", "responsabilidades genéricas que asume este tipo de perfil (basado en lo que lees de experiencia)"],
  "areas_dominio": ["lista", "de", "viñetas", "de", "sus areas funcionales de dominio (ej. Desarrollo web, Bases de datos, Gestión de proyectos)"],
  "conocimientos_especificos": {{
    "Sistemas Operativos": "Ej. Windows, Linux",
    "Lenguajes": "Ej. Java, C#, Python",
    "Desarrollo WEB": "Ej. JavaEE, ASP .NET MVC",
    "Herramientas CI/CD / DevOps": "Ej. Docker, Jenkins",
    "Bases de datos": "Ej. SQL Server, MySQL",
    "ERP / CRM": "Ej. SAP, Salesforce, Microsoft ERP",
    "Herramientas corporativas / Cloud": "Ej. O365, Azure, AWS, Active Directory, AutoCAD 2010",
    "Ingeniería / Diseño Industrial": "Ej. AutoCAD 2010, Diseño 3D, SolidWorks, APQP",
    "Automatización / Control": "Ej. PLC's, Sistemas hidráulicos",
    "Metodologías / Procesos": "Ej. Lean, Kaizen, SCRUM, Ósmosis inversa, Micro y Nano Filtración"
  }},
  "instruccion_critica_2_antiolvido": "Comprueba DOS VECES que has incluido: Diseño 3D, Moldes de inyección, Prensas, PLC's, Sistemas hidráulicos, SCRUM, APQP, Ósmosis inversa, Piping, P&ID, Lean, Kaizen si aparecen en cualquier zona del texto. NO RESUMAS.",
  "sectores_economicos": ["lista", "de", "sectores", "donde ha trabajado (ej. Institución educativa, Banca, Retail)"],
  "proyectos_realizados": [
    {{
      "empresa": "Nombre de la empresa o cliente puro",
      "fechas": "Rango de fechas o años (ej. MARZO 2023 – PRESENTE, o 2022, o 8 meses)",
      "proyecto": "Título del proyecto, cargo ocupado o rol",
      "objetivo": "Párrafo breve explicando qué se hizo, sistema, toma de requerimientos, etc",
      "niveles_intervencion": ["lista", "de", "tareas", "específicas", "en ESTE proyecto"],
      "entorno_tecnologico": "Tecnologías, lenguajes y frameworks separados por coma"
    }}
  ],
  "formacion_academica": [
    "Lista de líneas de formación académica",
    "Sigue este formato: Titulación en [Institución] [Fechas]"
  ],
  "idiomas": [
    "Inglés   :   Nivel Intermedio",
    "Español  :   Nativo"
  ],
  "cursos_certificaciones": [
    "Especialización en Machine Learning (2021)",
    "Scrum Master Certified"
  ]
}}

Si algún dato no existe en el CV, deja el array vacío [] o el objeto vacío {{}}, pero MANTÉN LA ESTRUCTURA COMPLETA SIEMPRE.
Es vital el orden cronológico INVERSO (del más reciente al más antiguo) en proyectos_realizados.
Trata de ser profesional, técnico y redactar/resumir con un tono corporativo.

TEXTO DEL CURRICULUM:
--------------------
{raw_text[:12000]}
"""

    response = client_openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful HR data extraction assistant. You only respond in strictly parsable JSON format matching the schema requested."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    
    response_text = response.choices[0].message.content.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
        
    try:
        return json.loads(response_text)
    except Exception as e:
        print(f"Error parsing JSON from LLM: {e}")
        return None

def add_header_logo(doc):
    logo_path = Path(__file__).parent / "logo.png"
    if logo_path.exists():
        header = doc.sections[0].header
        htable = header.add_table(1, 1, Inches(6))
        htable.autofit = True
        hcell = htable.rows[0].cells[0]
        hc_p = hcell.paragraphs[0]
        hc_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hrun = hc_p.add_run()
        hrun.add_picture(str(logo_path), width=Inches(2.0))

def add_footer(doc):
    footer = doc.sections[0].footer
    
    # Use a table to have left logo and right text
    p_orig = footer.paragraphs[0]
    p_orig.text = ""
    
    table = footer.add_table(1, 2, Inches(6))
    table.autofit = True
    cells = table.rows[0].cells
    
    p_left = cells[0].paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Busca todas las fotos que se llamen applus algo (ej. "applus1.png", "applus2.png")
    applus_logos = sorted(Path(__file__).parent.glob("applus*.png"))
    if applus_logos:
        run_img = p_left.add_run()
        for logo_path in applus_logos:
            run_img.add_picture(str(logo_path), width=Inches(0.6))
            run_img.add_text("   ") # Pequeño espaciador entre logos
    
    p_right = cells[1].paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    
    # We can fake the page numbering in Word manually if needed, but keeping it simple
    run = p_right.add_run("Reproducción prohibida")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(128, 128, 128)

def generate_corporate_cv_docx(candidate_row, parsed_data) -> io.BytesIO:
    doc = Document()
    
    # 1. Estilos Globales
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(10)
    font.color.rgb = RGBColor(0, 0, 0)
    
    add_header_logo(doc)
    add_footer(doc)
    
    cand_name = candidate_row.get('nombre', '') if candidate_row else parsed_data.get('nombre_candidato', '')
    cand_title = candidate_row.get('titulo_profesional', '') if candidate_row else parsed_data.get('titulo_profesional', 'Perfil Profesional')
    
    # Candidate Full Name top left
    p_name = doc.add_paragraph()
    run_name = p_name.add_run(cand_name.title() if cand_name else "")
    run_name.font.size = Pt(9)
    run_name.font.italic = True
    run_name.font.color.rgb = RGBColor(128, 128, 128)
    
    # Spacing
    doc.add_paragraph()
    
    # MAIN TITLE (Role)
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = p_title.add_run(cand_title)
    run_title.font.size = Pt(16)
    run_title.font.bold = True
    
    doc.add_paragraph() # Spacer

    # Helper function for underlined headers with full-width bottom border
    def add_section_header(title_text):
        p = doc.add_paragraph()
        run = p.add_run(title_text)
        run.font.size = Pt(12)
        
        # Add full-width bottom border (Underline stretches to margins)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '12')  # 1.5 pt
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '000000')
        pBdr.append(bottom)
        pPr.append(pBdr)
        
        p.paragraph_format.space_after = Pt(8)

    # Helper function for generic square bullets
    def add_bullet_list(items):
        for item in items:
            p = doc.add_paragraph()
            p.add_run("▪\t" + item)
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.first_line_indent = Inches(-0.25)
            p.paragraph_format.tab_stops.add_tab_stop(Inches(0.25))
            p.paragraph_format.space_after = Pt(3)

    # 1. Niveles de intervención
    intervencion = parsed_data.get("niveles_intervencion", [])
    if intervencion:
        add_section_header("Niveles de intervención")
        add_bullet_list(intervencion)
        doc.add_paragraph()

    # 2. Áreas de dominio (Incluye adentro Conocimientos Específicos)
    areas = parsed_data.get("areas_dominio", [])
    if areas:
        add_section_header("Áreas de dominio")
        add_bullet_list(areas)
        doc.add_paragraph()

    # 3. Conocimientos específicos (As a nested section purely with text underline)
    raw_conocimientos = parsed_data.get("conocimientos_especificos", {})
    # Remove empty pairs
    conocimientos = {k: v for k, v in raw_conocimientos.items() if v and isinstance(v, str) and str(v).lower() not in ["none", "null", "n/d", "n/a", ""]}
    
    # Remove "Sistemas Operativos: Windows" if that's the only one listed
    keys_to_drop = []
    for k, v in conocimientos.items():
        if "sistema" in k.lower() and "operativo" in k.lower():
            if v.strip().lower() == "windows":
                keys_to_drop.append(k)
    for k in keys_to_drop:
        del conocimientos[k]
    
    if conocimientos:
        p_ce = doc.add_paragraph()
        r_ce = p_ce.add_run("Conocimientos específicos")
        r_ce.font.size = Pt(11)
        r_ce.font.bold = True
        p_ce.paragraph_format.space_after = Pt(6)
        
        # Using tabs to align the colon and values like the template table
        for k, v in conocimientos.items():
            p = doc.add_paragraph()
            p.paragraph_format.tab_stops.add_tab_stop(Inches(1.8))
            p.paragraph_format.tab_stops.add_tab_stop(Inches(2.0))
            p.add_run("▪\t" + k + "\t:\t" + str(v))
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.first_line_indent = Inches(-0.25)
            p.paragraph_format.space_after = Pt(2)
        doc.add_paragraph()

    # 4. Sectores Económicos
    sectores = parsed_data.get("sectores_economicos", [])
    if sectores:
        add_section_header("Sectores Económicos")
        add_bullet_list(sectores)
        doc.add_paragraph()

    # 5. Proyectos Realizados
    proyectos = parsed_data.get("proyectos_realizados", [])
    if proyectos:
        add_section_header("Proyectos Realizados:")
        
        for proj in proyectos:
            table = doc.add_table(rows=1, cols=2)
            table.autofit = True
            cells = table.rows[0].cells
            
            # Company
            p_comp = cells[0].paragraphs[0]
            # Extra spacing at the top of the project block except the first one
            p_comp.paragraph_format.space_before = Pt(6) 
            r_comp = p_comp.add_run("- " + proj.get("empresa", "PROYECTO INDEPENDIENTE").upper())
            r_comp.font.bold = True
            
            # Dates
            p_date = cells[1].paragraphs[0]
            p_date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            r_date = p_date.add_run(proj.get("fechas", "").upper())
            r_date.font.bold = True
            
            # Project/Role
            p_proj = doc.add_paragraph()
            r_pref = p_proj.add_run("Proyecto: ")
            r_pref.font.underline = True
            r_pref.font.bold = True
            
            # Add Dash before the project name as requested by the user
            p_proj.add_run("- " + proj.get("proyecto", ""))
            p_proj.paragraph_format.space_after = Pt(6)
            
            # Objetivo
            if proj.get("objetivo"):
                p_obj = doc.add_paragraph()
                r_obj = p_obj.add_run("Objetivo: ")
                r_obj.font.bold = True
                p_obj.add_run(proj.get("objetivo", ""))
            
            # Niveles intervencion del proyecto
            proj_interv = proj.get("niveles_intervencion", [])
            if proj_interv:
                p_niv = doc.add_paragraph()
                r_niv = p_niv.add_run("Niveles de Intervención:")
                r_niv.font.bold = True
                add_bullet_list(proj_interv)
                
            # Entorno Tecnologico (conditional)
            entorno = proj.get("entorno_tecnologico", "")
            if isinstance(entorno, list):
                entorno = ", ".join(entorno)
            if entorno and str(entorno).lower() not in ["none", "null", "n/d", "n/a", ""]:
                p_ent = doc.add_paragraph()
                r_ent = p_ent.add_run("Entorno tecnológico: ")
                r_ent.font.bold = True
                p_ent.add_run(str(entorno))
                p_ent.paragraph_format.space_after = Pt(12)
            else:
                # Add default margin if missing
                if proj_interv or proj.get("objetivo"):
                    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # 6. Formación Académica (Includes Languages and Courses as nested)
    formacion = parsed_data.get("formacion_academica", [])
    idiomas = parsed_data.get("idiomas", [])
    cursos = parsed_data.get("cursos_certificaciones", [])
    
    if formacion or idiomas or cursos:
        add_section_header("Formación:")
        
        if formacion:
            for f in formacion:
                p = doc.add_paragraph()
                # Split by "en" to try bolding the title
                parts = f.split(" en ", 1)
                if len(parts) == 2:
                    r1 = p.add_run(parts[0] + " en ")
                    r1.font.bold = True
                    p.add_run(parts[1])
                else:
                    p.add_run(f)
                p.paragraph_format.space_after = Pt(4)
            doc.add_paragraph()
            
        if idiomas:
            p_id = doc.add_paragraph()
            r_id = p_id.add_run("Idiomas:")
            r_id.font.underline = True
            r_id.font.size = Pt(10)
            p_id.paragraph_format.space_after = Pt(4)
            add_bullet_list(idiomas)
            doc.add_paragraph()
            
        if cursos:
            p_cur = doc.add_paragraph()
            r_cur = p_cur.add_run("Conocimientos Complementarios:")
            r_cur.font.underline = True
            r_cur.font.size = Pt(10)
            p_cur.paragraph_format.space_after = Pt(4)
            add_bullet_list(cursos)

    # Save to BytesIO
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
