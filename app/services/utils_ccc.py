import pandas as pd
import numpy as np
from functools import lru_cache
from typing import Optional
# from app.connections import map2keys, ccc2pd

# try:
#     from app.connections.sybase import Connection
# except Exception as e:
#     raise ImportError("No se encontró ccc2pd. Coloca tu connections.py en app/ o asegúrate del path.") from e

try:
    import app.db_connections as dbc
except Exception as e:
    raise ImportError("No se encontró db_connections.") from e


# conn = Connection()

def safe_ccc2pd(q: str, *args, **kwargs) -> Optional[pd.DataFrame]:
    """Llama a conn.ccc2pd y garantiza que devuelve DataFrame o None."""
    try:
        res = dbc.ccc2pd(q, *args, **kwargs)
        if isinstance(res, pd.DataFrame):
            return res
        # si res es str (conn error) o None, devuelvo None
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@lru_cache(maxsize=1)
def get_base(hosp):

    """objectes del sistema"""

    q = """SELECT id, name, type FROM Patient..SYSOBJECTS"""
    
    p_objects = safe_ccc2pd(q, hosp, 'uci', 'prod')
    p_objects['db'] = 'Patient'
    
    q = """SELECT id, name, type FROM System..SYSOBJECTS"""
    
    s_objects = safe_ccc2pd(q, hosp, 'uci', 'prod')
    s_objects['db'] = 'System'
    
    objects = pd.concat([p_objects, s_objects]).drop_duplicates(keep='first').sort_values(['id']).reset_index(drop=True)
    
    del p_objects, s_objects
    
    objects.rename({'type':'ttype','name':'table'}, axis=1, inplace=True)
    
    """columnes del sistema"""
    
    q = """SELECT id, colid, name, remote_name FROM Patient..SYSCOLUMNS"""
    
    p_columns = safe_ccc2pd(q, hosp, 'uci', 'prod')
    p_columns['db'] = 'Patient'
    
    q = """SELECT id, colid, name, remote_name FROM System..SYSCOLUMNS"""
    
    s_columns = safe_ccc2pd(q, hosp, 'uci', 'prod')
    s_columns['db'] = 'System'
    
    columns = pd.concat([p_columns, s_columns]).drop_duplicates(keep='first').sort_values(['id','colid']).reset_index(drop=True)
    
    del p_columns, s_columns
    
    columns.rename({'name':'column','remote_name':'column_remote'}, axis=1, inplace=True)
    
    """creem taula base"""
    
    df = pd.merge(objects, columns, on=['db','id'], how='left')
    
    df['source'] = np.where(df['table'].str.startswith('S_'), 'system', 'patient')

    return df


def cross_join_tables(group):
    """Realiza cross join entre tablas de un mismo grupo de ID"""
    tables = group['table'].unique()
    
    if len(tables) < 2:
        return group
    
    # Separar por tabla
    df1 = group[group['table'] == tables[0]].copy()
    df2 = group[group['table'] == tables[1]].copy()
    
    # Cross join usando merge con key temporal
    df1['_key'] = 1
    df2['_key'] = 1
    crossed = df1.merge(df2, on='_key', suffixes=('_1', '_2'))
    
    # Combinar columnas de forma eficiente
    return pd.DataFrame({
        'table': crossed['table_1'] + '|' + crossed['table_2'],
        'clave': crossed['clave_1'],
        'ID': crossed['ID_1'],
        'description': crossed['description_1'].fillna('') + ' | ' + crossed['description_2'].fillna(''),
        'Value': crossed['Value_1'].combine_first(crossed['Value_2']),
        'tipo_variable': crossed['tipo_variable_2'].combine_first(crossed['tipo_variable_1']),
        'origen_variable': crossed['origen_variable_2'].combine_first(crossed['origen_variable_1']),
        'Codigo': crossed['Codigo_1'].combine_first(crossed['Codigo_2'])
    })

# def cross_join_tables(group):
#     """Realiza cross join entre tablas de un mismo grupo de ID"""
#     tables = group['table'].unique()

#     if len(tables) < 2:
#         return group

#     if 'variableref' in str(tables[1]).lower():
#         return group[group['table'] == tables[1]].copy()
#     else:
#         return group[group['table'] == tables[0]].copy()


def priority_score(row, column):
    """Calcula prioridad para selección de columnas"""
    col = row['column']
    table = row['table']

    # Casos especiales con máxima prioridad
    if (table == 'S_DefDevPars' and col == 'DevTypeID') or \
       (table == 'S_ExamAddInfo' and col == 'ExamVarID'):
        return -1
    
    # Coincidencia exacta o parcial con column
    column_parts = column.split('|')
    if col == column or col in column_parts:
        return 0
    
    # Limpiar col de las partes de column
    col_cleaned = col
    for part in column_parts:
        col_cleaned = col_cleaned.replace(part, "")
    
    # Comparaciones con prefijo de tabla
    table_prefix = table.replace("S_", "").replace("Ref", "")
    col_lower = col_cleaned.lower().strip()
    table_lower = table_prefix.lower()
    
    if col_lower == table_lower:
        return 1
    elif (col_lower in table_lower) or (table_lower in col_lower):
        return 2
    elif 'group' in col_lower:
        return 3
    
    return 4


