#로그인, 비번 찾기, 회원가입 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session
from db.database import get_db
from db.user_model import User
from utils.security import hash_password, verify_password
from utils.email_utils import generate_verification_code, send_verification_email

router = APIRouter()

# 인증번호 저장 : 보안성(?)
verification_codes = {}

# Request models
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    department: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class PasswordRecoveryRequest(BaseModel):
    email: EmailStr

class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str


def find_user_by_email(email: str, db: Session) -> User:
    return db.query(User).filter(User.email == email).first()

@router.post("/signup")
def signup(request: SignUpRequest, db: Session = Depends(get_db)):
    if not request.email.endswith("@korea.kr"):
        raise HTTPException(status_code=400, detail="'@korea.kr' 형식만 가능합니다.")

    if find_user_by_email(request.email, db):
        raise HTTPException(status_code=400, detail="이메일이 이미 존재합니다.")

    hashed_password = hash_password(request.password)
    new_user = User(
        email=request.email,
        password=hashed_password,
        name=request.name,
        department=request.department
    )
    db.add(new_user)
    db.commit()

    return {"message": "회원가입에 성공하였습니다."}


@router.post("/login")
def login_user(request: LoginRequest, db: Session = Depends(get_db)):
    user = find_user_by_email(request.email, db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    if not verify_password(request.password, user.password):
        raise HTTPException(status_code=400, detail="비밀번호가 올바르지 않습니다.")

    return {"message": "로그인에 성공하였습니다."}


@router.post("/findpwd")
def findpwd(request: PasswordRecoveryRequest, db: Session = Depends(get_db)):
    user = find_user_by_email(request.email, db)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    # 인증번호 생성 및 저장
    code = generate_verification_code()
    verification_codes[request.email] = code

    # 이메일 발송
    if not send_verification_email(request.email, code):
        raise HTTPException(status_code=500, detail="인증번호 이메일 발송에 실패했습니다.")

    return {"message": "인증번호가 이메일로 발송되었습니다."}


@router.post("/verify-code")
def verify_code(request: VerifyCodeRequest, db: Session = Depends(get_db)):
    if request.email not in verification_codes or verification_codes[request.email] != request.code:
        raise HTTPException(status_code=400, detail="유효하지 않은 인증번호입니다.")

    user = find_user_by_email(request.email, db)

    # 인증 성공 시 비밀번호 출력 
    return {"message": f"{request.email}님의 비밀번호는 {user.password}입니다."} # 보안성(?)