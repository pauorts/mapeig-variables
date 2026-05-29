import os
import pandas as pd
import math
from supabase import create_client, Client
import httpx 
from sqlalchemy import create_engine
from postgrest.exceptions import APIError


def connect2supabase():
    
    try:
        
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        supabase_email = os.environ.get("SUPABASE_EMAIL")
        supabase_pwd = os.environ.get("SUPABASE_PASSWORD")
        
        supabase = create_client(supabase_url=supabase_url, supabase_key=supabase_key)
        
        supabase.auth.sign_in_with_password({"email": supabase_email, "password": supabase_pwd})
        
        return supabase

    except httpx.HTTPStatusError as e:
        
        print(f"HTTP error: {e}")
        
        return None
    
    except httpx.RequestError as e:
        
        print(f"Connection error: {e}")
        
        return None

def postgres2pd(q):

    host = os.environ.get("SPOSTGRES_HOST")
    port = os.environ.get("SPOSTGRES_PORT")
    database = os.environ.get("SPOSTGRES_SERVICE")
    user = os.environ.get("SPOSTGRES_USERNAME")
    password = os.environ.get("SPOSTGRES_PASSWORD")

    try:

        engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}")
        
        chunks = []

        for chunk in pd.read_sql_query(sql=q, con=engine, chunksize=1000):
            
            chunks.append(chunk)
        
        df = pd.concat(chunks, ignore_index=True)

        return df

    except Exception as e:
        print(f"Error en la consulta: {e}")
        return engine

    finally:

        engine.dispose()

def pandas2supabase(df, table_name, mode):

    df.columns = df.columns.str.lower()
    
    df = df.applymap(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if isinstance(x, pd.Timestamp) else x)

    def convert_numeric_strings(x):
        if isinstance(x, str):
            if ',' in x:
                try:
                    return float(x.replace(',', '.'))
                except ValueError:
                    return x
            elif x.isdigit():
                return x
        return x

    df = df.applymap(convert_numeric_strings)
    
    df_supabase = df.to_dict(orient="records")
    
    df_supabase = [
    {
        key: (None if isinstance(value, float) and math.isnan(value) else
              int(value) if isinstance(value, float) and value.is_integer() else value)
        for key, value in record.items()
    }
    for record in df_supabase]

    client = connect2supabase()

    try:
        if mode == 'upsert':
            response = client.table(table_name).upsert(df_supabase).execute()
        else:
            response = client.table(table_name).insert(df_supabase).execute()
    except APIError as e:
        print("Error details (raw):", e.args)
        print("Error JSON:", e.args[0] if e.args else "No JSON response")
    except Exception as ex:
        print("Unexpected error:", ex)
    client.auth.sign_out()

def truncate(field, table_name):

    client = connect2supabase()
    client.table(table_name).delete().neq(field, 1).execute()
    client.auth.sign_out()
    