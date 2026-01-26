"""
로깅 설정 및 유틸리티
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from rich.logging import RichHandler
from rich.console import Console

console = Console()


def setup_logger(
    name: str = "story_saver",
    level: str = "INFO",
    log_file: str = None,
    max_size_mb: int = 10,
    backup_count: int = 5
) -> logging.Logger:
    """
    로거 설정
    
    Args:
        name: 로거 이름
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_file: 로그 파일 경로
        max_size_mb: 최대 파일 크기 (MB)
        backup_count: 백업 파일 수
    
    Returns:
        설정된 로거
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # 이미 핸들러가 있으면 제거
    logger.handlers.clear()
    
    # 콘솔 핸들러 (Rich 사용)
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True
    )
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # 파일 핸들러
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "story_saver") -> logging.Logger:
    """기존 로거 가져오기"""
    return logging.getLogger(name)
