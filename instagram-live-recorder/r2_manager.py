#!/usr/bin/env python3
"""
Cloudflare R2 관리 CLI 도구

사용법:
    python r2_manager.py list                    # 모든 파일 목록
    python r2_manager.py list --user username    # 특정 유저 파일
    python r2_manager.py usage                   # 사용량 확인
    python r2_manager.py download <key> <path>   # 파일 다운로드
    python r2_manager.py url <key>               # 다운로드 URL 생성
    python r2_manager.py delete <key>            # 파일 삭제
    python r2_manager.py test                    # 연결 테스트
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.utils.config import load_config
from src.storage.cloud_storage import CloudStorage, create_cloud_storage

console = Console()


def get_storage(config_path: str = "config/settings.yaml") -> CloudStorage:
    """CloudStorage 인스턴스 가져오기"""
    config = load_config(config_path)
    
    if not config.cloud_enabled:
        console.print("[red]클라우드 저장소가 비활성화되어 있습니다.[/red]")
        console.print("config/settings.yaml에서 cloud_storage.enabled를 true로 설정하세요.")
        sys.exit(1)
    
    storage = create_cloud_storage(config)
    
    if not storage:
        console.print("[red]R2 연결에 실패했습니다.[/red]")
        console.print("설정을 확인하세요: docs/CLOUDFLARE_R2_SETUP.md")
        sys.exit(1)
    
    return storage


def cmd_test(args):
    """연결 테스트"""
    console.print("[cyan]R2 연결 테스트 중...[/cyan]")
    
    try:
        storage = get_storage(args.config)
        
        if storage.test_connection():
            console.print("[green]✅ R2 연결 성공![/green]")
            
            # 추가 정보 표시
            usage = storage.get_storage_usage()
            console.print(f"\n버킷: {storage.bucket_name}")
            console.print(f"파일 수: {usage['file_count']}")
            console.print(f"사용량: {usage['total_size_formatted']}")
            console.print(f"예상 월 비용: {usage['estimated_monthly_cost']}")
        else:
            console.print("[red]❌ R2 연결 실패[/red]")
            
    except Exception as e:
        console.print(f"[red]오류: {e}[/red]")


def cmd_list(args):
    """파일 목록"""
    storage = get_storage(args.config)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]파일 목록 조회 중..."),
        console=console
    ) as progress:
        progress.add_task("loading", total=None)
        
        if args.user:
            files = storage.list_recordings(username=args.user)
        else:
            files = storage.list_files(max_keys=args.limit)
    
    if not files:
        console.print("[yellow]파일이 없습니다.[/yellow]")
        return
    
    # 테이블 생성
    table = Table(title=f"R2 파일 목록 ({len(files)}개)")
    table.add_column("파일", style="cyan")
    table.add_column("크기", justify="right", style="green")
    table.add_column("수정일", style="yellow")
    
    for f in files:
        modified = f['last_modified'].strftime('%Y-%m-%d %H:%M') if f.get('last_modified') else '-'
        table.add_row(
            f['key'],
            f.get('size_formatted', f"{f['size']:,}"),
            modified
        )
    
    console.print(table)
    
    # 총계
    total_size = sum(f['size'] for f in files)
    console.print(f"\n총 {len(files)}개 파일, {storage._format_size(total_size)}")


def cmd_usage(args):
    """사용량 확인"""
    storage = get_storage(args.config)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]사용량 조회 중..."),
        console=console
    ) as progress:
        progress.add_task("loading", total=None)
        usage = storage.get_storage_usage()
    
    # 기본 정보
    panel = Panel.fit(
        f"[bold]파일 수:[/bold] {usage['file_count']:,}개\n"
        f"[bold]총 사용량:[/bold] {usage['total_size_formatted']}\n"
        f"[bold]예상 월 비용:[/bold] {usage['estimated_monthly_cost']}",
        title="R2 저장소 사용량",
        border_style="blue"
    )
    console.print(panel)
    
    # 유저별 통계
    if usage.get('user_stats'):
        table = Table(title="유저별 사용량")
        table.add_column("유저", style="cyan")
        table.add_column("파일 수", justify="right")
        table.add_column("용량", justify="right", style="green")
        
        for username, stats in sorted(
            usage['user_stats'].items(),
            key=lambda x: x[1]['count'],
            reverse=True
        ):
            table.add_row(
                username,
                str(stats['count']),
                stats['size_formatted']
            )
        
        console.print(table)


def cmd_download(args):
    """파일 다운로드"""
    storage = get_storage(args.config)
    
    remote_path = args.key
    local_path = Path(args.output) if args.output else Path(remote_path).name
    
    console.print(f"[cyan]다운로드: {remote_path} -> {local_path}[/cyan]")
    
    if storage.download_file(remote_path, local_path):
        file_size = local_path.stat().st_size
        console.print(f"[green]✅ 다운로드 완료: {storage._format_size(file_size)}[/green]")
    else:
        console.print("[red]❌ 다운로드 실패[/red]")


def cmd_url(args):
    """다운로드 URL 생성"""
    storage = get_storage(args.config)
    
    expires_in = args.expires * 3600  # 시간 -> 초
    url = storage.get_download_url(args.key, expires_in=expires_in)
    
    if url:
        console.print(Panel.fit(
            f"[bold]파일:[/bold] {args.key}\n"
            f"[bold]유효 시간:[/bold] {args.expires}시간\n\n"
            f"[green]{url}[/green]",
            title="다운로드 URL",
            border_style="green"
        ))
    else:
        console.print("[red]URL 생성 실패[/red]")


def cmd_delete(args):
    """파일 삭제"""
    storage = get_storage(args.config)
    
    if not args.force:
        # 파일 정보 확인
        info = storage.get_file_info(args.key)
        if info:
            console.print(f"파일: {args.key}")
            console.print(f"크기: {info['size_formatted']}")
        
        confirm = console.input(f"\n[yellow]정말 삭제하시겠습니까? (y/N): [/yellow]")
        if confirm.lower() != 'y':
            console.print("취소됨")
            return
    
    if storage.delete_file(args.key):
        console.print(f"[green]✅ 삭제됨: {args.key}[/green]")
    else:
        console.print("[red]❌ 삭제 실패[/red]")


def cmd_info(args):
    """파일 정보 조회"""
    storage = get_storage(args.config)
    
    info = storage.get_file_info(args.key)
    
    if not info:
        console.print(f"[red]파일을 찾을 수 없습니다: {args.key}[/red]")
        return
    
    console.print(Panel.fit(
        f"[bold]파일:[/bold] {info['key']}\n"
        f"[bold]크기:[/bold] {info['size_formatted']}\n"
        f"[bold]타입:[/bold] {info['content_type']}\n"
        f"[bold]수정일:[/bold] {info['last_modified']}\n"
        f"[bold]ETag:[/bold] {info['etag']}\n"
        f"[bold]메타데이터:[/bold] {info['metadata']}",
        title="파일 정보",
        border_style="blue"
    ))


def main():
    parser = argparse.ArgumentParser(
        description="Cloudflare R2 관리 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  %(prog)s test                          연결 테스트
  %(prog)s list                          모든 파일 목록
  %(prog)s list --user username          특정 유저 파일만
  %(prog)s usage                         사용량 확인
  %(prog)s info path/to/file.mp4         파일 정보
  %(prog)s url path/to/file.mp4          다운로드 URL 생성
  %(prog)s download path/to/file.mp4     파일 다운로드
  %(prog)s delete path/to/file.mp4       파일 삭제
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        default='config/settings.yaml',
        help='설정 파일 경로'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='명령')
    
    # test
    sub_test = subparsers.add_parser('test', help='연결 테스트')
    sub_test.set_defaults(func=cmd_test)
    
    # list
    sub_list = subparsers.add_parser('list', help='파일 목록')
    sub_list.add_argument('--user', '-u', help='특정 유저만 필터링')
    sub_list.add_argument('--limit', '-l', type=int, default=100, help='최대 표시 수')
    sub_list.set_defaults(func=cmd_list)
    
    # usage
    sub_usage = subparsers.add_parser('usage', help='사용량 확인')
    sub_usage.set_defaults(func=cmd_usage)
    
    # info
    sub_info = subparsers.add_parser('info', help='파일 정보')
    sub_info.add_argument('key', help='R2 파일 경로')
    sub_info.set_defaults(func=cmd_info)
    
    # download
    sub_download = subparsers.add_parser('download', help='파일 다운로드')
    sub_download.add_argument('key', help='R2 파일 경로')
    sub_download.add_argument('-o', '--output', help='저장할 로컬 경로')
    sub_download.set_defaults(func=cmd_download)
    
    # url
    sub_url = subparsers.add_parser('url', help='다운로드 URL 생성')
    sub_url.add_argument('key', help='R2 파일 경로')
    sub_url.add_argument('-e', '--expires', type=int, default=1, help='유효 시간 (시간, 기본: 1)')
    sub_url.set_defaults(func=cmd_url)
    
    # delete
    sub_delete = subparsers.add_parser('delete', help='파일 삭제')
    sub_delete.add_argument('key', help='R2 파일 경로')
    sub_delete.add_argument('-f', '--force', action='store_true', help='확인 없이 삭제')
    sub_delete.set_defaults(func=cmd_delete)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
