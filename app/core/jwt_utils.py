from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import os
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from app.core.token_blacklist import is_token_blacklisted

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


def verify_token(token: str = Header(...), token_type: str = "access"):
    """Decode and validate a JWT token (access or refresh)."""
    try:
        # Decode JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Validate token type
        if token_type == "access" and "admin" not in payload:
            raise HTTPException(status_code=401, detail="Invalid access token format.")
        
        return payload
    
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or malformed token.")

def get_authenticated_user(token: str = Header(...)):
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token is blacklisted.")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return payload
    