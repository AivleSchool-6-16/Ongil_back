# ── 1) 베이스 이미지 ──
FROM python:3.11-slim

# ── 2) 시스템 의존성 설치 ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

# ── 3) 작업 디렉터리 설정 ──
WORKDIR /app

# ── 4) 파이썬 의존성 설치 ──
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── 5) 애플리케이션 코드 복사 ──
COPY . .

# ── 6) .env 파일은 보안상 이미지에 포함시키지 않고, 
#        컨테이너 실행 시 볼륨 마운트나 환경변수로 주입하세요.

# ── 7) 앱 포트 노출 ──
EXPOSE 8000

# ── 8) 컨테이너 시작 명령 ──
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]