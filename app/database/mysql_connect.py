import mysql.connector
from mysql.connector import Error
from fastapi import HTTPException

def get_connection():
    try:
        connection = mysql.connector.connect(
            host="ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com",
            user="admin",
            password="aivle202406",
            database="ongildb", charset='utf8mb4'
        )
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"Error connecting to the database: {e}")
        raise HTTPException(status_code=500, detail="Could not connect to the database.")
