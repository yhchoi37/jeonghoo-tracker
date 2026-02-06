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

# 3. CPU 전용 PyTorch 먼저 설치 (용량 절약 & 속도 최적화)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. 나머지 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# 5. Python 소스 코드 복사
# COPY main.py .
# COPY config.py .
# COPY state.py .
# COPY handlers.py .
# COPY ptz_manager.py .
# COPY frame_reader.py .
# COPY frame_analyzer.py .
# COPY debug_utils.py .
# COPY utils.py .

# 6. 실행
CMD ["python", "-u", "main.py"]
