"""
Instagram 스토리 다운로더

원본 품질로 스토리를 다운로드합니다.
"""
import os
import re
import time
import shutil
import requests
import threading
from pathlib import Path
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from src.utils.logger import get_logger
from src.monitor.story_monitor import StoryItem, DownloadHistory

logger = get_logger()


class DownloadError(Exception):
    """다운로드 관련 오류"""
    pass


class DiskSpaceError(DownloadError):
    """디스크 공간 부족"""
    pass


class SecurityError(DownloadError):
    """보안 관련 오류"""
    pass


@dataclass
class DownloadTask:
    """다운로드 작업"""
    story: StoryItem
    output_path: Path
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = "pending"  # pending, downloading, completed, failed
    error_message: str = ""
    file_size: int = 0


def validate_media_url(url: str) -> bool:
    """미디어 URL 보안 검증"""
    if not url:
        raise SecurityError("URL이 비어있습니다")
    
    try:
        parsed = urlparse(url)
        
        if parsed.scheme != 'https':
            raise SecurityError(f"HTTPS만 허용됩니다: {parsed.scheme}")
        
        # Instagram 관련 CDN 도메인만 허용
        allowed_domains = (
            'instagram.com',
            'cdninstagram.com',
            'fbcdn.net',
            'akamaized.net',
            'akamaihd.net',
        )
        
        domain = parsed.netloc.lower()
        if not any(domain.endswith(allowed) for allowed in allowed_domains):
            raise SecurityError(f"허용되지 않은 도메인: {domain}")
        
        return True
        
    except SecurityError:
        raise
    except Exception as e:
        raise SecurityError(f"URL 파싱 오류: {e}")


def check_disk_space(path: Path, min_space_mb: int = 500) -> bool:
    """디스크 여유 공간 확인"""
    try:
        check_path = path if path.exists() else path.parent
        while not check_path.exists() and check_path != check_path.parent:
            check_path = check_path.parent
        
        usage = shutil.disk_usage(check_path)
        free_mb = usage.free / (1024 * 1024)
        
        if free_mb < min_space_mb:
            logger.warning(f"디스크 여유 공간 부족: {free_mb:.0f}MB / 필요: {min_space_mb}MB")
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"디스크 공간 확인 실패: {e}")
        return True


