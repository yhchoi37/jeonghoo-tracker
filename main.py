"""
정후 트래커 (Jeonghoo Tracker)
아기 자동 추적 홈캠 시스템

Tapo C210 + Frigate + YOLO 기반 아기 추적
"""
import signal
import sys
import time
from typing import Optional

import paho.mqtt.client as mqtt
from ultralytics import YOLO

from config import config
from state import TrackerState
from frame_reader import LatestFrameReader
from ptz_manager import PTZManager
from handlers import StateRouter, DetectionProcessor
from debug_utils import get_debug_manager
from frame_analyzer import FrameAnalyzer
from utils import log


class JeonghooTracker:
    """정후 트래커 메인 클래스"""
    
    def __init__(self):
        self.state = TrackerState()
        self.ptz: Optional[PTZManager] = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self.frame_reader: Optional[LatestFrameReader] = None
        self.model: Optional[YOLO] = None
        self.router = StateRouter()
        self.running = False
        
        # FPS 제한
        self.min_frame_time = 1.0 / config.TARGET_FPS
        self.last_process_time = 0.0
    
    def _setup_signal_handlers(self) -> None:
        """시그널 핸들러 설정 (Graceful Shutdown)"""
        def signal_handler(signum, frame):
            log(f"🛑 시그널 {signum} 수신, 종료 중...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def _init_ptz(self) -> bool:
        """PTZ 초기화"""
        try:
            self.ptz = PTZManager()
            return True
        except Exception as e:
            log(f"❌ PTZ 초기화 실패: {e}")
            return False
    
    def _init_mqtt(self) -> bool:
        """MQTT 클라이언트 초기화"""
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.on_message = self._on_mqtt_message
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            
            self._mqtt_connect()
            self.mqtt_client.loop_start()
            return True
            
        except Exception as e:
            log(f"❌ MQTT 초기화 실패: {e}")
            return False
    
    def _mqtt_connect(self) -> None:
        """MQTT 브로커 연결"""
        try:
            self.mqtt_client.connect(
                config.MQTT_BROKER_IP,
                config.MQTT_PORT,
                config.MQTT_KEEPALIVE
            )
            # 오디오 + person 토픽 구독
            self.mqtt_client.subscribe(config.get_mqtt_audio_topic())
            self.mqtt_client.subscribe(config.get_mqtt_person_topic())
            log(f"✅ MQTT 연결 성공: {config.MQTT_BROKER_IP}")
        except Exception as e:
            log(f"⚠️ MQTT 연결 실패: {e}")
    
    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        """MQTT 연결 해제 콜백"""
        log(f"⚠️ MQTT 연결 해제: {reason_code}")
        # 자동 재연결 시도
        while self.running:
            try:
                time.sleep(5)
                log("🔄 MQTT 재연결 시도...")
                self._mqtt_connect()
                break
            except Exception as e:
                log(f"⚠️ MQTT 재연결 실패: {e}")
    
    def _on_mqtt_message(self, client, userdata, msg) -> None:
        """MQTT 메시지 수신 콜백"""
        # 보관된 메시지 무시
        if msg.retain:
            return
        
        # 시작 직후 무시
        if self.state.is_startup_period(config.STARTUP_IGNORE_TIME):
            return
        
        topic = msg.topic
        
        try:
            payload = msg.payload.decode()
            
            # 1. Person 감지 처리 (Frigate에서 사람 수)
            if "person" in topic and "audio" not in topic:
                try:
                    count = int(payload)
                    self.state.update_person_count(count)
                except ValueError:
                    pass
            
            # 2. 오디오 감지 처리
            elif "audio" in topic:
                if payload == "ON" and not self.state.target_locked:
                    if not self.state.is_searching:
                        log("👂 소리 감지됨! -> 수색 모드 진입 (5분간)")
                    self.state.start_searching()
                    if self.frame_reader and self.frame_reader.paused:
                        self.frame_reader.resume()
                    
        except Exception as e:
            log(f"⚠️ MQTT 메시지 처리 오류: {e}")
    
    def _init_model(self) -> bool:
        """YOLO 모델 로드"""
        log(f"🚀 OpenVINO 모델 로딩 중: {config.MODEL_PATH} ...")
        try:
            self.model = YOLO(config.MODEL_PATH, task='detect')
            log("✅ 모델 로드 완료")
            return True
        except Exception as e:
            log(f"❌ 모델 로드 실패: {e}")
            return False
    
    def _init_stream(self) -> bool:
        """비디오 스트림 초기화"""
        rtsp_url = config.get_rtsp_url()
        log(f"📹 스트림 연결 중: {rtsp_url}")
        
        try:
            self.frame_reader = LatestFrameReader(rtsp_url)
            time.sleep(1)  # 버퍼 채우기 대기
            return True
        except Exception as e:
            log(f"❌ 스트림 초기화 실패: {e}")
            return False
    
    def initialize(self) -> bool:
        """전체 시스템 초기화"""
        log("=" * 50)
        log("🚀 정후 트래커 초기화 중...")
        log("=" * 50)
        
        # 설정 검증
        if not config.validate():
            log("❌ 필수 설정값이 누락되었습니다 (TAPO_IP, TAPO_USER, TAPO_PASSWORD)")
            return False
        
        # 시그널 핸들러 설정
        self._setup_signal_handlers()
        
        # 디버그 매니저 초기화
        get_debug_manager()
        
        # 컴포넌트 초기화
        if not self._init_ptz():
            return False
        
        if not self._init_mqtt():
            return False
        
        if not self._init_model():
            return False
        
        if not self._init_stream():
            return False
        
        log("=" * 50)
        log("✅ 정후 트래커 시작 (상세 로그 모드)")
        log("=" * 50)
        
        return True
    
    def run(self) -> None:
        """메인 추적 루프"""
        self.running = True
        
        while self.running:
            # === 슬립 모드 처리 (프라이버시 모드) ===
            if self.state.is_sleep_mode:
                # 슬립 모드에서는 긴 간격으로만 체크
                if not self.state.can_check_sleep(config.SLEEP_CHECK_INTERVAL):
                    time.sleep(0.1)
                    continue
                
                self.state.mark_sleep_checked()
                
                # 프라이버시 확인 전엔 잠시 스트림을 켬
                if self.frame_reader.paused:
                    self.frame_reader.resume()

                # 프레임 읽어서 정상 화면인지 확인
                ret, frame = self.frame_reader.read()
                if not ret or frame is None:
                    continue
                
                if FrameAnalyzer.is_normal_frame(frame):
                    # 연속으로 정상 프레임 감지 시 복귀
                    count = self.state.increment_normal_count()
                    if count >= config.SLEEP_WAKE_CHECK_COUNT:
                        duration = self.state.get_sleep_duration()
                        log(f"☀️ 프라이버시 모드 해제 감지 -> 정상 모드 복귀 (슬립 {duration}초)")
                        self.state.exit_sleep_mode()
                else:
                    self.state.reset_normal_count()
                    # 주기적으로 슬립 상태 로그
                    if self.state.can_log_status(config.STATUS_LOG_INTERVAL):
                        duration = self.state.get_sleep_duration()
                        log(f"🌙 슬립 모드 유지 중... ({duration}초 경과)")
                        self.state.mark_status_logged()
                    
                    # 다시 바로 일시정지
                    self.frame_reader.pause()
                
                continue
            
            # === 정상 모드: FPS 제한 ===
            current_time = time.time()
            elapsed = current_time - self.last_process_time
            
            if elapsed < self.min_frame_time:
                time.sleep(self.min_frame_time - elapsed)
                continue
            
            self.last_process_time = time.time()
            
            # 대기 상태에서 빠져나왔다면(사람 감지/오디오 감지), 스트림 재개
            if self.frame_reader.paused:
                self.frame_reader.resume()

            # 프레임 읽기
            ret, frame = self.frame_reader.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            
            # === 프라이버시 모드 감지 ===
            if FrameAnalyzer.is_privacy_mode(frame):
                log("🌙 프라이버시 모드 감지 -> 슬립 모드 진입 (CPU 절약)")
                self.state.enter_sleep_mode()
                self.ptz.stop()
                continue
            
            # === 대기 모드 (사람 없음 + 수색 아님) ===
            if self.state.is_idle_mode(config.PERSON_TIMEOUT):
                # 대기 모드에서는 스트림 수신 완전 중단으로 CPU 절약
                if self.state.can_log_status(config.STATUS_LOG_INTERVAL):
                    log("💤 대기 모드 (사람 없음, RTSP 스트림 일시정지)")
                    self.state.mark_status_logged()
                self.ptz.stop()
                self.frame_reader.pause()
                time.sleep(config.IDLE_CHECK_INTERVAL)
                continue
            
            # YOLO 추론 (imgsz로 해상도 최적화)
            results = self.model(
                frame,
                verbose=False,
                conf=config.MODEL_CONFIDENCE,
                imgsz=config.MODEL_IMGSZ
            )
            
            # 최적 타겟 선정 (1순위: 정후)
            h, w = frame.shape[:2]
            detection = DetectionProcessor.find_best_target(results, w, h, target_classes=[1])
            
            # Fallback 로직: 추적 중인데 정후가 안 보이면 가족(0, 2) 확인
            if detection is None and (self.state.target_locked or self.state.was_tracking):
                detection = DetectionProcessor.find_best_target(
                    results, w, h, target_classes=config.FALLBACK_CLASSES
                )
                if detection is not None:
                    # Fallback 성공 시 로그 (디버깅용)
                    # log(f"⚠️ 정후 놓침 -> 대체 타겟(Class {detection.class_id}) 추적")
                    pass
            
            # 상태별 처리
            self.router.route(frame, detection, self.state, self.ptz)
    
    def shutdown(self) -> None:
        """시스템 종료"""
        log("🛑 정후 트래커 종료 중...")
        self.running = False
        
        if self.frame_reader:
            self.frame_reader.stop()
        
        if self.ptz:
            self.ptz.shutdown()
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        log("🛑 정후 트래커 종료 완료")


def main():
    """엔트리 포인트"""
    tracker = JeonghooTracker()
    
    if not tracker.initialize():
        log("❌ 초기화 실패, 프로그램 종료")
        sys.exit(1)
    
    try:
        tracker.run()
    except KeyboardInterrupt:
        log("⌨️ 키보드 인터럽트")
    finally:
        tracker.shutdown()


if __name__ == "__main__":
    main()
