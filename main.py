from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

from app.api.routes import admin, auth, board, mypage, roads
from app.core.token_blacklist import is_token_blacklisted
from app.core.jwt_utils import verify_token
from app.services.sync_views import sync_redis_to_mysql

DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 App is starting... Initializing scheduler")
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_redis_to_mysql, "interval", minutes=10)  # Run every 10 minutes
    scheduler.start()
    
    # Store the scheduler in app state to prevent garbage collection
    app.state.scheduler = scheduler  

    yield  # Allows the app to run

    print("🛑 Shutting down scheduler...")
    scheduler.shutdown()

# ✅ Initialize FastAPI with lifespan event handler
app = FastAPI(lifespan=lifespan)

# ✅ Middleware for Token Blacklist Check
@app.middleware("http")
async def check_token_blacklist(request: Request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is blacklisted.")
        if not verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return await call_next(request)

# ✅ Include Routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(board.router, prefix="/board", tags=["Board"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(roads.router, prefix="/roads", tags=["Roads"])


@app.get("/")
def root():
    return {"message": "개발 중.."}