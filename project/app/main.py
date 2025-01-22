from fastapi import FastAPI, Request, HTTPException, Depends
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.api.routes import auth, inquire
from app.utils.token_blacklist import is_token_blacklisted
from app.utils.jwt_utils import verify_token

DATABASE_URL = "mysql+pymysql://root:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency for DB sessions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

@app.middleware("http")
async def check_token_blacklist(request: Request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is blacklisted.")
        if not verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return await call_next(request)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(inquire.router, prefix="/inquire", tags=["Inquire"])

@app.get("/")
def root():
    return {"message": "개발 중.."}
