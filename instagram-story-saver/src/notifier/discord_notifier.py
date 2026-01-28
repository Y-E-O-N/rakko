"""
Discord 알림 서비스

Webhook 기반 비동기 전송, Rate limit 처리
"""
import html
import queue
import threading
import time
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class DiscordEmbed:
    """Discord Embed 메시지"""
    title: str = ""
    description: str = ""
    color: int = 0x5865F2  # Discord Blurple
    fields: List[Dict[str, Any]] = None
    footer: str = ""
    timestamp: bool = False

    def __post_init__(self):
        if self.fields is None:
            self.fields = []

    def to_dict(self) -> Dict[str, Any]:
        """Discord API 형식으로 변환"""
        embed = {}

        if self.title:
            embed['title'] = self.title
        if self.description:
            embed['description'] = self.description
        if self.color:
            embed['color'] = self.color
        if self.fields:
            embed['fields'] = self.fields
        if self.footer:
            embed['footer'] = {'text': self.footer}
        if self.timestamp:
            embed['timestamp'] = datetime.utcnow().isoformat()

        return embed


class DiscordNotifier:
    """Discord 알림 발송"""

    # 색상 상수
    COLOR_RED = 0xED4245      # 오류/실패
    COLOR_GREEN = 0x57F287    # 성공/완료
    COLOR_YELLOW = 0xFEE75C   # 경고
    COLOR_BLUE = 0x5865F2     # 정보
    COLOR_ORANGE = 0xE67E22   # 새 스토리 감지
    COLOR_PURPLE = 0x9B59B6   # 시작/종료

    def __init__(
        self,
        webhook_url: str,
        enabled: bool = True,
        max_retries: int = 3,
        queue_size: int = 100,
        message_delay: float = 0.5,
        request_timeout: int = 10,
        public_url: str = ""
    ):
        self.webhook_url = webhook_url
        self.enabled = enabled and bool(webhook_url)
        self.public_url = public_url.rstrip('/') if public_url else ""
        self.max_retries = max_retries
        self.message_delay = message_delay
        self.request_timeout = request_timeout

        if not self.enabled:
            return

        self._message_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # requests 세션 (연결 재사용)
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Instagram-Story-Saver/1.0'
        })

        self._start_worker()

    def _start_worker(self):
        """메시지 전송 워커 시작"""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._message_worker,
            daemon=True,
            name="DiscordWorker"
        )
        self._worker_thread.start()

    def _message_worker(self):
        """메시지 큐 처리 워커"""
        while not self._stop_event.is_set():
            try:
                try:
                    payload = self._message_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                self._send_with_retry(payload)
                self._message_queue.task_done()
                time.sleep(self.message_delay)

            except Exception as e:
                logger.error(f"Discord 워커 오류: {e}")

    def _send_with_retry(self, payload: Dict[str, Any]) -> bool:
        """재시도 로직이 포함된 메시지 전송"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self._session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.request_timeout
                )

                # Rate limit 처리
                if response.status_code == 429:
                    retry_after = response.json().get('retry_after', 5)
                    logger.warning(f"Discord rate limit, {retry_after}초 대기")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return True

            except requests.exceptions.Timeout:
                logger.warning(f"Discord 타임아웃, 재시도 {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"Discord 오류, 재시도 {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                time.sleep(2 ** attempt)

        logger.error(f"Discord 메시지 전송 실패: {last_error}")
        return False

    def send_embed(self, embed: DiscordEmbed, content: str = None):
        """Embed 메시지 전송 (큐에 추가)"""
        if not self.enabled:
            return

        payload = {'embeds': [embed.to_dict()]}
        if content:
            payload['content'] = content

        try:
            self._message_queue.put_nowait(payload)
        except queue.Full:
            logger.warning("Discord 메시지 큐가 가득 참")

    def send_message(self, content: str):
        """일반 텍스트 메시지 전송"""
        if not self.enabled:
            return

        try:
            self._message_queue.put_nowait({'content': content})
        except queue.Full:
            logger.warning("Discord 메시지 큐가 가득 참")

    def send_embed_sync(self, embed: DiscordEmbed, content: str = None) -> bool:
        """동기 방식 Embed 전송"""
        if not self.enabled:
            return False

        payload = {'embeds': [embed.to_dict()]}
        if content:
            payload['content'] = content

        return self._send_with_retry(payload)

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Discord markdown 특수문자 이스케이프"""
        if not text:
            return ""
        # Discord markdown 특수문자
        chars = ['*', '_', '`', '~', '|', '>', '#']
        result = str(text)
        for char in chars:
            result = result.replace(char, '\\' + char)
        return result

    def notify_new_story(self, story):
        """새 스토리 감지 알림"""
        media_type = "비디오" if story.is_video else "이미지"
        remaining = story.time_remaining
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)

        embed = DiscordEmbed(
            title="새 스토리 감지",
            description=f"**{self._escape_markdown(story.display_name)}** (@{story.username})",
            color=self.COLOR_ORANGE,
            fields=[
                {'name': '미디어 타입', 'value': media_type, 'inline': True},
                {'name': '업로드 시간', 'value': story.taken_at.strftime('%H:%M:%S'), 'inline': True},
                {'name': '남은 시간', 'value': f'{hours}시간 {minutes}분', 'inline': True},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_download_start(self, task):
        """다운로드 시작 알림"""
        story = task.story
        embed = DiscordEmbed(
            title="다운로드 시작",
            description=f"**{self._escape_markdown(story.display_name)}** (@{story.username})",
            color=self.COLOR_BLUE,
            fields=[
                {'name': '파일', 'value': task.output_path.name, 'inline': False},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_download_complete(self, task, cloud_path: str = None):
        """다운로드 완료 알림"""
        story = task.story
        size = self._format_size(task.file_size)

        fields = [
            {'name': '파일 크기', 'value': size, 'inline': True},
            {'name': '파일명', 'value': task.output_path.name, 'inline': False},
        ]

        # 클라우드 다운로드 링크 추가
        if self.public_url and cloud_path:
            download_url = f"{self.public_url}/{cloud_path}"
            fields.append({'name': '다운로드', 'value': f'[링크]({download_url})', 'inline': False})

        embed = DiscordEmbed(
            title="다운로드 완료",
            description=f"**{self._escape_markdown(story.display_name)}** (@{story.username})",
            color=self.COLOR_GREEN,
            fields=fields,
            timestamp=True
        )
        self.send_embed(embed)

    def notify_download_failed(self, task):
        """다운로드 실패 알림"""
        story = task.story
        error_msg = task.error_message[:200] if task.error_message else "알 수 없는 오류"

        embed = DiscordEmbed(
            title="다운로드 실패",
            description=f"**{self._escape_markdown(story.display_name)}** (@{story.username})",
            color=self.COLOR_RED,
            fields=[
                {'name': '오류', 'value': error_msg, 'inline': False},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_batch_complete(self, stories: list):
        """배치 다운로드 완료 알림"""
        if not stories:
            return

        # 유저별 그룹화
        by_user = {}
        for story in stories:
            if story.username not in by_user:
                by_user[story.username] = {'display_name': story.display_name, 'count': 0}
            by_user[story.username]['count'] += 1

        user_lines = []
        for username, info in by_user.items():
            user_lines.append(f"• {info['display_name']}: {info['count']}개")

        embed = DiscordEmbed(
            title="스토리 저장 완료",
            description=f"총 **{len(stories)}개** 저장됨",
            color=self.COLOR_GREEN,
            fields=[
                {'name': '유저별 현황', 'value': '\n'.join(user_lines) or '없음', 'inline': False},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_daily_summary(self, stats: dict):
        """일일 요약 알림"""
        embed = DiscordEmbed(
            title="일일 요약",
            description=datetime.now().strftime('%Y년 %m월 %d일'),
            color=self.COLOR_BLUE,
            fields=[
                {'name': '체크 횟수', 'value': f"{stats.get('total_checks', 0):,}회", 'inline': True},
                {'name': '발견된 스토리', 'value': f"{stats.get('total_new_stories', 0)}개", 'inline': True},
                {'name': '다운로드 완료', 'value': f"{stats.get('completed_downloads', 0)}개", 'inline': True},
                {'name': '다운로드 실패', 'value': f"{stats.get('failed_downloads', 0)}개", 'inline': True},
                {'name': '총 저장 용량', 'value': stats.get('total_size_formatted', '0 B'), 'inline': True},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_error(self, error: str):
        """에러 알림"""
        error_safe = str(error)[:400] if error else "알 수 없는 오류"

        embed = DiscordEmbed(
            title="오류 발생",
            description=error_safe,
            color=self.COLOR_RED,
            timestamp=True
        )
        self.send_embed(embed)

    def notify_startup(self, target_count: int):
        """시작 알림"""
        embed = DiscordEmbed(
            title="Instagram Story Saver 시작",
            color=self.COLOR_PURPLE,
            fields=[
                {'name': '모니터링 대상', 'value': f'{target_count}명', 'inline': True},
                {'name': '시작 시간', 'value': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'inline': True},
            ],
            timestamp=True
        )
        self.send_embed(embed)

    def notify_shutdown(self, stats: dict):
        """종료 알림"""
        embed = DiscordEmbed(
            title="Instagram Story Saver 종료",
            color=self.COLOR_PURPLE,
            fields=[
                {'name': '체크 횟수', 'value': f"{stats.get('total_checks', 0):,}", 'inline': True},
                {'name': '발견된 스토리', 'value': f"{stats.get('total_new_stories', 0)}", 'inline': True},
                {'name': '다운로드 완료', 'value': f"{stats.get('completed_downloads', 0)}", 'inline': True},
            ],
            footer=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            timestamp=True
        )
        self.send_embed_sync(embed)

    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형식으로 변환"""
        if size_bytes <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def test_connection(self) -> bool:
        """연결 테스트"""
        if not self.enabled:
            logger.warning("Discord 알림이 비활성화되어 있습니다")
            return False

        embed = DiscordEmbed(
            title="연결 테스트",
            description="Discord 알림 테스트 성공!",
            color=self.COLOR_GREEN,
            timestamp=True
        )
        return self.send_embed_sync(embed)

    def stop(self):
        """워커 스레드 정지"""
        if not self.enabled:
            return

        if hasattr(self, '_stop_event'):
            self._stop_event.set()
        if hasattr(self, '_worker_thread') and self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if hasattr(self, '_session') and self._session:
            self._session.close()


def create_discord_notifier(config) -> Optional[DiscordNotifier]:
    """설정에서 Discord Notifier 생성"""
    if not config.notify_enabled:
        return None

    if config.notify_provider != 'discord':
        return None

    webhook_url = config.discord_webhook_url
    if not webhook_url:
        logger.warning("Discord Webhook URL이 설정되지 않았습니다")
        return None

    # R2 public URL 가져오기
    public_url = getattr(config, 'r2_public_url', '') or ''

    return DiscordNotifier(
        webhook_url=webhook_url,
        enabled=True,
        max_retries=config.discord_max_retries,
        queue_size=config.discord_queue_size,
        message_delay=config.discord_message_delay,
        request_timeout=config.discord_request_timeout,
        public_url=public_url
    )
