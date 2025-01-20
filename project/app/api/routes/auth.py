#로그인, 로그아웃, 회원가입, 비번 찾기
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import redis

from app.db.database import get_db
from app.db.user_model import User
from app.utils.security import hash_password, verify_password
from app.utils.email_utils import generate_verification_code, send_verification_email
from app.utils.jwt_utils import create_access_token, verify_token, create_refresh_token
from app.utils.token_blacklist import add_token_to_blacklist, is_token_blacklisted

router = APIRouter()

try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
    
    # Test the connection
    redis_client.ping()
    print("Connected to Redis")
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None 

# 인증번호 임시 저장 : 보안성(
verification_codes = {}

# requests 모델 정의 
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    management_area: str
    department: str

    @field_validator("password")
    def validate_password(cls, value):
        if len(value) < 8 or not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c in "!@#$%^&*()" for c in value):
            raise ValueError("8자리 이상, 대소문자 포함, !@#$%^&*() 중 하나 이상 포함")
        return value

    @field_validator("confirm_password")
    def passwords_match(cls, value, info):
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("비밀번호가 다릅니다.")
        return value
    
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LogoutRequest(BaseModel):
    token: str

class FindPasswordRequest(BaseModel):
    email: EmailStr

class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str
    confirm_password: str


def find_user_by_email(email: str, db: Session) -> User:
    return db.query(User).filter(User.email == email).first()

@router.post("/signup")
def signup(request: SignUpRequest, db: Session = Depends(get_db)):
    if not request.email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="'@korea.kr' 형식만 가능합니다.")

    if find_user_by_email(request.email, db):
        raise HTTPException(status_code=400, detail="이메일이 이미 존재합니다.")

    hashed_password = hash_password(request.password)
    new_user = User(
        email=request.email,
        password=hashed_password,
        name=request.name,
        mgmt_area=request.management_area,
        department=request.department
    )
    db.add(new_user)
    db.commit()

    return {"message": "회원가입에 성공하였습니다."}


@router.post("/login")
def login_user(request: LoginRequest, db: Session = Depends(get_db)):
    user = find_user_by_email(request.email, db)
    if not request.email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="'@korea.kr' 형식만 가능합니다.")
    
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    if not verify_password(request.password, user.password):
        raise HTTPException(status_code=400, detail="비밀번호가 올바르지 않습니다.")

    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=15)
    )
    refresh_token = create_refresh_token(
        data={"sub": user.email}, expires_delta=timedelta(hours=3)
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/logout")
def logout(request: LogoutRequest):
    payload = verify_token(request.token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    expiration_time = payload.get("exp")
    current_time = datetime.now(timezone.utc).timestamp()
    remaining_time = max(int(expiration_time - current_time), 0)

    add_token_to_blacklist(request.token, remaining_time)
    return {"message": "로그아웃 되었습니다."}


@router.post("/refresh-token")
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    payload = verify_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    user = find_user_by_email(payload["sub"], db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=15)
    )
    new_refresh_token = create_refresh_token(
        data={"sub": user.email}, expires_delta=timedelta(hours=3)
    )

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.get("/protected")
def protected_route(token: str = Header(...)):
    """Example protected route"""
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token is blacklisted.")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {"message": f"You are authenticated as {payload['sub']}."}


@router.post("/findpwd")
def findpwd(request: FindPasswordRequest, db: Session = Depends(get_db)):
    """Request password recovery code"""
    user = find_user_by_email(request.email, db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    # Generate and store verification code
    code = generate_verification_code()
    verification_codes[request.email] = code

    # Send the code via email
    if not send_verification_email(request.email, code):
        raise HTTPException(status_code=500, detail="인증번호 이메일 발송에 실패했습니다.")

    return {"message": "인증번호가 이메일로 발송되었습니다."}


@router.post("/verify-code")
def verify_code(request: VerifyCodeRequest, db: Session = Depends(get_db)):
    """Verify the recovery code and issue a reset token"""
    if request.email not in verification_codes or verification_codes[request.email] != request.code:
        raise HTTPException(status_code=400, detail="유효하지 않은 인증번호입니다.")

    user = find_user_by_email(request.email, db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    # Issue a temporary token for password reset
    reset_token = create_access_token(
        data={"sub": user.email, "action": "password_reset"},
        expires_delta=timedelta(minutes=15)
    )

    return {
        "message": "인증번호가 유효합니다. 비밀번호를 재설정해야 합니다.",
        "reset_token": reset_token,
    }

  
@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset the user's password"""
    # Validate the reset token
    payload = verify_token(request.reset_token)
    if not payload or payload.get("action") != "password_reset":
        raise HTTPException(status_code=401, detail="Invaild reset token.")

    email = payload.get("sub")
    user = find_user_by_email(email, db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    # Check if passwords match
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    # Update the user's password
    hashed_password = hash_password(request.new_password)
    user.password = hashed_password
    db.commit()

    return {"message": "비밀번호가 성공적으로 재설정되었습니다."}