# dev.py
import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import date
from app.database.mysql_connect import get_connection
from mysql.connector import Error
from datetime import datetime, timedelta
from collections import defaultdict

router = APIRouter()

# Redis 연결
try:
  redis_client = redis.StrictRedis(host="ongil_redis", port=6379, db=0)
except Exception as e:
  print(f"Redis connection failed: {e}")
  redis_client = None


class UserInfoResponse(BaseModel):
  Permission: str
  Department: str | None
  CreatDt: date | None
  E_mail: EmailStr
  Name: str
  Jurisdiction: str | None


@router.get("/users", response_model=list[UserInfoResponse])
def get_user_info_list():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT CASE
                       WHEN p.is_admin = 1 THEN '자치구'
                       WHEN p.is_admin = 2 THEN '개발자'
                       ELSE '자치동'
                       END        AS Permission,
                   u.user_dept    AS Department,
                   u.CreatDt      AS CreatDt,
                   u.user_email   AS E_mail,
                   u.user_name    AS Name,
                   u.jurisdiction AS Jurisdiction
            FROM user_data u
                     LEFT JOIN permissions p ON u.user_email = p.user_email \
            """

    cursor.execute(query)
    results = cursor.fetchall()
    return results

  except Error as e:
    print(f"DB error: {e}")
    raise HTTPException(status_code=500, detail="유저 정보를 불러오는 데 실패했습니다.")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/status/real-time")
def get_online_users():
  count = redis_client.scard("online_users")
  return {"count": count}


@router.get("/status/real-time/users")
def get_online_user_list():
  if redis_client is None:
    raise HTTPException(status_code=500, detail="Redis 연결 오류")

  emails = [e.decode() for e in redis_client.smembers("online_users")]
  if not emails:  # 접속 중인 유저가 없으면 빈 리스트
    return []

  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    placeholders = ",".join(["%s"] * len(emails))
    query = (
      f"SELECT user_email AS email, user_name AS name, user_dept AS department "
      f"FROM user_data WHERE user_email IN ({placeholders})"
    )
    cursor.execute(query, tuple(emails))
    return cursor.fetchall()

  except Exception as e:
    print("online users API error:", e)
    raise HTTPException(status_code=500, detail="실시간 유저 조회 실패")

  finally:
    if 'cursor' in locals(): cursor.close()
    if 'connection' in locals() and connection.is_connected(): connection.close()


@router.get("/status/today-visitors")
def get_today_visitors():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT COUNT(DISTINCT ip_address) AS count
            FROM visit_logs
            WHERE DATE (visit_time) = CURDATE() \
            """

    cursor.execute(query)
    result = cursor.fetchone()
    return {"count": result["count"]}

  except Exception as e:
    raise HTTPException(status_code=500, detail="오늘 방문자 수 조회 실패")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/status/error-routes")
def get_error_routes():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT route, COUNT(*) AS count
            FROM error_logs
            WHERE DATE (created_at) = CURDATE()
            GROUP BY route
            ORDER BY count DESC \
            """
    cursor.execute(query)
    return cursor.fetchall()
  except Exception as e:
    raise HTTPException(status_code=500, detail="에러 경로 통계 실패")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/status/error-types")
def get_error_types():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT status_code, COUNT(*) AS count
            FROM error_logs
            WHERE DATE (created_at) = CURDATE()
            GROUP BY status_code \
            """
    cursor.execute(query)
    return cursor.fetchall()
  except Exception as e:
    raise HTTPException(status_code=500, detail="에러 유형 통계 실패")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/status/today-events")
def get_today_event_count():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT COUNT(*) AS count
            FROM error_logs
            WHERE DATE (created_at) = CURDATE() \
            """
    cursor.execute(query)
    result = cursor.fetchone()
    return {"count": result["count"]}
  except Exception as e:
    raise HTTPException(status_code=500, detail="에러 수 조회 실패")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/status/new-members")
def get_new_member_count():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    query = """
            SELECT COUNT(*) AS count
            FROM user_data
            WHERE CreatDt >= %s \
            """
    cursor.execute(query, (seven_days_ago,))
    result = cursor.fetchone()
    return {"count": result["count"]}

  except Exception as e:
    raise HTTPException(status_code=500, detail="신규 가입자 수 조회 실패")
  finally:
    if 'cursor' in locals() and cursor:
      cursor.close()
    if 'connection' in locals() and connection.is_connected():
      connection.close()


@router.get("/charts/new-members-monthly")
def new_members_monthly():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT DATE_FORMAT(CreatDt, '%Y-%m') AS month, COUNT(*) AS count
            FROM user_data
            WHERE CreatDt >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY month
            ORDER BY month \
            """
    cursor.execute(query)
    data = cursor.fetchall()
    return data
  except Exception as e:
    raise HTTPException(status_code=500, detail="신규 가입자 그래프 데이터 조회 실패")
  finally:
    cursor.close()
    connection.close()


