# 문의 게시판 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List, Optional
from app.utils.jwt_utils import verify_token
import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com",
        user="admin",     
        password="aivle202406",
        database="ongildb" 
    )

router = APIRouter()

class InquiryRequest(BaseModel):
    subject: str
    content: str

class InquiryResponse(BaseModel):
    id: int
    subject: str
    content: str
    date: datetime
    response: Optional[str]
    

# Helper function to get inquiries for a specific user
def get_user_inquiries(user_email: str):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT post_id AS id, post_title AS subject, post_text AS content, post_time AS date, NULL AS response 
            FROM posts 
            WHERE user_email = %s 
            ORDER BY post_time DESC
        """
        cursor.execute(query, (user_email,))
        inquiries = cursor.fetchall()
        return inquiries
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


@router.post("/inquires", response_model=dict)
def submit_inquiry(request: InquiryRequest, token: str = Depends(verify_token)):
    user_email = token["sub"]

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = """
            INSERT INTO posts (user_email, post_title, post_text, post_time) 
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query, (user_email, request.subject, request.content, datetime.now()))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "문의가 성공적으로 등록되었습니다."}

# Endpoint to retrieve user's inquiries
@router.get("/inquires", response_model=List[InquiryResponse])
def get_inquiries(token: str = Depends(verify_token)):
    user_email = token["sub"]
    inquiries = get_user_inquiries(user_email)
    if not inquiries:
        raise HTTPException(status_code=404, detail="문의 내역이 없습니다.")
    return inquiries

# Endpoint to retrieve a specific inquiry by ID
@router.get("/inquires/{inquiry_id}", response_model=InquiryResponse)
def get_inquiry(inquiry_id: int, token: str = Depends(verify_token)):
    user_email = token["sub"]

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT post_id AS id, post_title AS subject, post_text AS content, post_time AS date, NULL AS response 
            FROM posts 
            WHERE post_id = %s AND user_email = %s
        """
        cursor.execute(query, (inquiry_id, user_email))
        inquiry = cursor.fetchone()

        if not inquiry:
            raise HTTPException(status_code=404, detail="문의 내역을 찾을 수 없습니다.")

        return inquiry
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

