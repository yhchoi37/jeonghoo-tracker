"""
상태 핸들러 모듈
추적, 수색, 대기 등 상태별 로직을 분리하여 처리
"""
import math
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
import numpy as np

from config import config
from state import TrackerState
from ptz_manager import PTZManager
from debug_utils import get_debug_manager
from utils import log


class Detection:
    """감지 결과 클래스"""
    
    def __init__(
        self,
        box: List[float],
        confidence: float,
        score: float
    ):
        """
        Args:
            box: 바운딩 박스 [x1, y1, x2, y2]
            confidence: 모델 신뢰도
            score: 종합 점수 (신뢰도 + 중심 거리)
        """
        self.box = box
        self.confidence = confidence
        self.score = score
    
    @property
    def center(self) -> Tuple[float, float]:
        """박스 중심 좌표"""
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2


class DetectionProcessor:
    """YOLO 감지 결과 처리 클래스"""
    
    @staticmethod
    def find_best_target(
        results,
        frame_width: int,
        frame_height: int
    ) -> Optional[Detection]:
        """
        최적의 추적 타겟 선정
        
        신뢰도와 중심 거리를 가중 평균하여 점수 계산
        
        Args:
            results: YOLO 추론 결과
            frame_width: 프레임 너비
            frame_height: 프레임 높이
            
        Returns:
            최적 타겟 Detection 또는 None
        """
        cx, cy = frame_width / 2, frame_height / 2
        best_target: Optional[Detection] = None
        best_score = -1.0
        
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            
            # 한 번에 NumPy 변환 (최적화)
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            
            for i in range(len(xyxy)):
                x1, y1, x2, y2 = xyxy[i]
                conf = float(confs[i])
                
                # 박스 중심 계산
                bx_cx = (x1 + x2) / 2
                bx_cy = (y1 + y2) / 2
                
                # 중심으로부터의 정규화된 거리
                dist_x = abs(bx_cx - cx) / (frame_width / 2)
                dist_y = abs(bx_cy - cy) / (frame_height / 2)
                dist_factor = (dist_x + dist_y) / 2
                
                # 가중 점수 계산
                score = (
                    conf * config.CONFIDENCE_WEIGHT +
                    (1.0 - dist_factor) * config.DISTANCE_WEIGHT
                )
                
                if score > best_score:
                    best_score = score
                    best_target = Detection(
                        box=[x1, y1, x2, y2],
                        confidence=conf,
                        score=score
                    )
        
        return best_target


class VelocityCalculator:
    """PTZ 속도 계산 클래스"""
    
    @staticmethod
    def calculate(
        target_x: float,
        target_y: float,
        frame_width: int,
        frame_height: int
    ) -> Tuple[float, float]:
        """
        타겟 위치에 따른 PTZ 속도 계산
        
        Args:
            target_x: 타겟 X 좌표
            target_y: 타겟 Y 좌표
            frame_width: 프레임 너비
            frame_height: 프레임 높이
            
        Returns:
            (pan_velocity, tilt_velocity) 튜플
        """
        cx, cy = frame_width / 2, frame_height / 2
        
        # 정규화된 오차
        dx = (target_x - cx) / frame_width
        dy = (target_y - cy) / frame_height
        
        pan_val = 0.0
        tilt_val = 0.0
        
        # 데드존 외부에서만 속도 계산
        if abs(dx) > config.PAN_DEAD_ZONE:
            speed = min(
                abs(dx * config.VELOCITY_MULTIPLIER) ** config.VELOCITY_EXPONENT,
                1.0
            )
            pan_val = math.copysign(speed, dx)
        
        if abs(dy) > config.TILT_DEAD_ZONE:
            speed = min(
                abs(dy * config.VELOCITY_MULTIPLIER) ** config.VELOCITY_EXPONENT,
                1.0
            )
            # Y축은 반전 (화면 아래 = 틸트 위로)
            tilt_val = math.copysign(speed, -dy)
        
        return pan_val, tilt_val


