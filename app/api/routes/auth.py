from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime, timedelta, timezone
import redis
from mysql.connector import Error
from app.database.mysql_connect import get_connection
from app.core.security import hash_password, verify_password
from app.core.email_utils import generate_verification_code, send_verification_email, send_signup_email
from app.core.jwt_utils import create_access_token, verify_token, create_refresh_token
from app.core.token_blacklist import add_token_to_blacklist, is_token_blacklisted

router = APIRouter()

# redis 연결
try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None

# 인증번호 임시 저장 : 보안성(?)
verification_codes = {}

# requests 모델 정의
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    jurisdiction: str
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

class EmailCheckRequest(BaseModel):
    email: EmailStr

class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str
    confirm_password: str
    
    @field_validator("new_password")
    def validate_password(cls, value):
        if len(value) < 8 or not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c in "!@#$%^&*()" for c in value):
            raise ValueError("8자리 이상, 대소문자 포함, !@#$%^&*() 중 하나 이상 포함")
        return value

    @field_validator("confirm_password")
    def passwords_match(cls, value, info):
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("비밀번호가 다릅니다.")
        return value

# 사용자 확인 
def find_user_by_email(email: str):
    try:
        connection = get_connection()  
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM user_data WHERE user_email = %s"
        cursor.execute(query, (email,))
        user = cursor.fetchone()
        return user
    except Error as e:
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed.")
    finally:
        if 'cursor' in locals() and cursor:  
            cursor.close()
        if 'connection' in locals() and connection.is_connected(): 
            connection.close()

# 관리자 확인      
def is_admin(email: str):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = "SELECT is_admin FROM permissions WHERE user_email = %s"
        cursor.execute(query, (email,))
        result = cursor.fetchone()
        return result and result["is_admin"]
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# 1. 이메일 중복 및 형식 확인
@router.post("/signup/check-email")
def check_email(request: EmailCheckRequest):
    if not request.email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="'@gmail.com' 형식만 가능합니다.")

    if find_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="이메일이 이미 사용 중입니다.")

    return {"message": "사용 가능한 이메일입니다."}

# 2. 회원가입 인증 이메일 전송
@router.post("/signup/send-code")
def send_signup_code(request: EmailCheckRequest):
    if find_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="이메일이 이미 사용 중입니다.")

    token = create_access_token(data={"sub": request.email}, expires_delta=timedelta(minutes=10))
    redis_client.setex(f"signup_token:{request.email}", timedelta(minutes=10), token)

    if not send_signup_email(request.email, token):
        raise HTTPException(status_code=500, detail="인증 이메일 발송에 실패했습니다.")

    return {"message": "회원가입 인증 이메일이 발송되었습니다. 10분 이내에 인증을 완료해주세요."}

# 3. 이메일 인증 확인
@router.get("/signup/confirm", response_class=HTMLResponse)
def confirm_email(token: str = Query(...)):
    """
    이메일 인증 처리 - 성공하면 로그인으로 이동, 실패하면 팝업창 뜨도록 
    """
    try:
        payload = verify_token(token)
        email = payload.get("sub")

        if not email:
            raise HTTPException(status_code=400, detail="유효하지 않은 토큰입니다.")

        # Redis에서 인증 상태 업데이트
        redis_client.setex(f"verified:{email}", timedelta(minutes=30), "true")

        # 성공 페이지 반환 - 로그인 페이지로 이동하도록 
        return HTMLResponse(content=f"""
        <html>
            <body>
                <h1>이메일 인증 완료</h1>
                <p>이메일 인증이 성공적으로 완료되었습니다!</p>
            </body>
        </html>
        """, status_code=200)

    except Exception as e:
        # 실패 페이지 반환
        return HTMLResponse(content=f"""
        <html>
            <body>
                <h1>이메일 인증 실패</h1>
                <p>인증 토큰이 유효하지 않거나 만료되었습니다.</p>
            </body>
        </html>
        """, status_code=400)

