# 문의 게시판
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi import File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import magic
import redis
import os
import subprocess
import uuid
from app.database.mysql_connect import get_connection
from app.core.jwt_utils import verify_token, get_authenticated_user
from app.api.socket import *

router = APIRouter()

UPLOAD_FOLDER = "app/database/uploads/"
# 파일 없을 경우
if not os.path.exists(UPLOAD_FOLDER):
  os.makedirs(UPLOAD_FOLDER)

try:
  redis_client = redis.StrictRedis(host="localhost", port=6379, db=0,
                                   decode_responses=True)
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
    file_path
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


# 게시글 등록 요청 모델
class PostCreateRequest(BaseModel):
  board_id: int  # 0: 비밀글, 1: 공개글
  post_title: str
  post_category: str
  post_text: str


# 게시글 수정 요청 모델
class PostUpdateRequest(BaseModel):
  post_title: Optional[str] = None
  post_category: Optional[str] = None
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
  """전체 조회 - 게시글 id, 비밀글 여부, 작성자, 제목, 카테고리, 작성시간, 조회수 """
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
def get_post(post_id: int, user: dict = Depends(get_authenticated_user),
    background_tasks: BackgroundTasks = None):
  """특정 게시글 상세 조회 - 들어올 때마다 조회수 증가 """
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
    if post["board_id"] == 0 and post["user_email"] != user[
      "sub"] and not user.get("admin"):
      raise HTTPException(status_code=403, detail="비밀글에 접근할 수 없습니다.")

    # Redis에서 조회수 증가
    redis_key = f"post_views:{post_id}"
    redis_client.incr(redis_key)

    # 실시간 조회수 반영
    redis_views = int(redis_client.get(redis_key)) if redis_client.get(
        redis_key) else 0
    post["views"] += redis_views  # MySQL 값 + Redis 값

    return {"post": post}
  finally:
    cursor.close()
    connection.close()


