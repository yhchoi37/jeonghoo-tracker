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
        score: float,
        class_id: int
    ):
        """
        Args:
            box: 바운딩 박스 [x1, y1, x2, y2]
            confidence: 모델 신뢰도
            score: 종합 점수 (신뢰도 + 중심 거리)
            class_id: 클래스 ID
        """
        self.box = box
        self.confidence = confidence
        self.score = score
        self.class_id = class_id
    
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
        frame_height: int,
        target_classes: Optional[List[int]] = None,
        last_target_center: Optional[Tuple[float, float]] = None
    ) -> Optional[Detection]:
        """
        최적의 추적 타겟 선정
        
        Args:
            results: YOLO 추론 결과
            frame_width: 프레임 너비
            frame_height: 프레임 높이
            target_classes: 추적 대상 클래스 ID 리스트 (None이면 [1])
            last_target_center: 마지막 정후 위치 (Fallback 거리 제한용, 정규화 좌표)
            
        Returns:
            최적 타겟 Detection 또는 None
        """
        if target_classes is None:
            target_classes = [1]
            
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
            classes = boxes.cls.cpu().numpy()  # 클래스 ID
            
            for i in range(len(xyxy)):
                class_id = int(classes[i])
                
                # 타겟 클래스가 아니면 스킵
                if class_id not in target_classes:
                    continue
                
                x1, y1, x2, y2 = xyxy[i]
                conf = float(confs[i])
                
                # 박스 중심 계산
                bx_cx = (x1 + x2) / 2
                bx_cy = (y1 + y2) / 2
                
                # 중심 정규화 좌표 (0.0 ~ 1.0)
                norm_cx = bx_cx / frame_width
                norm_cy = bx_cy / frame_height
                
                # Fallback 거리 제한 확인 (마지막 위치가 있고, 정후 클래스가 아닌 경우)
                if last_target_center is not None and class_id != 1:
                    last_cx, last_cy = last_target_center
                    dist = math.sqrt((norm_cx - last_cx)**2 + (norm_cy - last_cy)**2)
                    
                    if dist > config.MAX_FALLBACK_DISTANCE:
                        # 너무 멀리 있는 대체 타겟은 무시
                        continue

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
                        score=score,
                        class_id=class_id
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
                abs(dx * config.PAN_VELOCITY_MULTIPLIER) ** config.VELOCITY_EXPONENT,
                1.0
            )
            pan_val = math.copysign(speed, dx)
        
        if abs(dy) > config.TILT_DEAD_ZONE:
            speed = min(
                abs(dy * config.TILT_VELOCITY_MULTIPLIER) ** config.VELOCITY_EXPONENT,
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
        # 감지된 경우 (정상 추적)
        if detection is not None:
            h, w = frame.shape[:2]
            
            # 처음 타겟 발견 시 로그
            if not state.was_tracking:
                log(f"👁️ 타겟 발견! 추적 시작 (Conf: {detection.confidence:.2f})")
            
            # 놓침 카운트 복구
            if state.loss_count > 0:
                 log(f"👁️ 타겟 재감지! 추적 계속 (놓침 {state.loss_count}회 만에 복구)")
                 state.reset_loss_count()
            
            # 정후(Class 1)를 찾았으면 Fallback 타이머 초기화 & 마지막 위치 갱신
            if detection.class_id == 1:
                state.reset_fallback_timer()
                # 정규화된 중심 좌표 저장
                cx, cy = detection.center
                state.update_last_target_pos((cx / w, cy / h))
            
            # 대체 타겟(Class 0, 2)인 경우 시간 제한 확인
            else:
                if state.fallback_start_time == 0.0:
                    state.start_fallback_timer()
                    log(f"⚠️ 대체 타겟(Class {detection.class_id}) 추적 시작 (최대 {config.MAX_FALLBACK_DURATION}초)")
                
                if state.is_fallback_timeout(config.MAX_FALLBACK_DURATION):
                    log("🚫 대체 추적 시간 초과! -> 추적 중단")
                    ptz.stop()
                    state.unlock_target()
                    state.reset_fallback_timer()
                    return

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
                tilt=tilt_val,
                status_override=f"[FALLBACK] Class {detection.class_id}" if detection.class_id != 1 else None
            )

        # 감지 안 된 경우 (유예 상태)
        else:
            # 유예 기간 동안은 정지
            ptz.stop()
            
            # 로그는 너무 자주 찍지 않도록 간헐적으로 출력 또는 생략
            if state.loss_count % 5 == 0:
                log(f"⚠️ 타겟 놓침 유예 중... ({state.loss_count}/{config.TRACKING_PATIENCE_COUNT})")
            
            # 디버그 이미지 (유예 상태 표시)
            debug = get_debug_manager()
            debug.save_debug_image(
                frame, state,
                status_override=f"[WAIT] Patience {state.loss_count}/{config.TRACKING_PATIENCE_COUNT}"
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
        log("🚫 타겟 놓침! (유예 시간 초과) -> 카메라 정지")
        
        ptz.stop()
        state.unlock_target()
        state.reset_loss_count()  # 카운트 초기화
        
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
        state.reset_loss_count()
        
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
        state.reset_loss_count()
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
        """
        # 상황 1: 타겟 감지됨 -> 무조건 추적
        if detection is not None:
            self.tracking_handler.handle(frame, detection, state, ptz)
        
        # 상황 2: 현재 추적 중 상태 (감지는 안 됨)
        elif state.target_locked:
            state.increment_loss_count()
            
            # 유예 시간 초과 확인
            if state.is_loss_patience_exceeded(config.TRACKING_PATIENCE_COUNT):
                self.lost_handler.handle(frame, detection, state, ptz)
            else:
                 # 유예 기간 중 -> 계속 TrackingHandler (detection=None)
                self.tracking_handler.handle(frame, None, state, ptz)
        
        # 상황 3: 방금 놓침 (State 상 Locked는 아니지만 직전까지 추적함)
        # -> 이미 LostHandler를 탔거나 Patience 초과 후 LostHandler 호출됨
        # -> 여기서는 was_tracking 체크보다는 명시적 상태 위주로 감
        
        # 상황 4: 수색 모드 (소리 감지)
        elif state.is_searching:
            self.searching_handler.handle(frame, detection, state, ptz)
        
        # 상황 5: 대기 모드
        else:
            self.idle_handler.handle(frame, detection, state, ptz)
