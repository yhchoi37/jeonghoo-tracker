"""
유틸리티 모듈
로깅, 헬퍼 함수 등
"""
from datetime import datetime


def log(msg: str) -> None:
    """타임스탬프 포함 로그 출력"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")
