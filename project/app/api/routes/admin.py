# 관리자 대시보드 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from app.utils.jwt_utils import verify_token
from app.db.mysql_connect import get_connection

router = APIRouter()

class FileRequest(BaseModel):
    req_id: str
    user_email: str
    confirm: bool
    req_date: datetime

  
def is_admin(email: str):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = "SELECT is_admin FROM permissions WHERE user_email = %s"
        cursor.execute(query, (email,))
        result = cursor.fetchone()
        return result and result["is_admin"]
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@router.get("/file-requests")
def get_file_requests(token: str = Depends(verify_token)):
    user_email = token["sub"]
    if not is_admin(user_email):
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM req_file ORDER BY req_date DESC"
        cursor.execute(query)
        file_requests = cursor.fetchall()
        return file_requests
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@router.post("/file-requests/approve")
def approve_file_request(req_id: str, token: str = Depends(verify_token)):
    user_email = token["sub"]
    if not is_admin(user_email):
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = "UPDATE req_file SET confirm = TRUE WHERE req_id = %s"
        cursor.execute(query, (req_id,))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "파일 요청이 승인되었습니다."}

@router.post("/file-requests/reject")
def reject_file_request(req_id: str, token: str = Depends(verify_token)):
    user_email = token["sub"]
    if not is_admin(user_email):
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = "DELETE FROM req_file WHERE req_id = %s"
        cursor.execute(query, (req_id,))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "파일 요청이 거부되었습니다."}