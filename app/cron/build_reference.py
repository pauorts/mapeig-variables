import pandas as pd
import numpy as np
import re
import os
import gc
import pickle
import hashlib
import zipfile
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine, text
import faiss
from sentence_transformers import SentenceTransformer
import unicodedata
import logging

from sqlalchemy.orm import Session
from app.db.database import SessionLocal

# Configuración de logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


USUARIO = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("HOST")
PUERTO = os.getenv("PUERTO")
BBDD = os.getenv("BBDD_snomed")

conexion_url = f"postgresql://{USUARIO}:{PASSWORD}@{HOST}:{PUERTO}/{BBDD}"
engine_snomed  = create_engine(conexion_url)

NODO_RAIZ = '138875005'

# ── Embedding cache — _v3 (model changed, recompute on first run) ───────────
EMB_CACHE_DIR      = os.getenv("EMB_CACHE_DIR", "app/embedding_cache")
SNOMED_EMB_CACHE   = os.path.join(EMB_CACHE_DIR, "snomed_emb.npy")
SNOMED_META_CACHE  = os.path.join(EMB_CACHE_DIR, "snomed_meta.pkl")
OPENEHR_EMB_CACHE  = os.path.join(EMB_CACHE_DIR, "openehr_emb.npy")
OPENEHR_META_CACHE = os.path.join(EMB_CACHE_DIR, "openehr_meta.pkl")

# Carpeta donde están los Excel
SOCMIC_FOLDER  = os.getenv("SOCMIC_FOLDER", "/app/SOCMIC_FOLDER")
ARCHIVO_ZIP   = os.getenv("ARCHIVO_ZIP",   "/app/archetypes_2026_01_29-15_34_10.zip")

MODELO_NOMBRE = os.getenv("MODELO_NOMBRE", "FremyCompany/BioLORD-2023-M")
modelo = SentenceTransformer(MODELO_NOMBRE)

# ── Memory-conscious encoding config for low-RAM machines ───────────────────
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
# Chunked encoding for huge corpora (SNOMED ~270k); avoids holding all
# intermediate tensors at once. None = let sentence-transformers decide.
EMBED_CHUNK_SIZE = int(os.getenv("EMBED_CHUNK_SIZE", "5000"))

# ── Thresholds (will be re-tuned on the 146-variable gold set) ──────────────
UMBRAL_SNOMED_HIGH    = float(os.getenv("UMBRAL_SNOMED_HIGH",    "0.75"))
UMBRAL_SNOMED_SUGGEST = float(os.getenv("UMBRAL_SNOMED_SUGGEST", "0.65"))
UMBRAL_OE_HIGH        = float(os.getenv("UMBRAL_OE_HIGH",        "0.75"))
UMBRAL_OE_SUGGEST     = float(os.getenv("UMBRAL_OE_SUGGEST",     "0.65"))

TOP_K_SNOMED  = 30   # FAISS candidates retrieved per SOCMIC variable for SNOMED
TOP_K_ARQ     = 8    # archetype candidates per variable
TOP_K_ELEM    = 8    # elements within an archetype

CATEGORIAS_SNOMED = {
    'Clinical finding (finding)',
    'Observable entity (observable entity)',
    'Procedure (procedure)',
    'Body structure (body structure)',
    'Substance (substance)',
    'Staging and scales (staging scale)',
    'Qualifier value (qualifier value)',
}

COLUMNAS_DB = [
    "variable", "grupo", "tipo_variable", "descripcion_socmic",
    "unidad_ucum", "unidad_openehr",
    "snomed_id", "snomed_term", "snomed_categoria", "icd10_code",
    "snomed_origen_mapeo", "snomed_score",
    "arquetipo_id", "at_code",
    "openehr_nombre", "openehr_descripcion", "openehr_tipo_dato",
    "openehr_categoria", "openehr_tipo_var",
    "validado", "activo", "notas_validacion",
]

USE_LLM = False

# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDING HELPERS (memory-conscious for <8 GB CPU-only machines)
# ═══════════════════════════════════════════════════════════════════════════════

def _int_str(x):
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return None


def _texts_hash(texts: list) -> str:
    h = hashlib.sha256()
    h.update(MODELO_NOMBRE.encode("utf-8"))
    for t in texts:
        h.update(t.encode("utf-8", errors="replace"))
    return h.hexdigest()


def _load_emb_cache(emb_path, meta_path, textos):
    if not (os.path.exists(emb_path) and os.path.exists(meta_path)):
        return None
    try:
        with open(meta_path, "rb") as f:
            meta = pickle.load(f)
        if meta.get("hash") != _texts_hash(textos):
            print("  Cache obsoleta, recomputando...")
            return None
        emb = np.load(emb_path)
        print(f"  Cache: {os.path.basename(emb_path)} ({emb.shape[0]} vectores)")
        return emb
    except Exception as e:
        print(f"  Error cache: {e}")
        return None


def _save_emb_cache(emb, meta_path, emb_path, textos):
    os.makedirs(EMB_CACHE_DIR, exist_ok=True)
    np.save(emb_path, emb)
    with open(meta_path, "wb") as f:
        pickle.dump({"hash": _texts_hash(textos)}, f)
    print(f"  Cache guardada: {os.path.basename(emb_path)}")


