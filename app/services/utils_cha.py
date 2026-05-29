import pandas as pd
import numpy as np
from functools import lru_cache
from typing import Optional

try:
    import app.db_connections as dbc
except Exception as e:
    raise ImportError("No se encontró db_connections.") from e


@lru_cache(maxsize=1)
def get_base_cha(hospital: str):
    """
    Obtiene metadata de todas las tablas del schema DataMart01
    en la base de datos CentricityDW.
    """

    # Objetos (tablas)
    q_objects = """
        SELECT o.object_id AS id,
               o.name AS [table],
               o.type AS ttype,
               s.name AS schema_name
        FROM sys.objects o
        JOIN sys.schemas s ON o.schema_id = s.schema_id
        WHERE o.type = 'U'
          AND s.name = 'DataMart01'
        ORDER BY o.name
    """
    objects = dbc.cha2pd( q_objects, hospital)

    # Columnas
    q_columns = """
        SELECT c.object_id AS id,
               c.column_id AS colid,
               c.name AS [column],
               t.name AS data_type,
               c.max_length,
               c.precision,
               c.scale,
               c.is_nullable
        FROM sys.columns c
        JOIN sys.objects o ON c.object_id = o.object_id
        JOIN sys.schemas s ON o.schema_id = s.schema_id
        JOIN sys.types t ON c.user_type_id = t.user_type_id
        WHERE s.name = 'DataMart01'
        ORDER BY o.name, c.column_id
    """
    columns = dbc.cha2pd( q_columns, hospital)

    # Merge tablas y columnas
    df = pd.merge(objects, columns, on='id', how='left')
    df['source'] = 'patient'  # como en tu ejemplo anterior
    df['db_name'] = 'CentricityDW'

    return df


####REF TABLES
@lru_cache(maxsize=1)
def get_varref_cha() -> pd.DataFrame:
    df = dbc.cha2pd("SELECT VariableId, VariableKey, Name, ValueChoiceName, ValueChoiceId, VariableTypeName, DataType FROM DataMart01.DimVariable", 'DT').drop_duplicates()
    if df is None or df.empty:
        df = pd.DataFrame(columns=['VariableID', 'VariableKey', 'Name', 'ValueChoiceName', 'ValueChoiceId', 'VariableGroupName', 'VariableTypeName', 'DataType' ])
    return df

@lru_cache(maxsize=1)
def get_pharma_cha() -> pd.DataFrame:
    pharma = dbc.cha2pd("SELECT PharmaProductKey, ProductName, GroupName FROM DataMart01.DimPharmaProduct", 'DT').drop_duplicates()
    if pharma is None or pharma.empty:
        pharma = pd.DataFrame()

    return pharma

@lru_cache(maxsize=1)
def get_code_cha() -> pd.DataFrame:
    code = dbc.cha2pd("SELECT CodedItemKey, CodedItemName, CodeGroupKey, CodedItemCode AS Codigo FROM DataMart01.DimCodedItem", 'DT').drop_duplicates()
    if code is None or code.empty:
        code = pd.DataFrame()

    group = dbc.cha2pd("SELECT CodeGroupKey, CodeGroupName, CodingSystemKey FROM DataMart01.DimCodeGroup", 'DT').drop_duplicates()
    if group is None or group.empty:
        group = pd.DataFrame()

    sys = dbc.cha2pd("SELECT CodingSystemKey, CodingSystemName FROM DataMart01.DimCodingSystem", 'DT').drop_duplicates()
    if sys is None or sys.empty:
        sys = pd.DataFrame()

    code = code.merge(group, on='CodeGroupKey', how='left').merge(sys, on='CodingSystemKey', how='left').drop_duplicates()
    return code

@lru_cache(maxsize=1)
def get_seqs_cha() -> pd.DataFrame:
    seqs = dbc.cha2pd("SELECT ConsumableId, ConsumableName FROM DataMart01.DimConsumable", 'DT').drop_duplicates()
    if seqs is None or seqs.empty:
        seqs = pd.DataFrame()
    
    return seqs

