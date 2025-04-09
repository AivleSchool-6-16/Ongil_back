# tests/routes/test_admin.py

import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from main import app  # main.py에서 FastAPI 인스턴스(app)를 import


# === Fake DB Connection, Cursor ===
class FakeCursor:
    def __init__(self, fetchone_data=None, fetchall_data=None):
        self._fetchone_data = fetchone_data
        self._fetchall_data = fetchall_data or []
        self.executed_queries = []

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))

    def fetchall(self):
        return self._fetchall_data

    def fetchone(self):
        return self._fetchone_data

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor_instance):
        self._cursor = cursor_instance

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


# === Override Dependencies ===


# (1) 인증 관련: 관리자 권한을 가진 사용자 반환
def fake_get_authenticated_user():
    return {"admin": True}  # 관리자 권한


app.dependency_overrides[
    # get_authenticated_user는 admin.py 내에서 from app.core.jwt_utils import get_authenticated_user 로 임포트됨
    # 해당 함수 객체에 대해 overrides를 적용합니다.
    __import__(
        "app.core.jwt_utils", fromlist=["get_authenticated_user"]
    ).get_authenticated_user
] = fake_get_authenticated_user


# (2) 이메일 전송: 실제 이메일 전송 기능을 사용하지 않고 Dummy 함수 사용
def fake_send_email(to_email, subject, body, attachment_path=None):
    # 필요 시 로그에 기록하거나 단순히 True를 반환합니다.
    return True


# monkeypatch로 email 전송 함수 오버라이드
# admin.py에서 send_email은 "from app.core.email_utils import send_email"로 임포트 되어 있음
# 따라서, "app.api.routes.admin.send_email" 경로로 오버라이드 할 수 있습니다.
@pytest.fixture(autouse=True)
def override_send_email(monkeypatch):
    monkeypatch.setattr("app.api.routes.admin.send_email", fake_send_email)


client = TestClient(app)


# === 테스트 케이스: 파일 요청 전체 조회 (GET /file-requests) ===
def test_get_file_requests(monkeypatch):
    # fake 데이터를 반환하는 커서 생성
    fake_data = [
        {
            "log_id": 1,
            "user_email": "test@example.com",
            "approve": None,
            "user_dept": "DeptA",
            "jurisdiction": "RegionA",
            "c_date": "2023-10-10T10:00:00",
        }
    ]
    fake_cursor = FakeCursor(fetchall_data=fake_data)
    fake_conn = FakeConnection(fake_cursor)

    def fake_get_connection():
        return fake_conn

    # admin.py 내의 get_connection을 오버라이드
    monkeypatch.setattr("app.api.routes.admin.get_connection", fake_get_connection)

    response = client.get("/file-requests")
    assert response.status_code == 200
    data = response.json()
    assert "file_requests" in data
    assert isinstance(data["file_requests"], list)
    # 반환받은 데이터의 내용 확인
    assert data["file_requests"][0]["log_id"] == 1
    assert data["file_requests"][0]["user_email"] == "test@example.com"


# === 테스트 케이스: 파일 승인 (POST /file-requests/approve/{log_id}) ===
def test_approve_file_request(monkeypatch):
    # fake 데이터: 승인 대상 요청 반환
    fake_request = {
        "user_email": "test@example.com",
        "recommended_roads": json.dumps(
            {
                "rds_rg": "Region1",
                "recommended_roads": [
                    {
                        "rds_id": "r1",
                        "road_name": "Road1",
                        "rbp": "data",
                        "rep": "data",
                        "rd_slope": "data",
                        "acc_occ": "data",
                        "acc_sc": "data",
                        "rd_fr": "data",
                        "pred_idx": "data",
                    }
                ],
            }
        ),
    }
    fake_cursor = FakeCursor(fetchone_data=fake_request)
    fake_conn = FakeConnection(fake_cursor)

    def fake_get_connection():
        return fake_conn

    monkeypatch.setattr("app.api.routes.admin.get_connection", fake_get_connection)

    # CSV 파일이 생성되고 삭제되는 부분이 있으므로, 임시 파일 경로를 사용해 실제 파일 조작이 일어나도 문제가 없도록 합니다.
    # 여기서는 실제 파일이 생성되는 것을 피하기 위해 os.remove도 monkeypatch로 처리합니다.
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.close()  # 파일 경로만 사용
    monkeypatch.setattr("os.remove", lambda path: None)

    response = client.post("/file-requests/approve/1")
    assert response.status_code == 200
    data = response.json()
    expected_message = (
        "파일이 test@example.com님에게 전송되었으며, 승인 처리되었습니다."
    )
    assert expected_message in data["message"]


# === 테스트 케이스: 파일 거부 (POST /file-requests/reject/{log_id}) ===
def test_reject_file_request(monkeypatch):
    fake_request = {"user_email": "test@example.com"}
    fake_cursor = FakeCursor(fetchone_data=fake_request)
    fake_conn = FakeConnection(fake_cursor)

    def fake_get_connection():
        return fake_conn

    monkeypatch.setattr("app.api.routes.admin.get_connection", fake_get_connection)

    response = client.post("/file-requests/reject/1")
    assert response.status_code == 200
    data = response.json()
    expected_message = (
        "파일 요청이 거부되었으며 test@example.com님에게 알림이 전송되었습니다."
    )
    assert expected_message in data["message"]