def _encode_chunked(textos, show_progress=True):
    """
    Encode a list of texts in chunks of EMBED_CHUNK_SIZE so peak memory stays low.
    Returns a contiguous float32 array. After each chunk we run gc.collect() to
    release intermediate tensors quickly — critical for SNOMED's 270k entries.
    """
    if not textos:
        # build an empty matrix of the right hidden size by encoding a dummy
        dim = modelo.get_sentence_embedding_dimension()
        return np.zeros((0, dim), dtype=np.float32)

    n = len(textos)
    chunk = EMBED_CHUNK_SIZE
    if n <= chunk:
        raw = modelo.encode(
            textos,
            batch_size=EMBED_BATCH_SIZE,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
            normalize_embeddings=False,  # we L2-normalise once at the end
        )
        return np.ascontiguousarray(raw, dtype=np.float32)

    parts = []
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        if show_progress:
            print(f"  chunk {start:>7d} → {end:>7d}  ({end/n:.0%})")
        raw = modelo.encode(
            textos[start:end],
            batch_size=EMBED_BATCH_SIZE,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        parts.append(np.ascontiguousarray(raw, dtype=np.float32))
        gc.collect()
    return np.vstack(parts)


def _embed(textos, emb_path, meta_path):
    """Encode with cache; returns L2-normalised float32 matrix."""
    emb = _load_emb_cache(emb_path, meta_path, textos)
    if emb is None:
        print(f"  Computando {len(textos)} embeddings...")
        emb = _encode_chunked(textos, show_progress=True)
        _save_emb_cache(emb, meta_path, emb_path, textos)
    else:
        emb = np.ascontiguousarray(emb, dtype=np.float32)
    if emb.ndim == 1:
        emb = emb.reshape(1, -1)
    faiss.normalize_L2(emb)
    return emb


def _embed_nocache(textos):
    emb = _encode_chunked(textos, show_progress=False)
    if emb.ndim == 1:
        emb = emb.reshape(1, -1)
    faiss.normalize_L2(emb)
    return emb

# ═══════════════════════════════════════════════════════════════════════════════
# SNOMED LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

def cargar_descripciones_activas():
    print("  Extrayendo descripciones SNOMED...")
    return pd.read_sql("""
        SELECT \"conceptId\", term, \"typeId\"
        FROM snomedct_irbd_full.glsd_description
        WHERE active = '1' AND \"languageCode\" = 'en'
    """, engine_snomed)

def cargar_relaciones_inferidas():
    print("  Extrayendo relaciones SNOMED...")
    return pd.read_sql("""
        SELECT \"sourceId\", \"destinationId\", \"typeId\"
        FROM snomedct_irbd_full.glsi_relationshipinferred
        WHERE active = 1 AND \"typeId\" = '116680003'
    """, engine_snomed)

def cargar_mapeo_icd10():
    print("  Extrayendo mapeos ICD-10...")
    df = pd.read_sql("""
        SELECT DISTINCT ON (\"referencedComponentId\")
            \"referencedComponentId\" AS conceptid,
            \"mapTarget\" AS codigo_icd10
        FROM snomedct_irbd_full.iefr_extendedmap
        WHERE active = 1 AND \"mapTarget\" IS NOT NULL
        ORDER BY \"referencedComponentId\", \"mapGroup\", \"mapPriority\"
    """, engine_snomed)
    return df.drop_duplicates(subset=['conceptid'], keep='first')

def encontrar_categoria_principal(nodo, relaciones_dict, memo):
    camino, visitados = [], set()
    actual = nodo
    while True:
        if actual in memo:
            res = memo[actual]
            for n in camino: memo[n] = res
            return res
        if actual not in relaciones_dict or actual in visitados:
            return None
        visitados.add(actual)
        camino.append(actual)
        padres = relaciones_dict[actual]
        if NODO_RAIZ in padres:
            for n in camino: memo[n] = actual
            return actual
        actual = padres[0]

def cargar_snomed() -> pd.DataFrame:
    df_desc = cargar_descripciones_activas()
    df_rel  = cargar_relaciones_inferidas()
    df_icd  = cargar_mapeo_icd10()

    df_desc['conceptId']    = df_desc['conceptId'].apply(_int_str)
    df_rel['sourceId']      = df_rel['sourceId'].apply(_int_str)
    df_rel['destinationId'] = df_rel['destinationId'].apply(_int_str)
    df_icd['conceptid']     = df_icd['conceptid'].apply(_int_str)

    df_desc = df_desc.dropna(subset=['conceptId'])
    df_rel  = df_rel.dropna(subset=['sourceId', 'destinationId'])

    df_unicos = df_desc[
        (df_desc.typeId == 900000000000003001) | (df_desc.typeId == 900000000000013009)
    ].sort_values('typeId').drop_duplicates(subset='conceptId', keep='first').copy()

    relaciones_dict = df_rel.groupby('sourceId')['destinationId'].apply(list).to_dict()
    memo = {}
    df_unicos['id_categoria'] = df_unicos['conceptId'].apply(
        lambda n: encontrar_categoria_principal(n, relaciones_dict, memo)
    )

    df_cat   = df_unicos[['conceptId', 'term']].rename(columns={'conceptId': 'id_categoria', 'term': 'nombre_categoria'})
    df_final = pd.merge(df_unicos, df_cat, on='id_categoria', how='left')[['conceptId', 'term', 'nombre_categoria']]
    df_final = pd.merge(df_final, df_icd, left_on='conceptId', right_on='conceptid', how='left').drop(columns=['conceptid'])

    print(f"  SNOMED: {len(df_final)} conceptos")
    return df_final

def limpiar_snomed(texto) -> str:
    if pd.isna(texto): return ""
    return re.sub(r'\s*\([^)]*\)$', '', str(texto).strip()).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# openEHR ARCHETYPE PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parsear_xml_openehr(xml_content, tipo_variable="unknown"):
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]

    nodo_id      = root.find('.//archetype_id/value')
    archetype_id = nodo_id.text if nodo_id is not None else "Desconocido"

    categoria = "Desconocida"
    if archetype_id != "Desconocido":
        partes = archetype_id.split('.')
        if len(partes) > 1:
            categoria = partes[1].replace('_', ' ').capitalize()

    info_estructural = {}
    for elem in root.iter():
        n_id = elem.find('node_id')
        if n_id is not None and n_id.text and n_id.text.startswith('at'):
            codigo_at = n_id.text
            tipo_var, unidades_var = None, []
            for attr in elem.findall('attributes'):
                rm_name = attr.find('rm_attribute_name')
                if rm_name is not None and rm_name.text == 'value':
                    for child in attr.findall('children'):
                        t_name = child.find('rm_type_name')
                        if t_name is not None:
                            tipo_var = t_name.text
                        for unit_node in child.findall('.//units'):
                            if unit_node.text and unit_node.text not in unidades_var:
                                unidades_var.append(unit_node.text)
            if tipo_var:
                info_estructural[codigo_at] = {
                    'tipo': tipo_var,
                    'unidades': ", ".join(unidades_var) if unidades_var else None
                }

    mapeos_snomed = {}
    for binding in root.findall('.//ontology/term_bindings'):
        if 'snomed' in binding.attrib.get('terminology', '').lower():
            for item in binding.findall('items'):
                codigo_at = item.attrib.get('code')
                nodo_snomed = item.find('.//code_string')
                if codigo_at and nodo_snomed is not None:
                    mapeos_snomed[codigo_at] = nodo_snomed.text

    filas = []
    term_defs = (
        root.find('.//ontology/term_definitions[@language="en"]')
        or root.find('.//ontology/term_definitions')
    )
    if term_defs is not None:
        for item_term in term_defs.findall('items'):
            codigo_at = item_term.attrib.get('code')
            nombre, descripcion = "", ""
            for sub in item_term.findall('items'):
                if sub.attrib.get('id') == 'text':        nombre    = sub.text or ""
                elif sub.attrib.get('id') == 'description': descripcion = sub.text or ""
            if "@ internal @" in descripcion or not nombre:
                continue
            datos     = info_estructural.get(codigo_at, {})
            tipo_final = datos.get('tipo')
            snomed_code = mapeos_snomed.get(codigo_at)
            if not tipo_final:
                if not snomed_code: continue
                tipo_final = "VALOR_CATEGORICO"
            filas.append({
                'Categoria':       categoria,
                'Tipo_Variable':   tipo_variable,
                'Variable_ID':     codigo_at,
                'Nombre_Variable': nombre,
                'Tipo_Dato':       tipo_final,
                'Unidades':        datos.get('unidades'),
                'Descripcion':     descripcion,
                'SNOMED_Code':     snomed_code,
                'Arquetipo_ID':    archetype_id,
            })
    return filas

def procesar_zip_a_dataframe(ruta_zip) -> pd.DataFrame:
    carpetas_utiles = ['observation', 'cluster', 'action', 'evaluation']
    todas = []
    with zipfile.ZipFile(ruta_zip, 'r') as zf:
        xmls = [
            f for f in zf.namelist()
            if any(c in f.lower().split('/') for c in carpetas_utiles) and f.endswith('.xml')
        ]
        for ruta in xmls:
            tipo = next((c for c in carpetas_utiles if c in ruta.lower().split('/')), "unknown")
            contenido = zf.read(ruta).decode('utf-8')
            todas.extend(parsear_xml_openehr(contenido, tipo_variable=tipo))
    df = pd.DataFrame(todas) if todas else pd.DataFrame()
    n_bind = df['SNOMED_Code'].notna().sum() if not df.empty else 0
    print(f"  openEHR: {len(df)} elementos  |  {n_bind} con binding SNOMED explícito")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SOCMIC LOADER
# ═══════════════════════════════════════════════════════════════════════════════

# Diccionarios para unificar traducciones y errores tipográficos (basado en tus imágenes)
MAP_TIPO_VARIABLE = {
    "boleana": "booleana",
    "numeric": "numerica",
    "data": "fecha",
    "proporcio": "proporcion",
    "codi/text categorica": "codi/text",
    "hh:mm": "hora (hh:mm)"
}

