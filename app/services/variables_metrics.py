import logging
from collections import defaultdict
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import itertools
# from tqdm import tqdm
import os
import json

from sqlalchemy.orm import Session

from app.db.models import VarsLocal
from app.services.utils_ccc import get_base, safe_ccc2pd, get_variables_dict
from app.services.utils_cha import get_variables_df_cha, get_base_cha
from app.db.database import SessionLocal
from datetime import datetime, timedelta

try:
    import app.db_connections as dbc
except Exception as e:
    raise ImportError("No se encontró db_connections.") from e

logger = logging.getLogger(__name__)

DATE_CANDIDATES = [
    'DateTime', 'EnterTime', 'EventTime', 'StartTime', 'EndTime',
    'Timestamp', 'Date', 'Time', 'ObservationDate', 'TS', 'ValueTime',
    'ProcedureStartTime', 'DiagnosisStartTime', 'EventDttm'
]


def _pick_date_column_for_table(base_df: pd.DataFrame, table: str) -> str:
    """Busca columna de fecha en una tabla priorizando nombres exactos."""
    cols = base_df[base_df['table'] == table]['column'].dropna().unique()
    
    if len(cols) == 0:
        return None
    
    # Búsqueda exacta (case-insensitive)
    lower_cols = {c.lower(): c for c in cols}
    for candidate in DATE_CANDIDATES:
        if candidate.lower() in lower_cols:
            return lower_cols[candidate.lower()]
    
    # Búsqueda por substring
    for col in cols:
        col_lower = col.lower()
        if 'date' in col_lower or 'time' in col_lower:
            return col
    
    return None


def _pick_value_column_for_table(base_df: pd.DataFrame, table: str) -> str:
    """Busca columna de valor en una tabla."""
    cols = base_df[base_df['table'] == table]['column'].dropna().unique()
    
    if len(cols) == 0:
        return None
    
    lower_cols = {c.lower(): c for c in cols}
    for candidate in ['Value', 'GivenDose', 'PeriodicAmount', 'VariableValue']:
        if candidate.lower() in lower_cols:
            return lower_cols[candidate.lower()]
    
    return None

def get_patients(hosp):
    q = """
        SELECT
            PatientID,
            AdminWardName AS servei,
            AdminWardEndTime
        FROM PV_AdminWards
        """
    
    aw = (
        safe_ccc2pd(q, hosp, 'uci', 'both')
        .sort_values(['PatientID', 'AdminWardEndTime'])
        .drop_duplicates('PatientID', keep='last')
        .reset_index(drop=True)
        )
    
    mi = aw[aw['servei']=='MEDICINA INTENSIVA'].reset_index(drop=True)
    
    del aw
    
    q = f"""
        SELECT 
            PatientID,
            PatientSSN,
            PatientFirstName,
            PatientLastName 
        FROM PV_PatientList 
        WHERE PatientID IN {tuple(set(mi['PatientID']))}
        AND DisTime IS NOT NULL
        """
    
    dummy = (
        safe_ccc2pd(q, hosp, 'uci', 'both')
        .sort_values(['PatientID'])
        .drop_duplicates('PatientID', keep='last')
        .reset_index(drop=True)
        )
    
    del mi
    
    mask = (
        dummy['PatientFirstName'].str.contains('prova|pp|test', na=False, case=False)
        | dummy['PatientLastName'].str.contains('prova|pp|test', na=False, case=False)
        | (dummy['PatientSSN'].str.len() != 10)
        )
    
    pat_ids = tuple(dummy.loc[~mask].PatientID.unique())
    
    del dummy, mask
    
    return pat_ids

def smart_round(x: float) -> float:
    """Redondea según magnitud del valor."""
    if x is None or pd.isna(x):
        return None
    if abs(x) >= 0.1:
        return round(x, 2)
    return float(f"{x:.2g}")

def safe_int(x):
    """Convierte a int si es posible, eliminando decimales .0."""
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        # Si es float con parte decimal 0, convertir a int
        if isinstance(x, float):
            return int(x)
        # Si es string con formato tipo "61527.0" → 61527
        if isinstance(x, str) and x.replace('.', '', 1).isdigit():
            return int(float(x))
        return int(x)
    except Exception:
        return x
    
def safe_int(x):
    try:
        if x in [None, "NA", "-", "nan"]:
            return None
        return int(float(x))
    except Exception:
        return None

def format_cadencia(cad):
    """Formatea timedelta a texto legible."""
    if cad is None or pd.isna(cad):
        return 'solo una medición'
    
    if not isinstance(cad, pd.Timedelta):
        return str(cad)
    
    total_seconds = cad.total_seconds()
    
    if total_seconds < 60:
        return f"cada {int(total_seconds)} segons"
    elif total_seconds < 3600:
        return f"cada {int(total_seconds // 60)} minuts"
    elif total_seconds < 86400:
        return f"cada {round(total_seconds / 3600, 1)} hores"
    else:
        return f"cada {round(total_seconds / 86400, 1)} dies"



