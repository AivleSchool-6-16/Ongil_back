# tests/routes/test_auth_extra.py

import json
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from main import app  # 프로젝트 루트에 있는 main.py에서 FastAPI 인스턴스(app)를 import


# --- Fake DB Connection, Cursor (테스트용) ---
class FakeCursor:
    def __init__(self):
        self.executed_queries = []

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))

    def fetchone(self):
        return {"is_admin": False}  # is_admin 검사용 기본 값

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor_instance=None):
        self._cursor = cursor_instance or FakeCursor()

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass

    def is_connected(self):
        return True


# --- Fake Redis ---
class FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, time_delta, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        if key in self.store:
            del self.store[key]


# --- Fake Functions and Overrides ---
def fake_find_user_none(email: str):
    """사용자가 없는 상황을 시뮬레이션"""
    return None


def fake_find_user(email: str):
    """사용자가 이미 존재하는 상황을 시뮬레이션"""
    return {"user_email": email, "user_ps": "hashed_password", "user_name": "Test User"}


def fake_verify_password(password, hashed):
    return password == "correct_password"


def fake_is_admin(email: str):
    return False


def fake_create_access_token(data, expires_delta):
    return "fake_access_token"


def fake_create_refresh_token(data, expires_delta):
    return "fake_refresh_token"


def fake_send_signup_email(email, token):
    return True


def fake_generate_verification_code():
    return "123456"


def fake_add_token_to_blacklist(token, remaining_time):
    return True


def fake_hash_password(password):
    return "hashed_" + password


# --- 오버라이드할 전역 변수 (인증 관련) ---
import app.api.routes.auth as auth_module

auth_module.find_user_by_email = fake_find_user_none
auth_module.is_admin = fake_is_admin
auth_module.hash_password = fake_hash_password
auth_module.verify_password = fake_verify_password
auth_module.create_access_token = fake_create_access_token
auth_module.create_refresh_token = fake_create_refresh_token
auth_module.send_signup_email = fake_send_signup_email
auth_module.generate_verification_code = fake_generate_verification_code
auth_module.add_token_to_blacklist = fake_add_token_to_blacklist

# Redis 클라이언트도 Fake로 대체
fake_redis = FakeRedis()
auth_module.redis_client = fake_redis

client = TestClient(app)


# --- 테스트 케이스 ---


def test_signup_send_code(monkeypatch):
    """
    POST /signup/send-code
    회원가입 시 비밀번호 검증 후, 인증 이메일 전송이 성공하는 경우
    """
    payload = {
        "email": "test@gmail.com",
        "password": "CorrectPass1!",
        "confirm_password": "CorrectPass1!",
        "name": "Test User",
        "jurisdiction": "RegionX",
        "department": "DeptX",
    }
    # 이메일 중복 확인: 사용자 없음
    monkeypatch.setattr(auth_module, "find_user_by_email", fake_find_user_none)
    # Redis의 setex를 FakeRedis를 사용하도록 처리
    fake_redis.store = {}  # 초기화
    response = client.post("auth/signup/send-code", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert "회원가입 인증 이메일이 발송되었습니다." in res_data.get("message", "")


def test_signup_confirm(monkeypatch):
    """
    GET /signup/confirm?token=...
    회원가입 이메일 인증 처리 (정상 처리 시 리디렉션)
    """
    # fake verify_token: 유효한 토큰 반환
    monkeypatch.setattr(
        auth_module, "verify_token", lambda token, **kwargs: {"sub": "test@gmail.com"}
    )
    # 사용자 미존재 상황: find_user_by_email 반환 None
    monkeypatch.setattr(auth_module, "find_user_by_email", fake_find_user_none)
    # Redis에서 회원가입 데이터 반환하도록 FakeRedis 설정
    user_data = {
        "email": "test@gmail.com",
        "password": "hashed_password",
        "name": "Test User",
        "jurisdiction": "RegionX",
        "department": "DeptX",
    }
    fake_redis.setex(
        "signup_data:test@gmail.com", timedelta(minutes=10), json.dumps(user_data)
    )
    # get_connection: Fake DB 연결, INSERT 시도 기록
    fake_cursor = FakeCursor()
    fake_conn = FakeConnection(fake_cursor)
    monkeypatch.setattr(auth_module, "get_connection", lambda: fake_conn)

    response = client.get(
        "/auth/signup/confirm?token=fake_token", allow_redirects=False
    )
    # 정상 처리 후, 리디렉션 (예: https://ongil.vercel.app)
    assert response.status_code in [302, 307]
    # Location 헤더에 리디렉션 URL이 포함되어 있어야 합니다.
    assert "https://ongil.vercel.app" in response.headers.get("location", "")


def test_signup_error():
    """
    GET /signup/error?error_type=invalid_token
    회원가입 에러 페이지를 반환 (HTMLResponse, 상태코드 400)
    """
    response = client.get("auth/signup/error?error_type=invalid_token")
    assert response.status_code == 400
    assert "인증 토큰이 유효하지 않거나 만료되었습니다." in response.text


def test_logout(monkeypatch):
    """
    POST /logout
    로그인 상태에서 로그아웃 요청 시, 성공 메시지 반환
    """
    # fake verify_token: token 검증에 성공하도록
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token, **kwargs: {
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        },
    )

    data = {"token": "dummy_token"}
    # URL 수정: /auth/logout로 요청
    response = client.post("/auth/logout", json=data)
    assert response.status_code == 200
    res_data = response.json()
    assert "로그아웃 되었습니다." in res_data.get("message", "")