MAP_ORIGEN_VARIABLE = {
    "registre": "registro",
    "regsitre": "registro",  # typo detectado
    "dispositiu": "dispositivo",
    "laboratori": "laboratorio",
    "calcul": "calculo",
    "derived": "derivado",
    "registre/dispositiu": "registro o dispositivo",
    "registre o dispositiu": "registro o dispositivo",
    "registro o dispositivo": "registro o dispositivo",
    "regsitre o dispoditiu": "registro o dispositivo", # typo complejo detectado
    "registre o automatico": "registro o automatico"
}

def normalizar_texto(texto: str, dicc_reemplazos: dict = None) -> str:
    """Normaliza el texto: quita acentos, unifica minúsculas, corrige typos y capitaliza."""
    if pd.isna(texto) or not isinstance(texto, str):
        return texto
    
    # 1. Quitar espacios en los extremos y convertir a minúsculas
    texto = texto.strip().lower()
    
    # 2. Eliminar acentos (Ej: 'Categòrica' -> 'categorica')
    texto = "".join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )
    
    # 3. Reemplazar usando el diccionario (Ej: 'registre' -> 'registro')
    if dicc_reemplazos and texto in dicc_reemplazos:
        texto = dicc_reemplazos[texto]
    
    # 4. Capitalizar la primera letra ('registro' -> 'Registro')
    # Nota: Si prefieres que 'codi/text' se mantenga tal cual, puedes 
    # añadir una condición, pero capitalize lo dejará como 'Codi/text'
    return texto.capitalize()

# def limpiar_texto_grupo(texto: str) -> str:
#     """Normaliza el texto: quita acentos, espacios extra y capitaliza de forma uniforme."""
#     if pd.isna(texto) or not isinstance(texto, str):
#         return texto
    
#     # 1. Quitar espacios en los extremos y convertir a minúsculas
#     texto = texto.strip().lower()
    
#     # 2. Eliminar acentos (NFD descompone caracteres como 'à' en 'a' + '`')
#     texto = "".join(
#         c for c in unicodedata.normalize('NFD', texto)
#         if unicodedata.category(c) != 'Mn'
#     )
    
#     # 3. Capitalizar la primera letra para que quede bonito (opcional)
#     return texto.capitalize()

def load_all_excels_from_folder(folder_path: str) -> pd.DataFrame:
    all_dfs = []
    files = [f for f in os.listdir(folder_path) if f.endswith((".xlsx", ".xls"))]
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos Excel en {folder_path}")
    print(f"📂 {len(files)} archivos Excel en {folder_path}")

    rename_map = {
        "Nom variable":  "variable",
        "ÀREA":          "grupo",
        "Tipus":         "tipo_variable",
        "Unidad (UCUM)": "unidad",
        "Descripció":    "descripcion",
        "Origen":        "origen_variable",
        "ID SNOMED":     "snomed_id",
    }

    for file in files:
        file_path = os.path.join(folder_path, file)
        print(f"\n📖 {file}")
        try:
            excel = pd.read_excel(file_path, sheet_name=None, dtype=str)
            base_dfs, categorias_df = [], None
            for sheet_name, df in excel.items():
                df.columns = df.columns.str.strip()
                available = [c for c in rename_map if c in df.columns]
                if len(available) >= 3:
                    sheet_df = df[available].rename(columns=rename_map)
                    sheet_df = sheet_df.dropna(subset=["variable"])
                    sheet_df = sheet_df[sheet_df["variable"].str.strip() != ""]
                    if not sheet_df.empty:
                        if "grupo" in sheet_df.columns:
                            sheet_df["grupo"] = sheet_df["grupo"].apply(lambda x: normalizar_texto(x))

                        if "tipo_variable" in sheet_df.columns:
                            sheet_df["tipo_variable"] = sheet_df["tipo_variable"].apply(lambda x: normalizar_texto(x, MAP_TIPO_VARIABLE))
                            
                        if "origen_variable" in sheet_df.columns:
                            sheet_df["origen_variable"] = sheet_df["origen_variable"].apply(lambda x: normalizar_texto(x, MAP_ORIGEN_VARIABLE))

                        sheet_df["_sheet"] = sheet_name
                        base_dfs.append(sheet_df)
                        print(f"  ✅ [principal]  {sheet_name!r:45s} → {len(sheet_df)} filas")
                    else:
                        print(f"  ⚠️ [vacía]      {sheet_name!r} omitida tras limpiar blancos")
                elif not available and df.shape[1] > 0:
                    categorias_df = df
            if base_dfs:
                file_df = pd.concat(base_dfs, ignore_index=True)
                if categorias_df is not None:
                    nuevas = []
                    for col in categorias_df.columns:
                        col_l = col.strip()
                        if col_l in file_df["variable"].values:
                            cats = categorias_df[col].dropna().unique().tolist()
                            if cats:
                                fila_base = file_df.loc[file_df["variable"] == col_l].iloc[0].to_dict()
                                for cat in cats:
                                    nueva = fila_base.copy()
                                    nueva["variable"] = f"{col_l} | {cat.strip()}"
                                    nuevas.append(nueva)
                    if nuevas:
                        file_df = pd.concat([file_df, pd.DataFrame(nuevas)], ignore_index=True)
                file_df = file_df.drop(columns=["_sheet"], errors="ignore")
                all_dfs.append(file_df)
        except Exception as e:
            print(f"  ⚠️ Error: {e}")

    if not all_dfs:
        raise ValueError("No se pudo cargar ningún Excel válido.")

    combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["variable"])
    print(f"\n🧩 Total: {len(combined)} variables únicas")
    return combined

def _clean_snomed(x):
    if pd.isnull(x) or str(x).strip() in ("", "nan", "None"): return None
    try: return str(int(float(x)))
    except (ValueError, TypeError): return None

def load_socmic(folder_path: str) -> pd.DataFrame:
    df = load_all_excels_from_folder(folder_path)
    df.columns = df.columns.str.strip()
    df["snomed_id"] = df["snomed_id"].apply(_clean_snomed) if "snomed_id" in df.columns else None
    for col in ["grupo", "tipo_variable", "unidad", "descripcion", "origen_variable"]:
        if col not in df.columns: df[col] = None
    print(f"  SOCMIC: {len(df)} variables  |  {df['snomed_id'].notna().sum()} con SNOMED en Excel")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT CONSTRUCTION FOR EMBEDDINGS
# ═══════════════════════════════════════════════════════════════════════════════
# Three text builders, one per role:
#   - SOCMIC variable   → concept-label query (used in Phase 1 and Phase 3b)
#   - SNOMED concept    → term-only document (Phase 1 and Phase 2)
#   - openEHR (arq, el) → '<archetype> :: <element>' (Phase 2 and Phase 3b)
# All are designed to be similar in shape (short concept labels) so cross-
# corpus cosine similarities are meaningful.

GENERIC_ELEMENT_NAMES = {
    'comment', 'comments', 'description', 'clinical description',
    'clinical interpretation', 'confounding factors', 'last updated',
    'method', 'system or structure examined', 'unknown', 'presence',
    'status', 'imaging findings', 'examination findings',
    'body structure', 'body site', 'impression', 'note', 'notes',
    'date', 'time', 'date/time', 'overall comment', 'multimedia',
    'extension', 'reference', 'narrative', 'parsable', 'identifier',
    'uri', 'no abnormality detected', 'no test result', 'unspecified',
    'other', 'remarks', 'no information', 'device',
}


def _tokens(s):
    return set(re.findall(r'\w{4,}', (s or '').lower()))


def socmic_query_text(row) -> str:
    """SOCMIC variable → concept-label string."""
    var  = str(row.get('variable',    '') or '').strip()
    desc = str(row.get('descripcion', '') or '').strip()
    # if not var:
    #     return desc[:120] if desc else ''
    # if not desc or desc.lower() == var.lower() or desc.lower() == 'nan':
    #     return var
    # new_tokens = _tokens(desc) - _tokens(var)
    return desc
    # return f"{var} | {desc}" if len(new_tokens) >= 1 else var


