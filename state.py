"""
상태 관리 모듈
TrackerState dataclass로 전역 상태를 캡슐화
"""
import time
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class TrackerState:
    """정후 트래커 상태 클래스"""
    
    # --- 오디오/수색 관련 ---
    last_audio_time: float = 0.0
    is_searching: bool = False
    current_preset_idx: int = 0
    last_scan_move_time: float = 0.0
    
    # --- 추적 관련 ---
    target_locked: bool = False
    was_tracking: bool = False
    
    # --- Frigate 연동 (사람 감지) ---
    person_detected_count: int = 0  # Frigate에서 감지한 사람 수
    last_person_update_time: float = 0.0  # 마지막 person MQTT 수신 시각
    
    # --- 디버그/로깅 관련 ---
    last_debug_time: float = 0.0
    last_status_log_time: float = 0.0
    
    # --- 시스템 ---
    startup_time: float = field(default_factory=time.time)
    
    # --- 슬립 모드 (프라이버시 모드) ---
    is_sleep_mode: bool = False
    sleep_mode_start_time: float = 0.0
    last_sleep_check_time: float = 0.0
    normal_frame_count: int = 0  # 연속 정상 프레임 카운트
    
    def start_searching(self) -> None:
        """수색 모드 시작"""
        self.last_audio_time = time.time()
        self.is_searching = True
        self.last_scan_move_time = 0.0  # 즉시 프리셋 이동 트리거
    
    def stop_searching(self) -> None:
        """수색 모드 종료"""
        self.is_searching = False
    
    def lock_target(self) -> None:
        """타겟 잠금"""
        self.target_locked = True
        self.is_searching = False  # 수색 중단
        self.was_tracking = True
    
    def unlock_target(self) -> None:
        """타겟 잠금 해제"""
        self.target_locked = False
        self.was_tracking = False
    
    def lost_target(self) -> None:
        """타겟 놓침 (추적 중이었다가 사라짐)"""
        self.target_locked = False
        # was_tracking은 유지하여 "방금 놓침" 감지에 사용
    
    def next_preset(self, preset_count: int) -> int:
        """다음 프리셋 인덱스 반환 및 업데이트"""
        idx = self.current_preset_idx % preset_count
        self.current_preset_idx += 1
        self.last_scan_move_time = time.time()
        return idx
    
    def should_move_preset(self, scan_interval: float) -> bool:
        """프리셋 이동 시간이 되었는지 확인"""
        return time.time() - self.last_scan_move_time > scan_interval
    
    def is_search_timeout(self, trigger_time: float) -> bool:
        """수색 시간이 종료되었는지 확인"""
        return time.time() - self.last_audio_time > trigger_time
    
    def get_search_remaining_time(self, trigger_time: float) -> int:
        """수색 남은 시간 (초) 반환"""
        return int(trigger_time - (time.time() - self.last_audio_time))
    
    def get_scan_remaining_time(self, scan_interval: float) -> int:
        """다음 프리셋 이동까지 남은 시간 (초) 반환"""
        return int(scan_interval - (time.time() - self.last_scan_move_time))
    
    def can_save_debug(self, save_interval: float) -> bool:
        """디버그 이미지 저장 가능 여부"""
        return time.time() - self.last_debug_time >= save_interval
    
    def mark_debug_saved(self) -> None:
        """디버그 이미지 저장 시간 갱신"""
        self.last_debug_time = time.time()
    
    def can_log_status(self, log_interval: float) -> bool:
        """상태 로그 출력 가능 여부"""
        return time.time() - self.last_status_log_time >= log_interval
    
    def mark_status_logged(self) -> None:
        """상태 로그 출력 시간 갱신"""
        self.last_status_log_time = time.time()
    
    def is_startup_period(self, ignore_time: float) -> bool:
        """시작 직후 무시 구간인지 확인"""
        return time.time() - self.startup_time < ignore_time
    
    # --- 슬립 모드 메서드 ---
    def enter_sleep_mode(self) -> None:
        """슬립 모드 진입 (프라이버시 모드 감지)"""
        self.is_sleep_mode = True
        self.sleep_mode_start_time = time.time()
        self.normal_frame_count = 0
        # 다른 상태 초기화
        self.target_locked = False
        self.is_searching = False
        self.was_tracking = False
    
    def exit_sleep_mode(self) -> None:
        """슬립 모드 종료"""
        self.is_sleep_mode = False
        self.normal_frame_count = 0
    
    def can_check_sleep(self, check_interval: float) -> bool:
        """슬립 모드 체크 시간이 되었는지 확인"""
        return time.time() - self.last_sleep_check_time >= check_interval
    
    def mark_sleep_checked(self) -> None:
        """슬립 모드 체크 시간 갱신"""
        self.last_sleep_check_time = time.time()
    
    def increment_normal_count(self) -> int:
        """정상 프레임 카운트 증가 및 반환"""
        self.normal_frame_count += 1
        return self.normal_frame_count
    
    def reset_normal_count(self) -> None:
        """정상 프레임 카운트 초기화"""
        self.normal_frame_count = 0
    
    def get_sleep_duration(self) -> int:
        """슬립 모드 지속 시간 (초) 반환"""
        if not self.is_sleep_mode:
            return 0
        return int(time.time() - self.sleep_mode_start_time)
    
    # --- 사람 감지 메서드 (Frigate 연동) ---
    def update_person_count(self, count: int) -> None:
        """Frigate에서 감지한 사람 수 업데이트"""
        self.person_detected_count = count
        self.last_person_update_time = time.time()
    
    def is_person_present(self, timeout: float = 30.0) -> bool:
        """
        사람이 있는지 확인
        
        Args:
            timeout: person MQTT 미수신 시 타임아웃 (초)
            
        Returns:
            사람이 있으면 True
        """
        # person MQTT가 오래 안 온 경우 (Frigate 문제 가능성)
        # 이 경우 안전하게 사람이 있다고 가정
        if time.time() - self.last_person_update_time > timeout:
            return True
        
        return self.person_detected_count > 0
    
    def is_idle_mode(self, timeout: float = 30.0) -> bool:
        """
        대기 모드 여부 확인 (사람 없음 + 수색 모드 아님)
        
        Args:
            timeout: person MQTT 타임아웃
            
        Returns:
            대기 모드면 True
        """
        return (
            not self.is_person_present(timeout) and
            not self.is_searching and
            not self.target_locked and
            not self.is_sleep_mode
        )
