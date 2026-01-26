#!/usr/bin/env python3
"""
Instagram Story Saver
지정된 Instagram 유저의 스토리를 자동으로 감지하고 저장합니다.
"""
import sys
import signal
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logger import setup_logger, get_logger
from src.utils.config import load_config, Config
from src.auth.instagram_auth import InstagramAuth, SessionManager
from src.monitor.story_monitor import StoryMonitor, StoryMonitorV2, StoryItem, DownloadHistory
from src.downloader.story_downloader import StoryDownloader, DownloadTask
from src.notifier.telegram_notifier import TelegramNotifier, create_notifier
from src.notifier.discord_notifier import DiscordNotifier, create_discord_notifier
from src.storage.cloud_storage import CloudStorage, create_cloud_storage
from src.storage.database import Database, DownloadRecord, create_database

console = Console()


class InstagramStorySaver:
    """Instagram 스토리 자동 저장기"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.config: Optional[Config] = None
        self.auth: Optional[InstagramAuth] = None
        self.session_manager: Optional[SessionManager] = None
        self.monitor: Optional[StoryMonitor] = None
        self.downloader: Optional[StoryDownloader] = None
        self.notifier: Optional[TelegramNotifier] = None
        self.discord_notifier: Optional[DiscordNotifier] = None
        self.cloud_storage: Optional[CloudStorage] = None
        self.database: Optional[Database] = None
        self.history: Optional[DownloadHistory] = None
        self.scheduler: Optional[BlockingScheduler] = None
        
        self._is_running = False
        self._pending_stories: List[StoryItem] = []
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """종료 시그널 핸들러 설정"""
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """종료 처리"""
        console.print("\n[yellow]종료 신호를 받았습니다. 정리 중...[/yellow]")
        self.stop()
    
    def initialize(self) -> bool:
        """초기화"""
        console.print(Panel.fit(
            "[bold blue]Instagram Story Saver[/bold blue]\n"
            "자동 스토리 감지 및 저장 시스템",
            border_style="blue"
        ))
        
        # 1. 설정 로드
        try:
            console.print("[cyan]설정 파일 로드 중...[/cyan]")
            self.config = load_config(self.config_path)
            console.print(f"  ✓ 타겟 유저: {len(self.config.targets)}명")
        except Exception as e:
            console.print(f"[red]설정 파일 로드 실패: {e}[/red]")
            return False
        
        # 2. 로거 설정
        setup_logger(
            level=self.config.log_level,
            log_file=self.config.log_file,
            max_size_mb=self.config.log_max_size,
            backup_count=self.config.log_backup_count
        )
        self.logger = get_logger()
        
        # 3. 다운로드 기록 로드
        console.print("[cyan]다운로드 기록 로드 중...[/cyan]")
        self.history = DownloadHistory(
            self.config.history_file,
            expire_hours=self.config.duplicate_check_hours
        )
        console.print("  ✓ 기록 로드 완료")
        
        # 4. Instagram 로그인
        console.print("[cyan]Instagram 로그인 중...[/cyan]")
        self.auth = InstagramAuth(
            username=self.config.ig_username,
            password=self.config.ig_password,
            session_file=self.config.session_file,
            totp_secret=self.config.ig_totp_secret,
            proxy=self.config.proxy,
            user_agent=self.config.user_agent,
            delay_min=self.config.api_delay_min,
            delay_max=self.config.api_delay_max
        )
        
        if not self.auth.login():
            console.print("[red]Instagram 로그인 실패[/red]")
            return False
        console.print("  ✓ 로그인 성공")
        
        self.session_manager = SessionManager(
            self.auth,
            cooldown_seconds=self.config.api_cooldown_seconds,
            max_failures=self.config.api_max_failures
        )
        
        # 5. 모니터 초기화
        console.print("[cyan]스토리 모니터 초기화 중...[/cyan]")
        self.monitor = StoryMonitorV2(
            client=self.auth.get_client(),
            targets=self.config.targets,
            history=self.history,
            batch_size=self.config.batch_size,
            batch_delay=self.config.batch_delay,
            targets_file=self.config.targets_file,
            download_videos=self.config.download_videos,
            download_images=self.config.download_images,
            video_quality=self.config.video_quality,
            image_quality=self.config.image_quality,
            story_expire_hours=self.config.story_expire_hours,
            user_id_resolve_delay=self.config.user_id_resolve_delay,
            user_id_resolve_batch=self.config.user_id_resolve_batch
        )
        console.print(f"  ✓ 모니터 준비 완료 (비디오: {self.config.video_quality}, 이미지: {self.config.image_quality})")
        
        # 6. 다운로더 초기화
        console.print("[cyan]다운로더 초기화 중...[/cyan]")
        self.downloader = StoryDownloader(
            output_dir=self.config.output_dir,
            filename_format=self.config.filename_format,
            max_concurrent=self.config.max_concurrent,
            min_disk_space_mb=self.config.min_disk_space_mb,
            save_thumbnails=self.config.save_thumbnails,
            history=self.history,
            timeout_connect=self.config.download_timeout_connect,
            timeout_read=self.config.download_timeout_read,
            chunk_size=self.config.download_chunk_size,
            max_retries=self.config.download_max_retries,
            disk_check_interval_mb=self.config.download_disk_check_interval_mb,
            queue_check_interval=self.config.download_queue_check_interval,
            max_completed_history=self.config.max_completed_history,
            user_agent=self.config.download_user_agent
        )
        console.print("  ✓ 다운로더 준비 완료")
        
        # 7. 데이터베이스 초기화
        console.print("[cyan]데이터베이스 초기화 중...[/cyan]")
        self.database = create_database(self.config)
        console.print(f"  ✓ 데이터베이스 준비 완료: {self.config.db_path}")

        # 8. 알림 서비스 초기화
        if self.config.notify_enabled:
            console.print("[cyan]알림 서비스 초기화 중...[/cyan]")
            if self.config.notify_provider == 'discord':
                self.discord_notifier = create_discord_notifier(self.config)
                if self.discord_notifier:
                    console.print("  ✓ Discord 알림 준비 완료")
                else:
                    console.print("  ⚠ Discord 알림 비활성화됨")
            else:
                self.notifier = create_notifier(self.config)
                if self.notifier:
                    console.print("  ✓ Telegram 알림 준비 완료")
                else:
                    console.print("  ⚠ Telegram 알림 비활성화됨")
        
        # 9. 클라우드 저장소 초기화
        if self.config.cloud_enabled:
            console.print("[cyan]클라우드 저장소 연결 중...[/cyan]")
            self.cloud_storage = create_cloud_storage(self.config)
            if self.cloud_storage:
                console.print("  ✓ Cloudflare R2 연결 완료")
            else:
                console.print("  ⚠ 클라우드 저장소 비활성화됨")
        
        # 10. 이벤트 콜백 등록
        self._register_callbacks()
        
        console.print("\n[green]✓ 초기화 완료![/green]\n")
        return True
    
    def _get_notifier(self):
        """현재 활성화된 알림 서비스 반환"""
        return self.discord_notifier or self.notifier

    def _register_callbacks(self):
        """이벤트 콜백 등록"""
        # 새 스토리 감지 시
        def on_new_story(story: StoryItem):
            self.logger.info(f"새 스토리: {story.display_name}")

            # DB에 감지 기록
            if self.database:
                self.database.add_story_detection(story)

            # 알림
            notifier = self._get_notifier()
            if notifier and self.config.notify_story_detected:
                notifier.notify_new_story(story)

            # 다운로드 시작
            self.downloader.download(story)

        self.monitor.on('on_new_story', on_new_story)

        # 다운로드 완료 시
        def on_download_complete(task: DownloadTask):
            # DB에 기록
            if self.database:
                record = DownloadRecord(
                    story_id=task.story.story_id,
                    username=task.story.username,
                    display_name=task.story.display_name,
                    media_type='video' if task.story.is_video else 'image',
                    file_path=str(task.output_path),
                    file_size=task.file_size,
                    downloaded_at=task.ended_at or datetime.now(),
                    taken_at=task.story.taken_at,
                    status='completed'
                )
                self.database.add_download(record)

            # 알림
            notifier = self._get_notifier()
            if notifier and self.config.notify_download_complete:
                notifier.notify_download_complete(task)

            # 클라우드 업로드
            if self.cloud_storage:
                self.cloud_storage.upload_story(task)

        # 다운로드 실패 시
        def on_download_failed(task: DownloadTask):
            # DB에 실패 기록
            if self.database:
                record = DownloadRecord(
                    story_id=task.story.story_id,
                    username=task.story.username,
                    display_name=task.story.display_name,
                    media_type='video' if task.story.is_video else 'image',
                    file_path='',
                    file_size=0,
                    downloaded_at=task.ended_at or datetime.now(),
                    taken_at=task.story.taken_at,
                    status='failed',
                    error_message=task.error_message
                )
                self.database.add_download(record)

            # 알림
            notifier = self._get_notifier()
            if notifier and self.config.notify_download_failed:
                notifier.notify_download_failed(task)

        self.downloader.on('on_download_complete', on_download_complete)
        self.downloader.on('on_download_failed', on_download_failed)
    
    def _check_stories(self):
        """스토리 체크 (스케줄러에서 호출)"""
        try:
            # 세션 유효성 확인
            if not self.session_manager.ensure_logged_in():
                self.logger.error("로그인 상태 복구 실패")
                return

            # 스토리 체크
            new_stories = self.monitor.check_all_stories()

            # DB에 체크 횟수 업데이트
            if self.database:
                self.database.update_daily_stats(checks=1)

            # 상태 출력
            stats = self.monitor.get_stats()
            download_stats = self.downloader.get_stats()

            status_line = (
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"체크 #{stats['total_checks']} | "
                f"새 스토리: {len(new_stories)} | "
                f"다운로드 중: {download_stats['active_downloads']} | "
                f"대기: {download_stats.get('pending_downloads', 0)}"
            )
            console.print(status_line)

            # 다운로드 기록 정리
            self.history.cleanup()

        except Exception as e:
            self.logger.error(f"스토리 체크 에러: {e}")
            notifier = self._get_notifier()
            if notifier and self.config.notify_errors:
                notifier.notify_error(str(e))
    
    def _send_daily_summary(self):
        """일일 요약 전송"""
        try:
            notifier = self._get_notifier()
            if not notifier or not self.config.notify_daily_summary:
                return

            # DB에서 통계 가져오기
            if self.database:
                daily_stats = self.database.get_daily_stats()
                if daily_stats:
                    stats = {
                        'total_checks': daily_stats.total_checks,
                        'total_new_stories': daily_stats.stories_detected,
                        'completed_downloads': daily_stats.downloads_completed,
                        'failed_downloads': daily_stats.downloads_failed,
                        'total_size_formatted': daily_stats.total_size_formatted
                    }
                else:
                    stats = {
                        'total_checks': 0,
                        'total_new_stories': 0,
                        'completed_downloads': 0,
                        'failed_downloads': 0,
                        'total_size_formatted': '0 B'
                    }
            else:
                # DB가 없으면 모니터/다운로더 통계 사용
                monitor_stats = self.monitor.get_stats() if self.monitor else {}
                download_stats = self.downloader.get_stats() if self.downloader else {}
                stats = {
                    'total_checks': monitor_stats.get('total_checks', 0),
                    'total_new_stories': monitor_stats.get('total_new_stories', 0),
                    'completed_downloads': download_stats.get('completed_downloads', 0),
                    'failed_downloads': download_stats.get('failed_downloads', 0),
                    'total_size_formatted': download_stats.get('total_size_formatted', '0 B')
                }

            notifier.notify_daily_summary(stats)
            self.logger.info("일일 요약 전송 완료")

        except Exception as e:
            self.logger.error(f"일일 요약 전송 에러: {e}")

    def start(self):
        """모니터링 시작"""
        if self._is_running:
            return

        self._is_running = True

        # 시작 알림
        notifier = self._get_notifier()
        if notifier:
            notifier.notify_startup(len(self.config.targets))

        # 스케줄러 설정
        self.scheduler = BlockingScheduler()

        # 스토리 체크 작업 등록
        self.scheduler.add_job(
            self._check_stories,
            IntervalTrigger(seconds=self.config.check_interval),
            id='check_stories',
            name='스토리 체크',
            max_instances=1,
            coalesce=True
        )

        # 일일 요약 작업 등록
        if self.config.notify_daily_summary:
            summary_hour = self.config.daily_summary_hour
            summary_minute = self.config.daily_summary_minute
            self.scheduler.add_job(
                self._send_daily_summary,
                CronTrigger(hour=summary_hour, minute=summary_minute),
                id='daily_summary',
                name='일일 요약'
            )
            console.print(f"  ✓ 일일 요약: 매일 {summary_hour:02d}:{summary_minute:02d}")
        
        console.print(Panel.fit(
            f"[green]모니터링 시작![/green]\n"
            f"체크 주기: {self.config.check_interval // 60}분\n"
            f"대상: {len(self.config.targets)}명\n\n"
            f"[dim]종료하려면 Ctrl+C를 누르세요[/dim]",
            border_style="green"
        ))
        
        # 즉시 첫 체크 실행
        self._check_stories()
        
        # 스케줄러 시작
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass
    
    def stop(self):
        """모니터링 중지"""
        if not self._is_running:
            return

        self._is_running = False

        console.print("[yellow]종료 중...[/yellow]")

        # 스케줄러 중지
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

        # 다운로드 중지
        if self.downloader:
            self.downloader.stop_all()

        # 종료 알림
        notifier = self._get_notifier()
        if notifier and self.monitor and self.downloader:
            stats = {
                **self.monitor.get_stats(),
                **self.downloader.get_stats()
            }
            notifier.notify_shutdown(stats)
            notifier.stop()

        # 데이터베이스 종료
        if self.database:
            self.database.close()

        console.print("[green]정상 종료되었습니다.[/green]")
    
    def show_status(self):
        """현재 상태 표시"""
        if not self.monitor or not self.downloader:
            console.print("[yellow]아직 초기화되지 않았습니다.[/yellow]")
            return
        
        # 모니터 상태
        monitor_stats = self.monitor.get_stats()
        table = Table(title="모니터링 상태")
        table.add_column("항목", style="cyan")
        table.add_column("값", style="green")
        
        table.add_row("실행 중", "✓" if self._is_running else "✗")
        table.add_row("마지막 체크", str(monitor_stats['last_check'] or '-'))
        table.add_row("총 체크 횟수", f"{monitor_stats['total_checks']:,}")
        table.add_row("발견된 스토리", f"{monitor_stats['total_new_stories']:,}")
        table.add_row("모니터링 대상", f"{monitor_stats['targets_count']:,}")
        
        console.print(table)
        
        # 다운로드 상태
        download_stats = self.downloader.get_stats()
        table2 = Table(title="다운로드 상태")
        table2.add_column("항목", style="cyan")
        table2.add_column("값", style="green")
        
        table2.add_row("다운로드 중", f"{download_stats['active_downloads']:,}")
        table2.add_row("대기 중", f"{download_stats.get('pending_downloads', 0):,}")
        table2.add_row("완료된 다운로드", f"{download_stats['completed_downloads']:,}")
        table2.add_row("실패한 다운로드", f"{download_stats['failed_downloads']:,}")
        table2.add_row("총 저장 용량", download_stats['total_size_formatted'])
        
        console.print(table2)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="Instagram Story 자동 저장기"
    )
    parser.add_argument(
        '-c', '--config',
        default='config/settings.yaml',
        help='설정 파일 경로 (기본: config/settings.yaml)'
    )
    parser.add_argument(
        '--test-discord',
        action='store_true',
        help='Discord 알림 테스트'
    )
    parser.add_argument(
        '--test-telegram',
        action='store_true',
        help='Telegram 알림 테스트'
    )
    parser.add_argument(
        '--test-login',
        action='store_true',
        help='Instagram 로그인 테스트'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='한 번만 체크하고 종료'
    )
    
    args = parser.parse_args()
    
    saver = InstagramStorySaver(config_path=args.config)

    # Discord 테스트 모드
    if args.test_discord:
        saver.config = load_config(args.config)
        discord_notifier = create_discord_notifier(saver.config)
        if discord_notifier:
            if discord_notifier.test_connection():
                console.print("[green]Discord 테스트 성공![/green]")
            else:
                console.print("[red]Discord 테스트 실패[/red]")
        else:
            console.print("[yellow]Discord가 설정되지 않았습니다.[/yellow]")
        return

    # Telegram 테스트 모드
    if args.test_telegram:
        if saver.initialize():
            if saver.notifier:
                if saver.notifier.test_connection():
                    console.print("[green]Telegram 테스트 성공![/green]")
                else:
                    console.print("[red]Telegram 테스트 실패[/red]")
            else:
                console.print("[yellow]Telegram이 설정되지 않았습니다.[/yellow]")
        return
    
    if args.test_login:
        saver.config = load_config(args.config)
        auth = InstagramAuth(
            username=saver.config.ig_username,
            password=saver.config.ig_password,
            session_file=saver.config.session_file
        )
        if auth.login():
            console.print("[green]로그인 성공![/green]")
        else:
            console.print("[red]로그인 실패[/red]")
        return
    
    # 초기화
    if not saver.initialize():
        console.print("[red]초기화 실패. 종료합니다.[/red]")
        sys.exit(1)
    
    # 한 번만 실행
    if args.once:
        saver._check_stories()
        saver.show_status()
        return
    
    # 정상 실행
    saver.start()


if __name__ == "__main__":
    main()