def snomed_doc_text(row) -> str:
    """SNOMED → label (FSN minus semantic-tag parens)."""
    return limpiar_snomed(row.get('term', ''))


def openehr_pair_text(arq_name: str, elem_name: str) -> str:
    """
    openEHR (archetype, element) → context-aware label.
    Examples:
      ('Blood pressure', 'Systolic')     -> 'Blood pressure :: Systolic'
      ('Body weight',    'Weight')        -> 'Body weight :: Weight'
      ('Heart rate',     'Rate')          -> 'Heart rate :: Rate'
      ('Blood pressure', 'Systolic BP')   -> 'Systolic BP'  (element subsumes archetype)
    """
    a = (arq_name or '').strip()
    e = (elem_name or '').strip()
    if not e: return a
    if not a: return e
    if a.lower() in e.lower(): return e          # element already names the concept
    if e.lower() in a.lower(): return a          # generic-named principal element
    return f"{a} :: {e}"

 
# ═══════════════════════════════════════════════════════════════════════════════
# ATTRIBUTE RE-RANKING
# ═══════════════════════════════════════════════════════════════════════════════
# Used only in Phase 1 (SOCMIC -> SNOMED) and Phase 3b fallback.
# Phase 2 (SNOMED -> openEHR) uses a different scorer — see that section.

# SOCMIC tipo_variable → compatible SNOMED top-level category
_TIPO_SNOMED = {
    'numerica':   {'observable': 1.0, 'finding': 0.5, 'procedure': 0.2,
                   'qualifier': 0.4, 'staging': 0.6, 'substance': 0.4,
                   'body structure': 0.1},
    'codi':       {'finding': 1.0, 'observable': 0.5, 'qualifier': 0.8,
                   'procedure': 0.4, 'staging': 0.8, 'substance': 0.9,
                   'body structure': 0.9},
    'text':       {'finding': 0.7, 'observable': 0.5, 'substance': 0.6,
                   'body structure': 0.6},
    'categorica': {'finding': 1.0, 'observable': 0.5, 'qualifier': 0.8,
                   'staging': 0.8, 'substance': 0.9, 'body structure': 0.9},
    'boolea':     {'finding': 1.0, 'observable': 0.6, 'qualifier': 0.5,
                   'body structure': 0.3, 'substance': 0.3},
    'data':       {'finding': 0.3, 'procedure': 0.3},
    'hora':       {'finding': 0.3, 'procedure': 0.3},
}

_ORIGEN_SNOMED = {
    'laboratorio':           {'observable': 1.0, 'substance': 0.9, 'finding': 0.5},
    'dispositivo':           {'observable': 1.0, 'finding': 0.4, 'body structure': 0.2},
    'observacion':           {'finding': 1.0, 'observable': 0.6, 'staging': 0.7,
                              'body structure': 0.7, 'substance': 0.5},
    'registro o automatico': {'finding': 0.8, 'observable': 0.6, 'substance': 0.7,
                              'body structure': 0.5},
    'registro o dispositivo':{'observable': 1.0, 'finding': 0.5, 'substance': 0.5},
    'derivado':              {'observable': 0.8, 'finding': 0.6},
    'calculo':               {'observable': 0.8, 'finding': 0.6},
}

# Unit→domain keyword rules (used by unit_compat)
_UNIT_RULES = [
    (('mmhg', 'mm hg', 'kpa'),        ('pressure', 'arterial', 'venous')),
    (('cmh2o', 'cmh₂o', 'cm h2o'),    ('pressure', 'cmh2o', 'airway')),
    (('kg', 'g'),                      ('weight', 'mass', 'body weight')),
    (('g/dl', 'g/l'),                  ('haemoglobin', 'hemoglobin', 'concentration')),
    (('%',),                           ('saturation', 'fraction', 'percent',
                                        'spo2', 'fio2', 'oxygen')),
    (('ml',),                          ('volume', 'output', 'fluid', 'urine')),
    (('l/min', 'ml/min', 'l/h'),       ('flow', 'rate', 'output', 'cardiac', 'minute')),
    (('/min', 'bpm'),                  ('rate', 'rhythm', 'frequency', 'pulse', 'respiratory')),
    (('°c', 'celsius', 'c'),           ('temperature',)),
    (('meq/l', 'mmol/l', 'mg/dl', 'μmol/l', 'umol/l'),
                                       ('concentration', 'level', 'sodium', 'potassium',
                                        'chloride', 'calcium', 'glucose', 'creatinine',
                                        'urea', 'lactate')),
    (('sec', 'seg', 'min', 'h', 'ms'), ('duration', 'time', 'interval')),
    (('cm', 'mm', 'm'),                ('length', 'diameter', 'height', 'depth')),
]


def _norm_attr(s):
    if pd.isna(s) or not isinstance(s, str): return ''
    s = s.strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    return s


def unit_compat(socmic_unit, target_text) -> float:
    u = _norm_attr(socmic_unit)
    t = (target_text or '').lower()
    if not u or u in ('_', 'none', 'nan'): return 0.0
    for unit_keys, term_keys in _UNIT_RULES:
        if any(k in u for k in unit_keys) and any(k in t for k in term_keys):
            return 1.0
    if u.replace(' ', '') in t.replace(' ', ''): return 0.7
    return 0.0


def _lookup_boost(attr_value, mapping, target_text):
    av = _norm_attr(attr_value)
    if not av: return 0.0
    submap = None
    for k, v in mapping.items():
        if k in av:
            submap = v; break
    if not submap: return 0.0
    tt = (target_text or '').lower()
    for k, boost in submap.items():
        if k in tt: return boost
    return 0.0


# Phase 1 composite score (SOCMIC vs SNOMED candidate)
W_SNOMED = dict(sim=0.65, tipo=0.15, origen=0.15, unit=0.05)


def score_snomed_candidate(socmic_row, candidate, sim):
    cat  = (candidate.get('nombre_categoria') or '').lower()
    term = (candidate.get('term') or '').lower()
    tipo_score   = _lookup_boost(socmic_row.get('tipo_variable'),    _TIPO_SNOMED,   cat)
    origen_score = _lookup_boost(socmic_row.get('origen_variable'),  _ORIGEN_SNOMED, cat)
    unit_score   = unit_compat(socmic_row.get('unidad'), term)
    score = (W_SNOMED['sim']    * float(sim)
           + W_SNOMED['tipo']   * tipo_score
           + W_SNOMED['origen'] * origen_score
           + W_SNOMED['unit']   * unit_score)
    return min(score, 1.0)


# ── openEHR attribute compatibility (used to tie-break in Phase 3a) ─────────
_TIPO_DATO_OE = {
    'numerica':   {'quantity': 1.0, 'count': 0.8, 'proportion': 0.7, 'ordinal': 0.5},
    'codi':       {'coded': 1.0, 'text': 0.7, 'boolean': 0.5, 'ordinal': 0.7,
                   'valor_categorico': 1.0},
    'text':       {'text': 1.0, 'coded': 0.6},
    'categorica': {'coded': 1.0, 'ordinal': 0.8, 'text': 0.6,
                   'valor_categorico': 1.0},
    'boolea':     {'boolean': 1.0, 'coded': 0.6},
    'data':       {'date': 1.0, 'datetime': 0.9},
    'hora':       {'time': 1.0, 'datetime': 0.9, 'duration': 0.6},
}

