# 열선 도로 추천 
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from typing import List
from app.utils.jwt_utils import verify_token
from app.db.mysql_connect import get_connection


router = APIRouter()

class RoadRecommendationResponse(BaseModel):
    rank: int
    road_name: str
    freezing_index: int
    traffic_volume: int

# 동 입력받기
def fetch_top_roads(district: str):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT road_name, freezing_index, traffic_volume 
            FROM road_info 
            WHERE district = %s 
            ORDER BY freezing_index DESC 
            LIMIT 3
        """
        cursor.execute(query, (district,))
        roads = cursor.fetchall()
        return roads
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@router.get("/recommendations", response_model=List[RoadRecommendationResponse])
def get_road_recommendations(district: str):
    roads = fetch_top_roads(district)
    if not roads:
        raise HTTPException(status_code=404, detail="해당 지역에 대한 열선도로 정보가 없습니다.")

    return [
        {"rank": i + 1, "road_name": road["road_name"], "freezing_index": road["freezing_index"], "traffic_volume": road["traffic_volume"]}
        for i, road in enumerate(roads)
    ]

# 파일 요청
@router.post("/file-request")
def request_road_file(district: str, token: str = Depends(verify_token)):
    user_email = token["sub"]

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = """
            INSERT INTO file_requests (user_email, district, request_time, status) 
            VALUES (%s, %s, %s, 'pending')
        """
        cursor.execute(query, (user_email, district, datetime.now()))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "파일 요청이 성공적으로 등록되었습니다."}