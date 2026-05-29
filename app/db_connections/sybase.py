import os
import pandas as pd
import pyodbc
import warnings

warnings.filterwarnings('ignore', category=UserWarning)

def ccc2pd(q, hospital, service, db):

    pr_ip, pr_usr, pr_pwd, dw_ip, dw_usr, dw_pwd = map2keys(hospital, service)

    if 'pr' in db or 'both' in db:

        conn_str = (
            f"DRIVER={{FreeTDS}};"
            f"SERVER={pr_ip};"
            f"PORT={os.getenv('SYBASE_PORT')};"
            f"DATABASE={os.getenv('SYBASE_DATABASE')};"
            f"UID={pr_usr};"
            f"PWD={pr_pwd};"
            f"TDS_Version={os.getenv('SYBASE_TDS_VERSION')};"
            )

        try:
        
            conexion = pyodbc.connect(conn_str)
            
        except pyodbc.Error as e:
            
            print(f"Connection error: {e}")
            
            return conn_str
        
        try:
    
            chunks = []
            for chunk in pd.read_sql_query(sql=q, con=conexion, chunksize=1000):
                chunks.append(chunk)
            data_pr = pd.concat(chunks, ignore_index=True)

            conexion.close()
        
        except Exception as e:
            
            print(f"Query error: {e}")
            
            # return conn_str
        
    if 'dw' in db or 'both' in db:

        conn_str = (
            f"DRIVER={{FreeTDS}};"
            f"SERVER={dw_ip};"
            f"PORT={os.getenv('SYBASE_PORT')};"
            f"DATABASE={os.getenv('SYBASE_DATABASE')};"
            f"UID={dw_usr};"
            f"PWD={dw_pwd};"
            f"TDS_Version={os.getenv('SYBASE_TDS_VERSION')};"
            )
        
        try:
        
            conexion = pyodbc.connect(conn_str)
            
        except pyodbc.Error as e:
            
            print(f"Connection error: {e}")
            
            # return conn_str
        
        try:
    
            chunks = []
            for chunk in pd.read_sql_query(sql=q, con=conexion, chunksize=1000):
                chunks.append(chunk)
            data_dw = pd.concat(chunks, ignore_index=True)
    
            conexion.close()
        
        except Exception as e:
            
            print(f"Query error: {e}")
            
            # return conn_str

    if 'pr' in db:

        return data_pr

    elif 'dw' in db:

        return data_dw

    elif 'both' in db:

        data = pd.concat([data_pr, data_dw]).drop_duplicates(keep='first').reset_index(drop=True)
        
        return data
    
def map2keys(hospital, service):

    d = {'hospital': ['jx', 'jx', 
                  'jx', 'jx', 
                  'jx', 'jx',
                  'vh', 'vh', 
                  'vh', 'vh', 
                  'vh', 'vh',
                  'vc', 'vc', 
                  'ar', 'ar', 
                  'gt', 'gt'],
     'service': ['uci', 'uci',
                'ucip', 'ucip', 
                'rea', 'rea',
                'uci', 'uci', 
                'ucip', 'ucip', 
                'ucin', 'ucin',
                'uci', 'uci', 
                'uci', 'uci', 
                'uci', 'uci'],
     'db': ['pr', 'dw', 
            'pr', 'dw', 
            'pr', 'dw',
            'pr', 'dw', 
            'pr', 'dw', 
            'pr', 'dw',
            'pr', 'dw', 
            'pr', 'dw', 
            'pr', 'dw'],
     'ip': [os.getenv('SYBASE_HOST_JX_UCI_PR'), os.getenv('SYBASE_HOST_JX_UCI_DW'),
            os.getenv('SYBASE_HOST_JX_UCIP_PR'), os.getenv('SYBASE_HOST_JX_UCIP_DW'),
           os.getenv('SYBASE_HOST_JX_REA_PR'), os.getenv('SYBASE_HOST_JX_REA_DW'),
           os.getenv('SYBASE_HOST_VH_UCI_PR'), os.getenv('SYBASE_HOST_VH_UCI_DW'),
           os.getenv('SYBASE_HOST_VH_UCIP_PR'), os.getenv('SYBASE_HOST_VH_UCIP_DW'),
           os.getenv('SYBASE_HOST_VH_UCIN_PR'), os.getenv('SYBASE_HOST_VH_UCIN_DW'),
           os.getenv('SYBASE_HOST_VC_UCI_PR'), os.getenv('SYBASE_HOST_VC_UCI_DW'),
           os.getenv('SYBASE_HOST_AR_UCI_PR'), os.getenv('SYBASE_HOST_AR_UCI_DW'),
           os.getenv('SYBASE_HOST_GT_UCI_PR'), os.getenv('SYBASE_HOST_GT_UCI_DW')],
        'usr': [os.getenv('SYBASE_USER_GENERIC'), os.getenv('SYBASE_USER_GENERIC'),
            os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER'),
           os.getenv('SYBASE_USER'), os.getenv('SYBASE_USER')],
        'pwd': [os.getenv('SYBASE_PASSWORD_GENERIC'), os.getenv('SYBASE_PASSWORD_GENERIC'),
            os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD_GENERIC2'), os.getenv('SYBASE_PASSWORD_GENERIC2'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD'),
           os.getenv('SYBASE_PASSWORD'), os.getenv('SYBASE_PASSWORD')]}
    
    df = pd.DataFrame(data=d)

    pr_ip = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='pr'))]['ip'].values[0]
    pr_usr = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='pr'))]['usr'].values[0]
    pr_pwd = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='pr'))]['pwd'].values[0]

    dw_ip = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='dw'))]['ip'].values[0]
    dw_usr = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='dw'))]['usr'].values[0]
    dw_pwd = df[(df['hospital']==hospital) & ((df['service']==service)) & ((df['db']=='dw'))]['pwd'].values[0]

    return pr_ip, pr_usr, pr_pwd, dw_ip, dw_usr, dw_pwd