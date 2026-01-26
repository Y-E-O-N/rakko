"""
Telegram 알림 서비스

안정적인 메시지 전송을 위해 동기 방식과 큐 기반 비동기 방식을 제공합니다.
Rate limit 처리 및 재시도 로직을 포함합니다.
"""
import html
import queue
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime
from src.utils.logger import get_logger
from src.monitor.live_monitor import LiveBroadcast
from src.recorder.stream_recorder import RecordingTask

logger = get_logger()

# telegram 패키지 사전 검증
TELEGRAM_AVAILABLE = False
Bot = None
TelegramError = Exception

try:
    from telegram import Bot as TelegramBot
    from telegram.error import TelegramError as TgError, RetryAfter, TimedOut
    Bot = TelegramBot
    TelegramError = TgError
    TELEGRAM_AVAILABLE = True
except ImportError:
    logger.warning("python-telegram-bot 패키지가 필요합니다: pip install python-telegram-bot")


class TelegramNotifier:
    """
    Telegram 알림 발송
    
    특징:
    - 메시지 큐를 사용한 비동기 전송
    - Rate limit 자동 처리
    - 재시도 로직
    - HTML 이스케이프
    """
    
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        max_retries: int = 3,
        queue_size: int = 100
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and TELEGRAM_AVAILABLE
        self.max_retries = max_retries
        
        if not self.enabled:
            if not TELEGRAM_AVAILABLE:
                logger.warning("Telegram 알림 비활성화됨: python-telegram-bot 패키지 필요")
            return
        
        # 봇 인스턴스 (lazy init)
        self._bot: Optional[Any] = None
        
        # 메시지 큐
        self._message_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 워커 스레드 시작
        self._start_worker()
    
    def _get_bot(self):
        """Bot 인스턴스 가져오기 (lazy init)"""
        if self._bot is None and Bot is not None:
            self._bot = Bot(token=self.bot_token)
        return self._bot
    
    def _start_worker(self):
        """메시지 전송 워커 스레드 시작"""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._message_worker,
            daemon=True,
            name="TelegramWorker"
        )
        self._worker_thread.start()
        logger.debug("Telegram 워커 스레드 시작됨")
    
    def _message_worker(self):
        """메시지 큐 처리 워커"""
        while not self._stop_event.is_set():
            try:
                # 큐에서 메시지 가져오기 (1초 타임아웃)
                try:
                    text, parse_mode = self._message_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 메시지 전송 (재시도 포함)
                self._send_with_retry(text, parse_mode)
                
                # 큐 작업 완료 표시
                self._message_queue.task_done()
                
                # Rate limit 방지를 위한 딜레이
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Telegram 워커 오류: {e}")
    
    def _send_with_retry(self, text: str, parse_mode: str = "HTML"):
        """재시도 로직이 포함된 메시지 전송"""
        bot = self._get_bot()
        if bot is None:
            logger.error("Telegram Bot 초기화 실패")
            return
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                )
                return  # 성공
                
            except RetryAfter as e:
                # Rate limit - 지정된 시간만큼 대기
                wait_time = e.retry_after + 1
                logger.warning(f"Telegram rate limit, {wait_time}초 대기")
                time.sleep(wait_time)
                
            except TimedOut:
                # 타임아웃 - 재시도
                logger.warning(f"Telegram 타임아웃, 재시도 {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)  # 지수 백오프
                
            except TelegramError as e:
                last_error = e
                error_msg = str(e).lower()
                
                # 복구 불가능한 오류
                if "chat not found" in error_msg or "bot was blocked" in error_msg:
                    logger.error(f"Telegram 오류 (복구 불가): {e}")
                    return
                
                # 다른 오류 - 재시도
                logger.warning(f"Telegram 오류, 재시도 {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(2 ** attempt)
                
            except Exception as e:
                last_error = e
                logger.warning(f"메시지 전송 실패, 재시도 {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(2 ** attempt)
        
        logger.error(f"Telegram 메시지 전송 최종 실패: {last_error}")
    
    def send_message(self, text: str, parse_mode: str = "HTML"):
        """
        메시지 전송 (큐에 추가)
        
        Args:
            text: 메시지 텍스트
            parse_mode: 파싱 모드 (HTML, Markdown, MarkdownV2)
        """
        if not self.enabled:
            return
        
        try:
            self._message_queue.put_nowait((text, parse_mode))
        except queue.Full:
            logger.warning("Telegram 메시지 큐가 가득 참, 메시지 버림")
    
    def send_message_sync(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        동기 방식 메시지 전송 (즉시 전송, 결과 반환)
        
        Args:
            text: 메시지 텍스트
            parse_mode: 파싱 모드
        
        Returns:
            전송 성공 여부
        """
        if not self.enabled:
            return False
        
        bot = self._get_bot()
        if bot is None:
            return False
        
        try:
            bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Telegram 동기 전송 실패: {e}")
            return False
    
    @staticmethod
    def _escape_html(text: str) -> str:
        """HTML 특수문자 이스케이프"""
        if not text:
            return ""
        return html.escape(str(text))
    
    def notify_live_detected(self, broadcast: LiveBroadcast):
        """라이브 감지 알림"""
        text = (
            f"🔴 <b>라이브 감지!</b>\n\n"
            f"👤 <b>{self._escape_html(broadcast.display_name)}</b>\n"
            f"📱 @{self._escape_html(broadcast.username)}\n"
            f"📝 {self._escape_html(broadcast.title) or '(제목 없음)'}\n"
            f"👥 시청자: {broadcast.viewer_count:,}명\n"
            f"⏰ 시작: {broadcast.started_at.strftime('%H:%M:%S')}"
        )
        self.send_message(text)
    
    def notify_recording_started(self, task: RecordingTask):
        """녹화 시작 알림"""
        broadcast = task.broadcast
        text = (
            f"🎬 <b>녹화 시작</b>\n\n"
            f"👤 <b>{self._escape_html(broadcast.display_name)}</b>\n"
            f"📱 @{self._escape_html(broadcast.username)}\n"
            f"📂 {self._escape_html(task.output_path.name)}"
        )
        self.send_message(text)
    
    def notify_recording_complete(self, task: RecordingTask):
        """녹화 완료 알림"""
        broadcast = task.broadcast
        
        # 녹화 시간 계산
        duration = ""
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
        
        text = (
            f"✅ <b>녹화 완료</b>\n\n"
            f"👤 <b>{self._escape_html(broadcast.display_name)}</b>\n"
            f"📱 @{self._escape_html(broadcast.username)}\n"
            f"⏱ 녹화 시간: {duration}\n"
            f"📦 파일 크기: {size}\n"
            f"📂 {self._escape_html(task.output_path.name)}"
        )
        self.send_message(text)
    
    def notify_recording_failed(self, task: RecordingTask):
        """녹화 실패 알림"""
        broadcast = task.broadcast
        # 에러 메시지 정리 (HTML 이스케이프 + 길이 제한)
        error_msg = self._escape_html(task.error_message[:200] if task.error_message else "알 수 없는 오류")
        
        text = (
            f"❌ <b>녹화 실패</b>\n\n"
            f"👤 <b>{self._escape_html(broadcast.display_name)}</b>\n"
            f"📱 @{self._escape_html(broadcast.username)}\n"
            f"⚠️ 오류: {error_msg}"
        )
        self.send_message(text)
    
    def notify_daily_summary(self, stats: dict):
        """일일 요약 알림"""
        text = (
            f"📊 <b>일일 요약</b>\n\n"
            f"🔍 총 체크 횟수: {stats.get('total_checks', 0):,}\n"
            f"🔴 감지된 라이브: {stats.get('total_lives_found', 0)}\n"
            f"✅ 완료된 녹화: {stats.get('completed_recordings', 0)}\n"
            f"❌ 실패한 녹화: {stats.get('failed_recordings', 0)}\n"
            f"📦 총 저장 용량: {stats.get('total_size_formatted', '0 B')}"
        )
        self.send_message(text)
    
    def notify_error(self, error: str):
        """에러 알림"""
        # 에러 메시지 정리
        error_safe = self._escape_html(str(error)[:400] if error else "알 수 없는 오류")
        
        text = (
            f"⚠️ <b>오류 발생</b>\n\n"
            f"{error_safe}"
        )
        self.send_message(text)
    
    def notify_startup(self, target_count: int):
        """시작 알림"""
        text = (
            f"🚀 <b>Instagram Live Recorder 시작</b>\n\n"
            f"👥 모니터링 대상: {target_count}명\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(text)
    
    def notify_shutdown(self, stats: dict):
        """종료 알림"""
        text = (
            f"🛑 <b>Instagram Live Recorder 종료</b>\n\n"
            f"📊 세션 통계:\n"
            f"  • 체크 횟수: {stats.get('total_checks', 0):,}\n"
            f"  • 감지된 라이브: {stats.get('total_lives_found', 0)}\n"
            f"  • 완료된 녹화: {stats.get('completed_recordings', 0)}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # 종료 알림은 즉시 전송
        self.send_message_sync(text)
    
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
            logger.warning("Telegram 알림이 비활성화되어 있습니다")
            return False
        
        return self.send_message_sync("🔔 Telegram 알림 테스트 성공!")
    
    def stop(self):
        """워커 스레드 정지"""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)


def create_notifier(config) -> Optional[TelegramNotifier]:
    """설정에서 Notifier 생성"""
    if not config.notify_enabled:
        logger.info("알림이 비활성화되어 있습니다")
        return None
    
    if not TELEGRAM_AVAILABLE:
        logger.warning(
            "python-telegram-bot 패키지가 없습니다. "
            "알림을 사용하려면: pip install python-telegram-bot"
        )
        return None
    
    if not config.telegram_token or not config.telegram_chat_id:
        logger.warning("Telegram 설정이 없습니다. 알림이 비활성화됩니다.")
        return None
    
    return TelegramNotifier(
        bot_token=config.telegram_token,
        chat_id=config.telegram_chat_id,
        enabled=True
    )
