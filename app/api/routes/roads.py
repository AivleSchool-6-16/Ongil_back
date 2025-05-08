# 열선 도로 추천
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Extra
import redis
import json
import pandas as pd
from app.core.jwt_utils import get_authenticated_user
from app.database.mysql_connect import get_connection
from app.models.model import load_model, predict
from app.api.socket import run_model_with_progress
import asyncio
from datetime import datetime  # ⬅️ 추가

router = APIRouter()

try:
  redis_client = redis.StrictRedis(
      host="ongil_redis", port=6379, db=0, decode_responses=True
  )
except Exception as e:
  print(f"Redis connection failed: {e}")
  redis_client = None

# 모델 & 스케일러 로드
model, scaler = load_model()


class UserWeight(BaseModel):
  region: str
  rd_slope_weight: float = 2.5
  acc_occ_weight: float = 3.0
  acc_sc_weight: float = 1.5
  rd_fr_weight: float = 1.5
  traff_weight: float = 1.5

  class Config:
    extra = Extra.ignore

  # ✅ 지역 지정 (sigungu 제거)


@router.get("/get_district")
def get_district(
    district: str, user: dict = Depends(get_authenticated_user)
):
  """seoul_info에 해당 읍/면/동/가(rds_rg)가 있는지 확인"""
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = "SELECT 1 FROM seoul_info WHERE rds_rg = %s LIMIT 1"
    cursor.execute(query, (district,))
    result = cursor.fetchone()

    if not result:
      raise HTTPException(
          status_code=404, detail=f"'{district}' 지역의 도로 정보가 없습니다."
      )

    return {"message": f"'{district}' 지역이 선택되었습니다."}
  finally:
    cursor.close()
    connection.close()


# ✅ 열선 도로 추천 (sigungu 제거, traff 추가)
@router.post("/recommend")
async def road_recommendations(
    input_data: UserWeight,
    user: dict = Depends(get_authenticated_user)
):
  start_time = datetime.now()  # ⬅️ 지연 시간 측정 시작
  try:
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # 진행률 소켓 전송
    asyncio.create_task(run_model_with_progress(user["sub"]))

    # 1) 대상 도로 조회 -------------------------------------------------
    cur.execute("""
                SELECT rds_id,
                       road_name,
                       rbp,
                       rep,
                       rd_slope,
                       acc_occ,
                       acc_sc,
                       rd_fr,
                       traff
                FROM seoul_info
                WHERE rds_rg = %s
                """, (input_data.region,))
    roads = cur.fetchall()
    if not roads:
      raise HTTPException(404, f"'{input_data.region}'에 해당 도로 데이터가 없습니다.")

    # 2) 예측 점수 계산 --------------------------------------------------
    df = pd.DataFrame(roads)
    X = df[["rd_slope", "acc_occ", "acc_sc", "rd_fr", "traff"]].values
    df["예측점수"] = predict(model, scaler, X)

    # 3) 가중치 정규화 ---------------------------------------------------
    w = {
      "rd_slope": input_data.rd_slope_weight,
      "acc_occ": input_data.acc_occ_weight,
      "acc_sc": input_data.acc_sc_weight,
      "rd_fr": input_data.rd_fr_weight,
      "traff": input_data.traff_weight,
    }
    s = sum(w.values()) or 1
    w = {k: v / s for k, v in w.items()}

    df["pred_idx"] = (
        df["예측점수"] * 0.3 +
        df["rd_slope"] * w["rd_slope"] +
        df["acc_occ"] * w["acc_occ"] +
        df["acc_sc"] * w["acc_sc"] +
        df["rd_fr"] * w["rd_fr"] +
        df["traff"] * w["traff"]
    )
    mn, mx = df["pred_idx"].min(), df["pred_idx"].max()
    df["pred_idx"] = (df["pred_idx"] - mn) / (mx - mn) * 100 if mx != mn else 50

    recommended = (
      df.sort_values("pred_idx", ascending=False)
      .head(10).to_dict("records")
    )

    # 4) 결과 Redis 캐시 & 로그 ------------------------------------------
    resp_json = json.dumps({"rds_rg": input_data.region,
                            "recommended_roads": recommended},
                           ensure_ascii=False)
    redis_client.setex(
        f"recommendations:{user['sub']}:{input_data.region}",
        900, resp_json)

    cur.execute("""INSERT INTO rec_road_log (user_email, recommended_roads)
                   VALUES (%s, %s)""",
                (user["sub"], resp_json))

    # 5) ★ AI 로그 테이블 기록 -------------------------------------------
    latency = (datetime.now() - start_time).total_seconds() * 1000  # ms
    cur.execute("""
                INSERT INTO ai_log
                (user_email, region, latency,
                 icing_weight, slope_weight,
                 accident_severity_weight, traffic_weight)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                  user["sub"], input_data.region, latency,
                  input_data.rd_fr_weight,
                  input_data.rd_slope_weight,
                  input_data.acc_sc_weight,
                  input_data.traff_weight,
                ))

    conn.commit()

    return {
      "user_weights": {
        "rd_slope_weight": input_data.rd_slope_weight,
        "acc_occ_weight": input_data.acc_occ_weight,
        "acc_sc_weight": input_data.acc_sc_weight,
        "rd_fr_weight": input_data.rd_fr_weight,
        "traff_weight": input_data.traff_weight,
      },
      "recommended_roads": recommended,
    }

  finally:
    if 'cur' in locals():  cur.close()
    if 'conn' in locals() and conn.is_connected(): conn.close()


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
            ORDER BY c_date DESC \
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
      raise HTTPException(
          status_code=404, detail="추천 로그를 찾을 수 없거나 권한이 없습니다."
      )

    log_id = log_entry[0]  # 가장 최근 log_id 추출

    # ask_check -> 1로 업데이트
    update_query = "UPDATE rec_road_log SET ask_check = 1 WHERE log_id = %s"
    cursor.execute(update_query, (log_id,))
    connection.commit()

    return {"message": f"파일 요청이 등록되었습니다 (log_id: {log_id})."}
  finally:
    cursor.close()
    connection.close()
