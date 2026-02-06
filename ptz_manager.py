"""
PTZ 매니저 모듈
Tapo 카메라 PTZ 제어를 담당하는 클래스
"""
import time
import threading
from typing import Optional, Any

from onvif import ONVIFCamera

from config import config
from utils import log


class PTZManager:
    """
    Tapo 카메라 PTZ 제어 클래스
    
    백그라운드 스레드에서 지속적으로 PTZ 명령을 전송합니다.
    재연결 및 에러 복구 로직을 포함합니다.
    """
    
    def __init__(self):
        self.ptz: Optional[Any] = None
        self.profile: Optional[str] = None
        
        # 현재 명령 속도
        self.cmd_pan: float = 0.0
        self.cmd_tilt: float = 0.0
        
        # 스레드 제어
        self.running = True
        self.lock = threading.Lock()
        
        # 초기 연결
        self._connect()
        
        # PTZ 명령 전송 스레드 시작
        self.thread = threading.Thread(target=self._command_loop, daemon=True)
        self.thread.start()
    
    def _connect(self) -> bool:
        """ONVIF PTZ 서비스 연결"""
        try:
            cam = ONVIFCamera(
                config.TAPO_IP,
                config.TAPO_ONVIF_PORT,
                config.TAPO_USER,
                config.TAPO_PASSWORD
            )
            
            media = cam.create_media_service()
            self.ptz = cam.create_ptz_service()
            
            profiles = media.GetProfiles()
            if not profiles:
                log("❌ PTZ 프로필을 찾을 수 없음")
                return False
            
            self.profile = profiles[0].token
            log("✅ Tapo PTZ 연결 성공")
            return True
            
        except Exception as e:
            log(f"❌ PTZ 연결 실패: {e}")
            log(f"   {config.PTZ_RECONNECT_DELAY}초 후 재시도...")
            self.ptz = None
            self.profile = None
            time.sleep(config.PTZ_RECONNECT_DELAY)
            return False
    
    def set_velocity(self, pan: float, tilt: float) -> None:
        """
        PTZ 속도 설정
        
        Args:
            pan: 수평 회전 속도 (-1.0 ~ 1.0)
            tilt: 수직 회전 속도 (-1.0 ~ 1.0)
        """
        with self.lock:
            self.cmd_pan = max(-1.0, min(1.0, pan))
            self.cmd_tilt = max(-1.0, min(1.0, tilt))
    
    def stop(self) -> None:
        """PTZ 정지"""
        self.set_velocity(0, 0)
    
    def goto_preset(self, preset_token: str) -> bool:
        """
        프리셋 위치로 이동
        
        Args:
            preset_token: 프리셋 토큰 번호
            
        Returns:
            성공 여부
        """
        if not self.ptz or not self.profile:
            log("⚠️ PTZ 미연결 상태에서 프리셋 이동 시도")
            return False
        
        try:
            req = self.ptz.create_type('GotoPreset')
            req.ProfileToken = self.profile
            req.PresetToken = str(preset_token)
            self.ptz.GotoPreset(req)
            
            # 프리셋 이동 시 속도 명령 초기화
            with self.lock:
                self.cmd_pan = 0
                self.cmd_tilt = 0
            
            log(f"🔭 프리셋 {preset_token}번으로 이동")
            return True
            
        except Exception as e:
            log(f"⚠️ 프리셋 이동 실패: {e}")
            return False
    
    def _command_loop(self) -> None:
        """PTZ 명령 전송 루프 (백그라운드 스레드)"""
        last_pan: float = 0.0
        last_tilt: float = 0.0
        
        while self.running:
            # PTZ 연결 확인
            if not self.ptz or not self.profile:
                self._connect()
                continue
            
            # 현재 명령 속도 읽기
            with self.lock:
                current_pan = self.cmd_pan
                current_tilt = self.cmd_tilt
            
            # 속도 변경 감지
            pan_changed = abs(current_pan - last_pan) > config.PTZ_VELOCITY_THRESHOLD
            tilt_changed = abs(current_tilt - last_tilt) > config.PTZ_VELOCITY_THRESHOLD
            stopped = current_pan == 0 and current_tilt == 0 and last_pan != 0
            
            if pan_changed or tilt_changed or stopped:
                try:
                    if current_pan == 0 and current_tilt == 0:
                        # 정지 명령
                        self.ptz.Stop({
                            'ProfileToken': self.profile,
                            'PanTilt': True,
                            'Zoom': True
                        })
                    else:
                        # 연속 이동 명령
                        req = {
                            'ProfileToken': self.profile,
                            'Velocity': {
                                'PanTilt': {'x': current_pan, 'y': current_tilt},
                                'Zoom': {'x': 0}
                            }
                        }
                        self.ptz.ContinuousMove(req)
                    
                    last_pan = current_pan
                    last_tilt = current_tilt
                    
                except Exception as e:
                    log(f"⚠️ PTZ 명령 전송 실패: {e}")
                    self.ptz = None  # 재연결 트리거
            
            time.sleep(config.PTZ_LOOP_INTERVAL)
    
    def shutdown(self) -> None:
        """PTZ 매니저 종료"""
        log("🛑 PTZ 매니저 종료 중...")
        self.running = False
        self.stop()
        
        # 스레드 종료 대기
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
        
        log("🛑 PTZ 매니저 종료됨")
    
    @property
    def is_connected(self) -> bool:
        """PTZ 연결 상태"""
        return self.ptz is not None and self.profile is not None