class StoryDownloader:
    """스토리 다운로더"""
    
    # 기본 User-Agent
    DEFAULT_USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )

    def __init__(
        self,
        output_dir: str = "data/stories",
        filename_format: str = "{username}_%Y%m%d_%H%M%S_{story_id}",
        max_concurrent: int = 3,
        min_disk_space_mb: int = 500,
        save_thumbnails: bool = False,
        history: Optional[DownloadHistory] = None,
        timeout_connect: int = 10,
        timeout_read: int = 60,
        chunk_size: int = 8192,
        max_retries: int = 3,
        disk_check_interval_mb: int = 10,
        queue_check_interval: float = 1.0,
        max_completed_history: int = 1000,
        user_agent: str = ""
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.filename_format = filename_format
        self.max_concurrent = max_concurrent
        self.min_disk_space_mb = min_disk_space_mb
        self.save_thumbnails = save_thumbnails
        self.history = history
        self.timeout_connect = timeout_connect
        self.timeout_read = timeout_read
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.disk_check_interval_mb = disk_check_interval_mb
        self.queue_check_interval = queue_check_interval
        self.max_completed_history = max_completed_history
        
        self.active_downloads: Dict[str, DownloadTask] = {}
        self.completed_downloads: List[DownloadTask] = []
        self._pending_queue: List[StoryItem] = []  # 대기열
        self._queue_lock = threading.Lock()  # 대기열 전용 락
        
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()
        
        # 대기열 처리 스레드
        self._queue_worker_running = True
        self._queue_worker = threading.Thread(
            target=self._process_queue,
            daemon=True,
            name="DownloadQueueWorker"
        )
        self._queue_worker.start()
        
        self._callbacks: Dict[str, List[Callable]] = {
            'on_download_start': [],
            'on_download_complete': [],
            'on_download_failed': []
        }
        
        # requests 세션 (연결 재사용)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': user_agent if user_agent else self.DEFAULT_USER_AGENT,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def on(self, event: str, callback: Callable):
        """이벤트 콜백 등록"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _emit(self, event: str, *args, **kwargs):
        """이벤트 발생"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"콜백 실행 에러 ({event}): {e}")
    
    def download(self, story: StoryItem) -> Optional[DownloadTask]:
        """스토리 다운로드 시작"""
        story_id = story.story_id
        
        # 이미 다운로드 중인지 확인
        with self._lock:
            if story_id in self.active_downloads:
                logger.debug(f"이미 다운로드 중: {story.username}")
                return self.active_downloads[story_id]
            
            # 최대 동시 다운로드 수 확인
            if len(self.active_downloads) >= self.max_concurrent:
                # 대기열에 추가
                with self._queue_lock:
                    # 중복 체크
                    if not any(s.story_id == story_id for s in self._pending_queue):
                        self._pending_queue.append(story)
                        logger.info(f"📋 대기열 추가: {story.username} (대기: {len(self._pending_queue)}개)")
                return None
        
        return self._start_download(story)
    
    def _start_download(self, story: StoryItem) -> Optional[DownloadTask]:
        """실제 다운로드 시작"""
        story_id = story.story_id
        
        # 디스크 공간 확인
        if not check_disk_space(self.output_dir, self.min_disk_space_mb):
            logger.error("디스크 공간 부족")
            return None
        
        # URL 확인
        media_url = story.media_url
        if not media_url:
            logger.error(f"미디어 URL이 없음: {story.username}")
            return None
        
        # 출력 경로 생성
        output_path = self._generate_output_path(story)
        
        # 다운로드 태스크 생성
        task = DownloadTask(
            story=story,
            output_path=output_path
        )
        
        with self._lock:
            self.active_downloads[story_id] = task
        
        # 백그라운드에서 다운로드 시작
        self._executor.submit(self._download_file, task)
        
        return task
    
    def _process_queue(self):
        """대기열 처리 워커"""
        while self._queue_worker_running:
            time.sleep(self.queue_check_interval)
            
            with self._lock:
                active_count = len(self.active_downloads)
            
            if active_count >= self.max_concurrent:
                continue
            
            with self._queue_lock:
                if not self._pending_queue:
                    continue
                
                # 대기열에서 다음 항목 가져오기
                story = self._pending_queue.pop(0)
            
            # 다운로드 시작
            logger.info(f"📋 대기열에서 시작: {story.username}")
            self._start_download(story)
    
    def _generate_output_path(self, story: StoryItem) -> Path:
        """출력 파일 경로 생성"""
        # 파일명 생성
        filename = self.filename_format.format(
            username=self._sanitize_filename(story.username),
            display_name=self._sanitize_filename(story.display_name),
            story_id=story.story_id
        )
        filename = story.taken_at.strftime(filename)
        
        # 확장자 추가
        filename = f"{filename}.{story.file_extension}"
        
        # 유저별 폴더
        user_dir = self.output_dir / self._sanitize_filename(story.username)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        return user_dir / filename
    
    def _sanitize_filename(self, name: str) -> str:
        """파일명에 사용할 수 없는 문자 제거"""
        if not name:
            return "unknown"
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
        sanitized = sanitized.replace(' ', '_')
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
        return sanitized or "unknown"
    
    def _download_file(self, task: DownloadTask):
        """파일 다운로드 (백그라운드 스레드)"""
        story = task.story
        
        logger.info(
            f"⬇️ 다운로드 시작: {story.display_name} "
            f"({'비디오' if story.is_video else '이미지'})"
        )
        
        task.status = "downloading"
        task.started_at = datetime.now()
        
        self._emit('on_download_start', task)
        
        try:
            media_url = story.media_url
            
            # URL 검증
            try:
                validate_media_url(media_url)
            except SecurityError as e:
                logger.error(f"URL 보안 검증 실패: {e}")
                raise DownloadError(f"보안 검증 실패: {e}")
            
            # 다운로드
            self._download_with_retry(media_url, task.output_path)
            
            # 썸네일 저장 (비디오의 경우)
            if self.save_thumbnails and story.is_video and story.thumbnail_url:
                thumb_path = task.output_path.with_suffix('.thumb.jpg')
                try:
                    self._download_with_retry(story.thumbnail_url, thumb_path, max_retries=2)
                except:
                    pass  # 썸네일 실패는 무시
            
            # 완료
            task.status = "completed"
            task.ended_at = datetime.now()
            
            if task.output_path.exists():
                task.file_size = task.output_path.stat().st_size
            
            # 기록에 추가
            if self.history:
                self.history.mark_downloaded(story.story_id)
            
            story.is_downloaded = True
            story.download_path = task.output_path
            
            logger.info(
                f"✅ 다운로드 완료: {story.display_name} "
                f"({self._format_size(task.file_size)})"
            )
            
            self._emit('on_download_complete', task)
            
        except DiskSpaceError as e:
            task.status = "failed"
            task.error_message = f"디스크 공간 부족: {e}"
            task.ended_at = datetime.now()
            logger.error(f"❌ 다운로드 실패 (디스크): {story.display_name}")
            self._emit('on_download_failed', task)
            
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)[:500]
            task.ended_at = datetime.now()
            logger.error(f"❌ 다운로드 실패: {story.display_name} - {e}")
            self._emit('on_download_failed', task)
        
        finally:
            with self._lock:
                if story.story_id in self.active_downloads:
                    del self.active_downloads[story.story_id]
                self.completed_downloads.append(task)
    
    def _download_with_retry(
        self,
        url: str,
        output_path: Path,
        max_retries: Optional[int] = None
    ):
        """재시도 로직이 포함된 다운로드"""
        if max_retries is None:
            max_retries = self.max_retries
            
        last_error = None
        temp_path = output_path.with_suffix('.tmp')
        
        for attempt in range(max_retries):
            try:
                response = self._session.get(
                    url,
                    stream=True,
                    timeout=(self.timeout_connect, self.timeout_read)
                )
                response.raise_for_status()
                
                with open(temp_path, 'wb') as f:
                    last_check_size = 0
                    check_interval = self.disk_check_interval_mb * 1024 * 1024
                    
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            
                            # 디스크 공간 체크
                            current_size = f.tell()
                            if current_size - last_check_size >= check_interval:
                                if not check_disk_space(self.output_dir, 50):
                                    raise DiskSpaceError("다운로드 중 디스크 공간 부족")
                                last_check_size = current_size
                
                # 완료 후 이름 변경
                temp_path.rename(output_path)
                return
                
            except DiskSpaceError:
                # 임시 파일 정리 후 예외 전파
                self._cleanup_temp_file(temp_path)
                raise
            except requests.exceptions.Timeout:
                last_error = DownloadError("타임아웃")
                logger.warning(f"다운로드 타임아웃, 재시도 {attempt + 1}/{max_retries}")
            except requests.exceptions.RequestException as e:
                last_error = DownloadError(f"요청 오류: {e}")
                logger.warning(f"다운로드 오류, 재시도 {attempt + 1}/{max_retries}: {e}")
            except Exception as e:
                last_error = DownloadError(f"알 수 없는 오류: {e}")
                logger.warning(f"다운로드 실패, 재시도 {attempt + 1}/{max_retries}: {e}")
            
            # 재시도 전 대기
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        
        # 최종 실패 시 임시 파일 정리
        self._cleanup_temp_file(temp_path)
        raise last_error or DownloadError("다운로드 실패")
    
    def _cleanup_temp_file(self, temp_path: Path):
        """임시 파일 정리"""
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
    
    def stop_all(self):
        """모든 다운로드 중지"""
        # 대기열 워커 정지
        self._queue_worker_running = False
        if self._queue_worker.is_alive():
            self._queue_worker.join(timeout=3)
        
        # 대기열 비우기
        with self._queue_lock:
            self._pending_queue.clear()
        
        # ThreadPoolExecutor 정지
        import sys
        if sys.version_info >= (3, 9):
            self._executor.shutdown(wait=True, cancel_futures=True)
        else:
            self._executor.shutdown(wait=True)
        
        self._session.close()
    
    def get_active_downloads(self) -> List[DownloadTask]:
        """활성 다운로드 목록"""
        with self._lock:
            return list(self.active_downloads.values())
    
    def get_stats(self) -> Dict:
        """다운로드 통계"""
        with self._lock:
            completed = [t for t in self.completed_downloads if t.status == "completed"]
            failed = [t for t in self.completed_downloads if t.status == "failed"]
            total_size = sum(t.file_size for t in completed)
            
            with self._queue_lock:
                pending_count = len(self._pending_queue)
            
            return {
                'active_downloads': len(self.active_downloads),
                'pending_downloads': pending_count,
                'completed_downloads': len(completed),
                'failed_downloads': len(failed),
                'total_size_bytes': total_size,
                'total_size_formatted': self._format_size(total_size)
            }
    
    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형식으로 변환"""
        if size_bytes <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
