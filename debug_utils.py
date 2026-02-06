"""
디버그 유틸리티 모듈
디버그 이미지 저장 및 관리 기능
"""
import os
import cv2
import glob
from datetime import datetime
from typing import Optional, List, Tuple
import numpy as np

from config import config
from state import TrackerState
from utils import log


class DebugImageManager:
    """
    디버그 이미지 저장 및 관리 클래스
    
    - 상태바가 포함된 디버그 이미지 저장
    - 오래된 이미지 자동 정리
    """
    
    # 상태별 배경색 (BGR)
    STATUS_COLORS = {
        'tracking': (0, 200, 0),      # 초록
        'searching': (255, 140, 0),   # 주황
        'idle': (50, 50, 50),         # 회색
        'lost': (0, 0, 255),          # 빨강
        'special': (0, 0, 255),       # 빨강
    }
    
    def __init__(self, debug_dir: Optional[str] = None):
        """
        Args:
            debug_dir: 디버그 이미지 저장 디렉토리 (None이면 config 사용)
        """
        self.debug_dir = debug_dir or config.DEBUG_DIR
        self._ensure_dir()
    
    def _ensure_dir(self) -> None:
        """디버그 디렉토리 생성"""
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
        except Exception as e:
            log(f"⚠️ 디버그 디렉토리 생성 실패: {e}")
    
    def save_debug_image(
        self,
        frame: np.ndarray,
        state: TrackerState,
        box: Optional[List[float]] = None,
        conf: float = 0.0,
        pan: float = 0.0,
        tilt: float = 0.0,
        status_override: Optional[str] = None
    ) -> bool:
        """
        디버그 이미지 저장
        
        Args:
            frame: 원본 프레임
            state: 현재 트래커 상태
            box: 감지된 바운딩 박스 [x1, y1, x2, y2]
            conf: 감지 신뢰도
            pan: 현재 팬 속도
            tilt: 현재 틸트 속도
            status_override: 상태 텍스트 오버라이드
            
        Returns:
            저장 성공 여부
        """
        if not config.SAVE_DEBUG_IMAGES:
            return False
        
        if not state.can_save_debug(config.DEBUG_SAVE_INTERVAL):
            return False
        
        try:
            annotated = frame.copy()
            h, w = annotated.shape[:2]
            cx, cy = w // 2, h // 2
            
            # 십자선 그리기
            self._draw_crosshair(annotated, cx, cy, h, w)
            
            # 감지 박스 그리기
            if box:
                self._draw_detection_box(annotated, box, conf)
            
            # 상태 텍스트 및 배경색 결정
            info_text, bg_color = self._get_status_info(
                state, pan, tilt, status_override
            )
            
            # 상단 상태바 그리기
            self._draw_status_bar(annotated, info_text, bg_color, w)
            
            # 파일 저장
            filename = self._generate_filename()
            cv2.imwrite(filename, annotated)
            
            log(f"📸 사진 저장: {info_text}")
            state.mark_debug_saved()
            
            # 오래된 파일 정리
            self._cleanup_old_files()
            
            return True
            
        except Exception as e:
            log(f"⚠️ 디버그 이미지 저장 실패: {e}")
            return False
    
    def _draw_crosshair(
        self,
        frame: np.ndarray,
        cx: int,
        cy: int,
        h: int,
        w: int
    ) -> None:
        """십자선 그리기"""
        cv2.line(frame, (cx, 0), (cx, h), (0, 255, 0), 1)
        cv2.line(frame, (0, cy), (w, cy), (0, 255, 0), 1)
    
    def _draw_detection_box(
        self,
        frame: np.ndarray,
        box: List[float],
        conf: float
    ) -> None:
        """감지 박스 및 라벨 그리기"""
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
        
        label = f"Jeonghoo {conf:.2f}"
        cv2.putText(
            frame, label, (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2
        )
    
    def _get_status_info(
        self,
        state: TrackerState,
        pan: float,
        tilt: float,
        status_override: Optional[str]
    ) -> Tuple[str, Tuple[int, int, int]]:
        """상태 텍스트 및 배경색 결정"""
        if status_override:
            return status_override, self.STATUS_COLORS['special']
        
        if state.target_locked:
            info_text = f"[TRACKING] SPD: P{pan:.1f}/T{tilt:.1f}"
            return info_text, self.STATUS_COLORS['tracking']
        
        if state.is_searching:
            preset_idx = state.current_preset_idx % len(config.SEARCH_PRESETS)
            preset = config.SEARCH_PRESETS[preset_idx]
            remain = state.get_search_remaining_time(config.AUDIO_TRIGGER_TIME)
            info_text = f"[SEARCHING] Preset {preset} ({remain}s left)"
            return info_text, self.STATUS_COLORS['searching']
        
        return "[IDLE] Waiting...", self.STATUS_COLORS['idle']
    
    def _draw_status_bar(
        self,
        frame: np.ndarray,
        text: str,
        bg_color: Tuple[int, int, int],
        width: int
    ) -> None:
        """상단 상태바 그리기"""
        cv2.rectangle(frame, (0, 0), (width, 40), bg_color, -1)
        cv2.putText(
            frame, text, (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
        )
    
    def _generate_filename(self) -> str:
        """디버그 이미지 파일명 생성"""
        timestamp = datetime.now().strftime('%H%M%S_%f')[:10]  # 마이크로초 일부 포함
        return os.path.join(self.debug_dir, f"{timestamp}.jpg")
    
    def _cleanup_old_files(self) -> None:
        """오래된 디버그 이미지 정리"""
        try:
            pattern = os.path.join(self.debug_dir, "*.jpg")
            files = sorted(glob.glob(pattern))
            
            # 최대 파일 수 초과 시 오래된 것부터 삭제
            excess_count = len(files) - config.DEBUG_MAX_FILES
            if excess_count > 0:
                for f in files[:excess_count]:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                        
        except Exception as e:
            log(f"⚠️ 디버그 파일 정리 실패: {e}")


# 전역 디버그 매니저 인스턴스
debug_manager: Optional[DebugImageManager] = None


def get_debug_manager() -> DebugImageManager:
    """디버그 매니저 싱글톤 인스턴스 반환"""
    global debug_manager
    if debug_manager is None:
        debug_manager = DebugImageManager()
    return debug_manager
