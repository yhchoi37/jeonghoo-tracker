"""
프레임 분석 모듈
프라이버시 모드 등 특수 화면 상태 감지
"""
import cv2
import numpy as np
from typing import Tuple

from config import config


class FrameAnalyzer:
    """
    프레임 분석 클래스
    
    프라이버시 모드, 연결 끊김 등 특수 상태를 감지합니다.
    """
    
    @staticmethod
    def get_brightness_stats(frame: np.ndarray) -> Tuple[float, float]:
        """
        프레임의 밝기 통계 계산
        
        Args:
            frame: BGR 프레임
            
        Returns:
            (평균 밝기, 표준편차) 튜플
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(np.mean(gray))
        std_brightness = float(np.std(gray))
        return mean_brightness, std_brightness
    
    @staticmethod
    def is_privacy_mode(frame: np.ndarray) -> bool:
        """
        프라이버시 모드 화면 감지
        
        Tapo C210 프라이버시 모드 특성:
        - 거의 검은 화면 (평균 밝기 매우 낮음)
        - 중앙에 흰 글씨가 있지만 전체적으로 분산 낮음
        
        Args:
            frame: BGR 프레임
            
        Returns:
            프라이버시 모드 여부
        """
        mean_brightness, std_brightness = FrameAnalyzer.get_brightness_stats(frame)
        
        is_dark = mean_brightness < config.PRIVACY_BRIGHTNESS_THRESHOLD
        is_uniform = std_brightness < config.PRIVACY_STD_THRESHOLD
        
        return is_dark and is_uniform
    
    @staticmethod
    def is_connection_lost(frame: np.ndarray) -> bool:
        """
        연결 끊김 화면 감지 (완전 검은 화면)
        
        Args:
            frame: BGR 프레임
            
        Returns:
            연결 끊김 여부
        """
        mean_brightness, std_brightness = FrameAnalyzer.get_brightness_stats(frame)
        
        # 완전히 검은 화면 (분산도 거의 0)
        return mean_brightness < 5 and std_brightness < 5
    
    @staticmethod
    def is_normal_frame(frame: np.ndarray) -> bool:
        """
        정상 프레임인지 확인
        
        Args:
            frame: BGR 프레임
            
        Returns:
            정상 프레임 여부
        """
        mean_brightness, _ = FrameAnalyzer.get_brightness_stats(frame)
        
        # 어느 정도 밝기가 있으면 정상
        return mean_brightness >= config.PRIVACY_BRIGHTNESS_THRESHOLD