def safe_to_datetime(val):
    """Convierte un valor (o lista/Serie) a datetime de forma segura y universal."""

    # 1️⃣ Si es lista o Serie → aplicar recursivamente
    if isinstance(val, (list, pd.Series)):
        return [safe_to_datetime(v) for v in val]

    # 2️⃣ Manejo de valores nulos o NaN
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None

    # 3️⃣ Manejo de bytes (por si viene de SQL codificado)
    if isinstance(val, bytes):
        for encoding in ("utf-8", "latin-1"):
            try:
                val = val.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"⚠️ Valor de fecha en bytes no decodificable: {val!r}")
            return None

    # 4️⃣ Conversión segura (incluye microsoft.sql.DateTimeOffset)
    try:
        dt = pd.to_datetime(str(val), errors="coerce", utc=True)
        if pd.isna(dt):
            return None

        # Si es un pandas.Timestamp, quitar zona horaria y devolver datetime nativo
        if isinstance(dt, pd.Timestamp):
            dt = dt.tz_convert(None) if dt.tzinfo else dt
            return dt.to_pydatetime()
        return dt

    except Exception as e:
        print(f"⚠️ Valor de fecha no convertible: {val!r} ({e})")
        return None

def formatear_metrics(metrics_dict):
    """Formatea métricas para presentación."""
    formatted = {}
    
    for key, val in metrics_dict.items():
        new_val = val.copy()
        
        # Redondear valores numéricos
        for field in ['Q1', 'Q2', 'Q3', 'porc_pacientes']:
            if field in new_val and new_val[field] is not None:
                new_val[field] = smart_round(new_val[field])
        
        # Convertir fechas a date
        for col in ['last_value']:
            if col in new_val and new_val[col] is not None:
                try:
                    if isinstance(new_val[col], pd.Timestamp):
                        new_val[col] = new_val[col].date()
                    else:
                        new_val[col] = pd.to_datetime(new_val[col]).date()
                except Exception:
                    pass
        
        # Formatear cadencia
        if 'cadencia' in new_val:
            new_val['cadencia'] = format_cadencia(new_val['cadencia'])
        
        formatted[key] = new_val
    
    return formatted    


def _calculate_quantiles_and_cadence_ccc(
    clave, var_id, value_id, table, value_col, date_col,
    is_numeric, is_categorical, pacientes_unicos, pats_tuple, hosp, 
    periodo_dias=30
):
    """Versión optimizada: calcula cuartiles, cadencia y métricas temporales sobre los últimos 50 pacientes y el último mes."""
    
    result = {
        'Q1': np.nan,
        'Q2': np.nan,
        'Q3': np.nan,
        'cadencia': np.nan,
        'count': 0,
        'porc_pacientes': np.nan,
        'last_value': None
    }

    try:
        fecha_corte_30 = datetime.now() - timedelta(days=periodo_dias)
        if table in ['P_MonVals', 'P_DerVals']:
            periodo_stats = 7
        else:
            periodo_stats = 30
        fecha_corte_stats = datetime.now() - timedelta(days=periodo_stats)

        str_30_dias = fecha_corte_30.strftime('%Y-%m-%d')
        str_stats = fecha_corte_stats.strftime('%Y-%m-%d')

        where_val = f"AND {value_col} = {value_id}" if (is_categorical and value_id != -99 and value_col) else ""

        # --- QUERY 1: Prevalencia (Rápida, 30 días) ---
        # Solo traemos los IDs distintos para calcular el porcentaje real del mes
        query_prevalencia = f"""
            SELECT DISTINCT PatientID AS pat_id
            FROM {table}
            WHERE {clave} = {var_id} {where_val}
              AND PatientID IN {pats_tuple}
              AND {date_col} >= '{str_30_dias}'
        """
        df_prev = safe_ccc2pd(query_prevalencia, hosp, 'uci', 'prod')
        
        if df_prev is not None and not df_prev.empty and pacientes_unicos > 0:
            result['porc_pacientes'] = (df_prev['pat_id'].nunique() / pacientes_unicos) * 100
        else:
            result['porc_pacientes'] = 0.0

        # --- QUERY 2: Estadísticos y Cadencia (Pesada, 7 o 30 días) ---
        if is_numeric and value_col:
            select_cols = f"PatientID AS pat_id, {value_col} AS Value, {date_col} AS date"
        elif date_col:
            select_cols = f"PatientID AS pat_id, {date_col} AS date"
        else:
            return result

        query_recent = f"""
            SELECT {select_cols}
            FROM {table}
            WHERE {clave} = {var_id} {where_val}
              AND PatientID IN {pats_tuple}
              AND {date_col} >= '{str_stats}'
        """
        df_recent = safe_ccc2pd(query_recent, hosp, 'uci', 'prod')

        query_last = f"""
            SELECT MAX({date_col}) AS last_date
            FROM {table}
            WHERE {clave} = {var_id} {where_val}
        """
        df_last = safe_ccc2pd(query_last, hosp, 'uci', 'prod')
        
        if (df_last is None or df_last.empty):
            return result

        df_last['last_date'] = safe_to_datetime(df_last['last_date'])
        result['last_value'] = df_last['last_date'].max()
        # result['first_value'] = df_last['date'].min()
        
        if df_recent is not None and not df_recent.empty:
            df_recent = df_recent.drop_duplicates()
            df_recent['date'] = safe_to_datetime(df_recent['date'])
            df_recent = df_recent.sort_values(by=['pat_id', 'date'])

            # Métricas
            result['count'] = len(df_recent)
            # if pacientes_unicos > 0:
            #     result['porc_pacientes'] = (df_recent.pat_id.nunique() / pacientes_unicos) * 100

            if is_numeric and 'Value' in df_recent.columns:
                result['Q1'] = float(df_recent['Value'].quantile(0.25))
                result['Q2'] = float(df_recent['Value'].quantile(0.5))
                result['Q3'] = float(df_recent['Value'].quantile(0.75))

            result['cadencia'] = (
                df_recent.groupby('pat_id')['date'].diff().median()
            )

    except Exception as e:
        print(f"⚠️ Error calculando stats para {clave}={var_id}: {e}")

    return result

