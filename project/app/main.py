from fastapi import FastAPI,Request, HTTPException
from app.db.database import Base, engine
from app.api.routes import auth
from app.utils.token_blacklist import is_token_blacklisted
from app.utils.jwt_utils import verify_token
# Create all tables in the database
Base.metadata.create_all(bind=engine)

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
app.include_router(board.router, prefix="/board", tags=["Board"])
# app.include_router(inquire.router, prefix="/inquire", tags=["Inquire"])
# app.include_router(roads.router, prefix="/roads", tags=["Roads"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])

@app.get("/")
def root():
    return {"message": "개발 중.."}
