"""
설정 파일 로더

환경 변수 지원:
- IG_USERNAME, IG_PASSWORD, IG_TOTP_SECRET
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- DISCORD_WEBHOOK_URL
- R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY
"""
import os
import re
import json
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


class ConfigValidationError(Exception):
    """설정 검증 오류"""
    pass


def _get_env(key: str, default: str = "") -> str:
    """환경 변수에서 값 가져오기 (민감정보용)"""
    return os.environ.get(key, default)


def _resolve_value(yaml_value: str, env_key: str) -> str:
    """
    YAML 값 또는 환경 변수에서 실제 값 결정
    
    YAML에서 ${ENV_VAR} 형식 지원
    """
    if not yaml_value:
        return _get_env(env_key, "")
    
    # ${ENV_VAR} 패턴 치환
    pattern = r'\$\{([^}]+)\}'
    
    def replace_env(match):
        env_name = match.group(1)
        return os.environ.get(env_name, "")
    
    resolved = re.sub(pattern, replace_env, yaml_value)
    return resolved


@dataclass
class TargetUser:
    """모니터링 대상 유저"""
    username: str
    user_id: Optional[int] = None
    alias: Optional[str] = None
    priority: str = "normal"
    enabled: bool = True
    notes: str = ""
    
    def __post_init__(self):
        # 유저네임 검증
        if not self.username:
            raise ConfigValidationError("username은 필수입니다")
        
        # 유저네임 형식 검증 (Instagram 규칙)
        if not re.match(r'^[a-zA-Z0-9._]{1,30}$', self.username):
            raise ConfigValidationError(
                f"유효하지 않은 username: {self.username}"
            )
        
        # 우선순위 검증
        if self.priority not in ('high', 'normal', 'low'):
            self.priority = 'normal'
    
    @property
    def display_name(self) -> str:
        return self.alias or self.username