def _calculate_quantiles_and_cadence_cha(
    clave, var_id, value_id, table, value_col, date_col,
    is_numeric, is_categorical, pacientes_activos_tabla, pats_tuple,
    periodo_dias=30
):
    """
    Versión CHA: Calcula cuartiles, cadencia y métricas temporales sobre los últimos 30 días.
    Utiliza dbc.cha2pd para la conexión.
    """
    result = {
        'Q1': np.nan,
        'Q2': np.nan,
        'Q3': np.nan,
        'cadencia': np.nan,
        'count': 0,
        'porc_pacientes': 0,
        'last_value': None
    }

    if not date_col:
        return result

    try:
        fecha_corte = datetime.now() - timedelta(days=periodo_dias)
        fecha_corte_str = fecha_corte.strftime('%Y-%m-%d')

        # 1️⃣ Query para datos recientes (últimos 30 días)
        # En CHA usamos CaseKey como identificador de paciente
        cols = f"CaseKey AS pat_id, {date_col} AS date"
        if is_numeric and value_col:
            cols += f", {value_col} AS Value"
        
        # where_val = ""
        # # Manejo de categóricas si tienen un valor específico definido
        # if is_categorical and value_id != -99 and value_col:
        #     # Asumiendo que value_col es numérico o string dependiendo de la tabla
        #     where_val = f"AND {value_col} = {value_id}"

        # Filtrar por fecha reciente directamente en SQL para no traer toda la tabla
        query_recent = f"""
            SELECT {cols}
            FROM {table}
            WHERE {clave} = {var_id}
              AND Casekey IN {pats_tuple}
        """

        df_recent = dbc.cha2pd(query_recent, 'DT')

        # 2️⃣ Query para último valor histórico (max date global)
        query_last = f"""
            SELECT MAX({date_col}) AS last_date
            FROM {table}
            WHERE {clave} = {var_id}
        """
        df_last = dbc.cha2pd(query_last, 'DT')

        # Procesar Last Date
        if df_last is not None and not df_last.empty:
            result['last_value'] = safe_to_datetime(df_last['last_date'].iloc[0])

        # Procesar Métricas Recientes
        if df_recent is not None and not df_recent.empty:
            df_recent = df_recent.drop_duplicates()
            df_recent['date'] = safe_to_datetime(df_recent['date'])
            df_recent = df_recent.sort_values(by=['pat_id', 'date'])

            # Count total de mediciones recientes
            result['count'] = len(df_recent)

            # Porcentaje de pacientes (sobre los activos en la tabla en ese periodo)
            if pacientes_activos_tabla > 0:
                uniq_pats = df_recent['pat_id'].nunique()
                result['porc_pacientes'] = (uniq_pats / pacientes_activos_tabla) * 100

            # Cuartiles (solo si es numérico y tenemos columna de valor)
            if is_numeric and 'Value' in df_recent.columns:
                # Convertir a numeric, forzando errores a NaN
                df_recent['Value'] = pd.to_numeric(df_recent['Value'], errors='coerce')
                result['Q1'] = float(df_recent['Value'].quantile(0.25))
                result['Q2'] = float(df_recent['Value'].quantile(0.5))
                result['Q3'] = float(df_recent['Value'].quantile(0.75))

            # Cadencia (Mediana de diferencia de tiempos por paciente)
            # Solo si hay más de 1 registro por paciente en promedio
            if len(df_recent) > df_recent['pat_id'].nunique():
                cadencias = df_recent.groupby('pat_id')['date'].diff()
                result['cadencia'] = cadencias.median()

    except Exception as e:
        logger.error(f"⚠️ Error calculando stats CHA para {clave}={var_id}: {e}")
        # print(f"⚠️ Error calculando stats CHA para {clave}={var_id}: {e}")

    return result


