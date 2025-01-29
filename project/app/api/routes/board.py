# 문의 게시판
from fastapi import APIRouter, HTTPException, Depends, Header, Query, BackgroundTasks
from fastapi import File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import redis
import os
from app.db.mysql_connect import get_connection
from app.utils.jwt_utils import verify_token, get_authenticated_user

router = APIRouter()

UPLOAD_FOLDER = "app/db/uploads/"
# 파일 없을 경우
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0, decode_responses=True)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None


# 게시글 등록 요청 모델
class PostCreateRequest(BaseModel):
    board_id: int  # 0: 비밀글, 1: 공개글
    post_title: str
    post_category: int
    post_text: str

# 게시글 수정 요청 모델
class PostUpdateRequest(BaseModel):
    post_title: Optional[str] = None
    post_category: Optional[int] = None
    post_text: Optional[str] = None

# 댓글 등록 요청 모델
class CommentRequest(BaseModel):
    comment: str

# 관리자 답변 요청 모델
class AnswerRequest(BaseModel):
    answer: str

# ✅ 1. 전체 게시글 조회 (조회수 실시간 반영)
@router.get("/")
def get_all_posts(user: dict = Depends(get_authenticated_user)):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        query = "SELECT post_id, board_id, user_email, post_title, post_category, post_time, views FROM Posts"
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
def get_post(post_id: int, user: dict = Depends(get_authenticated_user), background_tasks: BackgroundTasks = None):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # 게시글 조회
        query = "SELECT * FROM Posts WHERE post_id = %s"
        cursor.execute(query, (post_id,))
        post = cursor.fetchone()

        if not post:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")

        # 비밀글 접근 제한
        if post["board_id"] == 0 and post["user_email"] != user["sub"] and not user.get("admin"):
            raise HTTPException(status_code=403, detail="비밀글에 접근할 수 없습니다.")

        # Redis에서 조회수 증가
        redis_key = f"post_views:{post_id}"
        redis_client.incr(redis_key)

        # 실시간 조회수 반영
        redis_views = int(redis_client.get(redis_key)) if redis_client.get(redis_key) else 0
        post["views"] += redis_views # MySQL 값 + Redis 값

        return {"post": post}
    finally:
        cursor.close()
        connection.close()

# ✅ 3. 게시글 작성
@router.post("/")
def create_post(request: PostCreateRequest, user: dict = Depends(get_authenticated_user)):
    connection = None 
    cursor = None      

    try:
        connection = get_connection()
        cursor = connection.cursor()

        query = """
        INSERT INTO Posts (board_id, user_email, post_title, post_category, post_text, post_time, views)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (request.board_id, user["sub"], request.post_title, request.post_category, request.post_text, datetime.now(), 0))
        connection.commit()

        return {"message": "게시글이 등록되었습니다."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    finally:
        if cursor is not None:  # cursor가 None이 아닐 때만 닫기
            cursor.close()
        if connection is not None:  # connection도 None 체크 후 닫기
            connection.close()

# ✅ 4. 게시글 수정
@router.put("/{post_id}")
def update_post(post_id: int, request: PostUpdateRequest, user: dict = Depends(get_authenticated_user)):
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT user_email FROM Posts WHERE post_id = %s", (post_id,))
        post = cursor.fetchone()

        if not post or (post[0] != user["sub"] and not user.get("admin")):
            raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

        query = "UPDATE Posts SET post_title = %s, post_category = %s, post_text = %s WHERE post_id = %s"
        cursor.execute(query, (request.post_title, request.post_category, request.post_text, post_id))
        connection.commit()

        return {"message": "게시글이 수정되었습니다."}
    finally:
        cursor.close()
        connection.close()

# ✅ 5. 게시글 삭제
@router.delete("/{post_id}")
def delete_post(post_id: int, user: dict = Depends(get_authenticated_user)):
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT user_email FROM Posts WHERE post_id = %s", (post_id,))
        post = cursor.fetchone()

        if not post or (post[0] != user["sub"] and not user.get("admin")):
            raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")

        cursor.execute("DELETE FROM Posts WHERE post_id = %s", (post_id,))
        connection.commit()

        return {"message": "게시글이 삭제되었습니다."}
    finally:
        cursor.close()
        connection.close()

# ✅ 6. 게시글 검색
@router.get("/search/")
def search_posts(
    text: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    user: dict = Depends(get_authenticated_user)
):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = "SELECT post_id, board_id, user_email, post_title, post_category, post_time, views FROM Posts WHERE 1=1"
        params = []
        if text:
            query += " AND (post_title LIKE %s OR post_text LIKE %s)"
            params.append(f"%{text}%")
            params.append(f"%{text}%")
        if author:
            query += " AND user_email LIKE %s"
            params.append(f"%{author}%")

        cursor.execute(query, tuple(params))
        results = cursor.fetchall()

        # Redis에서 실시간 조회수 반영
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
def add_comment(post_id: int, request: CommentRequest, user: dict = Depends(get_authenticated_user)):
    try:
        connection = get_connection()
        cursor = connection.cursor()

        query = "INSERT INTO comments (post_id, user_email, comment, comment_date) VALUES (%s, %s, %s, NOW())"
        cursor.execute(query, (post_id, user["sub"], request.comment))
        connection.commit()

        return {"message": "댓글이 등록되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 8. 관리자 답변 작성
@router.post("/{post_id}/answer")
def add_answer(post_id: int, request: AnswerRequest, user: dict = Depends(get_authenticated_user)):
    if not user.get("admin"):
        raise HTTPException(status_code=403, detail="관리자만 답변을 작성할 수 있습니다.")

    try:
        connection = get_connection()
        cursor = connection.cursor()

        query = "INSERT INTO answer (post_id, user_email, ans_text, ans_date) VALUES (%s, %s, %s, NOW())"
        cursor.execute(query, (post_id, user["sub"], request.answer))
        connection.commit()

        return {"message": "관리자 답변이 등록되었습니다."}
    finally:
        cursor.close()
        connection.close()
        
# ✅ 파일 업로드 - 게시글 작성 혹은 수정 중에만
@router.post("/{post_id}/upload")
def upload_file(post_id: int, file: UploadFile = File(...), user: dict = Depends(verify_token)):
    try:
        # Validate file size (Example: Max 10MB)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        file_size = file.file.seek(0, 2)  # Get file size
        file.file.seek(0)  # Reset file pointer
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 10MB limit.")

        # Construct file path
        file_location = os.path.join(UPLOAD_FOLDER, file.filename)

        # Save file to disk
        with open(file_location, "wb") as f:
            f.write(file.file.read())

        # Save file metadata to DB
        connection = get_connection()
        cursor = connection.cursor()

        query = """
        INSERT INTO file_metadata (post_id, file_name, file_path, file_size, file_type, user_email, upload_time)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(query, (post_id, file.filename, file_location, file_size, file.content_type, user["sub"]))
        connection.commit()

        return {"message": "File uploaded successfully", "file_name": file.filename}
    finally:
        cursor.close()
        connection.close()


