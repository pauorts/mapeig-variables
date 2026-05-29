import os
import pandas as pd
import pyodbc
import jaydebeapi
import warnings

warnings.filterwarnings('ignore', category=UserWarning)

def cha2pd(q, center):

    if center == 'DT':
        # Ruta al fitxer .jar del JDBC
        jdbc_jar = "/opt/jdbc/mssql-jdbc.jar"
        jdbc_class = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
        jdbc_url = (
            f"jdbc:sqlserver://{os.getenv('CHA_DT_DW_IP')}:{os.getenv('CHA_DT_DW_PORT')};"
            f"databaseName={os.getenv('CHA_DT_DW_DB')};"
            "encrypt=false;"
        )

        user = os.getenv('CHA_DT_DW_USER')
        password = os.getenv('CHA_DT_DW_PWD')

        try:
            conn = jaydebeapi.connect(
                jclassname=jdbc_class,
                url=jdbc_url,
                driver_args=[user, password],
                jars=jdbc_jar
            )
        except Exception as e:
            print(f"Connection error: {e}")
            return jdbc_url

        try:
            curs = conn.cursor()
            curs.execute(q)
            rows = curs.fetchall()
            cols = [desc[0] for desc in curs.description]
            data = pd.DataFrame(rows, columns=cols)
            conn.close()
            return data
        except Exception as e:
            print(f"Query error: {e}")
            return jdbc_url