def update_all_metrics_ccc(db: Session, hosp, hospital_id: int, sybase_db_args: Optional[List]=None):
    """
    Calcula métricas por variable recorriendo tablas de forma optimizada.
    Agrega resultados de múltiples tablas para el mismo ID.
    """
    print("Obteniendo diccionario de variables...")
    
    # Obtener datos base
    base_df = get_base(hosp)
    vars_df = get_variables_dict(base_df, hosp)
    pat_ids = get_patients(hosp)
    
    print(f"{len(vars_df)} variables obtenidas, {len(base_df)} tablas en base_df")
    
    if vars_df is None or not isinstance(vars_df, pd.DataFrame) or vars_df.empty:
        print("⚠️ No hay variables disponibles")
        return {}
    
    # Normalizar ID
    vars_df['ID'] = pd.to_numeric(vars_df['ID'], errors='coerce').astype('Int64')
    
    # Obtener total de pacientes (una sola vez)
    fecha_corte = datetime.now() - timedelta(days=30)
    fecha_corte_str = fecha_corte.strftime('%Y-%m-%d')
    
    total_patients_query_adm = f"""
        SELECT DISTINCT PatientID FROM P_GeneralData
        WHERE PatientID IN {pat_ids} AND AdmissionTime >= '{fecha_corte_str}'
    """
    total_patients_query_disch = f"""
        SELECT DISTINCT PatientID FROM P_DischargeData
        WHERE PatientID IN {pat_ids}
        AND (DischargeTime >= '{fecha_corte_str}' OR DischargeTime IS NULL)
    """

    total_patients_adm = safe_ccc2pd(total_patients_query_adm, hosp, 'uci', 'prod')
    if not isinstance(total_patients_adm, pd.DataFrame) or total_patients_adm.empty:
        total_patients_adm = pd.DataFrame(columns=['PatientID'])

    total_patients_disch = safe_ccc2pd(total_patients_query_disch, hosp, 'uci', 'prod')
    if not isinstance(total_patients_disch, pd.DataFrame) or total_patients_disch.empty:
        total_patients_disch = pd.DataFrame(columns=['PatientID'])

    pacientes_unicos = len(set(total_patients_adm['PatientID']).union(set(total_patients_disch['PatientID'])))
    pats_tuple = tuple(set(total_patients_adm['PatientID']).union(set(total_patients_disch['PatientID'])))

    print(f"Total pacientes en el útimo mes: {pacientes_unicos}")
    
    
    # Procesar por cada clave
    claves = vars_df['clave'].dropna().unique().tolist()
    # claves = ['VariableID']
    
    for clave in claves:
        print(f"\nProcesando clave: {clave}")
        
        # IDs para esta clave
        ids_for_clave = vars_df[vars_df['clave'] == clave]['ID'].dropna().astype(int).unique().tolist()
        
        if not ids_for_clave:
            continue
        
        # Tablas que contienen esta columna
        tablas = base_df[
            (base_df['column'] == clave) &
            (base_df['source'] == 'patient') &
            (base_df['ttype'] == 'U ') &
            (~base_df['table'].str.contains('DW|old|Deleted|QRTZ|ComprVals|Newest|StylesOfTrendVariables|VariablesOfSections|error|CareRec|CareNotes', na=False, case=False))
        ]['table'].dropna().unique().tolist()
        # tablas = ['P_ObservRec']
        
        for tabla in tablas:
            print(f" Tabla: {tabla}")

            metrics_tabla = {}
            date_col = _pick_date_column_for_table(base_df, tabla)
            value_col = _pick_value_column_for_table(base_df, tabla)

            q = f"""SELECT DISTINCT {clave} as var_id
            FROM {tabla}
            """
            df_ids = safe_ccc2pd(q, hosp, 'uci', 'prod')
            
            print(f"{len(df_ids)} ids obtenidos")

            df = vars_df[(vars_df.ID.isin(tuple(df_ids.var_id.unique()))) & (vars_df.clave == clave)]
            
            grouped = df.groupby(['ID', df['Value'].fillna(-99), 'clave'])
            
            for (var_id, value, clave), group_df in grouped:
                # Convertir el valor a int o asignar -99 si era nulo
                if pd.isna(var_id):
                    continue
                
                value_id = value
                tipo_var = group_df['tipo_variable'].iloc[0] if 'tipo_variable' in group_df.columns else 'Altres'
                orig_var = group_df['origen_variable'].iloc[0] if 'origen_variable' in group_df.columns else 'Altres'
                codigo = group_df['Codigo'].iloc[0] if 'Codigo' in group_df.columns else '-'
                descrp = group_df['description'].iloc[0]
                is_numeric = tipo_var in ['Numèrica', 'Fàrmacs']
                is_categorical = (tipo_var == 'Categòrica') and (value_id != -99)

                stats = _calculate_quantiles_and_cadence_ccc(
                    clave, var_id, value_id, tabla, value_col, date_col,
                    is_numeric, is_categorical, pacientes_unicos, pats_tuple, hosp
                )
                
                metrics_tabla[(tabla, clave, var_id, value_id, descrp)] = {
                    'count': stats.get('count', 0),
                    'porc_pacientes': stats.get('porc_pacientes', 0),
                    'Q1': stats.get('Q1', np.nan),
                    'Q2': stats.get('Q2', np.nan),
                    'Q3': stats.get('Q3', np.nan),
                    'cadencia': stats.get('cadencia', np.nan),
                    'codigo': codigo,
                    'last_value': stats.get('last_value', None),
                    'tipo_variable': tipo_var,
                    'origen_variable': orig_var,
                }

            print("Insertando métricas en BD...")
            metrics_final = formatear_metrics(metrics_tabla)
            agregar_metricas_test(metrics_final, db, hospital_id)

    
    print("\nAñadiendo variables faltantes...")
    # existing_descrpt = db.query(VariableMetricsTest.description).all()
    # existing_dscrpt = set(existing_descrpt)
    raw_results = db.query(VarsLocal.description).filter(VarsLocal.hospital_id == hospital_id).all()
    existing_dscrpt = {fila[0] for fila in raw_results}

    # missing_vars = vars_df[~vars_df.apply(
    #     # lambda r: (r['ID'], r['clave'], int(r['Value']) if pd.notna(r['Value']) and str(r['Value']).isdigit() else -99) in existing_keys,
    #     lambda r: (str(r['description'])) in existing_dscrpt,
    #     axis=1
    # )].copy()
    missing_vars = vars_df[~vars_df['description'].astype(str).isin(existing_dscrpt)].copy()

    print(f"{len(missing_vars)} variables adicionales serán añadidas.")

    metrics_faltantes = {}
    for _, row in missing_vars.iterrows():
        # --- Limpieza y valores por defecto ---
        tabla = str(row.get('table') or 'NA')
        clave = str(row.get('clave')) if pd.notna(row.get('clave')) else 'NA'
        var_id = row.get('ID')
        value = row.get('Value')

        # --- Normalización de value_id ---
        if pd.notna(value) and str(value).isdigit():
            value_id = int(value)
        else:
            value_id = -99

        if pd.notna(var_id) and str(var_id).isdigit():
            var_id = int(var_id)
        else:
            var_id = -99

        # --- Añadir campo descriptivo para evitar duplicados ---
        description = str(row.get('description') or 'NA')
        tipo_variable = str(row.get('tipo_variable') or 'Altres')
        origen_variable = str(row.get('origen_variable') or 'Altres')
        codigo = str(row.get('Codigo') or '-')

        # 🔑 Nueva clave extendida con description
        key = (tabla, clave, var_id, value_id, description)

        # --- Añadir a metrics_faltantes ---
        metrics_faltantes[key] = {
            'count': 0,
            'porc_pacientes': 0,
            'Q1': np.nan,
            'Q2': np.nan,
            'Q3': np.nan,
            'cadencia': np.nan,
            'codigo': codigo,
            'last_value': None,
            'tipo_variable': tipo_variable,
            'origen_variable': origen_variable,
        }

    # --- Inserció en BD ---
    if metrics_faltantes:
        print("   💾 Insertando variables faltantes en BD...")
        metrics_faltantes_final = formatear_metrics(metrics_faltantes)
        agregar_metricas_test(metrics_faltantes_final, db, hospital_id)

    print("✅ Proceso completado con todas las variables en VariableMetricsTest.") 



