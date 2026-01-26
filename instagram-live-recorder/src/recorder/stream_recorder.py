"""
Instagram 라이브 스트림 녹화

디스크 공간, 파일 시스템 권한 등을 사전에 체크합니다.
"""
import os
import re
import time
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from src.utils.logger import get_logger
from src.monitor.live_monitor import LiveBroadcast

logger = get_logger()


class RecordingError(Exception):
    """녹화 관련 오류"""
    pass


class DiskSpaceError(RecordingError):
    """디스크 공간 부족"""
    pass


class DependencyError(RecordingError):
    """필수 의존성 누락"""
    pass


class SecurityError(RecordingError):
    """보안 관련 오류"""
    pass


@dataclass
class RecordingTask:
    """녹화 작업"""
    broadcast: LiveBroadcast
    output_path: Path
    process: Optional[subprocess.Popen] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = "pending"  # pending, recording, completed, failed
    error_message: str = ""
    file_size: int = 0
    retry_count: int = 0
    max_retries: int = 3


def validate_stream_url(url: str) -> bool:
    """
    스트림 URL 보안 검증
    
    Args:
        url: 검증할 URL
    
    Returns:
        유효하면 True
    
    Raises:
        SecurityError: 유효하지 않은 URL
    """
    if not url:
        raise SecurityError("스트림 URL이 비어있습니다")
    
    try:
        parsed = urlparse(url)
        
        # HTTPS만 허용
        if parsed.scheme not in ('https', 'http'):
            raise SecurityError(f"지원하지 않는 프로토콜: {parsed.scheme}")
        
        # Instagram 관련 도메인만 허용
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
        
        # 위험한 문자 체크
        dangerous_chars = [';', '|', '&', '$', '`', '\n', '\r']
        for char in dangerous_chars:
            if char in url:
                raise SecurityError(f"URL에 허용되지 않은 문자 포함: {repr(char)}")
        
        return True
        
    except SecurityError:
        raise
    except Exception as e:
        raise SecurityError(f"URL 파싱 오류: {e}")


def check_disk_space(path: Path, min_space_mb: int = 500) -> bool:
    """
    디스크 여유 공간 확인
    
    Args:
        path: 확인할 경로
        min_space_mb: 최소 필요 공간 (MB)
    
    Returns:
        충분한 공간이 있으면 True
    """
    try:
        # 경로가 없으면 부모 디렉토리 확인
        check_path = path if path.exists() else path.parent
        while not check_path.exists() and check_path != check_path.parent:
            check_path = check_path.parent
        
        usage = shutil.disk_usage(check_path)
        free_mb = usage.free / (1024 * 1024)
        
        if free_mb < min_space_mb:
            logger.warning(
                f"디스크 여유 공간 부족: {free_mb:.0f}MB / 필요: {min_space_mb}MB"
            )
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"디스크 공간 확인 실패: {e}")
        return True  # 확인 실패 시 일단 진행