def get_best_column(df, pattern, priority_col, tables_filter=None):
    """Función auxiliar para filtrar y seleccionar la mejor columna por tabla"""
    filtered = df[df['column'].str.contains(pattern, case=False, na=False)]
    
    if tables_filter is not None:
        filtered = filtered[filtered['table'].isin(tables_filter)]
    
    if filtered.empty:
        return pd.DataFrame()
    
    filtered = filtered.copy()
    filtered['priority'] = filtered.apply(lambda row: priority_score(row, priority_col), axis=1)
    
    return (filtered.sort_values(by=['table', 'priority'])
            .groupby('table', as_index=False)
            .first()
            .drop(columns=['priority']))


def get_variables_dict(base, hosp):
    """Función principal optimizada para obtener diccionario de variables"""
    
    # Filtro inicial optimizado
    dict_df = base[
        (base['source'] == 'system') & 
        (base['ttype'] == 'U ') & 
        (~base['table'].str.contains('DW|old|Deleted|temp|def', case=False, na=False))
    ].reset_index(drop=True)
    
    # Obtener columnas relevantes usando la función auxiliar
    ids_df = get_best_column(
        dict_df[dict_df['column'].str.contains('ID', case=True, na=False)],
        'ID',
        "ID|VariableID|VarID"
    )
    
    if ids_df.empty:
        return pd.DataFrame()
    
    tables = ids_df['table'].tolist()
    
    # Procesar todas las columnas necesarias
    names_df = get_best_column(dict_df, 'name|StringValue|descrip', "Name")
    value_df = get_best_column(dict_df, 'code', "Code", tables)
    datatype_df = get_best_column(dict_df, 'DataType', "DataType", tables)
    
    # VarType con filtro adicional
    vartype_filtered = dict_df[
        dict_df['column'].str.contains('VarType|Type', case=False, na=False) &
        ~dict_df['column'].str.contains('ID', case=True, na=False) &
        dict_df['table'].isin(tables)
    ]
    vartype_df = get_best_column(vartype_filtered, 'VarType|Type', "VarType|Type")
    
    # Merge eficiente de todas las columnas
    table_df = (ids_df[['table', 'column']].rename(columns={'column': 'ID'})
                .merge(names_df[['table', 'column']].rename(columns={'column': 'name'}), 
                       on='table', how='inner')
                .merge(value_df[['table', 'column']].rename(columns={'column': 'value'}), 
                       on='table', how='left')
                .merge(vartype_df[['table', 'column']].rename(columns={'column': 'vartype'}), 
                       on='table', how='left')
                .merge(datatype_df[['table', 'column']].rename(columns={'column': 'datatype'}), 
                       on='table', how='left'))
    
    # Procesar queries y construir resultados
    results = []
    
    for _, row in table_df.iterrows():
        # Construir lista de columnas válidas
        cols = [row['ID'], row['name'], row.get('value'), 
                row.get('vartype'), row.get('datatype')]
        cols = [c for c in cols if pd.notna(c) and isinstance(c, str)]
        
        if len(cols) < 2:
            continue
        
        # Query dinámica
        query = f"SELECT {', '.join(cols)} FROM System..{row['table']}"
        
        try:
            dat = safe_ccc2pd(query, hosp, 'uci', 'prod')
            
            if not isinstance(dat, pd.DataFrame) or dat.empty:
                continue
            
            # Procesar resultados
            for _, drow in dat.dropna(subset=[row['ID'], row['name']]).iterrows():
                results.append({
                    "table": row['table'],
                    "clave": row['ID'],
                    "ID": drow[row['ID']],
                    "description": drow[row['name']],
                    "Value": drow.get(row.get('value')) if pd.notna(row.get('value')) else None,
                    "tipo_variable": drow.get(row.get('datatype')) if pd.notna(row.get('datatype')) else None,
                    "origen_variable": drow.get(row.get('vartype')) if pd.notna(row.get('vartype')) else None
                })
        except Exception as e:
            print(f"⚠️ Error al ejecutar query en {row['table']}: {e}")
            continue

    if not results:
        return pd.DataFrame()
    
    # Construir DataFrame final
    dict_result = pd.DataFrame(results)
    
    # Separar valores numéricos y códigos
    dict_result['value_num'] = pd.to_numeric(dict_result['Value'], errors='coerce')
    dict_result['Codigo'] = np.where(dict_result['table'] == 'S_CodeRef',
                                    dict_result['Value'],
                                    np.nan)
    dict_result['Value'] = dict_result['value_num']
    dict_result['Value'] = np.where(dict_result['table'] == 'S_CodeRef',
                                    -99,
                                    dict_result['Value'])
    dict_result.drop(columns='value_num', inplace=True)
    
    # Identificar IDs con múltiples tablas
    multi_table_mask = (dict_result.groupby(['clave', 'ID'])['table']
                        .transform('nunique') > 1)
    
    df_multi = dict_result[multi_table_mask].copy()
    df_single = dict_result[~multi_table_mask].copy()
    
    # Procesar cross joins si hay datos multi-tabla
    if not df_multi.empty:
        df_multi_processed = (df_multi.groupby(['clave', 'ID'], group_keys=False)
                              .apply(cross_join_tables)
                              .reset_index(drop=True))
        dict_result = pd.concat([df_single, df_multi_processed], ignore_index=True)
    else:
        dict_result = df_single
    

    ## extract patient info
    q = f"""SELECT TOP 1 * FROM P_GeneralData"""
    adm_data = safe_ccc2pd(q, hosp, 'uci', 'prod')

    # adm_data.columns = adm_data.columns.str.lower()
    adm_data['table'] = 'P_GeneralData'
    adm_data['row'] = adm_data.index

    adm_datam = adm_data.melt(
        ['PatientID', 'table', 'row'],
        var_name='column',
        value_name='column_value'
    ).sort_values(['PatientID', 'table', 'row']).reset_index(drop=True).drop_duplicates(subset='column')

    rows_adm = []
    for col in adm_datam.column:
        row = {"table": 'P_GeneralData', 'description': col, 'tipo_variable': 'Admissió', 'origen_variable': 'Admissió'}
        rows_adm.append(row)
    dict_result = pd.concat([dict_result, pd.DataFrame(rows_adm)])
    
    q = f"""SELECT TOP 1 * FROM P_DischargeData"""
    disch_data = safe_ccc2pd(q, hosp, 'uci', 'prod')

    # disch_data.columns = disch_data.columns.str.lower()
    disch_data['table'] = 'P_DischargeData'
    disch_data['row'] = disch_data.index

    disch_datam = disch_data.melt(
        ['PatientID', 'table', 'row'],
        var_name='column',
        value_name='column_value'
    ).sort_values(['PatientID', 'table', 'row']).reset_index(drop=True).drop_duplicates(subset='column')

    rows_disch = []
    for col in disch_datam.column:
        row = {"table": 'P_DischargeData', 'description': col, 'tipo_variable': 'Alta', 'origen_variable': 'Alta'}
        rows_disch.append(row)
    dict_result = pd.concat([dict_result, pd.DataFrame(rows_disch)])

    
    # Conversiones finales
    dict_result['ID'] = pd.to_numeric(dict_result['ID'], errors='coerce')
    dict_result['Value'] = pd.to_numeric(dict_result['Value'], errors='coerce')
    dict_result['Value'] = dict_result['Value'].fillna(-99)
    dict_result['Codigo'] = dict_result['Codigo'].fillna('-')

    map_tipo_variable = {
        0: 'Numèrica',
        1: 'Categòrica',
        2: 'Binaria',
        3: 'Text lliure',
        4: 'Altres'
    }
    
    map_origen_variable_variableID = {
        1: 'Monitoritzada',
        2: 'Laboratori',
        4: 'Observacional',
        8: 'Derivada'
    }
    
    map_origen_variable_sequenceID = {
        0: 'Inserció',
        1: 'Lesió',
        2: 'Procediment infermera',
        3: 'Scores',
        4: 'Valoració'
    }
    
    # --- Transformación de tipo_variable ---
    dict_result['tipo_variable'] = np.where(
        dict_result['clave'] == 'VariableID',
        dict_result['tipo_variable'].map(map_tipo_variable).fillna('Altres'),
        np.select(
            [
                dict_result['table'].str.contains('pharma', case=False, na=False),
                dict_result['table'].str.contains('cod', case=False, na=False),
                dict_result['table'].str.contains('P_GeneralData', case=False, na=False),
                dict_result['table'].str.contains('P_DischargeData', case=False, na=False),
            ],
            [
                'Fàrmacs',
                'Codis i procediments',
                'Admissió',
                'Alta'
            ],
            default='Altres'
        )
    )
    
    # --- Transformación de origen_variable ---
    dict_result['origen_variable'] = np.select(
        [
            dict_result['clave'] == 'VariableID',
            dict_result['clave'] == 'SequenceID'
        ],
        [
            dict_result['origen_variable'].map(map_origen_variable_variableID).fillna('Altres'),
            dict_result['origen_variable'].map(map_origen_variable_sequenceID).fillna('Altres')
        ],
        default=dict_result['tipo_variable']
    )
    
    return dict_result