@dataclass
class Config:
    """전체 설정"""
    # Instagram
    ig_username: str = ""
    ig_password: str = ""
    ig_totp_secret: str = ""
    session_file: str = "data/sessions/session.json"
    
    # Monitor
    check_interval: int = 300
    batch_size: int = 50
    batch_delay: int = 10
    targets_file: str = "config/targets.json"
    
    # Recorder
    output_dir: str = "data/recordings"
    filename_format: str = "{username}_%Y%m%d_%H%M%S"
    output_format: str = "mp4"
    max_concurrent: int = 5
    quality: str = "best"
    min_disk_space_mb: int = 500  # 최소 디스크 여유 공간
    recording_max_retries: int = 3  # 녹화 실패 시 최대 재시도 횟수
    recording_retry_delay: int = 30  # 재시도 대기 시간 (초)

    # Database
    db_path: str = "data/recorder.db"
    
    # Cloud Storage
    cloud_enabled: bool = False
    cloud_provider: str = "r2"
    r2_account_id: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = "instagram-lives"
    r2_public_url: str = ""
    delete_after_upload: bool = False
    
    # Notifications
    notify_enabled: bool = True
    notify_provider: str = "discord"  # telegram, discord
    telegram_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    notify_live_detected: bool = True
    notify_recording_started: bool = True
    notify_recording_finished: bool = True
    notify_recording_failed: bool = True
    notify_daily_summary: bool = True
    daily_summary_hour: int = 23  # 일일 요약 전송 시간 (시)
    daily_summary_minute: int = 0  # 일일 요약 전송 시간 (분)
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "data/logs/recorder.log"
    log_max_size: int = 10
    log_backup_count: int = 5
    
    # Advanced
    proxy: str = ""
    user_agent: str = ""
    max_retries: int = 3
    retry_delay: int = 30
    
    # Runtime
    targets: List[TargetUser] = field(default_factory=list)
    
    def __post_init__(self):
        """설정 검증"""
        errors = []
        
        # Instagram 계정 검증
        if not self.ig_username:
            errors.append("instagram.username은 필수입니다")
        if not self.ig_password:
            errors.append("instagram.password는 필수입니다")
        
        # 숫자 범위 검증
        if self.check_interval < 60:
            errors.append("check_interval은 최소 60초 이상이어야 합니다 (API 제한)")
        if self.check_interval > 3600:
            errors.append("check_interval은 최대 3600초(1시간) 이하여야 합니다")
        
        if self.batch_size < 1 or self.batch_size > 100:
            errors.append("batch_size는 1-100 사이여야 합니다")
        
        if self.batch_delay < 1:
            errors.append("batch_delay는 최소 1초 이상이어야 합니다")
        
        if self.max_concurrent < 1 or self.max_concurrent > 10:
            errors.append("max_concurrent는 1-10 사이여야 합니다")
        
        # 품질 검증
        valid_qualities = ('best', '1080p', '720p', '480p', '360p')
        if self.quality not in valid_qualities:
            errors.append(f"quality는 {valid_qualities} 중 하나여야 합니다")
        
        # 출력 포맷 검증
        valid_formats = ('mp4', 'mkv', 'webm', 'ts')
        if self.output_format not in valid_formats:
            errors.append(f"output_format은 {valid_formats} 중 하나여야 합니다")
        
        # 로그 레벨 검증
        valid_levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        if self.log_level.upper() not in valid_levels:
            errors.append(f"log_level은 {valid_levels} 중 하나여야 합니다")
        
        # 클라우드 저장소 검증
        if self.cloud_enabled:
            if self.cloud_provider == "r2":
                if not self.r2_account_id:
                    errors.append("R2 사용 시 r2.account_id는 필수입니다")
                if not self.r2_access_key:
                    errors.append("R2 사용 시 r2.access_key_id는 필수입니다")
                if not self.r2_secret_key:
                    errors.append("R2 사용 시 r2.secret_access_key는 필수입니다")
        
        # 알림 검증
        if self.notify_enabled:
            if self.notify_provider == "telegram":
                if not self.telegram_token or not self.telegram_chat_id:
                    self.notify_enabled = False
            elif self.notify_provider == "discord":
                if not self.discord_webhook_url:
                    self.notify_enabled = False
            else:
                # 알 수 없는 provider
                self.notify_enabled = False
        
        # 오류가 있으면 예외 발생
        if errors:
            raise ConfigValidationError(
                "설정 검증 실패:\n" + "\n".join(f"  - {e}" for e in errors)
            )
    
    def mask_sensitive(self) -> Dict[str, Any]:
        """민감정보를 마스킹한 설정 반환 (로깅용)"""
        return {
            'ig_username': self.ig_username,
            'ig_password': '***' if self.ig_password else '',
            'ig_totp_secret': '***' if self.ig_totp_secret else '',
            'telegram_token': '***' if self.telegram_token else '',
            'discord_webhook_url': '***' if self.discord_webhook_url else '',
            'r2_access_key': '***' if self.r2_access_key else '',
            'r2_secret_key': '***' if self.r2_secret_key else '',
            'check_interval': self.check_interval,
            'targets_count': len(self.targets),
        }