# ✅ 4. 회원가입 완료
@router.post("/signup/complete")
def complete_signup(request: SignUpRequest):
    if not redis_client.get(f"verified:{request.email}"):
        raise HTTPException(status_code=400, detail="이메일 인증이 필요합니다.")

    if find_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="이메일이 이미 사용 중입니다.")

    hashed_password = hash_password(request.password)
    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = (
            "INSERT INTO user_data (user_email, user_ps, user_name, jurisdiction, user_dept) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        cursor.execute(query, (request.email, hashed_password, request.name, request.jurisdiction, request.department))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "회원가입이 완료되었습니다."}

# ✅ 로그인 API
@router.post("/login")
def login_user(request: LoginRequest):
    user = find_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not verify_password(request.password, user["user_ps"]):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    # 관리자 확인
    is_admin_user = is_admin(request.email)

    # JWT 토큰 생성 (Access & Refresh)
    access_token = create_access_token(
        data={"sub": request.email, "admin": is_admin_user}, expires_delta=timedelta(minutes=30)
    )
    refresh_token = create_refresh_token(
        data={"sub": request.email}, expires_delta=timedelta(days=7)
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "is_admin": is_admin_user
    }

# ✅ 로그아웃 
@router.post("/logout")
def logout(request: LogoutRequest):
    """logout"""
    payload = verify_token(request.token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    expiration_time = payload.get("exp")
    current_time = datetime.now(timezone.utc).timestamp()
    remaining_time = max(int(expiration_time - current_time), 0)

    add_token_to_blacklist(request.token, remaining_time)
    return {"message": "로그아웃 되었습니다."}

# ✅ refresh token으로 access token 요청 
@router.post("/refresh")
def refresh_token(refresh_token: str):
    """refresh 토큰 요청"""
    decoded_token = verify_token(refresh_token, token_type="refresh")
    email = decoded_token.get("sub")
    
    if not email:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")
    
    # 관리자 체크 
    is_admin_user = is_admin(email)
    
    # 새 토큰 발급 
    new_access_token = create_access_token(
        data={"sub": email, "admin": is_admin_user}, expires_delta=timedelta(minutes=15)
    )

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "is_admin": is_admin_user
    }

# 토큰 확인 
@router.get("/protected")
def protected_route(token: str = Header(...)):
    """토큰 확인하기 - debugging용"""
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token is blacklisted.")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {"message": f"You are authenticated as {payload['sub']}."}

# ✅ 비밀번호 찾기 
@router.post("/findpwd")
def findpwd(request: EmailCheckRequest):
    """비밀번호 재설정 위한 인증번호 이메일로 보내기"""
    user = find_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    code = generate_verification_code()
    verification_codes[request.email] = code

    if not send_verification_email(request.email, code):
        raise HTTPException(status_code=500, detail="인증번호 이메일 발송에 실패했습니다.")

    return {"message": "인증번호가 이메일로 발송되었습니다."}

# ✅ 비밀번호 인증 코드 확인 
@router.post("/verify-code")
def verify_code(request: VerifyCodeRequest):
    """인증번호 입력 후 확인"""
    if request.email not in verification_codes or verification_codes[request.email] != request.code:
        raise HTTPException(status_code=400, detail="유효하지 않은 인증번호입니다.")

    user = find_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    reset_token = create_access_token(
        data={"sub": user['user_email'], "action": "password_reset"},
        expires_delta=timedelta(minutes=15)
    )

    return {
        "message": "인증번호가 유효합니다. 비밀번호를 재설정해야 합니다.",
        "reset_token": reset_token,
    }

# ✅ 비밀번호 재설정 
@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    """비밀번호 재설정하기"""
    payload = verify_token(request.reset_token)
    if not payload or payload.get("action") != "password_reset":
        raise HTTPException(status_code=401, detail="Invalid reset token.")

    email = payload.get("sub")
    user = find_user_by_email(email)
    if not user:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일입니다.")

    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    hashed_password = hash_password(request.new_password)

    try:
        connection = get_connection()
        cursor = connection.cursor()
        query = "UPDATE user_data SET user_ps = %s WHERE user_email = %s"
        cursor.execute(query, (hashed_password, email))
        connection.commit()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return {"message": "비밀번호가 성공적으로 재설정되었습니다."}
