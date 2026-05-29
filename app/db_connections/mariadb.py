import os
import pandas as pd
import mysql.connector
from mysql.connector import Error

def mariadb2pd(db, q):

    if db == 'tasques':
    
        try:

            conexion = mysql.connector.connect(
                host=os.environ.get('PA_HOST'),
                user=os.environ.get('PA_USER'),
                password=os.environ.get('PA_PASSWORD'),
                database=os.environ.get('PA_DB')
            )
        
        except Error as e:
        
            print(f"Connection error: {e}")
            
            return None

    elif db == 'llistagipss':

        try:

            conexion = mysql.connector.connect(
                host=os.environ.get('LLU_HOST'),
                user=os.environ.get('LLU_USER'),
                password=os.environ.get('LLU_PASSWORD'),
                database=os.environ.get('LLU_DB')
            )
        
        except Error as e:
        
            print(f"Connection error: {e}")
            
            return None

    elif db == 'mapa_nrt':

        try:

            conexion = mysql.connector.connect(
                host=os.environ.get('MAP_HOST'),
                user=os.environ.get('MAP_USER'),
                password=os.environ.get('MAP_PASSWORD'),
                database=os.environ.get('MAP_DB')
            )
        
        except Error as e:
        
            print(f"Connection error: {e}")
            
            return None
        
    try:
        
        cursor = conexion.cursor()
        cursor.execute(q)
        
        chunks = []
        
        while True:
            chunk = cursor.fetchmany(1000)
            if not chunk:
                break
            chunk_df = pd.DataFrame(chunk, columns=[col[0] for col in cursor.description])
            chunk_df = chunk_df.dropna(axis=1, how='all')  # Elimina columnas donde todas las filas son NaN
            chunks.append(chunk_df)
        
        data = pd.concat(chunks, ignore_index=True)

        cursor.close()
        conexion.close()

        return data
    
    except Exception as e:
        
        print(f"Query error: {e}")
        
        return None