class StateHandler(ABC):
    """상태 핸들러 추상 기본 클래스"""
    
    @abstractmethod
    def handle(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        """
        상태별 처리 로직
        
        Args:
            frame: 현재 프레임
            detection: 감지 결과 (없으면 None)
            state: 트래커 상태
            ptz: PTZ 매니저
        """
        pass


class TrackingHandler(StateHandler):
    """타겟 추적 상태 핸들러"""
    
    def handle(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        if detection is None:
            return
        
        h, w = frame.shape[:2]
        
        # 처음 타겟 발견 시 로그
        if not state.was_tracking:
            log(f"👁️ 타겟 발견! 추적 시작 (Conf: {detection.confidence:.2f})")
        
        # 상태 업데이트
        state.lock_target()
        
        # 속도 계산
        tx, ty = detection.center
        pan_val, tilt_val = VelocityCalculator.calculate(tx, ty, w, h)
        
        # PTZ 제어
        ptz.set_velocity(pan_val, tilt_val)
        
        # 디버그 이미지 저장
        debug = get_debug_manager()
        debug.save_debug_image(
            frame, state,
            box=detection.box,
            conf=detection.confidence,
            pan=pan_val,
            tilt=tilt_val
        )


class LostHandler(StateHandler):
    """타겟 놓침 상태 핸들러"""
    
    def handle(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        log("🚫 타겟 놓침! (화면에서 사라짐) -> 카메라 정지")
        
        ptz.stop()
        state.unlock_target()
        
        # 놓친 순간 디버그 이미지 저장
        debug = get_debug_manager()
        debug.save_debug_image(
            frame, state,
            status_override="[LOST] Target Disappeared"
        )


class SearchingHandler(StateHandler):
    """소리 감지 수색 상태 핸들러"""
    
    def handle(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        state.target_locked = False
        
        # 수색 시간 종료 확인
        if state.is_search_timeout(config.AUDIO_TRIGGER_TIME):
            log("💤 수색 시간 종료 (5분 경과) -> 대기 모드")
            state.stop_searching()
            ptz.stop()
            return
        
        # 프리셋 이동 시간 확인
        if state.should_move_preset(config.SCAN_INTERVAL):
            idx = state.next_preset(len(config.SEARCH_PRESETS))
            target_preset = config.SEARCH_PRESETS[idx]
            
            log(f"🔎 수색 중: 프리셋 {target_preset}번으로 이동")
            ptz.goto_preset(target_preset)
            
            debug = get_debug_manager()
            debug.save_debug_image(frame, state)
        else:
            # 관찰 중 주기적 로그
            if state.can_log_status(config.SEARCH_LOG_INTERVAL):
                remain = state.get_scan_remaining_time(config.SCAN_INTERVAL)
                log(f"👀 관찰 중... (다음 이동까지 {remain}초)")
                state.mark_status_logged()
                
                debug = get_debug_manager()
                debug.save_debug_image(frame, state)


class IdleHandler(StateHandler):
    """대기 상태 핸들러"""
    
    def handle(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        state.target_locked = False
        ptz.stop()
        
        # 주기적 상태 로그 및 디버그 이미지
        if state.can_log_status(config.STATUS_LOG_INTERVAL):
            state.mark_status_logged()
            
            debug = get_debug_manager()
            debug.save_debug_image(frame, state)


class StateRouter:
    """상태에 따라 적절한 핸들러로 라우팅"""
    
    def __init__(self):
        self.tracking_handler = TrackingHandler()
        self.lost_handler = LostHandler()
        self.searching_handler = SearchingHandler()
        self.idle_handler = IdleHandler()
    
    def route(
        self,
        frame: np.ndarray,
        detection: Optional[Detection],
        state: TrackerState,
        ptz: PTZManager
    ) -> None:
        """
        현재 상태에 맞는 핸들러 실행
        
        Args:
            frame: 현재 프레임
            detection: 감지 결과
            state: 트래커 상태
            ptz: PTZ 매니저
        """
        # 상황 1: 타겟 감지됨 -> 추적
        if detection is not None:
            self.tracking_handler.handle(frame, detection, state, ptz)
        
        # 상황 2: 방금 놓침 (추적 중이었다가 사라짐)
        elif state.was_tracking:
            self.lost_handler.handle(frame, detection, state, ptz)
        
        # 상황 3: 수색 모드 (소리 감지)
        elif state.is_searching:
            self.searching_handler.handle(frame, detection, state, ptz)
        
        # 상황 4: 대기 모드
        else:
            self.idle_handler.handle(frame, detection, state, ptz)
