# 비밀번호 보안
import os
from passlib.context import CryptContext

# 환경변수에서 PEPPER 값을 가져옵니다.
pepper = os.getenv("PEPPER", "")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password + pepper)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password + pepper, hashed_password)