def update_all_metrics_cha(db: Session, hospital_id: int, sybase_db_args: Optional[List]=None):
    """
    Calcula métricas por variable recorriendo tablas de forma optimizada (Estilo CCC).
    Actualiza la tabla VariableMetricsTest.
    """
    logger.info("Obteniendo diccionario de variables CHA...")
    print("📌 Obteniendo diccionario de variables CHA...")
    
    vars_df = get_variables_df_cha()
    base_df = get_base_cha('DT')

    print(f"✅ {len(vars_df)} variables obtenidas, {len(base_df)} tablas en base_df")
        
    if vars_df is None or not isinstance(vars_df, pd.DataFrame) or vars_df.empty:
        logger.warning("No hay variables disponibles.")
        return

    # Normalizar IDs
    vars_df['ID'] = pd.to_numeric(vars_df['ID'], errors='coerce').astype('Int64')

    # fecha_corte_str = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    # q = f"""
    #     SELECT CaseKey, RoomKey, DepartmentKey, BedKey, RecordStartDttm, CaseId FROM Datamart01.FactCaseLocation
    #     WHERE RecordStartDttm > '{fecha_corte_str}'
    #     ORDER BY BedKey, RecordStartDttm 
    #     """
    # patients_uci = dbc.cha2pd(q, 'DT')

    # q = f"""
    #     SELECT CaseKey, EncounterKey FROM Datamart01.FactCase
    #     ORDER BY RecordStartDttm
    # """

    # case_encounter = cha_both_connections('JT',q).drop_duplicates('CaseKey', keep='last')

    # q = f"""
    #     SELECT EncounterKey, PatientKey FROM Datamart01.DimEncounter
    # """
    # encounter_patient = cha_both_connections('JT',q)

    # patients_uci = pd.merge(patients_uci, case_encounter, on = 'CaseKey', how="left")

    # patients_uci = pd.merge(patients_uci, encounter_patient, on = 'EncounterKey', how="left")

    # q = f"""
    #     SELECT LocationKey, LocationTypeName, LocationName FROM Datamart01.DimLocation ORDER BY LocationKey
    # """
    # camas = cha_both_connections('JT',q)

    # camas_pivot = pd.pivot(camas, index="LocationKey", columns="LocationTypeName", values="LocationName").reset_index().drop(["DepartmentGroup", "DeptType", "Hospital", "Not Mapped"], axis=1)

    # departments = camas_pivot[(~camas_pivot.Department.isnull()) & (camas_pivot.Department!="Not Mapped")][["LocationKey", "Department"]].copy()
    # bed = camas_pivot[(~camas_pivot.Bed.isnull()) & (camas_pivot.Bed!="Not Mapped")][["LocationKey", "Bed"]].copy()
    # room = camas_pivot[(~camas_pivot.Room.isnull()) & (camas_pivot.Room!="Not Mapped")][["LocationKey", "Room"]].copy()

    # patients_uci = pd.merge(patients_uci, departments, left_on="DepartmentKey", right_on="LocationKey", how="left")
    # patients_uci = pd.merge(patients_uci, bed, left_on="BedKey", right_on="LocationKey", how="left")
    # patients_uci = pd.merge(patients_uci, room, left_on="RoomKey", right_on="LocationKey", how="left")
    # patients_uci.drop(["LocationKey_x", "LocationKey_y"], axis=1, inplace=True)
    # patients_uci.rename(columns={"Department":"Servei", "Room":"Habitacio", "Bed":"Llit"}, inplace=True)

    # q = f"""
    #     SELECT 
    #         fc.CaseKey,
    #         p.PatientKey,
    #         fct.TimestampDttm,
    #         dtt.TimestampTypeCd
    #     FROM Datamart01.DimPatient p
    #     INNER JOIN Datamart01.FactCase fc
    #         ON p.PatientKey = fc.PatientKey
    #     LEFT JOIN Datamart01.FactCaseTimestamp fct
    #         ON fc.CaseKey = fct.CaseKey
    #     LEFT JOIN Datamart01.DimTimestampType dtt
    #         ON fct.TimestampTypeKey = dtt.TimestampTypeKey;
    # """

    # admtime_distime = cha_both_connections('JT',q)

    # admtime_distime2 = admtime_distime.copy()

    # admtime_distime = admtime_distime[admtime_distime.TimestampTypeCd.isin(["AICU", "DTICU"])].copy()
    # admtime_distime = admtime_distime.sort_values(["CaseKey", "TimestampDttm"], ascending=True).drop_duplicates(["CaseKey", "TimestampTypeCd"], keep="last")
    # admtime_distime = admtime_distime.pivot(index=["CaseKey", "PatientKey"], columns="TimestampTypeCd", values="TimestampDttm").reset_index()

    # admtime_distime = admtime_distime[~(admtime_distime.AICU.isnull()) & (admtime_distime.DTICU.isnull())].copy()

    # admtime_distime.rename(columns={"AICU": "AdmTime","DTICU":"DisTime"}, inplace=True)
    # admtime_distime['ult_mes'] = pd.to_datetime(datetime.now() - timedelta(days=30))

    # admtime_distime['AdmTime'] = admtime_distime['AdmTime'].astype(str)
    # admtime_distime['AdmTime'] = pd.to_datetime(admtime_distime['AdmTime'], errors='coerce')
    # admtime_distime['AdmTime'] = admtime_distime['AdmTime'].dt.tz_localize(None)

    # admtime_distime = admtime_distime[admtime_distime.AdmTime > admtime_distime.ult_mes]

    # pats_tuple = tuple(admtime_distime.CaseKey.unique())
    # pacientes_unicos = len(pats_tuple)

    # print(f"📊 Total pacientes en el útimo mes: {pacientes_unicos}")
    
    # Tablas objetivo
    # tablas_buenas = [
    #     'DataMart01.FactCaseVariableNumFloat'
    # ]
    tablas_buenas = [
        # 'FactCaseVariableDevice',
        # 'FactCaseVariableBoolString',
        # 'FactCaseVariableChoice',
        'FactCaseVariablenumFloat',
        'FactCaseProcedure',
        'FactCaseDiagnosis', 
        'FactPharmaProductAdmin'
    ]

    # Iterar por tipos de clave (VariableID, CodeID, etc.)
    claves = vars_df['clave'].dropna().unique().tolist()
    
    for clave in claves:
        print(f"\n🔍 Procesando clave: {clave}")
        
        # Filtrar variables que usan esta clave
        ids_for_clave = vars_df[vars_df['clave'] == clave]['ID'].dropna().astype('Int64').unique().tolist()
        ids_set = set(ids_for_clave)
        if len(ids_set) == 0:
            continue

        tablas = base_df[
            (base_df['column'] == clave) &
            (base_df['table'].isin(tablas_buenas))
        ]['table'].dropna().unique().tolist()

        prefix = "DataMart01."
        tablas = [t if t.startswith(prefix) else f"{prefix}{t}" for t in tablas]

        for tabla in tablas:
            t_name = tabla.split('.')[-1]
            print(f"  📊 Tabla: {t_name}")
            
            # Detectar columnas
            date_col = _pick_date_column_for_table(base_df, t_name)
            # print(date_col)
            value_col = _pick_value_column_for_table(base_df, t_name)
            
            if not date_col:
                print(f"    ⚠️ No se encontró columna de fecha para {tabla}, saltando.")
                continue

            # 1️⃣ Calcular total de pacientes activos en la tabla (últimos 30 días) para el denominador
            fecha_corte_str = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

            # q_pats = f"SELECT COUNT(DISTINCT CaseKey) as total FROM {tabla} WHERE {date_col} >= '{fecha_corte_str}'"
            # try:
            #     df_pats = dbc.cha2pd(q_pats, 'DT')
            #     pacientes_activos_tabla = df_pats['total'].iloc[0] if df_pats is not None else 0
            # except Exception:
            #     pacientes_activos_tabla = 0
            
            # print(f"    👥 Pacientes activos (30d): {pacientes_activos_tabla}")

            total_patients_query = f"""
                SELECT DISTINCT CaseKey FROM {tabla}
                WHERE {date_col} >= '{fecha_corte_str}'
            """

            total_patients = dbc.cha2pd(total_patients_query, 'DT')
            if not isinstance(total_patients, pd.DataFrame) or total_patients.empty:
                total_patients = pd.DataFrame(columns=['CaseKey'])
            pacientes_unicos = total_patients['CaseKey'].nunique()
            pats_tuple = tuple(total_patients['CaseKey'])

            print(f"    👥 Pacientes activos (30d): {pacientes_unicos}")

            # 2️⃣ Obtener IDs presentes en la tabla
            q_ids = f"SELECT DISTINCT {clave} as var_id FROM {tabla} WHERE {clave} IS NOT NULL"
            try:
                df_ids = dbc.cha2pd(q_ids, 'DT')
            except Exception as e:
                print(f"    ⚠️ Error consultando IDs: {e}")
                continue
            
            if df_ids is None or df_ids.empty:
                continue

            # Filtrar vars_df con los IDs encontrados
            ids_presentes = set(df_ids['var_id'].dropna().astype(int))
            df_curr = vars_df[
                (vars_df['ID'].isin(ids_presentes)) & 
                (vars_df['clave'] == clave)
            ]
            
            print(f"    ✅ {len(df_curr)} variables encontradas en tabla")
            
            # metrics_tabla = {}
            
            # Agrupar por ID y Value (para variables con valor específico)
            # Nota: vars_df en CHA puede no tener columna 'Value', asumimos manejo general
            if 'Value' not in df_curr.columns:
                df_curr['Value'] = -99
                
            grouped = df_curr.groupby(['ID'])
            
            for (var_id), group_df in grouped:
                metrics_tabla = {}

                if pd.isna(var_id):
                    continue

                if isinstance(var_id, (tuple, list)):
                    var_id = var_id[0]
                
                # Metadatos
                row = group_df.iloc[0]
                raw_value = row['Value']
                if pd.isna(raw_value):
                    value_id = -99
                else:
                    # 3. Aplicamos tu lógica de conversión si NO es nulo
                    # Nota: He mantenido tu lógica, pero asegúrate de que 'value' sea string para el replace
                    str_val = str(raw_value)
                    if str_val.replace('-', '').isdigit():
                        value_id = int(float(raw_value)) # float intermedio por si viene como 5.0
                    else:
                        value_id = raw_value
                descrp = row.get('description', 'NA')
                tipo_var = row.get('tipo_variable', 'Altres')
                orig_var = row.get('origen_variable', 'Altres')
                codigo = row.get('Codigo', '-')
                
                # Determinar tipos
                is_numeric = tipo_var in ['Numèrica', 'Fàrmacs', 'Float', 'Integer']
                is_categorical = (tipo_var == 'Categòrica') and (value_id != -99)

                # 3️⃣ Calcular métricas
                stats = _calculate_quantiles_and_cadence_cha(
                    clave, var_id, value_id, tabla, value_col, date_col,
                    is_numeric, is_categorical, pacientes_unicos, pats_tuple
                )
                
                metrics_tabla[(t_name, clave, var_id, value_id, descrp)] = {
                    'count': stats.get('count', 0),
                    'porc_pacientes': stats.get('porc_pacientes', 0),
                    'Q1': stats.get('Q1', np.nan),
                    'Q2': stats.get('Q2', np.nan),
                    'Q3': stats.get('Q3', np.nan),
                    'cadencia': stats.get('cadencia', np.nan),
                    'codigo': codigo,
                    'last_value': stats.get('last_value', None),
                    'tipo_variable': tipo_var,
                    'origen_variable': orig_var,
                }

                if metrics_tabla:
                    # print(f"   💾 Insertando {len(metrics_tabla)} métricas en BD...")
                    metrics_final = formatear_metrics(metrics_tabla)
                    agregar_metricas_test(metrics_final, db, hospital_id)

            # # 4️⃣ Insertar métricas en lotes por tabla
            # if metrics_tabla:
            #     print(f"   💾 Insertando {len(metrics_tabla)} métricas en BD...")
            #     metrics_final = formatear_metrics(metrics_tabla)
            #     agregar_metricas_test(metrics_final, db)

    # # --- Bloque para añadir variables faltantes (sin datos) ---
    # print("\n🔍 Añadiendo variables faltantes...")
    
    # # Obtener qué descripciones ya tenemos en la BD para no duplicar
    # raw_results = db.query(VariableMetricsTest.description).all()
    # existing_dscrpt = {fila[0] for fila in raw_results}

    # # Identificar variables de vars_df que no están en la BD
    # missing_vars = vars_df[~vars_df['description'].astype(str).isin(existing_dscrpt)].copy()

    # print(f"⚙️ {len(missing_vars)} variables adicionales serán añadidas con contadores a 0.")

    # metrics_faltantes = {}
    # for _, row in missing_vars.iterrows():
    #     # Extracción segura de datos
    #     tabla = str(row.get('table') or 'NA')
    #     clave = str(row.get('clave')) if pd.notna(row.get('clave')) else 'NA'
    #     var_id = row.get('ID')
    #     value = row.get('Value')

    #     if pd.notna(value) and str(value).replace('.','',1).isdigit():
    #         value_id = int(float(value))
    #     else:
    #         value_id = -99

    #     if pd.notna(var_id) and str(var_id).replace('.','',1).isdigit():
    #         var_id = int(float(var_id))
    #     else:
    #         var_id = -99

    #     description = str(row.get('description') or 'NA')
    #     tipo_variable = str(row.get('tipo_variable') or 'Altres')
    #     origen_variable = str(row.get('origen_variable') or 'Altres')
    #     tech = str(row.get('tech') or '-')
    #     codigo = str(row.get('Codigo') or '-')

    #     key = (tabla, clave, var_id, value_id, description)

    #     metrics_faltantes[key] = {
    #         'count': 0,
    #         'porc_pacientes': 0,
    #         'Q1': np.nan,
    #         'Q2': np.nan,
    #         'Q3': np.nan,
    #         'cadencia': np.nan,
    #         'codigo': codigo,
    #         'last_value': None,
    #         'tipo_variable': tipo_variable,
    #         'origen_variable': origen_variable,
    #         'technology': tech
    #     }

    # if metrics_faltantes:
    #     print("   💾 Insertando variables faltantes en BD...")
    #     metrics_faltantes_final = formatear_metrics(metrics_faltantes)
    #     agregar_metricas_test(metrics_faltantes_final, db)

    print("✅ Proceso CHA completado.")


