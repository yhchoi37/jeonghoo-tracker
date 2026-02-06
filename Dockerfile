FROM python:3.10-slim

WORKDIR /app

# 1. 시스템 필수 패키지 설치 (OpenCV, OpenVINO 구동용)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. requirements.txt 복사
COPY requirements.txt .

# 3. [핵심] CPU 전용 PyTorch 먼저 설치 (용량 절약 & 속도 최적화)
# N100에는 CUDA가 필요 없으므로 cpu 버전을 명시해서 받습니다.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. 나머지 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 복사 (혹은 docker-compose에서 볼륨 매핑한다면 생략 가능하지만 안전하게 복사)
# COPY main.py . 
# COPY best.pt .

# (참고: 실행 명령어는 docker-compose.yml에서 command로 덮어쓰거나 여기에 적어둠)
CMD ["python", "-u", "main.py"]
