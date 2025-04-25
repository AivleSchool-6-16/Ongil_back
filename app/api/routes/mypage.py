# mypage - 정보 조회, 수정, 탈퇴
from fastapi import APIRouter, HTTPException, Header, status, Depends
from datetime import datetime, timezone
import traceback
import mysql
from typing import Dict
from app.core.security import verify_password, hash_password
from app.core.jwt_utils import verify_token
from app.core.token_blacklist import is_token_blacklisted, add_token_to_blacklist
from app.database.mysql_connect import get_connection


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
def mypage_load(token: str = Header(...)):
    """마이페이지 정보 노출"""
    try:
        # Check if token is valid and extract email
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")

        user_email = verify_token(token).get("sub")

        # Fetch user details
        query = "SELECT user_email, user_name, user_dept, jurisdiction FROM user_data WHERE user_email = %s"
        user_info = execute_query(query, (user_email,))

        if not user_info:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        return {"user_info": user_info}
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load user information.",
        )


@router.get("/check_password")
def check_password(password: str, token: str = Header(...)):
    """비밀번호 확인"""
    try:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")

        user_email = verify_token(token).get("sub")

        # Get the stored hashed password
        query_user = "SELECT user_ps FROM user_data WHERE user_email = %s"
        user_record = execute_query(query_user, (user_email,))

        if not user_record:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        db_hashed_ps = user_record[0]["user_ps"]

        # Verify password using bcrypt
        if not verify_password(password, db_hashed_ps):
            raise HTTPException(status_code=400, detail="비밀번호가 다릅니다.")

        return {"message": "비밀번호가 확인되었습니다."}
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="비밀번호 인증에 실패하였습니다.",
        )


# 사용자 정보 수정
@router.put("/update_user")
def update_user(update_data: Dict[str, str], token: str = Header(...)):
    """user_ps, user_dept, jurisdiction만 가능"""
    try:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")

        user_email = verify_token(token).get("sub")

        allowed_columns = {"user_ps", "user_dept", "jurisdiction"}

        # Extract only allowed fields
        filtered_data = {
            key: value for key, value in update_data.items() if key in allowed_columns
        }

        if not filtered_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update.",
            )

        # user_ps이면 Hash password
        if "user_ps" in filtered_data:
            filtered_data["user_ps"] = hash_password(filtered_data["user_ps"])

        # Generate dynamic SQL query
        set_clause = ", ".join([f"{key} = %s" for key in filtered_data.keys()])
        values = list(filtered_data.values()) + [user_email]

        query = f"UPDATE user_data SET {set_clause} WHERE user_email = %s"

        # Execute update query
        execute_query(query, tuple(values))

        return {
            "message": "성공적으로 업데이트되었습니다.",
            "updated_fields": list(filtered_data.keys()),
        }
    except HTTPException as he:
        raise he
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="업데이트에 실패하였습니다.",
        )


# 회원탈퇴
@router.delete("/delete_user")
def delete_user(token: str = Header()):
    """회원 탈퇴 (연관된 모든 데이터 삭제 후 user_data 삭제)"""
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="만료된 토큰입니다.")

        user_email = payload.get("sub")
        if not user_email:
            raise HTTPException(status_code=400, detail="Invalid token payload.")

        connection = get_connection()
        cursor = connection.cursor()

        # 1️. user_email을 참조하는 테이블 먼저 삭제 (comments 등)
        execute_query("DELETE FROM comments WHERE user_email = %s", (user_email,))
        execute_query("DELETE FROM answer WHERE user_email = %s", (user_email,))
        execute_query("DELETE FROM file_metadata WHERE user_email = %s", (user_email,))

        # 2️. Posts 삭제
        execute_query("DELETE FROM Posts WHERE user_email = %s", (user_email,))

        # 3️. user_email 관련 테이블 삭제
        execute_query("DELETE FROM log WHERE user_email = %s", (user_email,))
        execute_query("DELETE FROM permissions WHERE user_email = %s", (user_email,))
        execute_query("DELETE FROM rec_road_log WHERE user_email = %s", (user_email,))

        # 4️. user_data 삭제
        execute_query("DELETE FROM user_data WHERE user_email = %s", (user_email,))

        # 5️. 토큰을 블랙리스트에 추가
        expiration_time = payload.get("exp")
        current_time = datetime.now(timezone.utc).timestamp()
        remaining_time = max(int(expiration_time - current_time), 0)
        add_token_to_blacklist(token, remaining_time)

        return {"message": "회원 탈퇴가 완료되었습니다."}

    except mysql.connector.IntegrityError as e:
        raise HTTPException(
            status_code=400, detail=f"Database integrity error: {str(e)}"
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"회원 탈퇴에 실패하였습니다. Error: {str(e)}"
        )

    finally:
        cursor.close()
        connection.close()