_ORIGEN_OE = {
    'dispositivo':           {'observation': 1.0, 'cluster': 0.4},
    'laboratorio':           {'observation': 1.0},
    'observacion':           {'observation': 0.9, 'evaluation': 0.7, 'cluster': 0.5},
    'registro o automatico': {'evaluation': 0.8, 'observation': 0.7, 'action': 0.6},
    'registro o dispositivo':{'observation': 1.0, 'cluster': 0.5},
    'derivado':              {'evaluation': 0.9, 'observation': 0.6},
    'calculo':               {'evaluation': 0.9, 'observation': 0.6},
}


def score_openehr_pair_for_socmic(socmic_row, ehr_row: dict) -> float:
    """
    Tie-break score when a SOCMIC's resolved SNOMED maps to multiple openEHR
    elements. Pure attribute match — no embedding similarity needed since
    they're all matched to the same SNOMED already.
    """
    tipo_dato = (ehr_row.get('Tipo_Dato')     or '').lower()
    tipo_var  = (ehr_row.get('Tipo_Variable') or '').lower()
    unit_oe   = (ehr_row.get('Unidades')      or '').lower()
    nom       = (ehr_row.get('Nombre_Variable') or '')

    tipo_score   = _lookup_boost(socmic_row.get('tipo_variable'),   _TIPO_DATO_OE, tipo_dato)
    origen_score = _lookup_boost(socmic_row.get('origen_variable'), _ORIGEN_OE,    tipo_var)
    unit_score   = unit_compat(socmic_row.get('unidad'), unit_oe) if unit_oe \
                   else unit_compat(socmic_row.get('unidad'), nom)
    return 0.50 * tipo_score + 0.30 * unit_score + 0.20 * origen_score


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE — three phases
# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1 : SOCMIC -> SNOMED     (per-variable retrieval + re-rank)
#  Phase 2 : SNOMED -> openEHR    (independent canonical mapping, competitive
#                                  assignment, granularity = element)
#  Phase 3 : SOCMIC -> openEHR    (lookup via Phase 1+2; embedding fallback)


def _int_str(x):
    try: return str(int(float(x)))
    except (TypeError, ValueError): return None


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — SOCMIC -> SNOMED
# ═══════════════════════════════════════════════════════════════════════════════
def match_socmic_to_snomed(df_socmic, df_snomed, top_k=TOP_K_SNOMED):
    df_s = df_snomed[df_snomed['nombre_categoria'].isin(CATEGORIAS_SNOMED)].copy()
    df_s['term_clean'] = df_s['term'].apply(limpiar_snomed)
    print(f"  [Fase 1] SNOMED filtrado: {len(df_s)} conceptos (de {len(df_snomed)})")

    snomed_lookup = df_snomed.drop_duplicates('conceptId').set_index('conceptId')
    result = df_socmic.copy()
    for col in ('snomed_id_resolved', 'snomed_term', 'snomed_categoria',
                'icd10_code', 'snomed_origen_mapeo', 'snomed_score',
                'snomed_top_candidates'):
        if col not in result.columns: result[col] = None

    # L1: gold from Excel
    n_l1 = 0
    for idx, row in result.iterrows():
        sid = _int_str(row.get('snomed_id'))
        if sid and sid in snomed_lookup.index:
            sr = snomed_lookup.loc[sid]
            result.at[idx, 'snomed_id_resolved']  = sid
            result.at[idx, 'snomed_term']         = sr['term']
            result.at[idx, 'snomed_categoria']    = sr['nombre_categoria']
            result.at[idx, 'icd10_code']          = sr.get('codigo_icd10')
            result.at[idx, 'snomed_origen_mapeo'] = 'EXCEL_DIRECTO'
            result.at[idx, 'snomed_score']        = 1.0
            n_l1 += 1
    print(f"  [Fase 1 / L1] EXCEL_DIRECTO: {n_l1}")

    # SNOMED embeddings (cached)
    snomed_texts = df_s.apply(snomed_doc_text, axis=1).tolist()
    emb_snomed   = _embed(snomed_texts, SNOMED_EMB_CACHE, SNOMED_META_CACHE)
    idx_snomed   = faiss.IndexFlatIP(emb_snomed.shape[1])
    idx_snomed.add(emb_snomed)
    snomed_records = df_s.to_dict('records')
    snomed_ids     = df_s['conceptId'].tolist()

    # SOCMIC embeddings
    soc_texts = result.apply(socmic_query_text, axis=1).tolist()
    soc_emb   = _embed_nocache(soc_texts)

    # L2: FAISS + composite rerank
    to_resolve = result[result['snomed_origen_mapeo'].isna()].index.tolist()
    if not to_resolve:
        return result, emb_snomed, snomed_ids, df_s

    positions = [result.index.get_loc(i) for i in to_resolve]
    q_emb     = soc_emb[positions]
    k         = min(top_k, len(snomed_ids))
    sims, idxs = idx_snomed.search(q_emb, k)

    n_high, n_suggest = 0, 0
    for r, soc_idx in enumerate(to_resolve):
        soc_row = result.loc[soc_idx]
        scored = []
        for j in range(k):
            pos = int(idxs[r][j]); sim = float(sims[r][j])
            cand = snomed_records[pos]
            attr = score_snomed_candidate(soc_row, cand, sim)
            scored.append((attr, sim, pos, cand))
        scored.sort(key=lambda x: x[0], reverse=True)

        attr, sim, pos, cand = scored[0]
        top5 = [{'conceptId': snomed_ids[p], 'term': c.get('term'),
                 'cat': c.get('nombre_categoria'),
                 'sim': round(s, 3), 'score': round(a, 3)}
                for a, s, p, c in scored[:5]]
        result.at[soc_idx, 'snomed_top_candidates'] = top5

        if attr < UMBRAL_SNOMED_SUGGEST: continue
        tag = 'SAPBERT_HIGH' if attr >= UMBRAL_SNOMED_HIGH else 'SAPBERT_SUGGEST'
        n_high    += int(attr >= UMBRAL_SNOMED_HIGH)
        n_suggest += int(UMBRAL_SNOMED_SUGGEST <= attr < UMBRAL_SNOMED_HIGH)

        result.at[soc_idx, 'snomed_id_resolved']  = snomed_ids[pos]
        result.at[soc_idx, 'snomed_term']         = cand.get('term')
        result.at[soc_idx, 'snomed_categoria']    = cand.get('nombre_categoria')
        result.at[soc_idx, 'icd10_code']          = cand.get('codigo_icd10')
        result.at[soc_idx, 'snomed_score']        = float(attr)
        result.at[soc_idx, 'snomed_origen_mapeo'] = f"{tag} ({attr:.2f} | sim={sim:.2f})"

    print(f"  [Fase 1 / L2] SAPBERT HIGH:    {n_high}")
    print(f"  [Fase 1 / L2] SAPBERT SUGGEST: {n_suggest}")
    print(f"  [Fase 1] sin SNOMED:           {result['snomed_origen_mapeo'].isna().sum()}")
    return result, emb_snomed, snomed_ids, df_s


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — SOCMIC -> openEHR (SOCMIC-driven retrieval, three confidence levels)
# ═══════════════════════════════════════════════════════════════════════════════
# L1 ARCHETYPE_BINDING : snomed_id matches an explicit XML term_binding
# L2 SNOMED_RETRIEVAL  : snomed_term (English) → openEHR pair text + rerank
# L3 DIRECT_EMBEDDING  : SOCMIC raw text → openEHR pair text (fallback only)
#
# No canonical SNOMED↔openEHR table — the retrieval is SOCMIC-driven, so only
# the variables we actually need drive lookups.


# Pattern to detect SNOMED (situation) "History of X" / "H/O: X" forms.
_HISTORY_OF_RE = re.compile(r'^\s*(?:history of|h/o:?)\s+', re.IGNORECASE)


