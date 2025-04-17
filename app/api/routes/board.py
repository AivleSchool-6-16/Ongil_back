# 문의 게시판
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from fastapi import File, Form, Body, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import magic
import redis
import os
import subprocess
from typing import List, Optional
from app.database.mysql_connect import get_connection
from app.core.jwt_utils import get_authenticated_user
from app.api.socket import *

router = APIRouter()

UPLOAD_FOLDER = "app/database/uploads/"
# 파일 없을 경우
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

try:
    redis_client = redis.StrictRedis(
        host="localhost", port=6379, db=0, decode_responses=True
    )
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None


def scan_file_with_clamav(file_path: str) -> bool:
    """
    ClamAV (clamscan)으로 파일을 검사하는 함수.
    return:
      - True : 바이러스 미검출(OK)
      - False: 바이러스 발견 또는 오류
    """
    cmd = [
        "clamscan",
        "--infected",
        "--no-summary",
        "--stdout",  # 결과를 stdout에 출력
        file_path,
    ]

    try:
        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode == 0:
            print(f"[ClamAV] No virus found in {file_path}")
            return True
        elif process.returncode == 1:
            print(f"[ClamAV] Virus found in {file_path} !!")
            print("Output:", process.stdout)
            return False
        else:
            print("[ClamAV] Error scanning file:", process.stderr)
            return False
    except FileNotFoundError:
        print("[ClamAV] clamscan command not found. Please install ClamAV.")
        return False


# 댓글 등록 요청 모델
class CommentRequest(BaseModel):
    comment: str


# 관리자 답변 요청 모델
class AnswerRequest(BaseModel):
    answer: str


# ✅ 1. 전체 게시글 조회 (조회수 실시간 반영)
@router.get("/")
def get_all_posts(user: dict = Depends(get_authenticated_user)):
    """전체 조회 - 게시글 ID, 비밀글 여부, 작성자(부서 & 관할), 제목, 카테고리, 작성시간, 조회수"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # `user_data` 조인하여 `user_dept`, `jurisdiction` 가져오기
        query = """
            SELECT p.post_id, p.board_id, p.user_email, u.user_dept, u.jurisdiction, 
                   p.post_title, p.post_category, p.post_time, p.views
            FROM Posts p
            JOIN user_data u ON p.user_email = u.user_email
        """
        cursor.execute(query)
        posts = cursor.fetchall()

        # Redis에서 조회수 가져와서 실시간 반영
        for post in posts:
            redis_key = f"post_views:{post['post_id']}"
            redis_views = redis_client.get(redis_key)
            post["views"] += int(redis_views) if redis_views else 0

        return {"posts": posts}

    finally:
        cursor.close()
        connection.close()


# ✅ 2. 특정 게시글 조회 (조회수 증가 & 실시간 반영)
@router.get("/{post_id}")
def get_post(
    post_id: int,
    user: dict = Depends(get_authenticated_user),
    background_tasks: BackgroundTasks = None,
):
    """특정 게시글 상세 조회 - 들어올 때마다 조회수 증가"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # `user_email`을 포함하여 게시글 작성자 정보 가져오기
        query = """
            SELECT p.post_id, p.board_id, p.user_email, u.user_name, u.user_dept, u.jurisdiction, 
                   p.post_title, p.post_category, p.post_text, p.post_time, p.views
            FROM Posts p
            JOIN user_data u ON p.user_email = u.user_email
            WHERE p.post_id = %s
        """
        cursor.execute(query, (post_id,))
        post = cursor.fetchone()

        if not post:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")

        # 비밀글 접근 제한 검사
        is_owner = user["sub"] == post["user_email"]
        is_admin = user.get("admin", False)

        if post["board_id"] == 0 and not is_owner and not is_admin:
            raise HTTPException(status_code=403, detail="비밀글에 접근할 수 없습니다.")

        # Redis에서 조회수 증가
        redis_key = f"post_views:{post_id}"
        redis_client.incr(redis_key)

        # 실시간 조회수 반영 (MySQL 값 + Redis 값)
        redis_views = (
            int(redis_client.get(redis_key)) if redis_client.get(redis_key) else 0
        )
        post["views"] += redis_views

        return {"post": post}

    finally:
        cursor.close()
        connection.close()


