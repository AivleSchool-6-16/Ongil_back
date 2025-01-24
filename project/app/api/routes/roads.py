# 열선 도로 추천 
import uuid
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
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

# 동 입력받기 - db 정리 후 query 고쳐야 함.
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

@router.get("/recommendations", response_model=List[RoadRecommendationResponse]) # db 수정 후 수정 
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
    """
    도로 파일 요청 등록 API
    """
    user_email = token["sub"]
    req_id = f"REQ{uuid.uuid4().hex[:8].upper()}"  # 고유한 req_id 생성

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = """
            INSERT INTO req_file (req_id, user_email, confirm, req_date) 
            VALUES (%s, %s, %s, NOW())
        """
        cursor.execute(query, (req_id, user_email, 0))  # confirm = 0으로 설정
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "파일 요청이 성공적으로 등록되었습니다.", "req_id": req_id}