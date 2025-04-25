from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
from starlette.responses import JSONResponse
from fastapi.routing import APIRoute
from datetime import datetime
from app.database.mysql_connect import get_connection
from app.api.routes import admin, auth, board, mypage, roads, dev
from app.core.token_blacklist import is_token_blacklisted
from app.core.jwt_utils import verify_token
from app.services.sync_views import sync_redis_to_mysql
from app.api.socket import socket_app
from dotenv import load_dotenv
import os
import redis

# ✅ 환경변수 로드
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path)

# ✅ DB 연결
DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ✅ Redis 연결
try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None

# ✅ DB 종속성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ 백그라운드 스케줄러
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 App is starting... Initializing scheduler")
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_redis_to_mysql, "interval", minutes=10)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    print("🛑 Shutting down scheduler...")
    scheduler.shutdown()

# ✅ FastAPI 앱 설정
app = FastAPI(root_path="/api", lifespan=lifespan)
app.mount("/socket.io", socket_app)

# ✅ 입력형식 오류 처리
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_messages = [{"field": error["loc"], "message": error["msg"]} for error in errors]
    return JSONResponse(
        status_code=400,
        content={"detail": "입력 형식이 올바르지 않습니다.", "errors": error_messages},
    )

# ✅ 제외 경로 설정
EXCLUDED_PATHS = [
    "/auth/login",
    "/auth/signup",
    "/docs",
    "/open-api",
    "/auth/signup/error",
    "/auth/signup/check-email",
    "/auth/signup/confirm",
    "/auth/signup/send-code",
    "/socket.io",
]

# ✅ 통합 미들웨어 (토큰 확인, Redis 접속자 등록, 방문 로그, 에러 로그 기록)
@app.middleware("http")
async def unified_tracking_middleware(request: Request, call_next):
    path = request.url.path
    token = request.headers.get("token", "")
    email = None
    is_excluded = any(path.startswith(ep) for ep in EXCLUDED_PATHS)
    status_code = None

    # 토큰 검증 및 접속자 등록
    if not is_excluded and token:
        try:
            if is_token_blacklisted(token):
                raise HTTPException(status_code=401, detail="토큰이 블랙리스트에 등록되었습니다.")
            payload = verify_token(token)
            email = payload.get("sub")
            if email and redis_client:
                redis_client.sadd("online_users", email)
        except Exception as e:
            print(f"[토큰 검증 실패] {e}")
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    # 요청 처리
    response = await call_next(request)
    status_code = response.status_code

    # 방문 로그 저장
    try:
        if not path.startswith(("/socket.io", "/docs", "/favicon.ico")):
            connection = get_connection()
            cursor = connection.cursor()
            query = "INSERT INTO visit_logs (user_email, route, ip_address) VALUES (%s, %s, %s)"
            cursor.execute(query, (email, path, request.client.host))
            connection.commit()
    except Exception as e:
        print(f"[방문 로그 기록 실패] {e}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'connection' in locals() and connection.is_connected():
            connection.close()

    # 에러 로그 저장
    if status_code >= 400:
        try:
            connection = get_connection()
            cursor = connection.cursor()
            query = "INSERT INTO error_logs (user_email, route, status_code) VALUES (%s, %s, %s)"
            cursor.execute(query, (email, path, status_code))
            connection.commit()
        except Exception as e:
            print(f"[에러 로그 기록 실패] {e}")
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'connection' in locals() and connection.is_connected():
                connection.close()

    return response

# ✅ CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 라우터 등록
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(board.router, prefix="/board", tags=["Board"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(roads.router, prefix="/roads", tags=["Roads"])
app.include_router(dev.router, prefix="/dev", tags=["Dev"])

@app.get("/")
def root():
    return {"message": "개발 중.."}
