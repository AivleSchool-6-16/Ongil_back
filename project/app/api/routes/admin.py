# 관리자 대시보드 
from fastapi import HTTPException, Header, APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()


# 데이터 조회 엔드포인트
@router.get("/api/data", response_model=List[Item])
async def get_data():
    return data

# 데이터 추가 엔드포인트
@router.post("/api/data", response_model=Item)
async def add_data(item: Item):
    data.append(item)
    return item