def load_config(config_path: str = "config/settings.yaml") -> Config:
    """
    YAML 설정 파일 로드
    
    환경 변수 우선순위:
    1. 환경 변수 (IG_USERNAME 등)
    2. YAML 파일의 ${ENV_VAR} 문법
    3. YAML 파일의 직접 값
    
    Args:
        config_path: 설정 파일 경로
    
    Returns:
        Config 객체
    
    Raises:
        FileNotFoundError: 설정 파일이 없을 때
        ConfigValidationError: 설정 검증 실패 시
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(
            f"설정 파일을 찾을 수 없습니다: {config_path}\n"
            f"config/settings.example.yaml을 복사하여 settings.yaml을 만드세요."
        )
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"YAML 파싱 오류: {e}")
    
    # 환경 변수와 YAML 값 결합
    ig_username = _resolve_value(
        data.get('instagram', {}).get('username', ''),
        'IG_USERNAME'
    )
    ig_password = _resolve_value(
        data.get('instagram', {}).get('password', ''),
        'IG_PASSWORD'
    )
    ig_totp_secret = _resolve_value(
        data.get('instagram', {}).get('totp_secret', ''),
        'IG_TOTP_SECRET'
    )
    
    telegram_token = _resolve_value(
        data.get('notifications', {}).get('telegram', {}).get('bot_token', ''),
        'TELEGRAM_BOT_TOKEN'
    )
    telegram_chat_id = _resolve_value(
        data.get('notifications', {}).get('telegram', {}).get('chat_id', ''),
        'TELEGRAM_CHAT_ID'
    )
    discord_webhook_url = _resolve_value(
        data.get('notifications', {}).get('discord', {}).get('webhook_url', ''),
        'DISCORD_WEBHOOK_URL'
    )
    
    r2_account_id = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('account_id', ''),
        'R2_ACCOUNT_ID'
    )
    r2_access_key = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('access_key_id', ''),
        'R2_ACCESS_KEY'
    )
    r2_secret_key = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('secret_access_key', ''),
        'R2_SECRET_KEY'
    )
    
    config = Config(
        # Instagram (환경 변수 지원)
        ig_username=ig_username,
        ig_password=ig_password,
        ig_totp_secret=ig_totp_secret,
        session_file=data.get('instagram', {}).get('session_file', 'data/sessions/session.json'),
        
        # Monitor
        check_interval=data.get('monitor', {}).get('check_interval', 300),
        batch_size=data.get('monitor', {}).get('batch_size', 50),
        batch_delay=data.get('monitor', {}).get('batch_delay', 10),
        targets_file=data.get('monitor', {}).get('targets_file', 'config/targets.json'),
        
        # Recorder
        output_dir=data.get('recorder', {}).get('output_dir', 'data/recordings'),
        filename_format=data.get('recorder', {}).get('filename_format', '{username}_%Y%m%d_%H%M%S'),
        output_format=data.get('recorder', {}).get('output_format', 'mp4'),
        max_concurrent=data.get('recorder', {}).get('max_concurrent', 5),
        quality=data.get('recorder', {}).get('quality', 'best'),
        min_disk_space_mb=data.get('recorder', {}).get('min_disk_space_mb', 500),
        recording_max_retries=data.get('recorder', {}).get('max_retries', 3),
        recording_retry_delay=data.get('recorder', {}).get('retry_delay', 30),

        # Database
        db_path=data.get('database', {}).get('path', 'data/recorder.db'),
        
        # Cloud Storage (환경 변수 지원)
        cloud_enabled=data.get('cloud_storage', {}).get('enabled', False),
        cloud_provider=data.get('cloud_storage', {}).get('provider', 'r2'),
        r2_account_id=r2_account_id,
        r2_access_key=r2_access_key,
        r2_secret_key=r2_secret_key,
        r2_bucket=data.get('cloud_storage', {}).get('r2', {}).get('bucket_name', 'instagram-lives'),
        r2_public_url=data.get('cloud_storage', {}).get('r2', {}).get('public_url', ''),
        delete_after_upload=data.get('cloud_storage', {}).get('r2', {}).get('delete_after_upload', False),
        
        # Notifications (환경 변수 지원)
        notify_enabled=data.get('notifications', {}).get('enabled', True),
        notify_provider=data.get('notifications', {}).get('provider', 'discord'),
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        discord_webhook_url=discord_webhook_url,
        notify_live_detected=data.get('notifications', {}).get('notify_on', {}).get('live_detected', True),
        notify_recording_started=data.get('notifications', {}).get('notify_on', {}).get('recording_started', True),
        notify_recording_finished=data.get('notifications', {}).get('notify_on', {}).get('recording_finished', True),
        notify_recording_failed=data.get('notifications', {}).get('notify_on', {}).get('recording_failed', True),
        notify_daily_summary=data.get('notifications', {}).get('notify_on', {}).get('daily_summary', True),
        daily_summary_hour=data.get('notifications', {}).get('daily_summary_time', {}).get('hour', 23),
        daily_summary_minute=data.get('notifications', {}).get('daily_summary_time', {}).get('minute', 0),
        
        # Logging
        log_level=data.get('logging', {}).get('level', 'INFO'),
        log_file=data.get('logging', {}).get('file', 'data/logs/recorder.log'),
        log_max_size=data.get('logging', {}).get('max_size_mb', 10),
        log_backup_count=data.get('logging', {}).get('backup_count', 5),
        
        # Advanced
        proxy=data.get('advanced', {}).get('proxy', ''),
        user_agent=data.get('advanced', {}).get('user_agent', ''),
        max_retries=data.get('advanced', {}).get('max_retries', 3),
        retry_delay=data.get('advanced', {}).get('retry_delay', 30),
    )
    
    # 타겟 유저 로드
    config.targets = load_targets(config.targets_file)
    
    return config


def load_targets(targets_path: str) -> List[TargetUser]:
    """
    타겟 유저 목록 로드

    지원 형식:
    1. 간단한 형식: {"targets": ["user1", "user2", "user3"]}
    2. 상세 형식: {"targets": [{"username": "user1", "alias": "별명", ...}]}
    3. 혼합 형식: {"targets": ["user1", {"username": "user2", "alias": "별명"}]}

    Args:
        targets_path: 타겟 파일 경로

    Returns:
        TargetUser 리스트

    Raises:
        ConfigValidationError: JSON 파싱 실패 시
    """
    targets_file = Path(targets_path)

    if not targets_file.exists():
        return []

    try:
        with open(targets_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigValidationError(
            f"타겟 파일 JSON 파싱 오류: {targets_path}\n"
            f"오류 위치: 라인 {e.lineno}, 컬럼 {e.colno}\n"
            f"상세: {e.msg}"
        )
    except Exception as e:
        raise ConfigValidationError(f"타겟 파일 읽기 오류: {e}")

    targets = []
    errors = []
    target_list = data.get('targets', []) if isinstance(data, dict) else data

    for i, item in enumerate(target_list):
        try:
            # 문자열인 경우 (간단한 형식)
            if isinstance(item, str):
                username = item.strip()
                if not username:
                    continue
                target = TargetUser(username=username)
            # 딕셔너리인 경우 (상세 형식)
            elif isinstance(item, dict):
                username = item.get('username', '').strip()
                if not username:
                    continue
                target = TargetUser(
                    username=username,
                    user_id=item.get('user_id'),
                    alias=item.get('alias'),
                    priority=item.get('priority', 'normal'),
                    enabled=item.get('enabled', True),
                    notes=item.get('notes', '')
                )
            else:
                continue

            if target.enabled:
                targets.append(target)

        except ConfigValidationError as e:
            errors.append(f"타겟 #{i + 1}: {e}")

    if errors:
        # 경고만 출력하고 계속 진행
        import logging
        logger = logging.getLogger("ig_recorder")
        for error in errors:
            logger.warning(error)

    return targets


def save_targets(targets: List[TargetUser], targets_path: str):
    """
    타겟 유저 목록 저장 (user_id 업데이트 등)
    """
    targets_file = Path(targets_path)
    
    # 기존 파일 로드
    if targets_file.exists():
        with open(targets_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {"targets": []}
    
    # 타겟 업데이트
    target_dict = {t.username: t for t in targets}
    
    for item in data.get('targets', []):
        username = item.get('username')
        if username in target_dict:
            item['user_id'] = target_dict[username].user_id
    
    data['last_updated'] = datetime.now().isoformat()
    
    with open(targets_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
