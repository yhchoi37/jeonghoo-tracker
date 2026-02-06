"""
프레임 리더 모듈
RTSP 스트림에서 최신 프레임을 읽는 스레드 기반 리더
"""
import cv2
import time
import threading
from typing import Optional, Tuple
import numpy as np

from utils import log


class LatestFrameReader:
    """
    RTSP 스트림에서 항상 최신 프레임만 유지하는 스레드 기반 리더
    
    컨텍스트 매니저 지원:
        with LatestFrameReader(url) as reader:
            ret, frame = reader.read()
    """
    
    def __init__(self, src: str, buffer_size: int = 1):
        """
        Args:
            src: RTSP 스트림 URL
            buffer_size: OpenCV 버퍼 크기 (1 권장)
        """
        self.src = src
        self.buffer_size = buffer_size
        
        self.cap: Optional[cv2.VideoCapture] = None
        self.lock = threading.Lock()
        self.ret = False
        self.frame: Optional[np.ndarray] = None
        self.stopped = False
        self.thread: Optional[threading.Thread] = None
        
        self._connect()
    
    def _connect(self) -> bool:
        """스트림 연결"""
        try:
            self.cap = cv2.VideoCapture(self.src)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
            
            if not self.cap.isOpened():
                log(f"⚠️ 스트림 연결 실패: {self.src}")
                return False
            
            log(f"✅ 스트림 연결 성공: {self.src}")
            self._start_thread()
            return True
            
        except Exception as e:
            log(f"❌ 스트림 연결 오류: {e}")
            return False
    
    def _start_thread(self) -> None:
        """프레임 읽기 스레드 시작"""
        if self.thread is not None and self.thread.is_alive():
            return
        
        self.stopped = False
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
    
    def _update_loop(self) -> None:
        """프레임 업데이트 루프 (백그라운드 스레드)"""
        consecutive_failures = 0
        max_failures = 30  # 30회 연속 실패 시 재연결
        
        while not self.stopped:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.1)
                continue
            
            try:
                ret, frame = self.cap.read()
                
                if not ret or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        log("⚠️ 프레임 읽기 연속 실패, 재연결 시도...")
                        self._reconnect()
                        consecutive_failures = 0
                    time.sleep(0.01)
                    continue
                
                consecutive_failures = 0
                
                with self.lock:
                    self.ret = ret
                    self.frame = frame
                
                time.sleep(0.005)  # CPU 사용률 조절
                
            except Exception as e:
                log(f"⚠️ 프레임 읽기 오류: {e}")
                time.sleep(0.1)
    
    def _reconnect(self) -> None:
        """스트림 재연결"""
        try:
            if self.cap is not None:
                self.cap.release()
            
            self.cap = cv2.VideoCapture(self.src)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
            
            if self.cap.isOpened():
                log("✅ 스트림 재연결 성공")
            else:
                log("❌ 스트림 재연결 실패")
                
        except Exception as e:
            log(f"❌ 스트림 재연결 오류: {e}")
    
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        최신 프레임 읽기
        
        Returns:
            (성공 여부, 프레임) 튜플
        """
        with self.lock:
            if self.frame is not None:
                return self.ret, self.frame.copy()
            return False, None
    
    def stop(self) -> None:
        """리더 정지 및 리소스 해제"""
        self.stopped = True
        
        # 스레드 종료 대기
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        
        # 캡처 해제
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        log("🛑 프레임 리더 정지됨")
    
    def __enter__(self) -> 'LatestFrameReader':
        """컨텍스트 매니저 진입"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """컨텍스트 매니저 종료"""
        self.stop()
    
    @property
    def is_running(self) -> bool:
        """리더 실행 중 여부"""
        return not self.stopped and self.thread is not None and self.thread.is_alive()
