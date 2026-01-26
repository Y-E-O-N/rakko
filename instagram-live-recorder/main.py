#!/usr/bin/env python3
"""
Instagram Live Recorder
자동으로 지정된 Instagram 유저의 라이브를 감지하고 녹화합니다.
"""
import sys
import signal
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logger import setup_logger, get_logger
from src.utils.config import load_config, Config
from src.auth.instagram_auth import InstagramAuth, SessionManager
from src.monitor.live_monitor import LiveMonitor, LiveMonitorV2, LiveBroadcast
from src.recorder.stream_recorder import StreamRecorder, RecordingTask
from src.notifier.telegram_notifier import TelegramNotifier, create_notifier as create_telegram_notifier
from src.notifier.discord_notifier import DiscordNotifier, create_discord_notifier
from src.storage.cloud_storage import CloudStorage, create_cloud_storage
from src.storage.database import Database, RecordingRecord, create_database

console = Console()


class InstagramLiveRecorder:
    """Instagram 라이브 자동 녹화기"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.config: Optional[Config] = None
        self.auth: Optional[InstagramAuth] = None
        self.session_manager: Optional[SessionManager] = None
        self.monitor: Optional[LiveMonitor] = None
        self.recorder: Optional[StreamRecorder] = None
        self.notifier: Optional[TelegramNotifier | DiscordNotifier] = None
        self.cloud_storage: Optional[CloudStorage] = None
        self.database: Optional[Database] = None
        self.scheduler: Optional[BlockingScheduler] = None
        
        self._is_running = False
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
            "[bold blue]Instagram Live Recorder[/bold blue]\n"
            "자동 라이브 감지 및 녹화 시스템",
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
        
        # 3. Instagram 로그인
        console.print("[cyan]Instagram 로그인 중...[/cyan]")
        self.auth = InstagramAuth(
            username=self.config.ig_username,
            password=self.config.ig_password,
            session_file=self.config.session_file,
            totp_secret=self.config.ig_totp_secret,
            proxy=self.config.proxy
        )
        
        if not self.auth.login():
            console.print("[red]Instagram 로그인 실패[/red]")
            return False
        console.print("  ✓ 로그인 성공")
        
        self.session_manager = SessionManager(self.auth)
        
        # 4. 모니터 초기화
        console.print("[cyan]라이브 모니터 초기화 중...[/cyan]")
        self.monitor = LiveMonitorV2(
            client=self.auth.get_client(),
            targets=self.config.targets,
            batch_size=self.config.batch_size,
            batch_delay=self.config.batch_delay,
            targets_file=self.config.targets_file
        )
        console.print("  ✓ 모니터 준비 완료")
        
        # 5. 녹화기 초기화
        console.print("[cyan]녹화기 초기화 중...[/cyan]")
        self.recorder = StreamRecorder(
            output_dir=self.config.output_dir,
            filename_format=self.config.filename_format,
            output_format=self.config.output_format,
            max_concurrent=self.config.max_concurrent,
            quality=self.config.quality,
            min_disk_space_mb=self.config.min_disk_space_mb,
            max_retries=self.config.recording_max_retries,
            retry_delay=self.config.recording_retry_delay
        )
        console.print(f"  ✓ 녹화기 준비 완료 (실패 시 최대 {self.config.recording_max_retries}회 재시도)")
        
        # 6. 알림 서비스 초기화
        if self.config.notify_enabled:
            console.print("[cyan]알림 서비스 초기화 중...[/cyan]")
            if self.config.notify_provider == "discord":
                self.notifier = create_discord_notifier(self.config)
                if self.notifier:
                    console.print("  ✓ Discord 알림 준비 완료")
                else:
                    console.print("  ⚠ Discord 알림 비활성화됨")
            else:
                self.notifier = create_telegram_notifier(self.config)
                if self.notifier:
                    console.print("  ✓ Telegram 알림 준비 완료")
                else:
                    console.print("  ⚠ Telegram 알림 비활성화됨")
        
        # 7. 클라우드 저장소 초기화
        if self.config.cloud_enabled:
            console.print("[cyan]클라우드 저장소 연결 중...[/cyan]")
            self.cloud_storage = create_cloud_storage(self.config)
            if self.cloud_storage:
                console.print("  ✓ Cloudflare R2 연결 완료")
            else:
                console.print("  ⚠ 클라우드 저장소 비활성화됨")

        # 8. 데이터베이스 초기화
        console.print("[cyan]데이터베이스 초기화 중...[/cyan]")
        self.database = create_database(self.config)
        console.print("  ✓ SQLite 데이터베이스 준비 완료")

        # 9. 이벤트 콜백 등록
        self._register_callbacks()
        
        console.print("\n[green]✓ 초기화 완료![/green]\n")
        return True
    
    def _register_callbacks(self):
        """이벤트 콜백 등록"""
        # 라이브 감지 시
        def on_live_start(broadcast: LiveBroadcast):
            self.logger.info(f"라이브 감지: {broadcast.display_name}")

            # DB에 라이브 감지 기록
            if self.database:
                self.database.add_live_detection(
                    broadcast_id=broadcast.broadcast_id,
                    username=broadcast.username,
                    display_name=broadcast.display_name,
                    title=broadcast.title or "",
                    viewer_count=broadcast.viewer_count
                )
                self.database.update_daily_stats(lives_detected=1)

            # 알림
            if self.notifier and self.config.notify_live_detected:
                self.notifier.notify_live_detected(broadcast)

            # 녹화 시작
            self.recorder.start_recording(broadcast)

        # 라이브 종료 시
        def on_live_end(broadcast: LiveBroadcast):
            self.logger.info(f"라이브 종료: {broadcast.display_name}")

        self.monitor.on('on_live_start', on_live_start)
        self.monitor.on('on_live_end', on_live_end)

        # 녹화 시작 시
        def on_recording_start(task: RecordingTask):
            if self.notifier and self.config.notify_recording_started:
                self.notifier.notify_recording_started(task)

        # 녹화 완료 시
        def on_recording_complete(task: RecordingTask):
            broadcast = task.broadcast

            # DB에 녹화 기록 저장
            if self.database:
                duration = 0
                if task.started_at and task.ended_at:
                    duration = int((task.ended_at - task.started_at).total_seconds())

                self.database.add_recording(RecordingRecord(
                    broadcast_id=broadcast.broadcast_id,
                    username=broadcast.username,
                    display_name=broadcast.display_name,
                    title=broadcast.title or "",
                    started_at=task.started_at,
                    ended_at=task.ended_at,
                    duration_seconds=duration,
                    file_path=str(task.output_path),
                    file_size=task.file_size,
                    status="completed",
                    retry_count=task.retry_count
                ))
                self.database.update_daily_stats(
                    completed=1,
                    duration=duration,
                    size=task.file_size
                )
                self.database.mark_live_recorded(broadcast.broadcast_id)

            if self.notifier and self.config.notify_recording_finished:
                self.notifier.notify_recording_complete(task)

            # 클라우드 업로드
            if self.cloud_storage:
                self.cloud_storage.upload_recording(task)

        # 녹화 실패 시
        def on_recording_failed(task: RecordingTask):
            broadcast = task.broadcast

            # DB에 실패 기록 저장
            if self.database:
                self.database.add_recording(RecordingRecord(
                    broadcast_id=broadcast.broadcast_id,
                    username=broadcast.username,
                    display_name=broadcast.display_name,
                    title=broadcast.title or "",
                    started_at=task.started_at,
                    ended_at=task.ended_at,
                    duration_seconds=0,
                    file_path=str(task.output_path),
                    file_size=0,
                    status="failed",
                    error_message=task.error_message,
                    retry_count=task.retry_count
                ))
                self.database.update_daily_stats(failed=1)

            if self.notifier and self.config.notify_recording_failed:
                self.notifier.notify_recording_failed(task)

        # 녹화 재시도 시
        def on_recording_retry(task: RecordingTask):
            self.logger.info(
                f"녹화 재시도: {task.broadcast.display_name} "
                f"({task.retry_count}/{task.max_retries})"
            )

        self.recorder.on('on_recording_start', on_recording_start)
        self.recorder.on('on_recording_complete', on_recording_complete)
        self.recorder.on('on_recording_failed', on_recording_failed)
        self.recorder.on('on_recording_retry', on_recording_retry)
    
    def _check_lives(self):
        """라이브 체크 (스케줄러에서 호출)"""
        try:
            # 세션 유효성 확인
            if not self.session_manager.ensure_logged_in():
                self.logger.error("로그인 상태 복구 실패")
                return

            # 라이브 체크
            active_lives = self.monitor.check_all_lives()

            # DB에 체크 기록
            if self.database:
                self.database.update_daily_stats(checks=1)

            # 상태 출력
            stats = self.monitor.get_stats()
            recording_stats = self.recorder.get_stats()

            status_line = (
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"체크 #{stats['total_checks']} | "
                f"활성 라이브: {stats['active_lives_count']} | "
                f"녹화 중: {recording_stats['active_recordings']}"
            )
            console.print(status_line)

        except Exception as e:
            self.logger.error(f"라이브 체크 에러: {e}")
            if self.notifier:
                self.notifier.notify_error(str(e))
    
    def _send_daily_summary(self):
        """일일 요약 알림 전송"""
        try:
            if not self.notifier or not self.config.notify_daily_summary:
                return

            # DB에서 오늘 통계 가져오기
            if self.database:
                daily_stats = self.database.get_daily_stats()
                if daily_stats:
                    stats = {
                        'total_checks': daily_stats.total_checks,
                        'total_lives_found': daily_stats.lives_detected,
                        'completed_recordings': daily_stats.recordings_completed,
                        'failed_recordings': daily_stats.recordings_failed,
                        'total_size_formatted': self._format_size(daily_stats.total_size_bytes)
                    }
                else:
                    # 모니터/레코더 통계 사용
                    monitor_stats = self.monitor.get_stats() if self.monitor else {}
                    recorder_stats = self.recorder.get_stats() if self.recorder else {}
                    stats = {**monitor_stats, **recorder_stats}
            else:
                monitor_stats = self.monitor.get_stats() if self.monitor else {}
                recorder_stats = self.recorder.get_stats() if self.recorder else {}
                stats = {**monitor_stats, **recorder_stats}

            self.notifier.notify_daily_summary(stats)
            self.logger.info("일일 요약 알림 전송 완료")

        except Exception as e:
            self.logger.error(f"일일 요약 전송 실패: {e}")

    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형식으로 변환"""
        if size_bytes <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def start(self):
        """모니터링 시작"""
        if self._is_running:
            return

        self._is_running = True

        # 시작 알림
        if self.notifier:
            self.notifier.notify_startup(len(self.config.targets))

        # 스케줄러 설정
        self.scheduler = BlockingScheduler()

        # 라이브 체크 작업 등록
        self.scheduler.add_job(
            self._check_lives,
            IntervalTrigger(seconds=self.config.check_interval),
            id='check_lives',
            name='라이브 체크',
            max_instances=1,
            coalesce=True
        )

        # 일일 요약 작업 등록 (매일 지정 시간)
        if self.config.notify_daily_summary and self.notifier:
            from apscheduler.triggers.cron import CronTrigger
            summary_hour = getattr(self.config, 'daily_summary_hour', 23)
            summary_minute = getattr(self.config, 'daily_summary_minute', 0)

            self.scheduler.add_job(
                self._send_daily_summary,
                CronTrigger(hour=summary_hour, minute=summary_minute),
                id='daily_summary',
                name='일일 요약',
                max_instances=1
            )
            console.print(f"  📊 일일 요약: 매일 {summary_hour:02d}:{summary_minute:02d}에 전송")
        
        console.print(Panel.fit(
            f"[green]모니터링 시작![/green]\n"
            f"체크 주기: {self.config.check_interval}초\n"
            f"대상: {len(self.config.targets)}명\n\n"
            f"[dim]종료하려면 Ctrl+C를 누르세요[/dim]",
            border_style="green"
        ))
        
        # 즉시 첫 체크 실행
        self._check_lives()
        
        # 스케줄러 시작 (블로킹)
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
        
        # 녹화 중지
        if self.recorder:
            self.recorder.stop_all()
        
        # 종료 알림
        if self.notifier and self.monitor and self.recorder:
            stats = {
                **self.monitor.get_stats(),
                **self.recorder.get_stats()
            }
            self.notifier.notify_shutdown(stats)
            # 알림 워커 스레드 정지
            self.notifier.stop()

        # 데이터베이스 연결 종료
        if self.database:
            self.database.close()

        console.print("[green]정상 종료되었습니다.[/green]")
    
    def show_status(self):
        """현재 상태 표시"""
        if not self.monitor or not self.recorder:
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
        table.add_row("발견된 라이브", f"{monitor_stats['total_lives_found']:,}")
        table.add_row("활성 라이브", f"{monitor_stats['active_lives_count']:,}")
        table.add_row("모니터링 대상", f"{monitor_stats['targets_count']:,}")
        
        console.print(table)
        
        # 녹화 상태
        recorder_stats = self.recorder.get_stats()
        table2 = Table(title="녹화 상태")
        table2.add_column("항목", style="cyan")
        table2.add_column("값", style="green")
        
        table2.add_row("녹화 중", f"{recorder_stats['active_recordings']:,}")
        table2.add_row("완료된 녹화", f"{recorder_stats['completed_recordings']:,}")
        table2.add_row("실패한 녹화", f"{recorder_stats['failed_recordings']:,}")
        table2.add_row("총 저장 용량", recorder_stats['total_size_formatted'])
        
        console.print(table2)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="Instagram Live 자동 녹화기"
    )
    parser.add_argument(
        '-c', '--config',
        default='config/settings.yaml',
        help='설정 파일 경로 (기본: config/settings.yaml)'
    )
    parser.add_argument(
        '--test-telegram',
        action='store_true',
        help='Telegram 알림 테스트'
    )
    parser.add_argument(
        '--test-discord',
        action='store_true',
        help='Discord 알림 테스트'
    )
    parser.add_argument(
        '--test-login',
        action='store_true',
        help='Instagram 로그인 테스트'
    )
    
    args = parser.parse_args()
    
    # 레코더 인스턴스 생성
    recorder = InstagramLiveRecorder(config_path=args.config)
    
    # 테스트 모드
    if args.test_telegram:
        recorder.config = load_config(args.config)
        from src.notifier.telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier(
            bot_token=recorder.config.telegram_token,
            chat_id=recorder.config.telegram_chat_id
        )
        if notifier.test_connection():
            console.print("[green]Telegram 테스트 성공![/green]")
        else:
            console.print("[red]Telegram 테스트 실패[/red]")
        return

    if args.test_discord:
        recorder.config = load_config(args.config)
        notifier = DiscordNotifier(
            webhook_url=recorder.config.discord_webhook_url
        )
        if notifier.test_connection():
            console.print("[green]Discord 테스트 성공![/green]")
        else:
            console.print("[red]Discord 테스트 실패[/red]")
        return
    
    if args.test_login:
        recorder.config = load_config(args.config)
        auth = InstagramAuth(
            username=recorder.config.ig_username,
            password=recorder.config.ig_password,
            session_file=recorder.config.session_file
        )
        if auth.login():
            console.print("[green]로그인 성공![/green]")
        else:
            console.print("[red]로그인 실패[/red]")
        return
    
    # 정상 실행
    if not recorder.initialize():
        console.print("[red]초기화 실패. 종료합니다.[/red]")
        sys.exit(1)
    
    recorder.start()


if __name__ == "__main__":
    main()