class StreamRecorder:
    """라이브 스트림 녹화기"""
    
    def __init__(
        self,
        output_dir: str = "data/recordings",
        filename_format: str = "{username}_%Y%m%d_%H%M%S",
        output_format: str = "mp4",
        max_concurrent: int = 5,
        quality: str = "best",
        min_disk_space_mb: int = 500,
        max_retries: int = 3,
        retry_delay: int = 30
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.filename_format = filename_format
        self.output_format = output_format
        self.max_concurrent = max_concurrent
        self.quality = quality
        self.min_disk_space_mb = min_disk_space_mb
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_completed_history = 1000  # 완료 기록 최대 보관 수

        self.active_recordings: Dict[str, RecordingTask] = {}
        self.completed_recordings: List[RecordingTask] = []
        self.failed_for_retry: List[RecordingTask] = []  # 재시도 대기 목록

        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()

        self._callbacks: Dict[str, List[Callable]] = {
            'on_recording_start': [],
            'on_recording_complete': [],
            'on_recording_failed': [],
            'on_recording_retry': []
        }
        
        # 의존성 상태
        self._ytdlp_available = False
        self._ffmpeg_available = False
        
        # yt-dlp/ffmpeg 존재 확인
        self._check_dependencies()
    
    def _check_dependencies(self):
        """필수 의존성 확인"""
        # yt-dlp 확인
        try:
            result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self._ytdlp_available = True
                logger.info(f"yt-dlp 버전: {result.stdout.strip()}")
        except FileNotFoundError:
            logger.warning(
                "yt-dlp를 찾을 수 없습니다. "
                "pip install yt-dlp 또는 시스템에 설치하세요."
            )
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp 버전 확인 타임아웃")
        except Exception as e:
            logger.warning(f"yt-dlp 확인 실패: {e}")
        
        # ffmpeg 확인
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self._ffmpeg_available = True
                version_line = result.stdout.split('\n')[0]
                logger.info(f"ffmpeg: {version_line}")
        except FileNotFoundError:
            logger.warning(
                "ffmpeg를 찾을 수 없습니다. "
                "시스템에 ffmpeg를 설치하세요."
            )
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg 버전 확인 타임아웃")
        except Exception as e:
            logger.warning(f"ffmpeg 확인 실패: {e}")
        
        if not self._ytdlp_available and not self._ffmpeg_available:
            logger.error("yt-dlp 또는 ffmpeg가 필요합니다. 녹화가 작동하지 않을 수 있습니다.")
    
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
    
    def start_recording(self, broadcast: LiveBroadcast) -> Optional[RecordingTask]:
        """
        라이브 녹화 시작
        
        Args:
            broadcast: 라이브 방송 정보
        
        Returns:
            RecordingTask 또는 None (실패 시)
        """
        broadcast_id = broadcast.broadcast_id
        
        # 의존성 확인
        if not self._ytdlp_available and not self._ffmpeg_available:
            logger.error("녹화 도구가 없습니다. yt-dlp 또는 ffmpeg를 설치하세요.")
            return None
        
        # 이미 녹화 중인지 확인
        with self._lock:
            if broadcast_id in self.active_recordings:
                logger.debug(f"이미 녹화 중: {broadcast.username}")
                return self.active_recordings[broadcast_id]
            
            # 최대 동시 녹화 수 확인
            if len(self.active_recordings) >= self.max_concurrent:
                logger.warning(
                    f"최대 동시 녹화 수 초과 ({self.max_concurrent}), "
                    f"{broadcast.username} 녹화 스킵"
                )
                return None
        
        # 디스크 공간 확인
        if not check_disk_space(self.output_dir, self.min_disk_space_mb):
            logger.error(
                f"디스크 공간 부족 (최소 {self.min_disk_space_mb}MB 필요), "
                f"{broadcast.username} 녹화 스킵"
            )
            return None
        
        # 출력 파일 경로 생성
        output_path = self._generate_output_path(broadcast)
        
        # 녹화 태스크 생성
        task = RecordingTask(
            broadcast=broadcast,
            output_path=output_path,
            max_retries=self.max_retries
        )
        
        with self._lock:
            self.active_recordings[broadcast_id] = task
        
        # 백그라운드에서 녹화 시작
        self._executor.submit(self._record_stream, task)
        
        return task
    
    def _generate_output_path(self, broadcast: LiveBroadcast) -> Path:
        """출력 파일 경로 생성"""
        now = datetime.now()
        
        # 파일명 생성
        filename = self.filename_format.format(
            username=self._sanitize_filename(broadcast.username),
            display_name=self._sanitize_filename(broadcast.display_name)
        )
        filename = now.strftime(filename)
        
        # 확장자 추가
        filename = f"{filename}.{self.output_format}"
        
        # 유저별 폴더 생성
        user_dir = self.output_dir / self._sanitize_filename(broadcast.username)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        return user_dir / filename
    
    def _sanitize_filename(self, name: str) -> str:
        """파일명에 사용할 수 없는 문자 제거"""
        if not name:
            return "unknown"
        # 파일명에 사용할 수 없는 문자 제거
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
        # 공백을 언더스코어로
        sanitized = sanitized.replace(' ', '_')
        # 너무 길면 자르기
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
        return sanitized or "unknown"
    
    def _record_stream(self, task: RecordingTask):
        """스트림 녹화 (백그라운드 스레드)"""
        broadcast = task.broadcast
        
        logger.info(f"🎬 녹화 시작: {broadcast.display_name} -> {task.output_path}")
        
        task.status = "recording"
        task.started_at = datetime.now()
        broadcast.is_recording = True
        broadcast.recording_started_at = task.started_at
        
        self._emit('on_recording_start', task)
        
        try:
            # 스트림 URL 선택
            stream_url = (
                broadcast.dash_abr_playback_url or 
                broadcast.dash_playback_url
            )
            
            if not stream_url:
                raise RecordingError("스트림 URL을 찾을 수 없습니다")
            
            # 보안: URL 검증
            try:
                validate_stream_url(stream_url)
            except SecurityError as e:
                logger.warning(f"URL 검증 실패: {e}")
                # Instagram에서 온 URL이므로 경고만 하고 계속 진행
                # 단, 로그에 기록하여 추후 분석 가능하게 함
            
            # yt-dlp로 녹화 (우선), 실패 시 ffmpeg
            if self._ytdlp_available:
                self._run_ytdlp(task, stream_url)
            elif self._ffmpeg_available:
                self._run_ffmpeg(task, stream_url)
            else:
                raise DependencyError("녹화 도구가 없습니다")
            
            # 녹화 완료
            task.status = "completed"
            task.ended_at = datetime.now()
            
            if task.output_path.exists():
                task.file_size = task.output_path.stat().st_size
            
            duration = task.ended_at - task.started_at
            logger.info(
                f"✅ 녹화 완료: {broadcast.display_name} "
                f"(시간: {duration}, 크기: {self._format_size(task.file_size)})"
            )
            
            self._emit('on_recording_complete', task)
            
        except DiskSpaceError as e:
            task.status = "failed"
            task.error_message = f"디스크 공간 부족: {e}"
            task.ended_at = datetime.now()
            logger.error(f"❌ 녹화 실패 (디스크): {broadcast.display_name}")
            self._emit('on_recording_failed', task)
            
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)[:500]  # 에러 메시지 길이 제한
            task.ended_at = datetime.now()

            logger.error(f"❌ 녹화 실패: {broadcast.display_name} - {e}")

            # 재시도 가능 여부 확인
            if self._should_retry(task, e):
                task.retry_count += 1
                logger.info(
                    f"🔄 녹화 재시도 예정: {broadcast.display_name} "
                    f"({task.retry_count}/{task.max_retries})"
                )
                self._emit('on_recording_retry', task)
                # 재시도 스케줄링
                self._schedule_retry(task)
            else:
                self._emit('on_recording_failed', task)

        finally:
            broadcast.is_recording = False

            with self._lock:
                if broadcast.broadcast_id in self.active_recordings:
                    del self.active_recordings[broadcast.broadcast_id]
                self.completed_recordings.append(task)
                # 완료 기록 크기 제한 (메모리 누적 방지)
                if len(self.completed_recordings) > self.max_completed_history:
                    self.completed_recordings = self.completed_recordings[-self.max_completed_history:]
    
    def _run_ytdlp(self, task: RecordingTask, stream_url: str):
        """yt-dlp로 스트림 녹화"""
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '-o', str(task.output_path),
            '--format', self._get_format_string(),
            '--merge-output-format', self.output_format,
            # 라이브 스트림 옵션
            '--live-from-start',  # 처음부터 녹화 시도
            '--wait-for-video', '5-30',  # 스트림 대기
            # 재시도 설정
            '--retries', '10',
            '--fragment-retries', '10',
            # 추가 옵션
            '--concurrent-fragments', '3',  # 동시 다운로드
            '--no-colors',  # 출력에서 색상 제거
            stream_url
        ]
        
        # URL은 보안상 마스킹하여 로그
        logger.debug(f"실행 명령: yt-dlp ... [URL_MASKED]")
        
        # 로그 파일로 출력 리다이렉트
        log_file = task.output_path.with_suffix('.log')
        
        try:
            with open(log_file, 'w', encoding='utf-8') as log_f:
                task.process = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                
                # 프로세스 완료 대기 (주기적으로 디스크 공간 체크)
                while task.process.poll() is None:
                    time.sleep(5)
                    
                    # 디스크 공간 체크
                    if not check_disk_space(self.output_dir, 100):  # 최소 100MB
                        logger.warning("디스크 공간 부족으로 녹화 중단")
                        task.process.terminate()
                        raise DiskSpaceError("녹화 중 디스크 공간 부족")
            
            returncode = task.process.returncode
            
            if returncode != 0:
                # 로그 파일에서 에러 확인
                error_msg = ""
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()[-20:]  # 마지막 20줄
                        error_msg = ''.join(lines)
                except:
                    pass
                
                # 일부 에러는 무시 (라이브 종료 등)
                if "HTTP Error 403" in error_msg or "is offline" in error_msg.lower():
                    logger.info("라이브가 종료되었습니다")
                elif "Interrupted by user" in error_msg:
                    logger.info("사용자에 의해 중단됨")
                elif "No space left" in error_msg:
                    raise DiskSpaceError("디스크 공간 부족")
                else:
                    raise RecordingError(f"yt-dlp 종료 코드: {returncode}")
        
        finally:
            # 로그 파일 정리 (성공 시 삭제)
            if task.status == "completed":
                try:
                    log_file.unlink(missing_ok=True)
                except:
                    pass
    
    def _run_ffmpeg(self, task: RecordingTask, stream_url: str):
        """FFmpeg로 직접 녹화 (폴백)"""
        cmd = [
            'ffmpeg',
            '-y',  # 덮어쓰기
            '-i', stream_url,
            '-c', 'copy',  # 재인코딩 없이 복사
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            str(task.output_path)
        ]
        
        task.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        # 주기적으로 체크
        while task.process.poll() is None:
            time.sleep(5)
            if not check_disk_space(self.output_dir, 100):
                task.process.terminate()
                raise DiskSpaceError("녹화 중 디스크 공간 부족")
        
        if task.process.returncode not in (0, 255):  # 255는 정상 종료
            stderr = ""
            if task.process.stderr:
                try:
                    stderr = task.process.stderr.read().decode('utf-8', errors='replace')
                except Exception:
                    stderr = "(stderr 읽기 실패)"
            raise RecordingError(f"FFmpeg 종료 코드: {task.process.returncode}")
    
    def _get_format_string(self) -> str:
        """yt-dlp 포맷 문자열"""
        format_map = {
            'best': 'best',
            '1080p': 'best[height<=1080]',
            '720p': 'best[height<=720]',
            '480p': 'best[height<=480]',
            '360p': 'best[height<=360]'
        }
        return format_map.get(self.quality, 'best')

    def _should_retry(self, task: RecordingTask, error: Exception) -> bool:
        """재시도 가능 여부 확인"""
        # 최대 재시도 횟수 초과
        if task.retry_count >= task.max_retries:
            logger.debug(f"최대 재시도 횟수 초과: {task.broadcast.username}")
            return False

        # 디스크 공간 부족은 재시도 불가
        if isinstance(error, DiskSpaceError):
            logger.debug("디스크 공간 부족 - 재시도 불가")
            return False

        # 의존성 오류는 재시도 불가
        if isinstance(error, DependencyError):
            logger.debug("의존성 오류 - 재시도 불가")
            return False

        # 스트림 URL 없음은 재시도 가능 (라이브가 아직 진행 중일 수 있음)
        error_msg = str(error).lower()
        if "url" in error_msg and "없" in error_msg:
            return True

        # 네트워크 관련 오류는 재시도
        network_errors = ['timeout', 'connection', 'network', 'socket', '403', '404']
        if any(ne in error_msg for ne in network_errors):
            return True

        # 기타 오류도 재시도 (일정 횟수까지)
        return True

    def _schedule_retry(self, task: RecordingTask):
        """재시도 스케줄링"""
        def retry_task():
            time.sleep(self.retry_delay)
            # 라이브가 여전히 진행 중인지 확인하고 재시도
            logger.info(f"🔄 녹화 재시도 시작: {task.broadcast.display_name}")
            self._retry_recording(task)

        self._executor.submit(retry_task)

    def _retry_recording(self, task: RecordingTask):
        """녹화 재시도"""
        broadcast = task.broadcast

        # 새 출력 경로 생성 (덮어쓰기 방지)
        task.output_path = self._generate_output_path(broadcast)
        task.status = "pending"
        task.error_message = ""
        task.started_at = None
        task.ended_at = None

        with self._lock:
            # 이미 녹화 중이면 스킵
            if broadcast.broadcast_id in self.active_recordings:
                logger.debug(f"이미 녹화 중 (재시도 취소): {broadcast.username}")
                return

            self.active_recordings[broadcast.broadcast_id] = task

        # 녹화 시작
        self._record_stream(task)

    def stop_recording(self, broadcast_id: str):
        """녹화 중지"""
        with self._lock:
            if broadcast_id not in self.active_recordings:
                return
            
            task = self.active_recordings[broadcast_id]
            
            if task.process and task.process.poll() is None:
                logger.info(f"녹화 중지: {task.broadcast.display_name}")
                task.process.terminate()
                try:
                    task.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    task.process.kill()
    
    def stop_all(self):
        """모든 녹화 중지"""
        with self._lock:
            for broadcast_id in list(self.active_recordings.keys()):
                self.stop_recording(broadcast_id)

        # Python 버전 호환성: cancel_futures는 3.9+에서만 지원
        import sys
        if sys.version_info >= (3, 9):
            self._executor.shutdown(wait=True, cancel_futures=True)
        else:
            self._executor.shutdown(wait=True)
    
    def get_active_recordings(self) -> List[RecordingTask]:
        """활성 녹화 목록"""
        with self._lock:
            return list(self.active_recordings.values())
    
    def get_stats(self) -> Dict:
        """녹화 통계"""
        with self._lock:
            completed = [t for t in self.completed_recordings if t.status == "completed"]
            failed = [t for t in self.completed_recordings if t.status == "failed"]
            total_size = sum(t.file_size for t in completed)
            total_retries = sum(t.retry_count for t in self.completed_recordings)

            return {
                'active_recordings': len(self.active_recordings),
                'completed_recordings': len(completed),
                'failed_recordings': len(failed),
                'total_retries': total_retries,
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
