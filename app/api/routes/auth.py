from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime, timedelta, timezone
import redis
import json
from mysql.connector import Error
from app.database.mysql_connect import get_connection
from app.core.security import hash_password, verify_password
from app.core.email_utils import generate_verification_code, send_verification_email, send_signup_email
from app.core.jwt_utils import create_access_token, verify_token, create_refresh_token
from app.core.token_blacklist import add_token_to_blacklist, is_token_blacklisted

router = APIRouter()

# Redis 연결
try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None

# 인증번호 임시 저장
verification_codes = {}

# 요청 모델 정의
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    jurisdiction: str
    department: str

    @field_validator("password")
    def validate_password(cls, value):
        """비밀번호 유효성 검증 - 8자리 이상, 대소문자 포함, 특수문자 포함"""
        if len(value) < 8:
            raise HTTPException(status_code=400, detail="비밀번호는 최소 8자리 이상이어야 합니다.")
        if not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c in "!@#$%^&*()" for c in value):
            raise HTTPException(status_code=400, detail="비밀번호는 대소문자 및 !@#$%^&*() 중 하나 이상 포함해야 합니다.")
        return value

    @field_validator("confirm_password")
    def passwords_match(cls, value, info):
        """비밀번호 확인 - 입력한 두 비밀번호가 일치하는지 검증"""
        if "password" in info.data and value != info.data["password"]:
            raise HTTPException(status_code=400, detail="입력한 비밀번호가 일치하지 않습니다.")
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
        """비밀번호 유효성 검증 - 8자리 이상, 대소문자 포함, 특수문자 포함"""
        if len(value) < 8:
            raise HTTPException(status_code=400, detail="새 비밀번호는 최소 8자리 이상이어야 합니다.")
        if not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c in "!@#$%^&*()" for c in value):
            raise HTTPException(status_code=400, detail="새 비밀번호는 대소문자 및 !@#$%^&*() 중 하나 이상 포함해야 합니다.")
        return value

    @field_validator("confirm_password")
    def passwords_match(cls, value, info):
        """비밀번호 확인 - 입력한 두 비밀번호가 일치하는지 검증"""
        if "new_password" in info.data and value != info.data["new_password"]:
            raise HTTPException(status_code=400, detail="입력한 새 비밀번호가 일치하지 않습니다.")
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
  """중복 및 형식 확인 """
  if not request.email.endswith("@gmail.com"):
    raise HTTPException(status_code=400, detail="'@gmail.com' 형식만 가능합니다.")

  if find_user_by_email(request.email):
    raise HTTPException(status_code=400, detail="이메일이 이미 사용 중입니다.")

  return {"message": "사용 가능한 이메일입니다."}


# 2. 비밀번호 검증 및 회원가입 인증 이메일 전송
@router.post("/signup/send-code")
def signup_send_code(request: SignUpRequest):
  """
  비밀번호 검증 및 회원가입 인증 이메일 전송
  - 비밀번호 검증 실패 시 오류 반환\n
  - 이메일 중복 확인 후 인증 이메일 전송\n
  - Redis에 사용자 정보 저장 (10분 유지)
  """
  hashed_password = hash_password(request.password)

  token = create_access_token(data={"sub": request.email},expires_delta=timedelta(minutes=10))
  user_data = {
    "email": request.email,
    "password": hashed_password,  # 해싱된 비밀번호 저장
    "name": request.name,
    "jurisdiction": request.jurisdiction,
    "department": request.department
  }
  redis_client.setex(f"signup_data:{request.email}", timedelta(minutes=10),json.dumps(user_data))

  if not send_signup_email(request.email, token):
    raise HTTPException(status_code=500, detail="인증 이메일 발송에 실패했습니다.")

  return {"message": "회원가입 인증 이메일이 발송되었습니다. 10분 이내에 인증을 완료해주세요."}


