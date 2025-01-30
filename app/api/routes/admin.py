# 관리자 대시보드 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
import csv
import json
import os
from app.core.jwt_utils import verify_token, get_authenticated_user
from app.database.mysql_connect import get_connection
from app.core.email_utils import send_file_email

router = APIRouter()

class FileRequest(BaseModel):
    req_id: str
    user_email: str
    confirm: bool
    req_date: datetime

# ✅ 파일 요청 확인
@router.get("/file-requests")
def get_file_requests(token: str = Depends(get_authenticated_user)):
    """파일 요청 확인"""
    if not token.get("admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # ✅ Retrieve file requests with user details
        query = """
        SELECT r.log_id, r.user_email, u.user_dept, u.jurisdiction, r.c_date
        FROM rec_road_log r
        JOIN user_data u ON r.user_email = u.user_email
        WHERE r.ask_check = 1
        ORDER BY r.c_date DESC
        """
        cursor.execute(query)
        requests = cursor.fetchall()

        return {"file_requests": requests}
    finally:
        cursor.close()
        connection.close()

# ✅ 파일 승인 
@router.post("/file-requests/approve/{log_id}")
def approve_file_request(log_id: int, user: dict = Depends(get_authenticated_user)):
    """승인 메일, 확인 후 ask_check 0으로 변경"""
    if not user.get("admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Get request details
        query = "SELECT user_email, recommended_roads FROM rec_road_log WHERE log_id = %s AND ask_check = 1"
        cursor.execute(query, (log_id,))
        request = cursor.fetchone()

        if not request:
            raise HTTPException(status_code=404, detail="해당 요청을 찾을 수 없거나 이미 처리되었습니다.")

        user_email = request["user_email"]
        recommended_roads = json.loads(request["recommended_roads"])

        # Generate CSV file
        csv_filename = f"road_recommendations_{log_id}.csv"
        csv_filepath = f"./{csv_filename}"  # Temporary directory

        with open(csv_filepath, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["road_id", "road_name", "rbp", "rep", "rd_slope", "acc_occ", "acc_sc", "pred_idx"])
            for road in recommended_roads:
                writer.writerow([
                    road["road_id"], road["road_name"], road["rbp"], road["rep"],
                    road["rd_slope"], road["acc_occ"], road["acc_sc"], road["pred_idx"]
                ])

        # Send email with CSV attachment
        email_subject = "도로 추천 결과 파일"
        email_body = f"{user_email}님,\n\n도로 추천 결과 파일을 첨부합니다."
        send_file_email(to_email=user_email, subject=email_subject, body=email_body, attachment_path=csv_filepath)

        # Reset `ask_check` to 0 instead of deleting (혹은 로그 delete하기)
        update_query = "UPDATE rec_road_log SET ask_check = 0 WHERE log_id = %s"
        cursor.execute(update_query, (log_id,))
        connection.commit()

        # Remove temporary file
        os.remove(csv_filepath)

        return {"message": f"파일이 {user_email}님에게 전송되었습니다."}
    finally:
        cursor.close()
        connection.close()

# ✅ 파일 거부
@router.post("/file-requests/reject/{log_id}")
def reject_file_request(log_id: int, user: dict = Depends(get_authenticated_user)):
    """reject 메일, 확인 후 ask_check 0으로 변경"""
    if not user.get("admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = "SELECT user_email FROM rec_road_log WHERE log_id = %s AND ask_check = 1"
        cursor.execute(query, (log_id,))
        request = cursor.fetchone()

        if not request:
            raise HTTPException(status_code=404, detail="해당 요청을 찾을 수 없거나 이미 처리되었습니다.")

        user_email = request["user_email"]

        # Send rejection email
        email_subject = "파일 요청이 거부되었습니다."
        email_body = f"{user_email}님,\n\n요청하신 도로 추천 파일이 거부되었습니다. 추가 문의는 관리자에게 연락하세요."
        send_file_email(to_email=user_email, subject=email_subject, body=email_body)

        # Reset `ask_check` to 0 instead of deleting - 혹은 log delete
        update_query = "UPDATE rec_road_log SET ask_check = 0 WHERE log_id = %s"
        cursor.execute(update_query, (log_id,))
        connection.commit()

        return {"message": f"파일 요청이 거부되었으며 {user_email}님에게 알림이 전송되었습니다."}
    finally:
        cursor.close()
        connection.close()