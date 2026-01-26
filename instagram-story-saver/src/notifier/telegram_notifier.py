"""
Telegram 알림 서비스

메시지 큐 기반 비동기 전송, Rate limit 처리
"""
import html
import queue
import threading
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from src.utils.logger import get_logger
from src.monitor.story_monitor import StoryItem
from src.downloader.story_downloader import DownloadTask

logger = get_logger()

# telegram 패키지 검증
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
    """Telegram 알림 발송"""
    
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        max_retries: int = 3,
        queue_size: int = 100,
        message_delay: float = 0.5
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and TELEGRAM_AVAILABLE
        self.max_retries = max_retries
        self.message_delay = message_delay
        
        if not self.enabled:
            return
        
        self._bot: Optional[Any] = None
        self._message_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        self._start_worker()
    
    def _get_bot(self):
        """Bot 인스턴스 가져오기"""
        if self._bot is None and Bot is not None:
            self._bot = Bot(token=self.bot_token)
        return self._bot
    
    def _start_worker(self):
        """메시지 전송 워커 시작"""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._message_worker,
            daemon=True,
            name="TelegramWorker"
        )
        self._worker_thread.start()
    
    def _message_worker(self):
        """메시지 큐 처리 워커"""
        while not self._stop_event.is_set():
            try:
                try:
                    text, parse_mode = self._message_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                self._send_with_retry(text, parse_mode)
                self._message_queue.task_done()
                time.sleep(self.message_delay)
                
            except Exception as e:
                logger.error(f"Telegram 워커 오류: {e}")
    
    def _send_with_retry(self, text: str, parse_mode: str = "HTML"):
        """재시도 로직이 포함된 메시지 전송"""
        bot = self._get_bot()
        if bot is None:
            return
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                )
                return
                
            except RetryAfter as e:
                wait_time = e.retry_after + 1
                logger.warning(f"Telegram rate limit, {wait_time}초 대기")
                time.sleep(wait_time)
            except TimedOut:
                logger.warning(f"Telegram 타임아웃, 재시도 {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)
            except TelegramError as e:
                last_error = e
                error_msg = str(e).lower()
                if "chat not found" in error_msg or "bot was blocked" in error_msg:
                    logger.error(f"Telegram 오류 (복구 불가): {e}")
                    return
                logger.warning(f"Telegram 오류, 재시도 {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                time.sleep(2 ** attempt)
        
        logger.error(f"Telegram 메시지 전송 실패: {last_error}")
    
    def send_message(self, text: str, parse_mode: str = "HTML"):
        """메시지 전송 (큐에 추가)"""
        if not self.enabled:
            return
        
        try:
            self._message_queue.put_nowait((text, parse_mode))
        except queue.Full:
            logger.warning("Telegram 메시지 큐가 가득 참")
    
    def send_message_sync(self, text: str, parse_mode: str = "HTML") -> bool:
        """동기 방식 메시지 전송"""
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
    
    def notify_new_story(self, story: StoryItem):
        """새 스토리 감지 알림"""
        media_type = "🎬 비디오" if story.is_video else "📷 이미지"
        remaining = story.time_remaining
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        text = (
            f"📸 <b>새 스토리!</b>\n\n"
            f"👤 <b>{self._escape_html(story.display_name)}</b>\n"
            f"📱 @{self._escape_html(story.username)}\n"
            f"📊 {media_type}\n"
            f"⏰ 업로드: {story.taken_at.strftime('%H:%M:%S')}\n"
            f"⌛ 남은 시간: {hours}시간 {minutes}분"
        )
        self.send_message(text)
    
    def notify_download_start(self, task: DownloadTask):
        """다운로드 시작 알림"""
        story = task.story
        text = (
            f"⬇️ <b>다운로드 시작</b>\n\n"
            f"👤 <b>{self._escape_html(story.display_name)}</b>\n"
            f"📱 @{self._escape_html(story.username)}\n"
            f"📂 {self._escape_html(task.output_path.name)}"
        )
        self.send_message(text)
    
    def notify_download_complete(self, task: DownloadTask):
        """다운로드 완료 알림"""
        story = task.story
        size = self._format_size(task.file_size)
        
        text = (
            f"✅ <b>다운로드 완료</b>\n\n"
            f"👤 <b>{self._escape_html(story.display_name)}</b>\n"
            f"📱 @{self._escape_html(story.username)}\n"
            f"📦 파일 크기: {size}\n"
            f"📂 {self._escape_html(task.output_path.name)}"
        )
        self.send_message(text)
    
    def notify_download_failed(self, task: DownloadTask):
        """다운로드 실패 알림"""
        story = task.story
        error_msg = self._escape_html(task.error_message[:200] if task.error_message else "알 수 없는 오류")
        
        text = (
            f"❌ <b>다운로드 실패</b>\n\n"
            f"👤 <b>{self._escape_html(story.display_name)}</b>\n"
            f"📱 @{self._escape_html(story.username)}\n"
            f"⚠️ 오류: {error_msg}"
        )
        self.send_message(text)
    
    def notify_batch_complete(self, stories: List[StoryItem]):
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
            user_lines.append(f"  • {self._escape_html(info['display_name'])}: {info['count']}개")
        
        text = (
            f"✅ <b>스토리 저장 완료</b>\n\n"
            f"📊 총 {len(stories)}개 저장됨\n\n"
            + "\n".join(user_lines)
        )
        self.send_message(text)
    
    def notify_daily_summary(self, stats: dict):
        """일일 요약 알림"""
        text = (
            f"📊 <b>일일 요약</b>\n\n"
            f"🔍 총 체크 횟수: {stats.get('total_checks', 0):,}\n"
            f"📸 발견된 스토리: {stats.get('total_new_stories', 0)}\n"
            f"✅ 다운로드 완료: {stats.get('completed_downloads', 0)}\n"
            f"❌ 다운로드 실패: {stats.get('failed_downloads', 0)}\n"
            f"📦 총 저장 용량: {stats.get('total_size_formatted', '0 B')}"
        )
        self.send_message(text)
    
    def notify_error(self, error: str):
        """에러 알림"""
        error_safe = self._escape_html(str(error)[:400] if error else "알 수 없는 오류")
        text = f"⚠️ <b>오류 발생</b>\n\n{error_safe}"
        self.send_message(text)
    
    def notify_startup(self, target_count: int):
        """시작 알림"""
        text = (
            f"🚀 <b>Instagram Story Saver 시작</b>\n\n"
            f"👥 모니터링 대상: {target_count}명\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(text)
    
    def notify_shutdown(self, stats: dict):
        """종료 알림"""
        text = (
            f"🛑 <b>Instagram Story Saver 종료</b>\n\n"
            f"📊 세션 통계:\n"
            f"  • 체크 횟수: {stats.get('total_checks', 0):,}\n"
            f"  • 발견된 스토리: {stats.get('total_new_stories', 0)}\n"
            f"  • 다운로드 완료: {stats.get('completed_downloads', 0)}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
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
        return None
    
    if not TELEGRAM_AVAILABLE:
        logger.warning("python-telegram-bot 패키지가 없습니다")
        return None
    
    if not config.telegram_token or not config.telegram_chat_id:
        logger.warning("Telegram 설정이 없습니다")
        return None
    
    return TelegramNotifier(
        bot_token=config.telegram_token,
        chat_id=config.telegram_chat_id,
        enabled=True,
        max_retries=config.telegram_max_retries,
        queue_size=config.telegram_queue_size,
        message_delay=config.telegram_message_delay
    )
