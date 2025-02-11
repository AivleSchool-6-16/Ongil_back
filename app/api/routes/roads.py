# 열선 도로 추천 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import List
import redis
import json
import pandas as pd
from app.core.jwt_utils import get_authenticated_user
from app.database.mysql_connect import get_connection
from app.models.model import load_model, predict


router = APIRouter()

try:
  redis_client = redis.StrictRedis(host="localhost", port=6379, db=0,decode_responses=True)
except Exception as e:
  print(f"Redis connection failed: {e}")
  redis_client = None

# 모델 & 스케일러 로드
model, scaler = load_model()

# User input model
class UserWeight(BaseModel):
    sigungu: int # 시군구 코드 5자리
    region: str
    rd_slope_weight: float = 3.0
    acc_occ_weight: float = 3.0
    acc_sc_weight: float = 2.0
    rd_fr_weight: float = 2.0


# ✅ 지역 지정
@router.get("/get_district")
def get_district(sigungu: int, district: str, user: dict = Depends(get_authenticated_user)):
    """road_info에 읍/면/동/가 있는지 확인"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = "SELECT 1 FROM road_info WHERE sig_cd = %s AND rds_rg = %s LIMIT 1"
        cursor.execute(query, (sigungu, district,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail=f"'{district}' 지역의 도로 정보가 없습니다.")

        return {"message": f"'{district}' 지역이 선택되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 열선 도로 추천
@router.post("/recommend")
def road_recommendations(input_data: UserWeight, user: dict = Depends(get_authenticated_user)):
    """
    사용자 입력을 받아 도로 추천을 수행하는 API
    """
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 지역 필터링
        query = "SELECT * FROM road_info WHERE sig_cd = %s AND rds_rg = %s"
        cursor.execute(query, (input_data.sigungu, input_data.region,))
        roads = cursor.fetchall()

        if not roads:
            raise HTTPException(status_code=404, detail=f"'{input_data.region}'에 해당하는 도로 데이터가 없습니다.")

        # 모델 예측 수행 (DataFrame이 아니므로 직접 반복문 사용)
        for road in roads:
            road["예측점수"] = predict(model, scaler, [road["rd_slope"], road["acc_occ"], road["acc_sc"], road["rd_fr"]])

        # user-defined weights 적용
        pred_idx_list = []
        recommended_roads = []

        for road in roads:
            pred_idx = (
                road["예측점수"] * 0.3 +
                road["rd_slope"] * input_data.rd_slope_weight +
                road["acc_occ"] * input_data.acc_occ_weight +
                road["acc_sc"] * input_data.acc_sc_weight +
                road["rd_fr"] * input_data.rd_fr_weight
            )
            pred_idx_list.append(pred_idx)
            road["pred_idx"] = pred_idx

        # 예측 점수 정규화
        min_score = min(pred_idx_list) if pred_idx_list else 0
        max_score = max(pred_idx_list) if pred_idx_list else 100

        for road in roads:
            if max_score - min_score > 0:
                road["pred_idx"] = ((road["pred_idx"] - min_score) / (max_score - min_score)) * 100
            else:
                road["pred_idx"] = 50  # 모든 값이 같다면 50으로 설정

            recommended_roads.append({
                "road_id": road["rds_id"],
                "road_name": road["road_name"],
                "rbp": road["rbp"],  # 시점
                "rep": road["rep"],  # 종점
                "rd_slope": road["rd_slope"],
                "acc_occ": road["acc_occ"],
                "acc_sc": road["acc_sc"],
                "rd_fr": road["rd_fr"],
                "pred_idx": road["pred_idx"]
            })

        # 상위 10개 추천
        recommended_roads = sorted(recommended_roads, key=lambda x: x["pred_idx"], reverse=True)[:10]

        # 지역 저장 후 JSON format으로 변환
        response_data = {
            "rds_rg": input_data.region,
            "recommended_roads": recommended_roads
        }
        recommended_roads_json = json.dumps(response_data, ensure_ascii=False)

        # Redis에 캐시 저장 (15분 TTL)
        redis_key = f"recommendations:{user['sub']}:{input_data.region}"
        redis_client.setex(redis_key, 900, recommended_roads_json)

        # 추천 결과 로그 저장
        log_query = """
            INSERT INTO rec_road_log (user_email, recommended_roads)
            VALUES (%s, %s)
        """
        cursor.execute(log_query, (user["sub"], recommended_roads_json))
        connection.commit()

        return {
            "user_weights": {
                "rd_slope_weight": input_data.rd_slope_weight,
                "acc_occ_weight": input_data.acc_occ_weight,
                "acc_sc_weight": input_data.acc_sc_weight,
                "rd_fr_weight": input_data.rd_fr_weight
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
@router.post("/file-request")
def request_road_file(user: dict = Depends(get_authenticated_user)):
    """파일 요청 API - rec_road_log의 ask_check로 확인"""
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 가장 최근의 log_id를 가져옴
        query = "SELECT log_id FROM rec_road_log WHERE user_email = %s ORDER BY log_id DESC LIMIT 1"
        cursor.execute(query, (user["sub"],))
        log_entry = cursor.fetchone()

        if not log_entry:
            raise HTTPException(status_code=404, detail="추천 로그를 찾을 수 없거나 권한이 없습니다.")

        log_id = log_entry[0]  # 가장 최근 log_id 추출

        # ask_check -> 1로 업데이트
        update_query = "UPDATE rec_road_log SET ask_check = 1 WHERE log_id = %s"
        cursor.execute(update_query, (log_id,))
        connection.commit()

        return {"message": f"파일 요청이 등록되었습니다 (log_id: {log_id})."}
    finally:
        cursor.close()
        connection.close()