def to_native(v):
    """Convierte valores numpy.* o pandas a tipos nativos de Python."""
    if isinstance(v, (np.generic,)):
        return v.item()
    if pd.isna(v):
        return None
    return v

def agregar_metricas_test(metrics, db: Session, hospital_id: int):
    """
    Inserta o actualiza métricas en VarsLocal para el hospital dado.
    """
    nuevos, actualizados = 0, 0
    for key, m in metrics.items():
        if len(key) == 4:
            tabla, clave, var_id, value_id = key
            description = str(m.get('description', '-'))
        elif len(key) == 5:
            tabla, clave, var_id, value_id, description = key
        else:
            logger.warning(f"⚠️ Clave con formato inesperado: {key}")
            continue
        try:
            with db.begin_nested():
                var_id = safe_int(var_id)
                value_id = safe_int(value_id)
                tabla_origen = str(tabla or "-")
                clave_str = str(clave)

                existing = db.query(VarsLocal).filter_by(
                    variable_id=var_id,
                    clave=clave_str,
                    value=value_id,
                    tabla_origen=tabla_origen,
                    hospital_id=hospital_id,
                ).first()

                clean_m = {k: to_native(v) for k, v in (m or {}).items()}

                if existing:
                    existing.description = str(description or clean_m.get("description", "-"))
                    existing.tipo_variable = str(clean_m.get("tipo_variable", "Altres"))
                    existing.origen_variable = str(clean_m.get("origen_variable", "Altres"))
                    existing.last_value = safe_to_datetime(clean_m.get("last_value"))
                    existing.count = to_native(clean_m.get("count", 0))
                    existing.q1 = to_native(clean_m.get("Q1"))
                    existing.q2 = to_native(clean_m.get("Q2"))
                    existing.q3 = to_native(clean_m.get("Q3"))
                    existing.porc_pats = to_native(clean_m.get("porc_pacientes", 0))
                    existing.cadencia = str(clean_m.get("cadencia") or "-")
                    existing.codigo = str(clean_m.get('codigo') or '-')
                    actualizados += 1
                else:
                    new_entry = VarsLocal(
                        variable_id=var_id,
                        value=value_id,
                        description=description,
                        tipo_variable=str(clean_m.get("tipo_variable", "Altres")),
                        origen_variable=str(clean_m.get("origen_variable", "Altres")),
                        clave=clave_str,
                        last_value=safe_to_datetime(clean_m.get("last_value")),
                        count=to_native(clean_m.get("count", 0)),
                        q1=to_native(clean_m.get("Q1")),
                        q2=to_native(clean_m.get("Q2")),
                        q3=to_native(clean_m.get("Q3")),
                        porc_pats=to_native(clean_m.get("porc_pacientes", 0)),
                        cadencia=str(clean_m.get("cadencia") or "-"),
                        tabla_origen=tabla_origen,
                        codigo=str(clean_m.get('codigo') or '-'),
                        hospital_id=hospital_id,
                    )
                    db.add(new_entry)
                    nuevos += 1
        except Exception as e:
            logger.exception(f"Error insertando métricas para variable_id={var_id}: {e}")
            continue

    db.commit()