@lru_cache(maxsize=1)
def get_variables_df_cha() -> pd.DataFrame:
    """Construye df con columnas: ID, Code (opcional), description, clave ('VariableID'/'PharmaID'/'CodeID')"""
    varref = get_varref_cha()
    pharma = get_pharma_cha()
    code = get_code_cha()
    seqs = get_seqs_cha()

    parts = []

    # VAR REF (VariableID)
    if not varref.empty:
        vr = varref.copy()
        vr['description'] = vr.apply(
            lambda r: f"{r['Name']} | {r['ValueChoiceName']}" if pd.notna(r.get('ValueChoiceName')) else r['Name'],
            axis=1
        )
        vr2 = vr.rename(columns={'VariableKey':'ID', 'DataType':'tipo_variable', 'ValueChoiceId':'Value', 'VariableTypeName':'origen_variable'}).drop(columns=['VariableId', 'Name','ValueChoiceName'], errors='ignore')
        vr2['clave'] = 'Variablekey'
        vr2['Codigo'] = pd.NA

        parts.append(vr2[['ID','Value','description','clave', 'tipo_variable', 'origen_variable', 'Codigo']])


    # PHARMA
    if not pharma.empty:
        p = pharma.copy()
        p['description'] = p.apply(lambda r: f"{r.get('ProductName','') } | { r.get('GroupName','') }".strip(" | "), axis=1)
        p2 = p.rename(columns={'PharmaProductKey':'ID'}).drop(columns=['ProductName','GroupName'], errors='ignore')
        p2['clave'] = 'PharmaProductKey'
        p2['tipo_variable'] = 'Fármaco'
        p2['origen_variable'] = 'Fàrmacs'
        p2['Codigo'] = pd.NA
        parts.append(p2[['ID','description','clave', 'tipo_variable', 'origen_variable', 'Codigo']])


    # CODE
    if not code.empty:
        c = code.copy()
        c['description'] = c.apply(lambda r: f"{r.get('CodedItemName','')} | {r.get('CodingSystemName','')}".strip(" | "), axis=1)
        c2 = c.rename(columns={'CodedItemKey':'ID', 'CodingSystemName':'origen_variable'}).drop(columns=['CodedItemName','CodeGroupName','CodingSystemName','CodeGroupKey','CodingSystemKey'], errors='ignore')
        c2['clave'] = 'CodedItemKey'
        c2['tipo_variable'] = 'Diagnósticos y procedimientos'
        parts.append(c2[['ID','description','clave', 'tipo_variable', 'origen_variable', 'Codigo']])

    # SEQS
    if not seqs.empty:
        s = seqs.copy()
        s['description'] = s['ConsumableName'].fillna('')
        s2 = s.rename(columns={'ConsumableId':'ID'}).drop(columns=['ConsumableName'], errors='ignore')
        s2['clave'] = 'ConsumableId'
        s2['tipo_variable'] = 'Inserció'
        s2['origen_variable'] = 'Inserciones'
        s2['Codigo'] = pd.NA
        parts.append(s2[['ID','description','clave', 'tipo_variable', 'origen_variable', 'Codigo']])

    if len(parts) == 0:
        return pd.DataFrame(columns=['ID','description','clave', 'tipo_variable', 'origen_variable'])

    dict_variables = pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
    # asegurar columnas
    if 'Value' not in dict_variables.columns:
        dict_variables['Value'] = pd.NA

    if 'Codigo' not in dict_variables.columns:
        dict_variables['Codigo'] = pd.NA

    # if 'DataType' not in dict_variables.columns:
    #     dict_variables['DataType'] = pd.NA

    # normalizar tipo ID como int where possible
    dict_variables['ID'] = pd.to_numeric(dict_variables['ID'], errors='coerce')
    # dict_variables['ID'] = dict_variables['ID'].astype(str)

    return dict_variables