# ✅ 게시글의 파일 목록 가져오기  
@router.get("/{post_id}/files")
def get_post_files(post_id: int):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
        SELECT file_id, file_name, file_path, file_size, file_type, upload_time, user_email
        FROM file_metadata WHERE post_id = %s
        """
        cursor.execute(query, (post_id,))
        files = cursor.fetchall()

        # Check if files exist, delete from DB if missing
        valid_files = []
        for file in files:
            if os.path.exists(file["file_path"]):
                valid_files.append(file)
            else:
                # Remove missing file entry from DB
                delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
                cursor.execute(delete_query, (file["file_id"],))
                connection.commit()

        if not valid_files:
            raise HTTPException(status_code=404, detail="No files found for this post.")

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
            raise HTTPException(status_code=404, detail="File metadata not found.")

        # Check if file exists
        if not os.path.exists(file["file_path"]):
            # Delete the file entry from the database if missing
            delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
            cursor.execute(delete_query, (file_id,))
            connection.commit()
            raise HTTPException(status_code=404, detail="File not found on the server.")

        return FileResponse(
            file["file_path"],
            filename=file["file_name"],
            media_type="application/octet-stream"
        )
    finally:
        cursor.close()
        connection.close()


# ✅ 파일 삭제 - 게시글 작성 혹은 수정 중에만   
@router.delete("/files/{file_id}")
def delete_file(file_id: int, user: dict = Depends(verify_token)):
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Retrieve file details
        query = "SELECT file_path, user_email FROM file_metadata WHERE file_id = %s"
        cursor.execute(query, (file_id,))
        file = cursor.fetchone()

        if not file:
            raise HTTPException(status_code=404, detail="File not found.")

        # Check if user is authorized to delete
        if file["user_email"] != user["sub"] and not user.get("admin"):
            raise HTTPException(status_code=403, detail="You do not have permission to delete this file.")

        # Delete the actual file from the disk
        if os.path.exists(file["file_path"]):
            os.remove(file["file_path"])

        # Remove file metadata from the database
        delete_query = "DELETE FROM file_metadata WHERE file_id = %s"
        cursor.execute(delete_query, (file_id,))
        connection.commit()

        return {"message": "File deleted successfully."}
    finally:
        cursor.close()
        connection.close()