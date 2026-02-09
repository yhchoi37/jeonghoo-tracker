"""
설정 관리 모듈
환경변수와 상수를 통합 관리하는 Config 클래스
"""
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    """정후 트래커 설정 클래스"""
    
    # --- 카메라 설정 ---
    TAPO_IP: str = field(default_factory=lambda: os.getenv('TAPO_IP', ''))
    TAPO_USER: str = field(default_factory=lambda: os.getenv('TAPO_USER', ''))
    TAPO_PASSWORD: str = field(default_factory=lambda: os.getenv('TAPO_PASSWORD', ''))
    TAPO_ONVIF_PORT: int = 2020
    
    # --- MQTT 설정 ---
    MQTT_BROKER_IP: str = field(default_factory=lambda: os.getenv('MQTT_BROKER_IP', '127.0.0.1'))
    MQTT_PORT: int = 1883
    MQTT_KEEPALIVE: int = 60
    
    # --- Frigate/스트림 설정 ---
    FRIGATE_CAMERA_NAME: str = field(default_factory=lambda: os.getenv('FRIGATE_CAMERA_NAME', 'livingroom'))
    GO2RTC_STREAM_NAME: str = field(default_factory=lambda: os.getenv('GO2RTC_STREAM_NAME', 'livingroom'))
    
    # --- 모델 설정 ---
    MODEL_PATH: str = 'yolo26n_jeonghoo_openvino_model'
    MODEL_CONFIDENCE: float = 0.5
    MODEL_IMGSZ: int = 640  # 추론 해상도 (작을수록 빠름)
    
    # --- 성능 설정 ---
    TARGET_FPS: int = 10  # 초당 처리 프레임 제한
    STARTUP_IGNORE_TIME: float = 10.0  # 시작 후 MQTT 무시 시간
    
    # --- 수색 모드 설정 ---
    AUDIO_TRIGGER_TIME: int = 300  # 소리 감지 후 수색 시간 (5분)
    SCAN_INTERVAL: int = 30  # 프리셋 이동 간격 (30초)
    SEARCH_PRESETS: List[str] = field(default_factory=lambda: ["1", "2", "4"])
    
    # --- 추적 알고리즘 파라미터 ---
    PAN_DEAD_ZONE: float = 0.1  # 수평 중심 허용 오차
    TILT_DEAD_ZONE: float = 0.15  # 수직 중심 허용 오차
    
    # PTZ 속도 제어 (Pan/Tilt 분리)
    PAN_VELOCITY_MULTIPLIER: float = 3.0  # 수평 속도 배율 (기존 2.8 -> 3.0 상향)
    TILT_VELOCITY_MULTIPLIER: float = 2.0  # 수직 속도 배율 (기존 2.8 -> 2.0 하향)
    VELOCITY_EXPONENT: float = 1.3  # 속도 지수 (가속도 곡선)
    
    # Fallback 안전장치
    TRACKING_PATIENCE_COUNT: int = 10  # 타겟 놓침 유예 프레임 수 (약 1초)
    FALLBACK_CLASSES: List[int] = field(default_factory=lambda: [0, 2])  # 대체 추적 클래스 (0:아빠, 2:엄마)
    MAX_FALLBACK_DISTANCE: float = 0.3  # 대체 추적 허용 반경 (화면 너비 비율)
    MAX_FALLBACK_DURATION: float = 5.0  # 대체 추적 최대 허용 시간 (초)
    
    # --- 타겟 선정 가중치 ---
    CONFIDENCE_WEIGHT: float = 0.6  # 신뢰도 가중치
    DISTANCE_WEIGHT: float = 0.4  # 중심 거리 가중치
    
    # --- 디버그 설정 ---
    DEBUG_DIR: str = field(default_factory=lambda: os.getenv('DEBUG_DIR', '/app/debug'))
    SAVE_DEBUG_IMAGES: bool = True
    DEBUG_SAVE_INTERVAL: float = 2.0  # 디버그 이미지 저장 간격
    DEBUG_MAX_FILES: int = 1000  # 최대 디버그 이미지 파일 수
    
    # --- PTZ 설정 ---
    PTZ_RECONNECT_DELAY: float = 3.0  # 연결 실패 시 재시도 대기
    PTZ_LOOP_INTERVAL: float = 0.1  # PTZ 명령 전송 주기
    PTZ_VELOCITY_THRESHOLD: float = 0.01  # 속도 변경 감지 임계값
    
    # --- 로그 설정 ---
    STATUS_LOG_INTERVAL: float = 10.0  # 상태 로그 출력 간격
    SEARCH_LOG_INTERVAL: float = 5.0  # 수색 중 로그 간격
    
    # --- 슬립 모드 설정 (프라이버시 모드) ---
    SLEEP_CHECK_INTERVAL: float = 1.0  # 슬립 모드 중 체크 간격 (초)
    PRIVACY_BRIGHTNESS_THRESHOLD: int = 30  # 프라이버시 모드 밝기 임계값
    PRIVACY_STD_THRESHOLD: int = 40  # 프라이버시 모드 표준편차 임계값
    SLEEP_WAKE_CHECK_COUNT: int = 3  # 연속 N회 정상 화면이면 복귀
    
    # --- 대기 모드 설정 (사람 없음) ---
    IDLE_CHECK_INTERVAL: float = 1.0  # 대기 모드 중 체크 간격 (초)
    PERSON_TIMEOUT: float = 30.0  # person MQTT 미수신 시 타임아웃 (초)
    
    def get_rtsp_url(self) -> str:
        """RTSP 스트림 URL 생성"""
        return f"rtsp://{self.MQTT_BROKER_IP}:8554/{self.GO2RTC_STREAM_NAME}"
    
    def get_mqtt_audio_topic(self) -> str:
        """MQTT 오디오 토픽 패턴 생성"""
        return f"frigate/{self.FRIGATE_CAMERA_NAME}/audio/+"
    
    def get_mqtt_person_topic(self) -> str:
        """MQTT person 토픽 생성"""
        return f"frigate/{self.FRIGATE_CAMERA_NAME}/person"
    
    def validate(self) -> bool:
        """필수 설정값 검증"""
        required = [self.TAPO_IP, self.TAPO_USER, self.TAPO_PASSWORD]
        return all(required)


# 전역 설정 인스턴스
config = Config()