def _base_concept_from_situation(snomed_term: str) -> str | None:
    """
    Strip 'History of '/'H/O:' prefix and the trailing semantic-tag parens.
    Returns the base concept string (e.g. "Dementia") or None if no rewrite
    is applicable.
    """
    if not snomed_term: return None
    term = limpiar_snomed(snomed_term)   # drop trailing (situation)
    m = _HISTORY_OF_RE.match(term)
    if not m: return None
    base = term[m.end():].strip()
    return base or None


def _build_openehr_corpus(df_ehr):
    """Build the openEHR (Arquetipo_ID, at_code) corpus once. Used by both
    L2 and L3. Each entry has the text we'll embed and the attributes we'll
    use for re-ranking."""
    rows = []
    for ehr_idx, r in df_ehr.iterrows():
        if r['Variable_ID'] == 'at0000': continue
        nom = str(r.get('Nombre_Variable', '') or '').strip()
        if not nom or nom.lower() in GENERIC_ELEMENT_NAMES: continue
        rows.append({
            'ehr_idx':       ehr_idx,
            'Arquetipo_ID':  r['Arquetipo_ID'],
            'at_code':       r['Variable_ID'],
            'arq_name':      r.get('Categoria'),
            'elem_name':     nom,
            'text':          openehr_pair_text(r.get('Categoria'), nom),
            'Tipo_Dato':     r.get('Tipo_Dato'),
            'Tipo_Variable': r.get('Tipo_Variable'),
            'Unidades':      r.get('Unidades'),
            'SNOMED_Code':   _int_str(r.get('SNOMED_Code')),
            'Descripcion':   r.get('Descripcion'),
        })
    return rows


def match_socmic_to_openehr(df_with_snomed, df_ehr,
                             top_k=15, umbral=UMBRAL_OE_SUGGEST):
    """
    Three-level matching, SOCMIC-driven.
    Output: single consolidated column set + origen_mapeo with level prefix.
    """
    result = df_with_snomed.copy()
    for c in ('arquetipo_id', 'at_code', 'openehr_nombre', 'openehr_descripcion',
              'openehr_categoria', 'openehr_tipo_dato', 'openehr_tipo_var',
              'unidad_openehr', 'openehr_score', 'openehr_origen_mapeo',
              'openehr_top_candidates'):
        if c not in result.columns: result[c] = None

    # Build openEHR corpus
    oe_rows = _build_openehr_corpus(df_ehr)
    print(f"  [Fase 2] Corpus openEHR: {len(oe_rows)} elementos elegibles")
    if not oe_rows:
        return result

    # Index by SNOMED binding for instant L1 lookup
    binding_to_rows: dict[str, list] = {}
    for i, r in enumerate(oe_rows):
        if r['SNOMED_Code']:
            binding_to_rows.setdefault(r['SNOMED_Code'], []).append(i)
    print(f"  [Fase 2] Elementos con term_binding SNOMED: "
          f"{sum(len(v) for v in binding_to_rows.values())} "
          f"({len(binding_to_rows)} SNOMEDs únicos)")

    # ── Embed the openEHR corpus once (cached) ─────────────────────────────
    oe_texts = [r['text'] for r in oe_rows]
    oe_emb   = _embed(oe_texts, OPENEHR_EMB_CACHE, OPENEHR_META_CACHE)
    idx_oe   = faiss.IndexFlatIP(oe_emb.shape[1])
    idx_oe.add(oe_emb)

    n_binding, n_retrieval, n_direct, n_none = 0, 0, 0, 0

    # ── Split SOCMIC into "has SNOMED" / "no SNOMED" ──────────────────────
    has_snomed = result[result['snomed_id_resolved'].notna()].index.tolist()
    no_snomed  = result[result['snomed_id_resolved'].isna()].index.tolist()
    print(f"  [Fase 2] Con SNOMED resuelto: {len(has_snomed)}")
    print(f"  [Fase 2] Sin SNOMED resuelto: {len(no_snomed)}")

    # ── L1 + L2: variables with snomed_id_resolved ────────────────────────
    if has_snomed:
        # L1: try explicit binding match first
        l1_resolved = set()
        for soc_idx in has_snomed:
            soc_row = result.loc[soc_idx]
            sid = _int_str(soc_row.get('snomed_id_resolved'))
            if not sid: continue
            bound_idxs = binding_to_rows.get(sid, [])
            if not bound_idxs: continue

            # If multiple elements bind to the same SNOMED, pick the one
            # whose attributes match SOCMIC best.
            best = None
            for oi in bound_idxs:
                oe_r = oe_rows[oi]
                attr = score_openehr_pair_for_socmic(soc_row, oe_r)
                if best is None or attr > best[1]: best = (oi, attr)
            oi, attr = best
            chosen = oe_rows[oi]
            _write_match(result, soc_idx, chosen, df_ehr,
                         score=1.0, tag=f"ARCHETYPE_BINDING (attr={attr:.2f})")
            l1_resolved.add(soc_idx)
            n_binding += 1

        # L2: SNOMED_RETRIEVAL for the rest
        l2_pending = [i for i in has_snomed if i not in l1_resolved]
        if l2_pending:
            # Query = snomed_term (English canonical)
            queries = [
                str(result.loc[i, 'snomed_term'] or '').strip() or
                socmic_query_text(result.loc[i])
                for i in l2_pending
            ]
            # Strip SNOMED semantic-tag parens for cleaner embedding
            queries = [limpiar_snomed(q) for q in queries]
            q_emb = _embed_nocache(queries)
            k = min(top_k, len(oe_rows))
            sims, idxs = idx_oe.search(q_emb, k)

            for r, soc_idx in enumerate(l2_pending):
                soc_row = result.loc[soc_idx]
                scored = []
                for j in range(k):
                    oi = int(idxs[r][j])
                    sim = float(sims[r][j])
                    oe_r = oe_rows[oi]
                    attr = score_openehr_pair_for_socmic(soc_row, oe_r)
                    # Composite: similarity dominates, attributes refine
                    final = 0.75 * sim + 0.25 * attr
                    scored.append((final, sim, oi, oe_r))
                scored.sort(key=lambda x: x[0], reverse=True)

                top5 = [
                    {'Arquetipo_ID': c[3]['Arquetipo_ID'],
                     'at_code':      c[3]['at_code'],
                     'elem_name':    c[3]['elem_name'],
                     'sim':          round(c[1], 3),
                     'score':        round(c[0], 3)}
                    for c in scored[:5]
                ]
                result.at[soc_idx, 'openehr_top_candidates'] = top5

                final, sim, oi, oe_r = scored[0]
                if final < umbral: n_none += 1; continue
                tag = f"SNOMED_RETRIEVAL ({final:.2f} | sim={sim:.2f})"
                _write_match(result, soc_idx, oe_r, df_ehr, score=final, tag=tag)
                n_retrieval += 1

    # ── L2b: Retry with base concept for SNOMED (situation) "History of X" ──
    # SOCMIC variables whose gold SNOMED is "History of dementia (situation)"
    # rarely have a direct openEHR equivalent because openEHR models the
    # concept atomically (Dementia) plus a temporal qualifier. We retry the
    # retrieval using the stripped base concept as the query.
    if has_snomed:
        still_pending = [
            i for i in has_snomed
            if pd.isna(result.loc[i, 'arquetipo_id'])
        ]
        retry_targets = []
        retry_queries = []
        for soc_idx in still_pending:
            base = _base_concept_from_situation(result.loc[soc_idx, 'snomed_term'])
            if not base: continue
            retry_targets.append(soc_idx)
            retry_queries.append(base)

        if retry_targets:
            print(f"  [Fase 2 / L2b] Reintentos 'History of X' → base concept: "
                  f"{len(retry_targets)}")
            q_emb = _embed_nocache(retry_queries)
            k = min(top_k, len(oe_rows))
            sims, idxs = idx_oe.search(q_emb, k)

            n_retry = 0
            for r, soc_idx in enumerate(retry_targets):
                soc_row = result.loc[soc_idx]
                scored = []
                for j in range(k):
                    oi = int(idxs[r][j])
                    sim = float(sims[r][j])
                    oe_r = oe_rows[oi]
                    attr = score_openehr_pair_for_socmic(soc_row, oe_r)
                    final = 0.75 * sim + 0.25 * attr
                    scored.append((final, sim, oi, oe_r))
                scored.sort(key=lambda x: x[0], reverse=True)

                top5 = [
                    {'Arquetipo_ID': c[3]['Arquetipo_ID'],
                     'at_code':      c[3]['at_code'],
                     'elem_name':    c[3]['elem_name'],
                     'sim':          round(c[1], 3),
                     'score':        round(c[0], 3)}
                    for c in scored[:5]
                ]
                # Preserve original top5 if present; this overwrite is fine —
                # the base-concept top5 is more relevant for the picked match.
                result.at[soc_idx, 'openehr_top_candidates'] = top5

                final, sim, oi, oe_r = scored[0]
                if final < umbral: continue
                base = retry_queries[r]
                tag = (f"SNOMED_RETRIEVAL_BASE ({final:.2f} | sim={sim:.2f} "
                       f"| base=\"{base[:30]}\")")
                _write_match(result, soc_idx, oe_r, df_ehr, score=final, tag=tag)
                n_retry += 1
            print(f"  [Fase 2 / L2b] SNOMED_RETRIEVAL_BASE: {n_retry}")

    # ── L3: DIRECT_EMBEDDING fallback for variables without SNOMED ────────
    if no_snomed:
        queries = [socmic_query_text(result.loc[i]) for i in no_snomed]
        q_emb = _embed_nocache(queries)
        k = min(top_k, len(oe_rows))
        sims, idxs = idx_oe.search(q_emb, k)

        for r, soc_idx in enumerate(no_snomed):
            soc_row = result.loc[soc_idx]
            scored = []
            for j in range(k):
                oi = int(idxs[r][j])
                sim = float(sims[r][j])
                oe_r = oe_rows[oi]
                attr = score_openehr_pair_for_socmic(soc_row, oe_r)
                final = 0.75 * sim + 0.25 * attr
                scored.append((final, sim, oi, oe_r))
            scored.sort(key=lambda x: x[0], reverse=True)

            top5 = [
                {'Arquetipo_ID': c[3]['Arquetipo_ID'],
                 'at_code':      c[3]['at_code'],
                 'elem_name':    c[3]['elem_name'],
                 'sim':          round(c[1], 3),
                 'score':        round(c[0], 3)}
                for c in scored[:5]
            ]
            result.at[soc_idx, 'openehr_top_candidates'] = top5

            final, sim, oi, oe_r = scored[0]
            if final < umbral: n_none += 1; continue
            tag = f"DIRECT_EMBEDDING ({final:.2f} | sim={sim:.2f})"
            _write_match(result, soc_idx, oe_r, df_ehr, score=final, tag=tag)
            n_direct += 1

    print(f"  [Fase 2 / L1] ARCHETYPE_BINDING:  {n_binding}")
    print(f"  [Fase 2 / L2] SNOMED_RETRIEVAL:    {n_retrieval}")
    print(f"  [Fase 2 / L3] DIRECT_EMBEDDING:    {n_direct}")
    print(f"  [Fase 2]      Sin openEHR:         {n_none}")
    print(f"  [Fase 2]      Total con openEHR:   {result['arquetipo_id'].notna().sum()} / {len(result)}")
    return result


