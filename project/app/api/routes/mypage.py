# mypage - 정보 조회, 수정, 탈퇴 
import hashlib
import traceback
from typing import Dict
import mysql.connector
from fastapi import APIRouter, HTTPException, status

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="password",
        database="ongil"
    )

def execute_query(query: str, params: tuple = ()):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)  # dictionary=True → 결과를 dict로 받음
        cursor.execute(query, params)
        
        if query.strip().lower().startswith("select"):
            result = cursor.fetchall()
        else:
            conn.commit()
            result = None
        
        return result
    except Exception as e:
        # 에러 추적 로그
        traceback.print_exc()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

router = APIRouter()

@router.get("/mypage_load")
def mypage_load(email: str):
    try:
        query = "SELECT * FROM user_data WHERE user_email = %s"
        user_info = execute_query(query, (email,))
        return {"user_info": user_info}
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="마이페이지 정보 조회 실패"
        )


@router.get("/check_password")
def check_password(email:str ,password:str):
    try:
        query_user = "SELECT user_ps FROM user_data WHERE user_email = %s"
        user_record = execute_query(query_user, (email,))

        if not user_record:
            raise HTTPException(status_code=404, detail="해당 이메일의 사용자를 찾을 수 없습니다.")

        db_hashed_ps = user_record[0]['user_ps']
        given_hashed_ps = hash_password(password)

        if db_hashed_ps != given_hashed_ps: # 비밀번호 해쉬값 불일치
            raise HTTPException(status_code=400, detail="incorrect password!")
        return {"message": "비밀번호 일치."}

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="비밀번호 검증 실패"
        )
    
@router.put("/update_user") # 사용자 정보 업데이트 
def update_user(email: str, update_data: Dict[str, str]):
    try:
        allowed_columns = {"user_ps", "user_dept", "jurisdiction"}
        
        # 전달받은 update_data 중 허용된 컬럼만 추출
        filtered_data = {
            key: value 
            for key, value in update_data.items() 
            if key in allowed_columns
        }
        
        if not filtered_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # 동적 SQL 쿼리 생성
        set_clause = ", ".join([f"{key} = %s" for key in filtered_data.keys()])
        values = list(filtered_data.values()) + [email]
        
        query = f"UPDATE user_data SET {set_clause} WHERE user_email = %s"
        
        # 쿼리 실행
        execute_query(query, tuple(values))
        
        return {
            "message": "User data updated successfully",
            "updated_fields": list(filtered_data.keys())
        }
    
    except HTTPException as he:
        raise he
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="사용자 정보 업데이트 실패"
        )
