# 1. Python 이미지를 기반으로 한다 (최신 버전 권장)
FROM python:3.10-slim

# 2. 앱 디렉토리 지정
WORKDIR /app

# 3. 소스 코드 전체 복사
COPY . /app

# 4. 필요한 패키지 설치 (requirements.txt가 꼭 필요!)
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 5. 8000번 포트 개방 (FastAPI 기본 포트)
EXPOSE 8000

# 6. uvicorn으로 FastAPI 서버 실행 (main:app → main.py 파일의 app 객체)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
