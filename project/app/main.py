from fastapi import FastAPI
from app.api.routes import auth, board, inquire, roads, mypage

app = FastAPI()

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(board.router, prefix="/board", tags=["Board"])
app.include_router(inquire.router, prefix="/inquire", tags=["Inquire"])
app.include_router(roads.router, prefix="/roads", tags=["Roads"])
app.include_router(mypage.router, prefix="/mypage", tags=["MyPage"])