# 3. 이메일 인증 확인
@router.get("/signup/confirm")
def confirm_email(token: str = Query(...)):
    """
    이메일 인증 완료 시 해싱된 비밀번호 포함 사용자 정보를 DB에 저장 후,
    (원하는 프론트엔드 도메인으로) 리디렉트하며 토큰도 넘긴다.
    """
    try:
        payload = verify_token(token)
        email = payload.get("sub")

        if not email:
            return RedirectResponse(url="/signup/error?error_type=invalid_token")

        # 이미 이메일이 있다면
        if find_user_by_email(email):
            return RedirectResponse(url="https://ongil.vercel.app")

        # 레디스에서 확인
        user_data_json = redis_client.get(f"signup_data:{email}")
        if not user_data_json:
            return RedirectResponse(url="/signup/error?error_type=missing_info")

        user_data = json.loads(user_data_json)

        # DB에 user_data 저장
        try:
            connection = get_connection()
            cursor = connection.cursor()
            query = """
                INSERT INTO user_data (user_email, user_ps, user_name, jurisdiction, user_dept)
                VALUES (%s, %s, %s, %s, %s)
            """
            values = (
                user_data["email"],
                user_data["password"],  # 이미 암호화된 상태
                user_data["name"],
                user_data["jurisdiction"],
                user_data["department"]
            )
            cursor.execute(query, values)
            connection.commit()
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

        # 레디스에서 데이터 삭제
        redis_client.delete(f"signup_data:{email}")

        # 인증 완료 후 로그인 리디렉션
        return RedirectResponse(url="https://ongil.vercel.app")

    except Exception:
        return RedirectResponse(url="/signup/error?error_type=unknown")


# 3-1. 회원가입 인증 에러
@router.get("/signup/error", response_class=HTMLResponse)
def signup_error(error_type: str = Query("unknown")):
  """
  회원가입 중 오류가 발생했을 때 오류 메시지를 표시하는 페이지
  """
  error_messages = {
    "invalid_token": "인증 토큰이 유효하지 않거나 만료되었습니다.",
    "missing_info": "회원가입 정보가 누락되었습니다. 다시 진행해주세요.",
    "already_registered": "이미 회원가입된 이메일입니다. 로그인하세요.",
    "unknown": "알 수 없는 오류가 발생했습니다. 다시 시도해주세요."
  }

  error_message = error_messages.get(error_type, error_messages["unknown"])

  return HTMLResponse(content=f"""
    <html>
        <head>
            <script>
                window.onload = function() {{
                    alert("{error_message}");
                    window.location.href = "/signup";
                }};
            </script>
        </head>
        <body>
        </body>
    </html>
    """, status_code=400)


# ✅ 로그인
@router.post("/login")
def login_user(request: LoginRequest):
    user = find_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 이메일입니다.")

    # 관리자 권한 값 조회 (일반 사용자: 1, 개발자: 2 등)
    admin_value = is_admin(request.email)

    # is_admin이 2 (개발자 계정)일 때는 비밀번호 해시 검증 대신 평문 비교를 사용
    if admin_value == 2:
        if request.password != user["user_ps"]:
            raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    else:
        # 일반 사용자: 해시된 비밀번호 검증
        if not verify_password(request.password, user["user_ps"]):
            raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")

    # 토큰 생성 시, 관리자 여부 값을 payload에 포함
    access_token = create_access_token(
        data={"sub": request.email, "admin": admin_value},
        expires_delta=timedelta(hours=12)
    )
    refresh_token = create_refresh_token(
        data={"sub": request.email},
        expires_delta=timedelta(days=7)
    )
    # ✅ 로그인 성공 시 online_users Set에 등록
    redis_client.sadd("online_users", request.email)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "is_admin": admin_value
    }

# ✅ 로그아웃
@router.post("/logout")
def logout(request: LogoutRequest):
    payload = verify_token(request.token)
    if not payload:
        raise HTTPException(status_code=401, detail="만료된 토큰입니다.")

    expiration_time = payload.get("exp")
    current_time = datetime.now(timezone.utc).timestamp()
    remaining_time = max(int(expiration_time - current_time), 0)
    add_token_to_blacklist(request.token, remaining_time)

    # ✅ 접속자 목록에서 제거
    email = payload.get("sub")
    redis_client.srem("online_users", email)

    return {"message": "로그아웃 되었습니다."}


# ✅ refresh token으로 access token 요청
@router.post("/refresh")
def refresh_token(refresh_token: str):
  """refresh 토큰 요청"""
  decoded_token = verify_token(refresh_token, token_type="refresh")
  email = decoded_token.get("sub")

  if not email:
    raise HTTPException(status_code=401, detail="인증이 만료되었습니다. 다시 로그인하세요.")

  # 관리자 체크
  is_admin_user = is_admin(email)

  # 새 토큰 발급
  new_access_token = create_access_token(
      data={"sub": email, "admin": is_admin_user},
      expires_delta=timedelta(hours=12)
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
    raise HTTPException(status_code=401, detail="토큰이 블랙리스트에 등록되었습니다.")

  payload = verify_token(token)
  if not payload:
    raise HTTPException(status_code=401, detail="만료된 토큰입니다.")

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
  if request.email not in verification_codes or verification_codes[
    request.email] != request.code:
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
    raise HTTPException(status_code=401, detail="인증이 만료되었습니다. 인증번호를 다시 발송하세요.")

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
