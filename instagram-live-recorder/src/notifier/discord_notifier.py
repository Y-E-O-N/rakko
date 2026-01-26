"""
Discord 알림 서비스 (Webhook 기반)

Discord Webhook을 사용하여 알림을 전송합니다.
봇 토큰 없이 Webhook URL만으로 메시지를 보낼 수 있습니다.
"""
import queue
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime
import requests
from src.utils.logger import get_logger
from src.monitor.live_monitor import LiveBroadcast
from src.recorder.stream_recorder import RecordingTask

logger = get_logger()


class DiscordNotifier:
    """
    Discord Webhook 알림 발송

    특징:
    - Webhook URL만으로 간편 설정
    - 메시지 큐를 사용한 비동기 전송
    - Rate limit 자동 처리
    - 재시도 로직
    - Embed 메시지 지원
    """

    # Discord Embed 색상
    COLOR_RED = 0xED4245      # 라이브 감지
    COLOR_GREEN = 0x57F287    # 녹화 완료
    COLOR_BLUE = 0x3498DB     # 녹화 시작
    COLOR_YELLOW = 0xFEE75C   # 경고
    COLOR_ORANGE = 0xE67E22   # 에러
    COLOR_PURPLE = 0x9B59B6   # 시작/종료

    def __init__(
        self,
        webhook_url: str,
        enabled: bool = True,
        max_retries: int = 3,
        queue_size: int = 100,
        username: str = "Instagram Live Recorder"
    ):
        self.webhook_url = webhook_url
        self.enabled = enabled and bool(webhook_url)
        self.max_retries = max_retries
        self.username = username

        if not self.enabled:
            if not webhook_url:
                logger.warning("Discord 알림 비활성화됨: Webhook URL 필요")
            return

        # 메시지 큐
        self._message_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 워커 스레드 시작
        self._start_worker()

    def _start_worker(self):
        """메시지 전송 워커 스레드 시작"""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._message_worker,
            daemon=True,
            name="DiscordWorker"
        )
        self._worker_thread.start()
        logger.debug("Discord 워커 스레드 시작됨")

    def _message_worker(self):
        """메시지 큐 처리 워커"""
        while not self._stop_event.is_set():
            try:
                # 큐에서 메시지 가져오기 (1초 타임아웃)
                try:
                    payload = self._message_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # 메시지 전송 (재시도 포함)
                self._send_with_retry(payload)

                # 큐 작업 완료 표시
                self._message_queue.task_done()

                # Rate limit 방지를 위한 딜레이
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Discord 워커 오류: {e}")

    def _send_with_retry(self, payload: Dict[str, Any]) -> bool:
        """재시도 로직이 포함된 메시지 전송"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10
                )

                # Rate limit 처리
                if response.status_code == 429:
                    retry_after = response.json().get('retry_after', 5)
                    logger.warning(f"Discord rate limit, {retry_after}초 대기")
                    time.sleep(retry_after)
                    continue

                # 성공
                if response.status_code in (200, 204):
                    return True

                # 다른 오류
                logger.warning(
                    f"Discord 전송 실패 (HTTP {response.status_code}), "
                    f"재시도 {attempt + 1}/{self.max_retries}"
                )
                time.sleep(2 ** attempt)

            except requests.exceptions.Timeout:
                logger.warning(f"Discord 타임아웃, 재시도 {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)

            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"Discord 요청 오류, 재시도 {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(2 ** attempt)

        logger.error(f"Discord 메시지 전송 최종 실패: {last_error}")
        return False

    def send_message(self, content: str = None, embeds: list = None):
        """
        메시지 전송 (큐에 추가)

        Args:
            content: 일반 텍스트 메시지
            embeds: Embed 메시지 리스트
        """
        if not self.enabled:
            return

        payload = {"username": self.username}

        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds

        try:
            self._message_queue.put_nowait(payload)
        except queue.Full:
            logger.warning("Discord 메시지 큐가 가득 참, 메시지 버림")

    def send_message_sync(self, content: str = None, embeds: list = None) -> bool:
        """
        동기 방식 메시지 전송 (즉시 전송, 결과 반환)
        """
        if not self.enabled:
            return False

        payload = {"username": self.username}

        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds

        return self._send_with_retry(payload)

    def _create_embed(
        self,
        title: str,
        description: str = None,
        color: int = None,
        fields: list = None,
        footer: str = None,
        timestamp: bool = True
    ) -> Dict[str, Any]:
        """Discord Embed 생성"""
        embed = {"title": title}

        if description:
            embed["description"] = description
        if color:
            embed["color"] = color
        if fields:
            embed["fields"] = fields
        if footer:
            embed["footer"] = {"text": footer}
        if timestamp:
            embed["timestamp"] = datetime.utcnow().isoformat()

        return embed

    def notify_live_detected(self, broadcast: LiveBroadcast):
        """라이브 감지 알림"""
        embed = self._create_embed(
            title="🔴 라이브 감지!",
            color=self.COLOR_RED,
            fields=[
                {"name": "👤 유저", "value": f"**{broadcast.display_name}**\n@{broadcast.username}", "inline": True},
                {"name": "👥 시청자", "value": f"{broadcast.viewer_count:,}명", "inline": True},
                {"name": "📝 제목", "value": broadcast.title or "(제목 없음)", "inline": False},
                {"name": "⏰ 시작 시간", "value": broadcast.started_at.strftime('%Y-%m-%d %H:%M:%S'), "inline": True},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_recording_started(self, task: RecordingTask):
        """녹화 시작 알림"""
        broadcast = task.broadcast
        embed = self._create_embed(
            title="🎬 녹화 시작",
            color=self.COLOR_BLUE,
            fields=[
                {"name": "👤 유저", "value": f"**{broadcast.display_name}**\n@{broadcast.username}", "inline": True},
                {"name": "📂 파일", "value": task.output_path.name, "inline": False},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_recording_complete(self, task: RecordingTask):
        """녹화 완료 알림"""
        broadcast = task.broadcast

        # 녹화 시간 계산
        duration = "알 수 없음"
        if task.started_at and task.ended_at:
            delta = task.ended_at - task.started_at
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                duration = f"{hours}시간 {minutes}분 {seconds}초"
            elif minutes > 0:
                duration = f"{minutes}분 {seconds}초"
            else:
                duration = f"{seconds}초"

        # 파일 크기
        size = self._format_size(task.file_size)

        embed = self._create_embed(
            title="✅ 녹화 완료",
            color=self.COLOR_GREEN,
            fields=[
                {"name": "👤 유저", "value": f"**{broadcast.display_name}**\n@{broadcast.username}", "inline": True},
                {"name": "⏱ 녹화 시간", "value": duration, "inline": True},
                {"name": "📦 파일 크기", "value": size, "inline": True},
                {"name": "📂 파일", "value": task.output_path.name, "inline": False},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_recording_failed(self, task: RecordingTask):
        """녹화 실패 알림"""
        broadcast = task.broadcast
        error_msg = task.error_message[:200] if task.error_message else "알 수 없는 오류"

        embed = self._create_embed(
            title="❌ 녹화 실패",
            color=self.COLOR_ORANGE,
            fields=[
                {"name": "👤 유저", "value": f"**{broadcast.display_name}**\n@{broadcast.username}", "inline": True},
                {"name": "⚠️ 오류", "value": error_msg, "inline": False},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_daily_summary(self, stats: dict):
        """일일 요약 알림"""
        embed = self._create_embed(
            title="📊 일일 요약",
            color=self.COLOR_PURPLE,
            fields=[
                {"name": "🔍 총 체크 횟수", "value": f"{stats.get('total_checks', 0):,}", "inline": True},
                {"name": "🔴 감지된 라이브", "value": f"{stats.get('total_lives_found', 0)}", "inline": True},
                {"name": "✅ 완료된 녹화", "value": f"{stats.get('completed_recordings', 0)}", "inline": True},
                {"name": "❌ 실패한 녹화", "value": f"{stats.get('failed_recordings', 0)}", "inline": True},
                {"name": "📦 총 저장 용량", "value": stats.get('total_size_formatted', '0 B'), "inline": True},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_error(self, error: str):
        """에러 알림"""
        error_safe = str(error)[:400] if error else "알 수 없는 오류"

        embed = self._create_embed(
            title="⚠️ 오류 발생",
            description=error_safe,
            color=self.COLOR_ORANGE
        )
        self.send_message(embeds=[embed])

    def notify_startup(self, target_count: int):
        """시작 알림"""
        embed = self._create_embed(
            title="🚀 Instagram Live Recorder 시작",
            color=self.COLOR_PURPLE,
            fields=[
                {"name": "👥 모니터링 대상", "value": f"{target_count}명", "inline": True},
                {"name": "⏰ 시작 시간", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "inline": True},
            ]
        )
        self.send_message(embeds=[embed])

    def notify_shutdown(self, stats: dict):
        """종료 알림"""
        embed = self._create_embed(
            title="🛑 Instagram Live Recorder 종료",
            color=self.COLOR_PURPLE,
            fields=[
                {"name": "🔍 체크 횟수", "value": f"{stats.get('total_checks', 0):,}", "inline": True},
                {"name": "🔴 감지된 라이브", "value": f"{stats.get('total_lives_found', 0)}", "inline": True},
                {"name": "✅ 완료된 녹화", "value": f"{stats.get('completed_recordings', 0)}", "inline": True},
            ]
        )
        # 종료 알림은 즉시 전송
        self.send_message_sync(embeds=[embed])

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

        embed = self._create_embed(
            title="🔔 Discord 알림 테스트",
            description="테스트 메시지가 정상적으로 전송되었습니다!",
            color=self.COLOR_GREEN
        )
        return self.send_message_sync(embeds=[embed])

    def stop(self):
        """워커 스레드 정지"""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)


def create_discord_notifier(config) -> Optional[DiscordNotifier]:
    """설정에서 Discord Notifier 생성"""
    if not config.notify_enabled:
        logger.info("알림이 비활성화되어 있습니다")
        return None

    if not config.discord_webhook_url:
        logger.info("Discord Webhook URL이 설정되지 않았습니다")
        return None

    return DiscordNotifier(
        webhook_url=config.discord_webhook_url,
        enabled=True
    )