@router.get("/charts/visitors-by-month")
def visitors_by_month():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT DATE_FORMAT(visit_time, '%Y-%m') AS month, COUNT(DISTINCT ip_address) AS count
            FROM visit_logs
            WHERE visit_time >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY month
            ORDER BY month \
            """
    cursor.execute(query)
    return cursor.fetchall()
  except:
    raise HTTPException(status_code=500, detail="방문자 그래프 데이터 조회 실패")
  finally:
    cursor.close()
    connection.close()


@router.get("/charts/error-routes")
def error_routes():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT route, COUNT(*) AS count
            FROM error_logs
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY route
            ORDER BY count DESC \
            """
    cursor.execute(query)
    return cursor.fetchall()
  except:
    raise HTTPException(status_code=500, detail="에러 경로 데이터 조회 실패")
  finally:
    cursor.close()
    connection.close()


@router.get("/charts/error-types")
def error_types():
  try:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
            SELECT status_code, COUNT(*) AS count
            FROM error_logs
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY status_code \
            """
    cursor.execute(query)
    return cursor.fetchall()
  except:
    raise HTTPException(status_code=500, detail="에러 타입 데이터 조회 실패")
  finally:
    cursor.close()
    connection.close()


# dev.py
@router.get("/ai/logs")
def get_ai_logs(limit: int = 10):
  """최근 AI 예측 로그 n건"""
  try:
    conn = get_connection();
    cur = conn.cursor(dictionary=True)
    cur.execute("""
                SELECT id,
                       user_email,
                       region,
                       latency,
                       icing_weight,
                       slope_weight,
                       accident_severity_weight,
                       traffic_weight, timestamp
                FROM ai_log
                ORDER BY id DESC
                    LIMIT %s
                """, (limit,))
    return cur.fetchall()
  finally:
    cur.close();
    conn.close()


# dev.py  ── AI 사용량 카운트용
@router.get("/status/recent-recommend")
def recent_recommend_count(hours: int = 24):
  try:
    conn = get_connection();
    cur = conn.cursor()
    cur.execute(f"""
            SELECT COUNT(*) 
              FROM rec_road_log
             WHERE timestamp >= NOW() - INTERVAL %s HOUR
        """, (hours,))
    return {"count": cur.fetchone()[0]}
  finally:
    cur.close();
    conn.close()


# === NEW: 권한 enum 변환 도우미 ---------------------------------
PERM2INT = {"자치동": 0, "자치구": 1, "개발자": 2}


# === NEW: 권한 수정 --------------------------------------------
class PermPatch(BaseModel):
  new_permission: str  # '자치구' | '개발자' | '자치동'


@router.patch("/users/{email}")
def change_user_permission(email: EmailStr, body: PermPatch):
  perm_int = PERM2INT.get(body.new_permission)
  if perm_int is None:
    raise HTTPException(400, "잘못된 권한 값")

  try:
    conn = get_connection();
    cur = conn.cursor()
    # permissions 테이블 없으면 user_data에 is_admin 직접 저장하셔도 됩니다
    cur.execute("REPLACE INTO permissions (user_email,is_admin) VALUES (%s,%s)",
                (email, perm_int))
    conn.commit()
    return {"ok": True}

  except Exception as e:
    raise HTTPException(500, "권한 변경 실패")

  finally:
    cur.close();
    conn.close()


# === NEW: 회원 추방(하드 delete 예시) ----------------------------
@router.delete("/users/{email}")
def delete_user(email: EmailStr):
  try:
    conn = get_connection();
    cur = conn.cursor()
    cur.execute("DELETE FROM permissions WHERE user_email=%s", (email,))
    cur.execute("DELETE FROM user_data WHERE user_email=%s", (email,))
    conn.commit()
    return {"ok": True}
  except:
    raise HTTPException(500, "회원 삭제 실패")
  finally:
    cur.close();
    conn.close()
