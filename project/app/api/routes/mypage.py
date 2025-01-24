# mypage - 정보 조회, 수정, 탈퇴 
from fastapi import APIRouter, HTTPException, Header, status, Depends
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime, timedelta, timezone
import traceback
from typing import Dict
from app.utils.security import verify_password
from app.utils.jwt_utils import verify_token
from app.utils.token_blacklist import is_token_blacklisted, add_token_to_blacklist
from app.db.mysql_connect import get_connection


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
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail="Database query execution failed.") 
    finally: 
        if cursor: 
            cursor.close() 
        if conn: 
            conn.close() 

router = APIRouter() 

@router.get("/mypage_load") 
def mypage_load(email: str, token: str = Header(...)): 
    try: 
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")

        user_email = verify_token(token).get("sub")
        if user_email != email:
            raise HTTPException(status_code=403, detail="Unauthorized access.")

        query = "SELECT user_email, user_name, user_dept, jurisdiction FROM user_data WHERE user_email = %s" 
        user_info = execute_query(query, (email,)) 
        if not user_info:
            raise HTTPException(status_code=404, detail="User not found.")
        return {"user_info": user_info} 
    except Exception: 
        traceback.print_exc() 
        raise HTTPException( 
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to load user information." 
        ) 

@router.get("/check_password") 
def check_password(email: str, password: str, token: str = Header(...)): 
    try: 
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")

        user_email = verify_token(token).get("sub")
        if user_email != email:
            raise HTTPException(status_code=403, detail="Unauthorized access.")

        query_user = "SELECT user_ps FROM user_data WHERE user_email = %s" 
        user_record = execute_query(query_user, (email,)) 

        if not user_record: 
            raise HTTPException(status_code=404, detail="User not found.") 

        db_hashed_ps = user_record[0]['user_ps'] 

        if not verify_password(password, db_hashed_ps):  # Verify hashed password
            raise HTTPException(status_code=400, detail="Incorrect password.") 
        return {"message": "Password matches."} 

    except Exception: 
        traceback.print_exc() 
        raise HTTPException( 
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to verify password." 
        ) 

@router.put("/update_user")  # 사용자 정보 업데이트  
def update_user(email: str, update_data: Dict[str, str], token: str = Header(...)): 
    try: 
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")

        user_email = verify_token(token).get("sub")
        if user_email != email:
            raise HTTPException(status_code=403, detail="Unauthorized access.")

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
                detail="No valid fields to update." 
            ) 

        # 동적 SQL 쿼리 생성 
        set_clause = ", ".join([f"{key} = %s" for key in filtered_data.keys()]) 
        values = list(filtered_data.values()) + [email] 

        query = f"UPDATE user_data SET {set_clause} WHERE user_email = %s" 

        # 쿼리 실행 
        execute_query(query, tuple(values)) 

        return { 
            "message": "User data updated successfully.", 
            "updated_fields": list(filtered_data.keys()) 
        } 

    except HTTPException as he: 
        raise he 
    except Exception: 
        traceback.print_exc() 
        raise HTTPException( 
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to update user data." 
        )

@router.delete("/delete_user")  # 회원 탈퇴 
def delete_user(token: str = Header(...)):
    try:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")

        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token.")

        user_email = payload.get("sub")
        if not user_email:
            raise HTTPException(status_code=400, detail="Invalid token payload.")

        # Delete user from user_data
        query_delete_user = "DELETE FROM user_data WHERE user_email = %s"
        execute_query(query_delete_user, (user_email,))

        # Add token to blacklist
        expiration_time = payload.get("exp")
        current_time = datetime.now(timezone.utc).timestamp()
        remaining_time = max(int(expiration_time - current_time), 0)
        add_token_to_blacklist(token, remaining_time)

        return {"message": "User account deleted successfully."}

    except HTTPException as he:
        raise he
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user account."
        )

@router.delete("/user_delete/{user_email}") # 회원탈퇴 임시
def user_delete(email:str):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        sql = "DELETE FROM user_data WHERE user_email = %s"
        cursor.execute(sql, (email,))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "회원 탈퇴 완료."
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회원탈퇴 실패"
        )