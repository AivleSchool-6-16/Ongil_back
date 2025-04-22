# tests/routes/test_board.py

import json
import os
import tempfile
from datetime import datetime
from io import BytesIO
import pytest
from fastapi.testclient import TestClient

from main import app
from app.api.routes.board import get_authenticated_user as board_get_user


# --- Fake DB Connection 및 Cursor ---
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

    def cursor(self, dictionary=False):
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

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, time_delta, value):
        self.store[key] = value

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)

    def delete(self, key):
        if key in self.store:
            del self.store[key]


# Fake Notify Functions (WebSocket 알림 대신 아무것도 하지 않음)
async def fake_notify_new_post(post_data):
    return


async def fake_notify_new_comment(comment):
    return


# --- Fake 함수들 ---
def fake_get_connection():
    # 필요에 따라 FakeCursor의 반환 데이터를 다르게 설정할 수 있습니다.
    fake_data = [
        {
            "post_id": 1,
            "board_id": 1,
            "user_email": "user@example.com",
            "user_dept": "DeptA",
            "jurisdiction": "RegionX",
            "post_title": "Test Post",
            "post_category": "General",
            "post_time": datetime(2023, 10, 10, 10, 0, 0),
            "views": 100,
        }
    ]
    fake_cursor = FakeCursor(fetchall_data=fake_data)
    return FakeConnection(fake_cursor)


# --- Monkeypatch 대상: get_connection, redis_client, notify_new_post ---
import app.api.routes.board as board_module


# Fake user 함수
def fake_user():
    return {"sub": "user@example.com", "admin": True}


# 테스트 시작 전에
app.dependency_overrides[board_get_user] = fake_user

# Fake redis instance
fake_redis = FakeRedis()
board_module.redis_client = fake_redis
# Fake notification function
board_module.notify_new_post = fake_notify_new_post

# TestClient 생성 (단, board 엔드포인트는 /board 로 마운트되었다고 가정)
client = TestClient(app)


# --- 테스트 케이스 ---
def test_get_all_posts(monkeypatch):
    """
    GET /board/ - 전체 게시글 조회
    """
    # get_connection 오버라이드
    monkeypatch.setattr(board_module, "get_connection", fake_get_connection)

    # Fake Redis: 게시글의 조회수 추가 (예: post_views:1 => "10")
    fake_redis.store["post_views:1"] = "10"

    response = client.get("/board/")
    assert response.status_code == 200
    data = response.json()
    assert "posts" in data
    assert isinstance(data["posts"], list)
    # 기본 게시글 데이터: views 값 100 + Redis 조회수 10 = 110
    post = data["posts"][0]
    assert post["post_id"] == 1
    assert post["user_email"] == "user@example.com"
    assert post["views"] == 110


def test_get_post(monkeypatch):
    """
    GET /board/{post_id} - 특정 게시글 조회 및 조회수 증가
    """
    # Fake post 데이터
    fake_post = {
        "post_id": 1,
        "board_id": 1,
        "user_email": "user@example.com",
        "user_name": "User One",
        "user_dept": "DeptA",
        "jurisdiction": "RegionX",
        "post_title": "Test Post",
        "post_category": "General",
        "post_text": "This is a test post.",
        "post_time": datetime(2023, 10, 10, 10, 0, 0),
        "views": 100,
    }
    fake_cursor = FakeCursor(fetchone_data=fake_post)
    monkeypatch.setattr(
        board_module, "get_connection", lambda: FakeConnection(fake_cursor)
    )
    # Fake Redis: 게시글 조회수 초기값
    fake_redis.store["post_views:1"] = "5"  # 인크리먼트 후 조회수 추가

    # 로그인 인증은 Depends(get_authenticated_user); 테스트용으로 패스
    monkeypatch.setattr(
        board_module, "get_authenticated_user", lambda: {"sub": "user@example.com"}
    )

    response = client.get("/board/1")
    assert response.status_code == 200
    data = response.json()
    post = data["post"]
    # 조회수: 기존 100 + Redis (5 incremented to at least 6 after incr)
    assert post["post_id"] == 1
    assert "user@example.com" in post["user_email"]


def test_search_posts(monkeypatch):
    """
    GET /board/search/ - 게시글 검색 (타이틀, 텍스트)
    """
    fake_results = [
        {
            "post_id": 2,
            "board_id": 1,
            "user_email": "search@example.com",
            "user_dept": "DeptB",
            "jurisdiction": "RegionY",
            "post_title": "Searchable Title",
            "post_category": "Info",
            "post_time": datetime(2023, 10, 11, 12, 0, 0),
            "views": 50,
        }
    ]
    fake_cursor = FakeCursor(fetchall_data=fake_results)
    monkeypatch.setattr(
        board_module, "get_connection", lambda: FakeConnection(fake_cursor)
    )
    # Fake Redis: 검색 결과, no extra views
    fake_redis.store["post_views:2"] = "0"

    response = client.get("/board/search/?title=Searchable")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    results = data["results"]
    assert isinstance(results, list)
    assert len(results) >= 1
    assert "Searchable" in results[0]["post_title"]


def test_add_comment(monkeypatch):
    """
    POST /board/{post_id}/comment - 댓글 등록
    """
    # Fake DB 연결: 댓글 삽입 후, 마지막 댓글 조회
    fake_comment = {
        "comment_id": 1,
        "post_id": 1,
        "user_email": "user@example.com",
        "comment": "This is a test comment.",
        "comment_date": datetime(2023, 10, 10, 11, 0, 0),
    }
    fake_cursor = FakeCursor(fetchone_data=fake_comment)
    monkeypatch.setattr(
        board_module, "get_connection", lambda: FakeConnection(fake_cursor)
    )
    # Fake notification for new comment
    monkeypatch.setattr(board_module, "notify_new_comment", fake_notify_new_post)
    # 인증: 간단히 통과
    monkeypatch.setattr(
        board_module, "get_authenticated_user", lambda: {"sub": "user@example.com"}
    )

    payload = {"comment": "This is a test comment."}
    response = client.post("/board/1/comment", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "댓글이 등록되었습니다." in data.get("message", "")
    assert data.get("comment", {}).get("comment_id") == 1


# 필요하다면 update_post, delete_post, add_answer, delete_answer, 파일 다운로드 등 추가 테스트 케이스를 작성합니다.
