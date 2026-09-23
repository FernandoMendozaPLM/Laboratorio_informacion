from dotenv import load_dotenv
import os
import pyodbc
import time

load_dotenv()   #Cargar variables de entorno desde el archivo .env
USER = os.getenv("USER")
PASSWORD = os.getenv("PASSWORD")

#Scrip para conexión a SQL Server
connection_scrip = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=172.31.4.184,3364;"
    "DATABASE=Medinet;"
    f"UID={USER};"
    f"PWD={PASSWORD};"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


def create_connection(
        connection_scrip: str,
        max_attempts = 10,
        retry_seconds = 1,
        timeout = 10
    ):
    """Intenta conectarse a la base de datos"""

    for attempt in range(1, max_attempts +1):
        try:
            print(f"Intento {attempt}/{max_attempts}: "
                  f"Estableciendo conexión...")
            
            connection = pyodbc.connect(
            connection_scrip,
            timeout= timeout # tiempo que tarda en intentar volver a conectarse antes de fallar
            ) 

            print("!!!Conexión exitosa¡¡¡")
            return connection

        except pyodbc.Error as e:
            print(f"Error de conexión: {e}")

            if attempt < max_attempts:
                print(f"Reintentnado en {retry_seconds} segundos...")
                time.sleep(retry_seconds) # despues que falló un intento espera para volver a intentar
                
    raise ConnectionError("No fue posbile conectarse a la base de datos")

connection = create_connection(connection_scrip)