def _write_match(result, soc_idx, oe_r, df_ehr, score, tag):
    """Populate the openEHR columns for one SOCMIC row."""
    result.at[soc_idx, 'arquetipo_id']        = oe_r['Arquetipo_ID']
    result.at[soc_idx, 'at_code']             = oe_r['at_code']
    result.at[soc_idx, 'openehr_nombre']      = oe_r['elem_name']
    result.at[soc_idx, 'openehr_categoria']   = oe_r['arq_name']
    result.at[soc_idx, 'openehr_tipo_dato']   = oe_r['Tipo_Dato']
    result.at[soc_idx, 'openehr_tipo_var']    = oe_r['Tipo_Variable']
    result.at[soc_idx, 'unidad_openehr']      = oe_r['Unidades']
    result.at[soc_idx, 'openehr_descripcion'] = oe_r.get('Descripcion')
    result.at[soc_idx, 'openehr_score']       = float(score)
    result.at[soc_idx, 'openehr_origen_mapeo'] = tag



# ═══════════════════════════════════════════════════════════════════════════════
# PASO 4 — INSERCIÓN / ACTUALIZACIÓN EN BASE DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════
 
def guardar_referencia(df_ref: pd.DataFrame, engine) -> None:
    print("\n💾 Insertando en base de datos...")

    df_db = df_ref.copy()

    # Eliminar snomed_id original del Excel antes de renombrar el resuelto
    if "snomed_id" in df_db.columns and "snomed_id_resolved" in df_db.columns:
        df_db = df_db.drop(columns=["snomed_id"])

    df_db = df_db.rename(columns={
        "descripcion":        "descripcion_socmic",
        "unidad":             "unidad_ucum",
        "snomed_id_resolved": "snomed_id",
    })

    COLUMNAS_MODELO = [
        "variable", "grupo", "tipo_variable", "descripcion_socmic",
        "unidad_ucum", "unidad_openehr",
        "snomed_id", "snomed_term", "snomed_categoria", "icd10_code",
        "snomed_origen_mapeo", "snomed_score",
        "arquetipo_id", "at_code",
        "openehr_nombre", "openehr_descripcion", "openehr_tipo_dato",
        "openehr_categoria", "openehr_tipo_var",
    ]

    for col in COLUMNAS_MODELO:
        if col not in df_db.columns:
            df_db[col] = None

    df_db = df_db[COLUMNAS_MODELO]

    # ── Forzar tipos numéricos para columnas Float del modelo ─────────────────
    # pandas inicializa con None → dtype object; hay que convertir explícitamente
    # o pandas/SQLAlchemy escribirá la columna staging como TEXT y PostgreSQL
    # rechazará el INSERT por DatatypeMismatch.
    df_db["snomed_score"] = pd.to_numeric(df_db["snomed_score"], errors="coerce")

    df_db = df_db.where(pd.notnull(df_db), None)

    print(f"  📋 Shape final: {df_db.shape}")
    print(f"  🔎 Dtype snomed_score: {df_db['snomed_score'].dtype}")

    staging = "varref_staging"

    try:
        with engine.begin() as conn:

            conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))
            df_db.to_sql(staging, conn, if_exists="replace", index=False)
            conn.execute(text(
                f"CREATE INDEX idx_{staging}_variable ON {staging}(variable)"
            ))

            conn.execute(text(f"""
                INSERT INTO "VarsRef" (
                    variable, grupo, tipo_variable, descripcion_socmic,
                    unidad_ucum, unidad_openehr,
                    snomed_id, snomed_term, snomed_categoria, icd10_code,
                    snomed_origen_mapeo, snomed_score,
                    arquetipo_id, at_code,
                    openehr_nombre, openehr_descripcion, openehr_tipo_dato,
                    openehr_categoria, openehr_tipo_var
                )
                SELECT
                    variable, grupo, tipo_variable, descripcion_socmic,
                    unidad_ucum, unidad_openehr,
                    snomed_id, snomed_term, snomed_categoria, icd10_code,
                    snomed_origen_mapeo, snomed_score::double precision,
                    arquetipo_id, at_code,
                    openehr_nombre, openehr_descripcion, openehr_tipo_dato,
                    openehr_categoria, openehr_tipo_var
                FROM {staging}
                ON CONFLICT (variable) DO UPDATE SET
                    grupo               = EXCLUDED.grupo,
                    tipo_variable       = EXCLUDED.tipo_variable,
                    descripcion_socmic  = EXCLUDED.descripcion_socmic,
                    unidad_ucum         = EXCLUDED.unidad_ucum,
                    unidad_openehr      = EXCLUDED.unidad_openehr,
                    snomed_id           = EXCLUDED.snomed_id,
                    snomed_term         = EXCLUDED.snomed_term,
                    snomed_categoria    = EXCLUDED.snomed_categoria,
                    icd10_code          = EXCLUDED.icd10_code,
                    snomed_origen_mapeo = EXCLUDED.snomed_origen_mapeo,
                    snomed_score        = EXCLUDED.snomed_score,
                    arquetipo_id        = EXCLUDED.arquetipo_id,
                    at_code             = EXCLUDED.at_code,
                    openehr_nombre      = EXCLUDED.openehr_nombre,
                    openehr_descripcion = EXCLUDED.openehr_descripcion,
                    openehr_tipo_dato   = EXCLUDED.openehr_tipo_dato,
                    openehr_categoria   = EXCLUDED.openehr_categoria,
                    openehr_tipo_var    = EXCLUDED.openehr_tipo_var
            """))

            conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))

        print(f"✅ {len(df_db)} variables insertadas/actualizadas.")

    except Exception as e:
        print(f"❌ Error durante la inserción: {e}")
        raise
 
# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT FOR THESIS METRICS (full df_ref + Phase-1 gold evaluation)
# ═══════════════════════════════════════════════════════════════════════════════
# Both files are written to OUTPUT_DIR, which must be a volume-mounted path so
# they survive the `--rm` of the batch container. Defaults to /app/metrics_output.

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/metrics_output")

def _serialise_candidates(df):
    """top_candidates columns hold python lists of dicts; JSON-encode them so
    they survive the round-trip to xlsx as readable text."""
    import json
    df = df.copy()
    for col in ("snomed_top_candidates", "openehr_top_candidates"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
            )
    return df


def exportar_df_completo(df_ref: pd.DataFrame) -> None:
    """Dump the FULL in-memory reference dataframe (all debug columns intact:
    snomed_id_resolved, snomed_score, snomed_origen_mapeo, snomed_top_candidates,
    openehr_score, openehr_origen_mapeo, openehr_top_candidates, ...).
    This is the file to use for ALL coverage statistics and score histograms."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "df_ref_full.xlsx")
    _serialise_candidates(df_ref).to_excel(out, index=False)
    print(f"📤 [export] Reference dataframe completo → {out}  ({df_ref.shape[0]} filas, {df_ref.shape[1]} cols)")


def evaluar_gold_snomed(df_socmic, df_snomed, top_k=TOP_K_SNOMED) -> None:
    """
    Phase-1 GOLD evaluation. For every SOCMIC variable that ships with a manual
    SNOMED id, run the SAME retrieval + re-rank used in match_socmic_to_snomed
    but WITHHOLD the gold id, then record whether the gold concept is recovered
    at rank 1 / within top-5, together with the score the pipeline would assign.

    Writes gold_eval.xlsx to OUTPUT_DIR. Scoring (top-1/top-5 agreement) is done
    afterwards on that file — no SNOMED instance required for the scoring step.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Same filtered SNOMED corpus, embeddings and index as Phase 1.
    df_s = df_snomed[df_snomed['nombre_categoria'].isin(CATEGORIAS_SNOMED)].copy()
    df_s['term_clean'] = df_s['term'].apply(limpiar_snomed)
    snomed_texts   = df_s.apply(snomed_doc_text, axis=1).tolist()
    emb_snomed     = _embed(snomed_texts, SNOMED_EMB_CACHE, SNOMED_META_CACHE)  # cache hit
    idx_snomed     = faiss.IndexFlatIP(emb_snomed.shape[1])
    idx_snomed.add(emb_snomed)
    snomed_records = df_s.to_dict('records')
    snomed_ids     = df_s['conceptId'].tolist()

    # Gold subset: variables with a manual snomed_id that resolves into the corpus.
    gold = df_socmic[df_socmic['snomed_id'].notna()].copy()
    gold_rows = []
    for _, soc_row in gold.iterrows():
        gold_id = _int_str(soc_row.get('snomed_id'))
        if not gold_id:
            continue
        # Embed the query exactly like Phase 1, search, re-rank with the same scorer.
        q_emb = _embed_nocache([socmic_query_text(soc_row)])
        k = min(top_k, len(snomed_ids))
        sims, idxs = idx_snomed.search(q_emb, k)
        scored = []
        for j in range(k):
            pos = int(idxs[0][j]); sim = float(sims[0][j])
            cand = snomed_records[pos]
            attr = score_snomed_candidate(soc_row, cand, sim)
            scored.append((attr, sim, pos, cand))
        scored.sort(key=lambda x: x[0], reverse=True)

        ranked_ids = [snomed_ids[p] for _, _, p, _ in scored]
        best_attr, best_sim, best_pos, best_cand = scored[0]
        gold_rows.append({
            'variable':      soc_row.get('variable'),
            'gold_id':       gold_id,
            'gold_in_corpus': gold_id in snomed_ids,
            'pred_top1_id':  ranked_ids[0] if ranked_ids else None,
            'pred_top1_term': best_cand.get('term'),
            'pred_top1_score': round(float(best_attr), 4),
            'top1_hit':      bool(ranked_ids) and ranked_ids[0] == gold_id,
            'top5_hit':      gold_id in ranked_ids[:5],
            'top5_ids':      ",".join(str(x) for x in ranked_ids[:5]),
        })

    gdf = pd.DataFrame(gold_rows)
    out = os.path.join(OUTPUT_DIR, "gold_eval.xlsx")
    gdf.to_excel(out, index=False)

    # Quick log so you see the headline number in the batch output immediately.
    n = len(gdf)
    in_corpus = gdf['gold_in_corpus'].sum() if n else 0
    if n:
        committed = gdf[gdf['pred_top1_score'] >= UMBRAL_SNOMED_SUGGEST]
        print(f"📤 [gold] {n} gold variables ({in_corpus} resolve into corpus) → {out}")
        print(f"📤 [gold] Top-1 agreement (all):        {gdf['top1_hit'].mean():.1%}")
        print(f"📤 [gold] Top-5 agreement (all):        {gdf['top5_hit'].mean():.1%}")
        if len(committed):
            print(f"📤 [gold] Top-1 agreement (score≥{UMBRAL_SNOMED_SUGGEST}): "
                  f"{committed['top1_hit'].mean():.1%}  (n={len(committed)})")
    else:
        print("📤 [gold] No gold variables found (df_socmic has no snomed_id).")

# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    db: Session = SessionLocal()
    engine = db.bind
 
    try:
        df_socmic = load_socmic(SOCMIC_FOLDER)
        df_snomed = cargar_snomed()

        df_ehr = procesar_zip_a_dataframe(ARCHIVO_ZIP)

        df_s, emb_snomed, snomed_ids, df_snomed_filtered = match_socmic_to_snomed(df_socmic, df_snomed)

        df_ref = match_socmic_to_openehr(df_s, df_ehr)

        # ── Thesis metric exports (must run while SNOMED engine is alive) ──────
        # exportar_df_completo(df_ref)              # full df → df_ref_full.xlsx
        # evaluar_gold_snomed(df_socmic, df_snomed) # gold eval → gold_eval.xlsx

        guardar_referencia(df_ref, engine)
        
    finally:
        db.close()