def test_refresh(monkeypatch):
    """
    POST /refresh
    refresh 토큰을 이용해 access token 재발급
    """
    # fake verify_token: refresh 토큰 검증 (token_type="refresh" 무시)
    monkeypatch.setattr(
        auth_module, "verify_token", lambda token, **kwargs: {"sub": "test@gmail.com"}
    )
    monkeypatch.setattr(auth_module, "is_admin", fake_is_admin)
    monkeypatch.setattr(
        auth_module,
        "create_access_token",
        lambda data, expires_delta: "new_fake_access_token",
    )
    response = client.post("/auth/refresh?refresh_token=dummy_refresh_token")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data.get("access_token") == "new_fake_access_token"
    assert res_data.get("token_type") == "bearer"
    assert res_data.get("is_admin") is False


def test_findpwd(monkeypatch):
    """
    POST /findpwd
    비밀번호 찾기 - 존재하는 이메일이면 인증번호 이메일 발송
    """
    # 사용자 존재 여부: find_user_by_email 반환 사용자 정보
    monkeypatch.setattr(auth_module, "find_user_by_email", fake_find_user)
    monkeypatch.setattr(auth_module, "generate_verification_code", lambda: "123456")
    monkeypatch.setattr(
        auth_module, "send_verification_email", lambda email, code: True
    )

    data = {"email": "test@gmail.com"}
    response = client.post("auth/findpwd", json=data)
    assert response.status_code == 200
    res_data = response.json()
    assert "인증번호가 이메일로 발송되었습니다." in res_data.get("message", "")


def test_verify_code(monkeypatch):
    """
    POST /verify-code
    올바른 인증코드 입력 시, reset_token 발급
    """
    # 먼저, 테스트 전에 global verification_codes에 값을 셋팅
    auth_module.verification_codes["test@gmail.com"] = "123456"
    monkeypatch.setattr(auth_module, "find_user_by_email", fake_find_user)

    data = {"email": "test@gmail.com", "code": "123456"}
    response = client.post("auth/verify-code", json=data)
    assert response.status_code == 200
    res_data = response.json()
    assert "인증번호가 유효합니다. 비밀번호를 재설정해야 합니다." in res_data.get(
        "message", ""
    )
    assert "reset_token" in res_data


def test_reset_password(monkeypatch):
    """
    POST /reset-password
    비밀번호 재설정: 유효한 reset_token과 일치하는 새 비밀번호 제공 시 성공
    """
    # fake verify_token: reset token 검증, action이 "password_reset"
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token, **kwargs: {"sub": "test@gmail.com", "action": "password_reset"},
    )
    monkeypatch.setattr(auth_module, "find_user_by_email", fake_find_user)
    monkeypatch.setattr(auth_module, "hash_password", lambda pwd: "hashed_new_password")

    # Fake DB 연결 (UPDATE 쿼리 기록용)
    fake_cursor = FakeCursor()
    fake_conn = FakeConnection(fake_cursor)
    monkeypatch.setattr(auth_module, "get_connection", lambda: fake_conn)

    data = {
        "reset_token": "dummy_reset_token",
        "new_password": "NewPass1!",
        "confirm_password": "NewPass1!",
    }
    response = client.post("auth/reset-password", json=data)
    assert response.status_code == 200
    res_data = response.json()
    assert "비밀번호가 성공적으로 재설정되었습니다." in res_data.get("message", "")
