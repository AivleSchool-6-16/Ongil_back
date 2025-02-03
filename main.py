from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import admin, auth, board, mypage, roads
from app.core.token_blacklist import is_token_blacklisted
from app.core.jwt_utils import verify_token
from app.services.sync_views import sync_redis_to_mysql
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

# ✅ MySQL 연결 설정
DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ✅ FastAPI Dependency: 데이터베이스 세션 제공
def get_db():
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
  print("🚀 App is starting... Initializing scheduler")
  # 백그라운드 작업 스케줄러 설정
  scheduler = BackgroundScheduler()
  scheduler.add_job(sync_redis_to_mysql, "interval", minutes=10)  # 10분마다 실행
  scheduler.start()

  # 스케줄러 상태 저장 (GC 방지)
  app.state.scheduler = scheduler

  yield  # 애플리케이션 실행

  print("🛑 Shutting down scheduler...")
  scheduler.shutdown()


# ✅ 웹 선언
app = FastAPI(lifespan=lifespan)

# 입력형식 오류 handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,  
        content={"detail": "입력 형식이 올바르지 않습니다."}
    )

# ✅ Middleware
@app.middleware("http")
async def check_token_blacklist(request: Request, call_next):
  
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="토큰이 블랙리스트에 등록되었습니다.")
        if not verify_token(token):
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ✅ 라우터 추가
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(board.router, prefix="/board", tags=["Board"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(roads.router, prefix="/roads", tags=["Roads"])

# ✅ WebSocket 서버 마운트 (board.py에서 설정한 socket_app과 연결)
from app.api.routes.board import socket_app
app.mount("/ws", socket_app)

@app.get("/")
def root():
  return {"message": "개발 중.."}
