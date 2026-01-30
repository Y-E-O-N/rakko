"""
설정 파일 로더

환경 변수 지원:
- IG_USERNAME, IG_PASSWORD, IG_TOTP_SECRET
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
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
    """환경 변수에서 값 가져오기"""
    return os.environ.get(key, default)


def _resolve_value(yaml_value: str, env_key: str) -> str:
    """YAML 값 또는 환경 변수에서 실제 값 결정"""
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
        if not self.username:
            raise ConfigValidationError("username은 필수입니다")
        
        # Instagram 유저네임 규칙 검증
        if not re.match(r'^[a-zA-Z0-9._]{1,30}$', self.username):
            raise ConfigValidationError(f"유효하지 않은 username: {self.username}")
        
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
    
    # Instagram API 설정
    api_delay_min: float = 1.0  # API 요청 간 최소 딜레이 (초)
    api_delay_max: float = 3.0  # API 요청 간 최대 딜레이 (초)
    api_cooldown_seconds: int = 300  # API 제한 시 쿨다운 (초)
    api_max_failures: int = 3  # 연속 실패 허용 횟수
    user_id_resolve_delay: float = 2.0  # 유저 ID 조회 간 딜레이 (초)
    user_id_resolve_batch: int = 10  # 유저 ID 조회 배치 크기
    
    # Monitor
    check_interval_min: int = 18000  # 5시간 (초)
    check_interval_max: int = 21600  # 6시간 (초)
    batch_size: int = 20
    batch_delay: int = 5
    targets_file: str = "config/targets.json"
    history_file: str = "data/download_history.json"
    story_expire_hours: int = 24  # 스토리 만료 시간
    
    # Downloader
    output_dir: str = "data/stories"
    filename_format: str = "{username}_%Y%m%d_%H%M%S_{story_id}"
    max_concurrent: int = 3
    download_videos: bool = True
    download_images: bool = True
    save_thumbnails: bool = False
    min_disk_space_mb: int = 500
    video_quality: str = "highest"  # highest, lowest, 720p, 480p, 360p
    image_quality: str = "highest"  # highest, lowest
    download_timeout_connect: int = 10  # 연결 타임아웃 (초)
    download_timeout_read: int = 60  # 읽기 타임아웃 (초)
    download_chunk_size: int = 8192  # 다운로드 청크 크기 (바이트)
    download_max_retries: int = 3  # 다운로드 재시도 횟수
    download_disk_check_interval_mb: int = 10  # 디스크 체크 간격 (MB)
    download_queue_check_interval: float = 1.0  # 대기열 체크 간격 (초)
    max_completed_history: int = 1000  # 완료 기록 최대 보관 수
    download_user_agent: str = ""  # 다운로드 요청 User-Agent (빈 값이면 기본값 사용)

    # Cloud Storage
    cloud_enabled: bool = False
    cloud_provider: str = "r2"
    r2_account_id: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = "instagram-stories"
    r2_public_url: str = ""
    delete_after_upload: bool = False
    cloud_multipart_threshold_mb: int = 50  # 멀티파트 업로드 임계값 (MB)
    cloud_multipart_chunksize_mb: int = 25  # 멀티파트 청크 크기 (MB)
    cloud_max_concurrency: int = 5  # 업로드 동시성
    cloud_connect_timeout: int = 30  # 클라우드 연결 타임아웃 (초)
    cloud_read_timeout: int = 60  # 클라우드 읽기 타임아웃 (초)
    cloud_max_retries: int = 5  # 클라우드 업로드 재시도 횟수
    
    # Notifications
    notify_enabled: bool = True
    notify_provider: str = "discord"  # "discord" or "telegram"
    # Discord 설정
    discord_webhook_url: str = ""
    discord_queue_size: int = 100
    discord_max_retries: int = 3
    discord_message_delay: float = 0.5
    discord_request_timeout: int = 10  # Discord 요청 타임아웃 (초)
    # Telegram 설정
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_queue_size: int = 100  # 메시지 큐 크기
    telegram_max_retries: int = 3  # 메시지 재시도 횟수
    telegram_message_delay: float = 0.5  # 메시지 간 딜레이 (초)
    # 알림 종류
    notify_story_detected: bool = True
    notify_download_complete: bool = True
    notify_download_failed: bool = True
    notify_daily_summary: bool = True
    notify_errors: bool = True

    # Database
    db_path: str = "data/story_saver.db"

    # Daily Summary
    daily_summary_hour: int = 23
    daily_summary_minute: int = 0
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "data/logs/story_saver.log"
    log_max_size: int = 10
    log_backup_count: int = 5
    
    # Advanced
    proxy: str = ""
    user_agent: str = ""
    max_retries: int = 3
    retry_delay: int = 30
    duplicate_check_hours: int = 24
    
    # Runtime
    targets: List[TargetUser] = field(default_factory=list)
    
    def __post_init__(self):
        """설정 검증"""
        errors = []
        
        if not self.ig_username:
            errors.append("instagram.username은 필수입니다")
        if not self.ig_password:
            errors.append("instagram.password는 필수입니다")
        
        # 숫자 범위 검증
        if self.check_interval_min < 300:  # 최소 5분
            errors.append("check_interval_min은 최소 300초(5분) 이상이어야 합니다")
        if self.check_interval_max < self.check_interval_min:
            errors.append("check_interval_max는 check_interval_min보다 커야 합니다")
        
        if self.batch_size < 1 or self.batch_size > 50:
            errors.append("batch_size는 1-50 사이여야 합니다")
        
        if self.max_concurrent < 1 or self.max_concurrent > 10:
            errors.append("max_concurrent는 1-10 사이여야 합니다")
        
        # 로그 레벨 검증
        valid_levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        if self.log_level.upper() not in valid_levels:
            errors.append(f"log_level은 {valid_levels} 중 하나여야 합니다")
        
        # 클라우드 저장소 검증
        if self.cloud_enabled and self.cloud_provider == "r2":
            if not self.r2_account_id:
                errors.append("R2 사용 시 r2.account_id는 필수입니다")
            if not self.r2_access_key:
                errors.append("R2 사용 시 r2.access_key_id는 필수입니다")
            if not self.r2_secret_key:
                errors.append("R2 사용 시 r2.secret_access_key는 필수입니다")
        
        # 알림 검증
        if self.notify_enabled:
            if self.notify_provider == 'discord':
                if not self.discord_webhook_url:
                    self.notify_enabled = False
            elif self.notify_provider == 'telegram':
                if not self.telegram_token or not self.telegram_chat_id:
                    self.notify_enabled = False
        
        if errors:
            raise ConfigValidationError(
                "설정 검증 실패:\n" + "\n".join(f"  - {e}" for e in errors)
            )
    
    def mask_sensitive(self) -> Dict[str, Any]:
        """민감정보를 마스킹한 설정 반환"""
        return {
            'ig_username': self.ig_username,
            'ig_password': '***' if self.ig_password else '',
            'telegram_token': '***' if self.telegram_token else '',
            'discord_webhook_url': '***' if self.discord_webhook_url else '',
            'r2_access_key': '***' if self.r2_access_key else '',
            'r2_secret_key': '***' if self.r2_secret_key else '',
            'check_interval_min': self.check_interval_min,
            'check_interval_max': self.check_interval_max,
            'targets_count': len(self.targets),
        }


def load_config(config_path: str = "config/settings.yaml") -> Config:
    """YAML 설정 파일 로드"""
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
        data.get('instagram', {}).get('username', ''), 'IG_USERNAME'
    )
    ig_password = _resolve_value(
        data.get('instagram', {}).get('password', ''), 'IG_PASSWORD'
    )
    ig_totp_secret = _resolve_value(
        data.get('instagram', {}).get('totp_secret', ''), 'IG_TOTP_SECRET'
    )
    
    # Discord
    discord_webhook_url = _resolve_value(
        data.get('notifications', {}).get('discord', {}).get('webhook_url', ''),
        'DISCORD_WEBHOOK_URL'
    )

    # Telegram
    telegram_token = _resolve_value(
        data.get('notifications', {}).get('telegram', {}).get('bot_token', ''),
        'TELEGRAM_BOT_TOKEN'
    )
    telegram_chat_id = _resolve_value(
        data.get('notifications', {}).get('telegram', {}).get('chat_id', ''),
        'TELEGRAM_CHAT_ID'
    )
    
    r2_account_id = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('account_id', ''),
        'R2_ACCOUNT_ID'
    )
    r2_access_key = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('access_key_id', ''),
        'R2_ACCESS_KEY_ID'
    )
    r2_secret_key = _resolve_value(
        data.get('cloud_storage', {}).get('r2', {}).get('secret_access_key', ''),
        'R2_SECRET_ACCESS_KEY'
    )
    
    config = Config(
        # Instagram
        ig_username=ig_username,
        ig_password=ig_password,
        ig_totp_secret=ig_totp_secret,
        session_file=data.get('instagram', {}).get('session_file', 'data/sessions/session.json'),
        
        # Instagram API 설정
        api_delay_min=data.get('instagram', {}).get('api_delay_min', 1.0),
        api_delay_max=data.get('instagram', {}).get('api_delay_max', 3.0),
        api_cooldown_seconds=data.get('instagram', {}).get('api_cooldown_seconds', 300),
        api_max_failures=data.get('instagram', {}).get('api_max_failures', 3),
        user_id_resolve_delay=data.get('instagram', {}).get('user_id_resolve_delay', 2.0),
        user_id_resolve_batch=data.get('instagram', {}).get('user_id_resolve_batch', 10),
        
        # Monitor
        check_interval_min=data.get('monitor', {}).get('check_interval_min', 18000),
        check_interval_max=data.get('monitor', {}).get('check_interval_max', 21600),
        batch_size=data.get('monitor', {}).get('batch_size', 20),
        batch_delay=data.get('monitor', {}).get('batch_delay', 5),
        targets_file=data.get('monitor', {}).get('targets_file', 'config/targets.json'),
        history_file=data.get('monitor', {}).get('history_file', 'data/download_history.json'),
        story_expire_hours=data.get('monitor', {}).get('story_expire_hours', 24),
        
        # Downloader
        output_dir=data.get('downloader', {}).get('output_dir', 'data/stories'),
        filename_format=data.get('downloader', {}).get('filename_format', '{username}_%Y%m%d_%H%M%S_{story_id}'),
        max_concurrent=data.get('downloader', {}).get('max_concurrent', 3),
        download_videos=data.get('downloader', {}).get('download_videos', True),
        download_images=data.get('downloader', {}).get('download_images', True),
        save_thumbnails=data.get('downloader', {}).get('save_thumbnails', False),
        min_disk_space_mb=data.get('downloader', {}).get('min_disk_space_mb', 500),
        video_quality=data.get('downloader', {}).get('video_quality', 'highest'),
        image_quality=data.get('downloader', {}).get('image_quality', 'highest'),
        download_timeout_connect=data.get('downloader', {}).get('timeout_connect', 10),
        download_timeout_read=data.get('downloader', {}).get('timeout_read', 60),
        download_chunk_size=data.get('downloader', {}).get('chunk_size', 8192),
        download_max_retries=data.get('downloader', {}).get('max_retries', 3),
        download_disk_check_interval_mb=data.get('downloader', {}).get('disk_check_interval_mb', 10),
        download_queue_check_interval=data.get('downloader', {}).get('queue_check_interval', 1.0),
        max_completed_history=data.get('downloader', {}).get('max_completed_history', 1000),
        download_user_agent=data.get('downloader', {}).get('user_agent', ''),

        # Cloud Storage
        cloud_enabled=data.get('cloud_storage', {}).get('enabled', False),
        cloud_provider=data.get('cloud_storage', {}).get('provider', 'r2'),
        r2_account_id=r2_account_id,
        r2_access_key=r2_access_key,
        r2_secret_key=r2_secret_key,
        r2_bucket=data.get('cloud_storage', {}).get('r2', {}).get('bucket_name', 'instagram-stories'),
        r2_public_url=data.get('cloud_storage', {}).get('r2', {}).get('public_url', ''),
        delete_after_upload=data.get('cloud_storage', {}).get('delete_after_upload', False),
        cloud_multipart_threshold_mb=data.get('cloud_storage', {}).get('multipart_threshold_mb', 50),
        cloud_multipart_chunksize_mb=data.get('cloud_storage', {}).get('multipart_chunksize_mb', 25),
        cloud_max_concurrency=data.get('cloud_storage', {}).get('max_concurrency', 5),
        cloud_connect_timeout=data.get('cloud_storage', {}).get('connect_timeout', 30),
        cloud_read_timeout=data.get('cloud_storage', {}).get('read_timeout', 60),
        cloud_max_retries=data.get('cloud_storage', {}).get('max_retries', 5),
        
        # Notifications
        notify_enabled=data.get('notifications', {}).get('enabled', True),
        notify_provider=data.get('notifications', {}).get('provider', 'discord'),
        # Discord
        discord_webhook_url=discord_webhook_url,
        discord_queue_size=data.get('notifications', {}).get('discord', {}).get('queue_size', 100),
        discord_max_retries=data.get('notifications', {}).get('discord', {}).get('max_retries', 3),
        discord_message_delay=data.get('notifications', {}).get('discord', {}).get('message_delay', 0.5),
        discord_request_timeout=data.get('notifications', {}).get('discord', {}).get('request_timeout', 10),
        # Telegram
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        telegram_queue_size=data.get('notifications', {}).get('telegram', {}).get('queue_size', 100),
        telegram_max_retries=data.get('notifications', {}).get('telegram', {}).get('max_retries', 3),
        telegram_message_delay=data.get('notifications', {}).get('telegram', {}).get('message_delay', 0.5),
        # 알림 종류
        notify_story_detected=data.get('notifications', {}).get('notify_on', {}).get('story_detected', True),
        notify_download_complete=data.get('notifications', {}).get('notify_on', {}).get('download_complete', True),
        notify_download_failed=data.get('notifications', {}).get('notify_on', {}).get('download_failed', True),
        notify_daily_summary=data.get('notifications', {}).get('notify_on', {}).get('daily_summary', True),
        notify_errors=data.get('notifications', {}).get('notify_on', {}).get('errors', True),

        # Database
        db_path=data.get('database', {}).get('path', 'data/story_saver.db'),

        # Daily Summary
        daily_summary_hour=data.get('notifications', {}).get('daily_summary_hour', 23),
        daily_summary_minute=data.get('notifications', {}).get('daily_summary_minute', 0),
        
        # Logging
        log_level=data.get('logging', {}).get('level', 'INFO'),
        log_file=data.get('logging', {}).get('file', 'data/logs/story_saver.log'),
        log_max_size=data.get('logging', {}).get('max_size_mb', 10),
        log_backup_count=data.get('logging', {}).get('backup_count', 5),
        
        # Advanced
        proxy=data.get('advanced', {}).get('proxy', ''),
        user_agent=data.get('advanced', {}).get('user_agent', ''),
        max_retries=data.get('advanced', {}).get('max_retries', 3),
        retry_delay=data.get('advanced', {}).get('retry_delay', 30),
        duplicate_check_hours=data.get('advanced', {}).get('duplicate_check_hours', 24),
    )
    
    config.targets = load_targets(config.targets_file)
    
    return config


def load_targets(targets_path: str) -> List[TargetUser]:
    """
    타겟 유저 목록 로드

    지원 형식:
    1. 간단한 형식: {"targets": ["user1", "user2", "user3"]}
    2. 상세 형식: {"targets": [{"username": "user1", "alias": "별명", ...}]}
    3. 혼합 형식: {"targets": ["user1", {"username": "user2", "alias": "별명"}]}
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
            f"오류 위치: 라인 {e.lineno}, 컬럼 {e.colno}"
        )

    targets = []
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
            import logging
            logging.getLogger("story_saver").warning(f"타겟 #{i + 1}: {e}")

    return targets


def save_targets(targets: List[TargetUser], targets_path: str):
    """타겟 유저 목록 저장"""
    import logging
    targets_file = Path(targets_path)
    
    if targets_file.exists():
        try:
            with open(targets_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger = logging.getLogger("story_saver")
            logger.warning(f"기존 타겟 파일 읽기 실패, 새로 생성: {e}")
            data = {"targets": []}
    else:
        data = {"targets": []}
    
    target_dict = {t.username: t for t in targets}
    
    for item in data.get('targets', []):
        username = item.get('username')
        if username in target_dict:
            item['user_id'] = target_dict[username].user_id
    
    data['last_updated'] = datetime.now().isoformat()
    
    # 원자적 쓰기 (임시 파일 사용)
    temp_file = targets_file.with_suffix('.tmp')
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_file.rename(targets_file)
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        raise
