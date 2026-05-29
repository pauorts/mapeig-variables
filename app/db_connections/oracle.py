import os
import pandas as pd
import oracledb

# Segons ChatGPT-4o, la BBDD de cronicitat te alguna configuració de contrasenyes 'antiga' que no la fa compatible amb la versió thin de l'última versió del package oracledb.
# Per arreglar-ho, s'hauria de descarregar manualment un driver d'oracle instant client i incloure la seva instalació al dockerfile.

def ecap_etls(f, entorn):

    if entorn == 'prod':

        dblinks = ['@p6209_prod','@p6211_prod']

    else:
    
        dblinks = ['@p6209_exp','@p6211_exp']
    
    df = pd.DataFrame()

    for dblink in dblinks:
    
        df = pd.concat([df, f(dblink)])
        print('dblink', dblink, 'extracted!')

    return df

def oracle2pd(db, q):

    if db == 'ecap':
    
        try:

            dsn_tns = oracledb.makedsn(os.environ.get('ECAP_HOST'), os.environ.get('ECAP_PORT'), service_name=os.environ.get('ECAP_SERVICE'))
            conexion = oracledb.connect(user=os.environ.get('ECAP_USERNAME'), password=os.environ.get('ECAP_PASSWORD'), dsn=dsn_tns)
        
        except oracledb.DatabaseError as e:
        
            print(f"Connection error: {e}")
            
            return dsn_tns

    # elif db == 'cronicitat': 

    #     try:

    #         dsn_tns = oracledb.makedsn(os.environ.get('CRON_HOST'), os.environ.get('CRON_PORT'), service_name=os.environ.get('CRON_SERVICE'))
    #         conexion = oracledb.connect(user=os.environ.get('CRON_USERNAME'), password=os.environ.get('CRON_PASSWORD'), dsn=dsn_tns)
        
    #     except oracledb.DatabaseError as e:
        
    #         print(f"Connection error: {e}")
            
    #         return dsn_tns

    elif db == 'uci':

        try:

            dsn_tns = oracledb.makedsn(os.environ.get('EXADOT_HOST'), os.environ.get('EXADOT_PORT'), service_name=os.environ.get('EXADOT_SERVICE'))
            conexion = oracledb.connect(user=os.environ.get('EXADOT_USERNAME'), password=os.environ.get('EXADOT_PASSWORD'), dsn=dsn_tns)
        
        except oracledb.DatabaseError as e:
        
            print(f"Connection error: {e}")
            
            return dsn_tns
        
    try:
        
        cursor = conexion.cursor()
        cursor.execute(q)
        
        chunks = []
        
        while True:
            chunk = cursor.fetchmany(1000)
            if not chunk:
                break
            chunk_df = pd.DataFrame(chunk, columns=[col[0] for col in cursor.description])
            chunks.append(chunk_df)
        
        data = pd.concat(chunks, ignore_index=True)

        cursor.close()
        conexion.close()

        return data
    
    except Exception as e:
        
        print(f"Query error: {e}")
        
        return None