# ✅ 3. 게시글 작성
@router.post("/")
async def create_post_with_file(
    board_id: int = Form(...),
    post_title: str = Form(...),
    post_category: str = Form(...),
    post_text: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),
    user: dict = Depends(get_authenticated_user),
):
    """게시글 작성 + 파일 업로드"""
    connection = get_connection()
    cursor = None

    try:
        cursor = connection.cursor()

        # 1. 게시글을 먼저 DB에 저장
        query = """
            INSERT INTO Posts (board_id, user_email, post_title, post_category, post_text, post_time, views)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (
                board_id,
                user["sub"],
                post_title,
                post_category,
                post_text,
                datetime.now(),
                0,
            ),
        )
        connection.commit()

        # 2. 방금 저장한 `post_id` 가져오기
        cursor.execute("SELECT LAST_INSERT_ID()")
        post_id = cursor.fetchone()[0]

        # 3. 파일이 있을 경우 처리
        uploaded_files_data = []
        if files:
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
            allowed_extensions = ["png", "jpg", "jpeg", "gif"]

            for file in files:
                content = await file.read()
                file_size = len(content)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400, detail=f"업로드 파일의 최대 크기는 10MB입니다."
                    )

                if "." not in file.filename:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}에 확장자가 없습니다.",
                    )
                ext = file.filename.rsplit(".", 1)[-1].lower()
                if ext not in allowed_extensions:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}: 허용되지 않은 확장자입니다.",
                    )

                file_path = os.path.join(UPLOAD_FOLDER, file.filename)
                with open(file_path, "wb") as f:
                    f.write(content)

                mime = magic.Magic(mime=True)
                detected_mime = mime.from_file(file_path)
                if not detected_mime.startswith("image/"):
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}: 허용되지 않은 파일 형식입니다.",
                    )

                file_query = """
                    INSERT INTO file_metadata (post_id, file_name, file_path, file_size, file_type, user_email, upload_time)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """
                cursor.execute(
                    file_query,
                    (
                        post_id,
                        file.filename,
                        file_path,
                        file_size,
                        detected_mime,
                        user["sub"],
                    ),
                )
                connection.commit()

                uploaded_files_data.append(
                    {
                        "file_name": file.filename,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_type": detected_mime,
                    }
                )

        # 4. 생성된 게시글 데이터 가져오기
        cursor.execute("SELECT * FROM Posts WHERE post_id = %s", (post_id,))
        new_post = cursor.fetchone()

        # 5. WebSocket을 통해 새 게시글 알림 (파일 정보 포함)
        post_data = {
            "post_id": new_post[0],
            "board_id": new_post[1],
            "user_email": new_post[2],
            "post_title": new_post[3],
            "post_category": new_post[4],
            "post_text": new_post[5],
            "post_time": new_post[6].isoformat(),
            "views": new_post[7],
            "files": uploaded_files_data,
        }
        await notify_new_post(post_data)

        return {
            "message": "게시글이 등록되었습니다.",
            "post_id": post_id,
            "files": uploaded_files_data,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if cursor:
            cursor.close()
            connection.close()


# ✅ 4. 게시글 수정 권한 확인
@router.get("/{post_id}/edit")
async def get_post_for_edit(post_id: int, user: dict = Depends(get_authenticated_user)):
    """게시글 수정 페이지 접근 - 권한 확인 및 기존 데이터 반환"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 1. 게시글 가져오기 (작성자만 접근 가능)
        cursor.execute("SELECT * FROM Posts WHERE post_id = %s", (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")

        if post["user_email"] != user["sub"]:
            raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

        # 2. 첨부 파일 목록 가져오기
        cursor.execute(
            "SELECT file_id, file_name, file_path FROM file_metadata WHERE post_id = %s",
            (post_id,),
        )
        files = cursor.fetchall()

        return {"post": post, "files": files}
    finally:
        cursor.close()
        connection.close()


# ✅ 4-1. 게시글 수정
@router.put("/{post_id}")
async def update_post(
    post_id: int,
    board_id: int = Form(...),
    post_title: str = Form(...),
    post_category: str = Form(...),
    post_text: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),  # 업데이트할 파일 리스트
    user: dict = Depends(get_authenticated_user),
):
    """게시글 수정 + 기존 파일 삭제 후 새 파일 저장"""
    connection = get_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # 1️. 게시글 내용 수정
        update_query = """
            UPDATE Posts
            SET board_id = %s, post_title = %s, post_category = %s, post_text = %s, post_time = %s
            WHERE post_id = %s
        """
        cursor.execute(
            update_query,
            (board_id, post_title, post_category, post_text, datetime.now(), post_id),
        )
        connection.commit()

        # 2️. 기존 파일 삭제 (post_id에 속한 모든 파일 삭제)
        cursor.execute(
            "SELECT file_id, file_path FROM file_metadata WHERE post_id = %s",
            (post_id,),
        )
        existing_files = cursor.fetchall()

        for file in existing_files:
            # 실제 파일 삭제
            if os.path.exists(file["file_path"]):
                os.remove(file["file_path"])

            # DB에서 파일 메타데이터 삭제
            cursor.execute(
                "DELETE FROM file_metadata WHERE file_id = %s", (file["file_id"],)
            )
            connection.commit()

        # 3. 파일 추가 (새 파일 업로드)
        uploaded_files_data = []
        if files:
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
            allowed_extensions = ["png", "jpg", "jpeg", "gif"]

            for file in files:
                content = await file.read()
                file_size = len(content)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}의 최대 크기는 10MB입니다.",
                    )

                if "." not in file.filename:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}에 확장자가 없습니다.",
                    )
                ext = file.filename.rsplit(".", 1)[-1].lower()
                if ext not in allowed_extensions:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}: 허용되지 않은 확장자입니다.",
                    )

                file_path = os.path.join(UPLOAD_FOLDER, file.filename)
                with open(file_path, "wb") as f:
                    f.write(content)

                mime = magic.Magic(mime=True)
                detected_mime = mime.from_file(file_path)
                if not detected_mime.startswith("image/"):
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 {file.filename}: 허용되지 않은 파일 형식입니다.",
                    )

                # DB에 새 파일 정보 저장
                file_query = """
                    INSERT INTO file_metadata (post_id, file_name, file_path, file_size, file_type, user_email, upload_time)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """
                cursor.execute(
                    file_query,
                    (
                        post_id,
                        file.filename,
                        file_path,
                        file_size,
                        detected_mime,
                        user["sub"],
                    ),
                )
                connection.commit()

                uploaded_files_data.append(
                    {
                        "file_name": file.filename,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_type": detected_mime,
                    }
                )

        # 4. 수정된 게시글 데이터 조회
        cursor.execute("SELECT * FROM Posts WHERE post_id = %s", (post_id,))
        updated_post = cursor.fetchone()

        # datetime 변환 (post_time)
        if updated_post and "post_time" in updated_post:
            updated_post["post_time"] = updated_post["post_time"].isoformat()

        # 5️. 수정된 파일 목록 가져오기
        cursor.execute(
            """
            SELECT file_id, file_name, file_path, file_size, file_type, upload_time
            FROM file_metadata WHERE post_id = %s
        """,
            (post_id,),
        )
        updated_files = cursor.fetchall()

        # 파일의 datetime 변환 (upload_time)
        for file in updated_files:
            if "upload_time" in file:
                file["upload_time"] = file["upload_time"].isoformat()

        # WebSocket을 통해 수정된 게시글 정보 전송
        post_data = {
            "post_id": updated_post["post_id"],
            "board_id": updated_post["board_id"],
            "user_email": updated_post["user_email"],
            "post_title": updated_post["post_title"],
            "post_category": updated_post["post_category"],
            "post_text": updated_post["post_text"],
            "post_time": updated_post["post_time"],
            "views": updated_post["views"],
            "files": updated_files,
        }
        await notify_updated_post(post_data)

        # 최종 응답 반환
        return {
            "message": "게시글이 수정되었습니다.",
            "post": updated_post,
            "files": updated_files,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if cursor:
            cursor.close()
            connection.close()


# ✅ 5. 게시글 삭제
@router.delete("/{post_id}")
def delete_post(post_id: int, user: dict = Depends(get_authenticated_user)):
    """게시글 삭제"""
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 삭제할 게시글의 소유자 확인
        cursor.execute("SELECT user_email FROM Posts WHERE post_id = %s", (post_id,))
        post = cursor.fetchone()

        if not post or (post[0] != user["sub"] and not user.get("admin")):
            raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")

        # 1. 관련 댓글 삭제
        cursor.execute("DELETE FROM comments WHERE post_id = %s", (post_id,))

        # 2. 관련 답변 삭제
        cursor.execute("DELETE FROM answer WHERE post_id = %s", (post_id,))

        # 3. 게시글 삭제
        cursor.execute("DELETE FROM Posts WHERE post_id = %s", (post_id,))
        connection.commit()

        return {"message": "게시글이 삭제되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 6. 게시글 검색
@router.get("/search/")
def search_posts(
    title: Optional[str] = Query(None),
    text: Optional[str] = Query(None),
    user: dict = Depends(get_authenticated_user),
):
    """게시글 검색 - 타이틀 혹은 내용"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # `user_data` 조인하여 `user_dept`, `jurisdiction` 가져오기
        query = """
            SELECT p.post_id, p.board_id, p.user_email, u.user_dept, u.jurisdiction, 
                   p.post_title, p.post_category, p.post_time, p.views
            FROM Posts p
            JOIN user_data u ON p.user_email = u.user_email
            WHERE 1=1
        """
        params = []

        if title:
            query += " AND p.post_title LIKE %s"
            params.append(f"%{title}%")

        if text:
            query += " AND p.post_text LIKE %s"
            params.append(f"%{text}%")

        cursor.execute(query, tuple(params))
        results = cursor.fetchall()

        # Redis에서 실시간 조회수 가져오기
        for post in results:
            redis_key = f"post_views:{post['post_id']}"
            redis_views = redis_client.get(redis_key)
            post["views"] += int(redis_views) if redis_views else 0

        return {"results": results}

    finally:
        cursor.close()
        connection.close()


# ✅ 7. 댓글 작성
@router.post("/{post_id}/comment")
async def add_comment(
    post_id: int, request: CommentRequest, user: dict = Depends(get_authenticated_user)
):
    """일반 댓글 작성"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 댓글 삽입
        query = "INSERT INTO comments (post_id, user_email, comment, comment_date) VALUES (%s, %s, %s, NOW())"
        cursor.execute(query, (post_id, user["sub"], request.comment))
        connection.commit()

        # 생성된 댓글 가져오기 - socket
        cursor.execute(
            "SELECT * FROM comments WHERE post_id = %s ORDER BY comment_date DESC LIMIT 1",
            (post_id,),
        )
        new_comment = cursor.fetchone()

        # datetime 변환 (comment_date)
        if new_comment and "comment_date" in new_comment:
            new_comment["comment_date"] = new_comment["comment_date"].isoformat()
        await notify_new_comment(new_comment)

        return {"message": "댓글이 등록되었습니다.", "comment": new_comment}
    finally:
        cursor.close()
        connection.close()


# ✅ 7-1. 댓글 삭제
@router.delete("/{post_id}/comment/{comment_id}")
async def delete_comment(
    post_id: int, comment_id: int, user: dict = Depends(get_authenticated_user)
):
    """댓글 삭제"""
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 댓글 존재 확인
        cursor.execute(
            "SELECT * FROM comments WHERE post_id = %s AND comment_id = %s",
            (post_id, comment_id),
        )
        existing_comment = cursor.fetchone()
        if not existing_comment:
            raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")

        # 댓글 작성자 확인 (본인만 삭제 가능)
        if existing_comment[2] != user["sub"] and not user.get(
            "admin"
        ):  # `user_email` 필드가 2번째 인덱스라고 가정
            raise HTTPException(
                status_code=403, detail="본인 혹은 관리자만 댓글을 삭제할 수 있습니다."
            )

        # 댓글 삭제
        delete_query = "DELETE FROM comments WHERE comment_id = %s"
        cursor.execute(delete_query, (comment_id,))
        connection.commit()

        # WebSocket을 통해 삭제된 댓글 알림
        await notify_deleted_comment({"post_id": post_id, "comment_id": comment_id})

        return {"message": "댓글이 삭제되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 8. 관리자 답변 작성
@router.post("/{post_id}/answer")
async def add_answer(
    post_id: int, request: AnswerRequest, user: dict = Depends(get_authenticated_user)
):
    """관리자 답변"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 답변 삽입
        query = "INSERT INTO answer (post_id, user_email, ans_text, ans_date) VALUES (%s, %s, %s, NOW())"
        cursor.execute(query, (post_id, user["sub"], request.answer))
        connection.commit()

        # 생성된 답변 가져오기 -socket
        cursor.execute(
            "SELECT * FROM answer WHERE post_id = %s ORDER BY ans_date DESC LIMIT 1",
            (post_id,),
        )
        new_answer = cursor.fetchone()

        # datetime 변환 (ans_date)
        if new_answer and "ans_date" in new_answer:
            new_answer["ans_date"] = new_answer["ans_date"].isoformat()
        await notify_new_answer(new_answer)

        return {"message": "관리자 답변이 등록되었습니다.", "answer": new_answer}
    finally:
        cursor.close()
        connection.close()


# ✅ 8-1. 관리자 답변 삭제
@router.delete("/{post_id}/answer/{answer_id}")
async def delete_answer(
    post_id: int, answer_id: int, user: dict = Depends(get_authenticated_user)
):
    """관리자 답변 삭제 - 다른 관리자의 답변도 삭제 가능"""
    if not user.get("admin"):  # 관리자 여부 확인
        raise HTTPException(
            status_code=403, detail="관리자만 답변을 삭제할 수 있습니다."
        )

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 답변 존재 여부 확인
        cursor.execute(
            "SELECT * FROM answer WHERE post_id = %s AND ans_id = %s",
            (post_id, answer_id),
        )
        existing_answer = cursor.fetchone()
        if not existing_answer:
            raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")

        # 답변 삭제
        delete_query = "DELETE FROM answer WHERE ans_id = %s"
        cursor.execute(delete_query, (answer_id,))
        connection.commit()

        # WebSocket을 통해 삭제된 답변 알림
        await notify_deleted_answer({"post_id": post_id, "answer_id": answer_id})

        return {"message": "답변이 삭제되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 9. 댓글&답변 가져오기
@router.get("/{post_id}/comments-answers")
async def get_comments_and_answers(post_id: int):
    """게시글의 댓글 및 관리자 답변 조회"""
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 해당 게시글의 댓글 가져오기
        cursor.execute(
            """
            SELECT c.comment_id, u.user_email, u.user_name, u.user_dept, u.jurisdiction, c.comment, c.comment_date
            FROM comments c
            JOIN user_data u ON c.user_email = u.user_email
            WHERE c.post_id = %s
            ORDER BY c.comment_date ASC
        """,
            (post_id,),
        )
        comments = cursor.fetchall()

        # 해당 게시글의 관리자 답변 가져오기
        cursor.execute(
            """
            SELECT ans_id, ans_text, ans_date
            FROM answer
            WHERE post_id = %s
            ORDER BY ans_date ASC
        """,
            (post_id,),
        )
        answers = cursor.fetchall()

        # JSON 형식으로 변환
        comments_list = [
            {
                "comment_id": c[0],
                "user_email": c[1],
                "user_name": c[2],  # 사용자 이름
                "user_dept": c[3],  # 부서 정보
                "jurisdiction": c[4],  # 관할권 정보
                "comment": c[5],
                "comment_date": c[6].isoformat(),
            }
            for c in comments
        ]
        answers_list = [
            {"answer_id": a[0], "answer_text": a[1], "answer_date": a[2].isoformat()}
            for a in answers
        ]
        return {
            "post_id": post_id,
            "comments": comments_list,
            "admin_answers": answers_list,
        }

    finally:
        cursor.close()
        connection.close()


# ✅ 게시글의 파일 목록 가져오기
@router.get("/{post_id}/files")
def get_post_files(post_id: int):
    """파일 목록 - 게시물 조회, 게시글 수정에 연결"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
        SELECT file_id, file_name, file_path, file_size, file_type, upload_time, user_email
        FROM file_metadata WHERE post_id = %s
        """
        cursor.execute(query, (post_id,))
        files = cursor.fetchall()

        # 파일 없으면 db 메타 데이터 정리
        valid_files = []
        for file in files:
            if os.path.exists(file["file_path"]):
                valid_files.append(file)
            else:
                delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
                cursor.execute(delete_query, (file["file_id"],))
                connection.commit()

        if not valid_files:
            raise HTTPException(
                status_code=404, detail="이 게시글에는 업로드된 파일이 없습니다."
            )

        return {"files": valid_files}
    finally:
        cursor.close()
        connection.close()


# ✅ 파일 다운로드
@router.get("/files/{file_id}/download")
def download_file(file_id: int):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = "SELECT file_path, file_name FROM file_metadata WHERE file_id = %s"
        cursor.execute(query, (file_id,))
        file = cursor.fetchone()

        if not file:
            raise HTTPException(status_code=404, detail="파일 업로드 기록이 없습니다.")

        # 파일 존재 여부
        if not os.path.exists(file["file_path"]):
            # 파일 메타 데이터가 없을 때, 실제 파일 삭제
            delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
            cursor.execute(delete_query, (file_id,))
            connection.commit()
            raise HTTPException(status_code=404, detail="파일이 존재하지 않습니다.")

        return FileResponse(
            file["file_path"],
            filename=file["file_name"],
            media_type="application/octet-stream",
        )
    finally:
        cursor.close()
        connection.close()


# ✅ 파일 삭제
@router.delete("/files/{file_id}")
def delete_file(file_id: int, user: dict = Depends(get_authenticated_user)):
    """파일 삭제 - 게시글 작성 혹은 수정 중에만 연결 가능"""
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 파일 확인
        query = "SELECT file_path, user_email FROM file_metadata WHERE file_id = %s"
        cursor.execute(query, (file_id,))
        file = cursor.fetchone()

        if not file:
            raise HTTPException(status_code=404, detail="File not found.")

        # 파일 권한 확인
        if file["user_email"] != user["sub"] and not user.get("admin"):
            raise HTTPException(status_code=403, detail="파일 삭제 권한이 없습니다.")

        # 실제 파일 삭제
        if os.path.exists(file["file_path"]):
            os.remove(file["file_path"])

        # db에서 메타 데이터 삭제
        delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
        cursor.execute(delete_query, (file_id,))
        connection.commit()

        return {"message": "File deleted successfully."}
    finally:
        cursor.close()
        connection.close()
