# 열선 도로 추천 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import List
import redis
import json
import pandas as pd
from app.core.jwt_utils import verify_token, get_authenticated_user
from app.database.mysql_connect import get_connection
from app.models.model import train_model

router = APIRouter()

try:
  redis_client = redis.StrictRedis(host="localhost", port=6379, db=0,decode_responses=True)
except Exception as e:
  print(f"Redis connection failed: {e}")
  redis_client = None

# User input model
class UserWeight(BaseModel):
  sigungu: int
  region: str
  rd_slope_weight: float = 4.0
  acc_occ_weight: float = 3.0
  acc_sc_weight: float = 3.0


# ✅ 지역 지정
@router.get("/get_district")
def get_district(sigungu: int, district: str, user: dict = Depends(get_authenticated_user)):
  """Check if the district (읍면동) exists in road_info"""
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    query = "SELECT COUNT(*) AS count FROM road_info WHERE sig_cd = %s and rds_rg = %s"
    cursor.execute(query, (sigungu, district,))
    result = cursor.fetchone()

    if result["count"] == 0:
      raise HTTPException(status_code=404, detail=f"'{district}' 지역의 도로 정보가 없습니다.")

    return {"message": f"'{district}' 지역이 선택되었습니다."}
  finally:
    cursor.close()
    connection.close()


# ✅ 열선 도로 추천
@router.post("/recommend")
def road_recommendations(input_data: UserWeight, user: dict = Depends(get_authenticated_user)):
  """가중치를 적용하여 추천 점수를 계산하고 json형식으로 로그 저장(상위10개)"""
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    # 지역 필터링
    query = "SELECT * FROM road_info WHERE sig_cd = %s and rds_rg = %s"
    cursor.execute(query, (input_data.sigungu, input_data.region,))
    roads = cursor.fetchall()

    if not roads:
      raise HTTPException(status_code=404, detail=f"'{input_data.region}'에 해당하는 도로 데이터가 없습니다.")

    # user-defined weights 적용 
    recommended_roads = []
    for road in roads:
      pred_idx = (
          road["rd_slope"] * input_data.rd_slope_weight +
          road["acc_occ"] * input_data.acc_occ_weight +
          road["acc_sc"] * input_data.acc_sc_weight
      )
      recommended_roads.append({
        "road_id": road["road_id"],
        "road_name": road["road_name"],
        "rbp": road["rbp"],  # 시점
        "rep": road["rep"],  # 종점
        "rd_slope": road["rd_slope"],
        "acc_occ": road["acc_occ"],
        "acc_sc": road["acc_sc"],
        "pred_idx": pred_idx
      })

    # 상위 10개 
    recommended_roads = sorted(recommended_roads, key=lambda x: x["pred_idx"],reverse=True)[:10]

    # Convert list to JSON format
    recommended_roads_json = json.dumps(recommended_roads, ensure_ascii=False)

    # Redis에 캐시 저장
    redis_key = f"recommendations:{user['sub']}:{input_data.region}"
    redis_client.setex(redis_key, 900, recommended_roads_json)  # Cache for 15 minutes

    # JSON data로 저장 
    log_query = """
        INSERT INTO rec_road_log (user_email, recommended_roads)
        VALUES (%s, %s)
        """
    cursor.execute(log_query, (user["sub"], recommended_roads_json))
    connection.commit()

    cursor.execute("SELECT LAST_INSERT_ID()")
    log_id = cursor.fetchone()["LAST_INSERT_ID()"]

    return {
        "log_id": log_id,  # log_id 필요 ?
        "user_weights": {
            "rd_slope_weight": input_data.rd_slope_weight,
            "acc_occ_weight": input_data.acc_occ_weight,
            "acc_sc_weight": input_data.acc_sc_weight
        },
        "recommended_roads": recommended_roads
    }
  finally:
    cursor.close()
    connection.close()


# ✅ 추천 로그 확인
@router.get("/recommendations/log")
def get_recommendation_logs(user: dict = Depends(get_authenticated_user)):
  """해당 id의 log 확인용"""
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT log_id, c_date, recommended_roads, ask_check
        FROM rec_road_log
        WHERE user_email = %s
        ORDER BY c_date DESC
        """
    cursor.execute(query, (user["sub"],))
    logs = cursor.fetchall()

    # Convert JSON string to Python list before returning
    for log in logs:
      log["recommended_roads"] = json.loads(log["recommended_roads"])

    return {"recommendation_logs": logs}
  finally:
    cursor.close()
    connection.close()


# ✅ 파일 요청 
@router.post("/file-request/{log_id}")
def request_road_file(log_id: int,user: dict = Depends(get_authenticated_user)):
  """파일 요청 api - rec_road_log의 ask_check로 확인"""
  try:
    connection = get_connection()
    cursor = connection.cursor()
    # Check if log_id exists and belongs to the user
    query = "SELECT * FROM rec_road_log WHERE log_id = %s AND user_email = %s"
    cursor.execute(query, (log_id, user["sub"]))
    log_entry = cursor.fetchone()

    if not log_entry:
      raise HTTPException(status_code=404, detail="추천 로그를 찾을 수 없거나 권한이 없습니다.")

    # ask_check 0 to 1으로 업데이트
    update_query = "UPDATE rec_road_log SET ask_check = 1 WHERE log_id = %s"
    cursor.execute(update_query, (log_id,))
    connection.commit()

    return {"message": f"파일 요청이 등록되었습니다 (log_id: {log_id})."}
  finally:
    cursor.close()
    connection.close()

