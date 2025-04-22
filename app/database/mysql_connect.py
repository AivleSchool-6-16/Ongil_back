# import mysql.connector
# from mysql.connector import Error
# from fastapi import HTTPException

# def get_connection():
#     try:
#         connection = mysql.connector.connect(
#             host="127.0.0.1",    # 호스트는 "localhost"로 지정
#             port=3307,           # 포트 번호를 별도의 인자로 지정
#             user="root",
#             password="1234",
#             database="backup_db",
#             # charset='utf8mb4'
#         )
#         if connection.is_connected():
#             return connection
#     except Error as e:
#         print(f"Error connecting to the database: {e}")
#         raise HTTPException(status_code=500, detail="Could not connect to the database.")

import mysql.connector
from mysql.connector import Error
from fastapi import HTTPException

def get_connection():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            port=3307,
            user="root",
            password="1234",
            database="backup_db",
            charset='utf8mb4',
            collation='utf8mb4_general_ci',  # 연결 시 사용할 콜레이션 지정
            use_pure=True  # 순수 Python 구현 사용 (일부 환경에서 도움이 될 수 있음)
        )
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"Error connecting to the database: {e}")
        raise HTTPException(status_code=500, detail="Could not connect to the database.")
