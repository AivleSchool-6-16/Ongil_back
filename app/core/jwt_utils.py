from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import os
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from app.core.token_blacklist import is_token_blacklisted
from typing import Optional

load_dotenv() 
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set or loaded correctly.")


def create_access_token(data: dict, expires_delta: timedelta):
    """
    Create a short-lived access token
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict, expires_delta: timedelta):
    """
    Create a long-lived refresh token
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: Optional[str] = Header(None), token_type: str = "access"):
    """JWT 토큰을 디코딩하고 유효성을 검사하는 함수"""
    if not token:
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")

    try:
        # JWT 토큰 디코딩
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # "admin" 뿐만 아니라 "sub"도 포함하는지 확인
        if token_type == "access" and "admin" not in payload and "sub" not in payload:
            raise HTTPException(status_code=401, detail="잘못된 접근 토큰 형식입니다.")

        return payload  # 정상적인 경우 페이로드 반환

    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않거나 손상된 토큰입니다.")

def get_authenticated_user(token: Optional[str] = Header(None)):
    """토큰을 검증하고 인증된 사용자 정보를 반환하는 함수"""
    if not token:
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")

    if is_token_blacklisted(token):  # 블랙리스트 체크
        raise HTTPException(status_code=401, detail="이 토큰은 블랙리스트에 등록되었습니다.")

    try:
        payload = verify_token(token)
        return payload  # 정상적인 경우 사용자 정보를 반환
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"인증 실패: {str(e)}")
    