# ✅ 3. 게시글 작성
@router.post("/")
async def create_post(request: PostCreateRequest, user: dict = Depends(get_authenticated_user)):
    """게시글 작성 """
    try:
        connection = get_connection()
        cursor = connection.cursor()

        query = """
            INSERT INTO Posts (board_id, user_email, post_title, post_category, post_text, post_time, views)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
        cursor.execute(query, (
            request.board_id, user["sub"], request.post_title, request.post_category,
            request.post_text, datetime.now(), 0))
        connection.commit()

        # 생성된 게시글 가져오기
        cursor.execute("SELECT * FROM Posts WHERE post_id = LAST_INSERT_ID()")
        new_post = cursor.fetchone()

        # WebSocket을 통해 새 게시글 알림 (JSON 변환)
        post_data = {
            "post_id": new_post[0],
            "board_id": new_post[1],
            "user_email": new_post[2],
            "post_title": new_post[3],
            "post_category": new_post[4],
            "post_text": new_post[5],
            "post_time": new_post[6].isoformat(),
            "views": new_post[7]
        }
        await notify_new_post(post_data)  # WebSocket 이벤트 전송

        return {"message": "게시글이 등록되었습니다."}
    finally:
        cursor.close()
        connection.close()


# ✅ 4. 게시글 수정
@router.put("/{post_id}")
async def update_post(post_id: int, request: PostUpdateRequest, user: dict = Depends(get_authenticated_user)):
  """게시글 수정 - 본인 혹은 관리자만 """
  try:
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT user_email FROM Posts WHERE post_id = %s",
                   (post_id,))
    post = cursor.fetchone()

    if not post or (post[0] != user["sub"] and not user.get("admin")):
      raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    query = "UPDATE Posts SET post_title = %s, post_category = %s, post_text = %s WHERE post_id = %s"
    cursor.execute(query, (
      request.post_title, request.post_category, request.post_text, post_id))
    connection.commit()

    # 수정된 게시글 가져오기
    cursor.execute("SELECT * FROM Posts WHERE post_id = %s", (post_id,))
    updated_post = cursor.fetchone()

    # WebSocket을 통해 게시글 수정 알림
    await notify_updated_post(updated_post)

    return {"message": "게시글이 수정되었습니다."}
  finally:
    cursor.close()
    connection.close()


# ✅ 5. 게시글 삭제
@router.delete("/{post_id}")
def delete_post(post_id: int, user: dict = Depends(get_authenticated_user)):
  """게시글 삭제 - 본인 혹은 관리자만 """
  try:
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT user_email FROM Posts WHERE post_id = %s",
                   (post_id,))
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
def search_posts(text: Optional[str] = Query(None),author: Optional[str] = Query(None), user: dict = Depends(get_authenticated_user)):
  """게시글 검색 """
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
async def add_comment(post_id: int, request: CommentRequest, user: dict = Depends(get_authenticated_user)):
  """일반 댓글 작성 """
  try:
    connection = get_connection()
    cursor = connection.cursor()

    query = "INSERT INTO comments (post_id, user_email, comment, comment_date) VALUES (%s, %s, %s, NOW())"
    cursor.execute(query, (post_id, user["sub"], request.comment))
    connection.commit()

    # 생성된 댓글 가져오기
    cursor.execute(
        "SELECT * FROM comments WHERE post_id = %s ORDER BY comment_date DESC LIMIT 1",
        (post_id,))
    new_comment = cursor.fetchone()

    # WebSocket을 통해 댓글 추가 알림
    await notify_new_comment(new_comment)

    return {"message": "댓글이 등록되었습니다."}
  finally:
    cursor.close()
    connection.close()
    
# ✅ 7-1. 댓글 수정
@router.put("/{post_id}/comment/{comment_id}")
async def update_comment(post_id: int, comment_id: int, request: CommentRequest, user: dict = Depends(get_authenticated_user)):
    """ 댓글 수정 """
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 댓글 존재 확인
        cursor.execute("SELECT * FROM comments WHERE post_id = %s AND id = %s", (post_id, comment_id))
        existing_comment = cursor.fetchone()
        if not existing_comment:
            raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")

        # 댓글 작성자 확인 (자신의 댓글만 수정 가능)
        if existing_comment[2] != user["sub"]:  # `user_email` 필드가 2번째 인덱스라고 가정
            raise HTTPException(status_code=403, detail="본인만 댓글을 수정할 수 있습니다.")

        # 댓글 업데이트
        update_query = "UPDATE comments SET comment = %s WHERE id = %s"
        cursor.execute(update_query, (request.comment, comment_id))
        connection.commit()

        # 수정된 댓글 가져오기
        cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
        updated_comment = cursor.fetchone()

        # ✅ WebSocket을 통해 수정된 댓글 알림
        await notify_updated_comment(updated_comment)

        return {"message": "댓글이 수정되었습니다."}
    finally:
        cursor.close()
        connection.close()

# ✅ 7-2. 댓글 삭제
@router.delete("/{post_id}/comment/{comment_id}")
async def delete_comment(post_id: int, comment_id: int, user: dict = Depends(get_authenticated_user)):
    """ 댓글 삭제 """
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # 댓글 존재 확인
        cursor.execute("SELECT * FROM comments WHERE post_id = %s AND id = %s", (post_id, comment_id))
        existing_comment = cursor.fetchone()
        if not existing_comment:
            raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")

        # 댓글 작성자 확인 (본인만 삭제 가능)
        if existing_comment[2] != user["sub"]:  # `user_email` 필드가 2번째 인덱스라고 가정
            raise HTTPException(status_code=403, detail="본인만 댓글을 삭제할 수 있습니다.")

        # 댓글 삭제
        delete_query = "DELETE FROM comments WHERE id = %s"
        cursor.execute(delete_query, (comment_id,))
        connection.commit()

        # ✅ WebSocket을 통해 삭제된 댓글 알림
        await notify_deleted_comment({"post_id": post_id, "comment_id": comment_id})

        return {"message": "댓글이 삭제되었습니다."}
    finally:
        cursor.close()
        connection.close()

# ✅ 8. 관리자 답변 작성
@router.post("/{post_id}/answer")
def add_answer(post_id: int, request: AnswerRequest, user: dict = Depends(get_authenticated_user)):
  """관리자 답변 """
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
async def upload_file(
    post_id: int,
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_authenticated_user)):
  """파일 업로드"""
  if file is None:
    raise HTTPException(status_code=400, detail="파일이 제공되지 않았습니다.")

  connection = get_connection()
  cursor = None  # cursor를 None으로 초기화

  try:
    # 1️⃣ **파일 크기 검사 (10MB 제한)**
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read()  # 🔥 비동기적으로 파일 읽기
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
      raise HTTPException(status_code=400, detail="파일의 최대 크기는 10MB입니다.")

    # 2️⃣ **파일 확장자 검사 (허용된 확장자 목록)**
    ext = file.filename.rsplit('.', 1)[-1].lower()
    allowed_extensions = ["png", "jpg", "jpeg", "gif"]
    if ext not in allowed_extensions:
      raise HTTPException(status_code=400, detail="허용되지 않은 확장자입니다.")

    # 3️⃣ **MIME 타입 검사 (`python-magic` 활용)**
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    with open(file_path, "wb") as f:
      f.write(content)  # 🔥 content를 한 번만 사용 (파일 저장)

    mime = magic.Magic(mime=True)
    detected_mime = mime.from_file(file_path)
    print(f"Detected MIME Type: {detected_mime}")

    if not detected_mime.startswith("image/"):
      os.remove(file_path)  # 🔥 MIME 타입이 이미지가 아닐 경우 파일 삭제
      raise HTTPException(status_code=400, detail="허용되지 않은 파일 형식입니다.")

    # 4️⃣ **데이터베이스에 파일 정보 저장**
    cursor = connection.cursor()
    query = """
            INSERT INTO file_metadata (post_id, file_name, file_path, file_size, file_type, user_email, upload_time)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
    cursor.execute(query, (
    post_id, file.filename, file_path, file_size, detected_mime, user["sub"]))
    connection.commit()

    return {"message": "파일 업로드 성공", "file_name": file.filename}

  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

  finally:
    # 5️⃣ **커서 및 DB 연결 닫기**
    if cursor:
      cursor.close()
      connection.close()


# ✅ 게시글의 파일 목록 가져오기  
@router.get("/{post_id}/files")
def get_post_files(post_id: int):
  """파일 목록 - 확인용 api """
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
      raise HTTPException(status_code=404,
                          detail="No files found for this post.")

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
      raise HTTPException(status_code=404,
                          detail="File not found on the server.")

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
def delete_file(file_id: int, user: dict = Depends(get_authenticated_user)):
  """파일 삭제 - 게시글 작성 혹은 수정 중에만 연결 가능 """
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
      raise HTTPException(status_code=403,
                          detail="You do not have permission to delete this file.")

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