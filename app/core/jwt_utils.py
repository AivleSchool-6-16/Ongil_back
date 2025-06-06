import logging
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import os
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from app.core.token_blacklist import is_token_blacklisted
from typing import Optional

# .env 파일 위치 명시
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set or loaded correctly.")

# 로거 설정 (필요에 따라 다른 이름/레벨로 설정 가능)
logger = logging.getLogger("app.core.jwt_utils")
logger.setLevel(logging.INFO)


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


def verify_token(token: str, token_type: str = "access"):
    """JWT 토큰을 디코딩하고 유효성을 검사하는 함수"""
    if not token:
        # 토큰이 없는 경우
        logger.warning("[TokenError] 인증 토큰이 전혀 제공되지 않았습니다.")
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")

    try:
        # ✅ JWT 토큰 디코딩
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # ✅ "sub" 필드는 일반 사용자 식별, "admin"은 관리자 식별
        if token_type == "access" and "sub" not in payload:
            logger.warning("[TokenError] 접근 토큰에 'sub' 필드가 없습니다.")
            raise HTTPException(status_code=401, detail="잘못된 접근 토큰 형식입니다.")

        return payload  # 정상적인 경우 페이로드 반환

    except JWTError as e:
        # 로그에 구체적인 에러 메시지 기록
        logger.error(f"[TokenError] JWT 검증 실패: {e}")
        raise HTTPException(
            status_code=401, detail="유효하지 않거나 손상된 토큰입니다."
        )


def get_authenticated_user(token: Optional[str] = Header(None)):
    """토큰을 검증하고 인증된 사용자 정보를 반환하는 함수"""
    if is_token_blacklisted(token):  # 블랙리스트 체크
        logger.warning("[TokenBlacklist] 블랙리스트에 등록된 토큰 접근 시도.")
        raise HTTPException(
            status_code=401, detail="이 토큰은 블랙리스트에 등록되었습니다."
        )

    try:
        payload = verify_token(token)
        return payload  # 정상적인 경우 사용자 정보를 반환
    except Exception as e:
        # 인증 실패 시 로그
        logger.error(f"[AuthenticationFailed] {e}")
        raise HTTPException(status_code=401, detail=f"인증 실패: {str(e)}")
