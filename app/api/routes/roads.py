# 열선 도로 추천 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import redis
import json
import pandas as pd
from app.core.jwt_utils import get_authenticated_user
from app.database.mysql_connect import get_connection
from app.models.model import load_model, predict
from app.api.socket import run_model_with_progress
import asyncio 


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
async def road_recommendations(input_data: UserWeight, user: dict = Depends(get_authenticated_user)):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        
        asyncio.create_task(run_model_with_progress(user["sub"]))

        # 1. 필요한 데이터만 가져오고, 쿼리 속도 향상을 위해 인덱스 활용
        query = """
        SELECT rds_id, road_name, rbp, rep, rd_slope, acc_occ, acc_sc, rd_fr 
        FROM road_info 
        WHERE sig_cd = %s AND rds_rg = %s
        """
        cursor.execute(query, (input_data.sigungu, input_data.region))
        roads = cursor.fetchall()

        if not roads:
            raise HTTPException(status_code=404, detail=f"'{input_data.region}'에 해당하는 도로 데이터가 없습니다.")

        # 2. 리스트를 DataFrame으로 변환하여 벡터 연산 최적화
        df = pd.DataFrame(roads)

        # 3. 모델 예측을 벡터 연산으로 수행 (predict가 벡터 입력을 지원해야 함)
        feature_array = df[['rd_slope', 'acc_occ', 'acc_sc', 'rd_fr']].values
        df["예측점수"] = predict(model, scaler, feature_array)  

        # 4. 사용자 가중치를 적용하여 pred_idx 계산
        df["pred_idx"] = (
            df["예측점수"] * 0.3 +
            df["rd_slope"] * input_data.rd_slope_weight +
            df["acc_occ"] * input_data.acc_occ_weight +
            df["acc_sc"] * input_data.acc_sc_weight +
            df["rd_fr"] * input_data.rd_fr_weight
        )

        # 5. 정규화 처리 (벡터 연산)
        min_score, max_score = df["pred_idx"].min(), df["pred_idx"].max()
        if max_score - min_score > 0:
            df["pred_idx"] = ((df["pred_idx"] - min_score) / (max_score - min_score)) * 100
        else:
            df["pred_idx"] = 50  # 모든 값이 동일하면 50으로 설정

        # 6. 상위 10개만 선택하여 반환
        recommended_roads = df.sort_values("pred_idx", ascending=False).head(10).to_dict(orient="records")

        # 7. Redis 캐싱 적용
        response_data = {
            "rds_rg": input_data.region,
            "recommended_roads": recommended_roads
        }
        recommended_roads_json = json.dumps(response_data, ensure_ascii=False)
        redis_key = f"recommendations:{user['sub']}:{input_data.region}"
        redis_client.setex(redis_key, 900, recommended_roads_json)

        # 8. 추천 결과 로그 저장 (비동기 처리 가능)
        log_query = "INSERT INTO rec_road_log (user_email, recommended_roads) VALUES (%s, %s)"
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