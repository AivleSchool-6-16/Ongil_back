from fastapi import FastAPI, Request, HTTPException, Depends
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.api.routes import auth, inquire, mypage, board, admin, roads
from app.utils.token_blacklist import is_token_blacklisted
from app.utils.jwt_utils import verify_token


DATABASE_URL = "mysql+pymysql://admin:aivle202406@ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com:3306/ongildb"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
app = FastAPI()
# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(inquire.router, prefix="/inquire", tags=["Inquire"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])
app.include_router(board.router, prefix="/board", tags=["Board"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(roads.router, prefix="/roads", tags=["Roads"])

def get_db():
    try:
        connection = mysql.connector.connect(
            host="ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com",
            user="admin",
            password="aivle202406",
            database="ongildb"
        )
        if connection.is_connected():
            yield connection
    except Error as e:
        print(f"Error connecting to the database: {e}")
        raise HTTPException(status_code=500, detail="Could not connect to the database.")
    finally:
        if connection.is_connected():
            connection.close()

@app.middleware("http")
async def check_token_blacklist(request: Request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        if is_token_blacklisted(token):
            raise HTTPException(status_code=401, detail="Token is blacklisted.")
        if not verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return await call_next(request)



@app.get("/")
def main(): 
    return {"message": "개발 중.."}




