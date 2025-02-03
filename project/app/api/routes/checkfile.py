import os
import uuid
import subprocess

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import magic  # python-magic, 실제 파일 MIME 타입 확인용 

import subprocess
import os


# 업로드 디렉토리
UPLOAD_DIR = "example"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()

# CORS 설정(필요시)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 운영 환경에 맞게 설정
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def scan_file_with_clamav(file_path: str) -> bool:
    """
    ClamAV (clamscan)으로 파일을 검사하는 함수.
    return:
      - True : 바이러스 미검출(OK)
      - False: 바이러스 발견 또는 오류
    """
    # clamscan 의 return code
    # 0 => 악성코드 없음
    # 1 => 악성코드 발견
    # 2 => 사용법 오류 or 스캔 중 오류
    cmd = [
        "clamscan",
        "--infected",
        "--no-summary",  
        "--stdout",      # 결과를 stdout에 출력
        file_path
    ]

    try:
        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode == 0:
            # 0 => OK
            print(f"[ClamAV] No virus found in {file_path}")
            return True
        elif process.returncode == 1:
            # 1 => 바이러스 발견
            print(f"[ClamAV] Virus found in {file_path} !!")
            print("Output:", process.stdout)
            return False
        else:
            # 2 => 스캔 오류
            print("[ClamAV] Error scanning file:", process.stderr)
            return False
    except FileNotFoundError:
        print("[ClamAV] clamscan command not found. Please install ClamAV.")
        return False

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    단일 파일 업로드 + ClamAV 검사 예시
    """
    # 1) 파일 크기 검사(10MB 이하)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일의 최대 크기는 10MB입니다")
    
    """
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        file_size = file.file.seek(0, 2)  # Get file size
        file.file.seek(0)  # Reset file pointer
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 10MB limit.")
    """
    # 2) 파일 확장자 검사 (선택적으로 가능)
    #    예: 이미지 파일만 허용한다고 했을 때
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ["png", "jpg", "jpeg", "gif"]:
        raise HTTPException(status_code=400, detail="허용되지 않은 확장자입니다")

    # 3) MIME 타입 검사 (python-magic 등 활용 - 선택)
    #    임시 파일에 저장 후 magic으로 검사
    temp_filename = f"{uuid.uuid4()}"
    temp_file_path = os.path.join(UPLOAD_DIR, temp_filename)

    # 파일 저장(비동기 모드이므로 async write 사용)
    with open(temp_file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    # MIME 타입 검사 
    mime = magic.from_file(temp_file_path, mime=True)
    print("Detected MIME:", mime)

    # 이미지 MIME인지 확인
    if not mime.startswith("image/"):
        os.remove(temp_file_path)
        raise HTTPException(status_code=400, detail="파일 타입이 다릅니다")

    # 4) ClamAV 검사
    is_clean = scan_file_with_clamav(temp_file_path)
    if not is_clean:
        # 감염되었거나 오류 => 파일 삭제 후 에러 반환
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=400, detail="파일이 감염되었거나 오류가 발생했습니다")

    # 5) 최종적으로 안전하다고 판단되면, 원하는 최종 파일명으로 이동/저장
    final_filename = f"{uuid.uuid4()}_{file.filename}" #    여기서는 간단히 UUID로 재저장 예시
    final_path = os.path.join(UPLOAD_DIR, final_filename)
    os.rename(temp_file_path, final_path)

    connection = get_connection()
    try:
        cursor = connection.cursor()
        query = """
        INSERT INTO file_metadata (post_id, file_name, file_path, file_size, file_type, user_email, upload_time)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(query, (post_id, final_filename, final_path, file_size, file.content_type, user["sub"]))
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    return JSONResponse(content={
        "message": "File uploaded and scanned successfully",
        "filename": final_filename,
        "mime_type": mime
    }, status_code=200)
