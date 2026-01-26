"""
SQLite 데이터베이스 모듈

스토리 다운로드 기록 및 통계 관리
"""
import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class DownloadRecord:
    """다운로드 기록"""
    story_id: str
    username: str
    display_name: str
    media_type: str  # 'video' or 'image'
    file_path: str
    file_size: int
    downloaded_at: datetime
    taken_at: datetime
    cloud_url: Optional[str] = None
    status: str = "completed"  # completed, failed
    error_message: Optional[str] = None
    id: Optional[int] = None


@dataclass
class DailyStats:
    """일일 통계"""
    date: date
    total_checks: int = 0
    stories_detected: int = 0
    downloads_completed: int = 0
    downloads_failed: int = 0
    total_size_bytes: int = 0
    id: Optional[int] = None

    @property
    def total_size_formatted(self) -> str:
        """읽기 쉬운 형식의 크기"""
        size = self.total_size_bytes
        if size <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class Database:
    """SQLite 데이터베이스 관리"""

    def __init__(self, db_path: str = "data/story_saver.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """스레드별 연결 가져오기"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _get_cursor(self):
        """커서 컨텍스트 매니저"""
        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            raise e
        finally:
            cursor.close()

    def _init_db(self):
        """데이터베이스 초기화"""
        with self._get_cursor() as cursor:
            # 다운로드 기록 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    media_type TEXT NOT NULL,
                    file_path TEXT,
                    file_size INTEGER DEFAULT 0,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    taken_at TIMESTAMP,
                    cloud_url TEXT,
                    status TEXT DEFAULT 'completed',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 일일 통계 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    total_checks INTEGER DEFAULT 0,
                    stories_detected INTEGER DEFAULT 0,
                    downloads_completed INTEGER DEFAULT 0,
                    downloads_failed INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 스토리 감지 기록 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS story_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    media_type TEXT,
                    taken_at TIMESTAMP,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(story_id)
                )
            ''')

            # 인덱스 생성
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_username ON downloads(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_date ON downloads(downloaded_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date)')

        logger.debug(f"데이터베이스 초기화 완료: {self.db_path}")

    def add_download(self, record: DownloadRecord) -> int:
        """다운로드 기록 추가"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT OR REPLACE INTO downloads
                (story_id, username, display_name, media_type, file_path, file_size,
                 downloaded_at, taken_at, cloud_url, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.story_id,
                record.username,
                record.display_name,
                record.media_type,
                record.file_path,
                record.file_size,
                record.downloaded_at.isoformat() if record.downloaded_at else None,
                record.taken_at.isoformat() if record.taken_at else None,
                record.cloud_url,
                record.status,
                record.error_message
            ))

            # 일일 통계 업데이트
            today = date.today()
            if record.status == 'completed':
                self._update_daily_stat(cursor, today, 'downloads_completed', 1)
                self._update_daily_stat(cursor, today, 'total_size_bytes', record.file_size)
            else:
                self._update_daily_stat(cursor, today, 'downloads_failed', 1)

            return cursor.lastrowid

    def add_story_detection(self, story) -> int:
        """스토리 감지 기록 추가"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT OR IGNORE INTO story_detections
                (story_id, username, display_name, media_type, taken_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                story.story_id,
                story.username,
                story.display_name,
                'video' if story.is_video else 'image',
                story.taken_at.isoformat() if story.taken_at else None
            ))

            # 일일 통계 업데이트
            if cursor.rowcount > 0:
                self._update_daily_stat(cursor, date.today(), 'stories_detected', 1)

            return cursor.lastrowid

    # 허용된 통계 필드 (SQL 인젝션 방지)
    _ALLOWED_STAT_FIELDS = frozenset([
        'total_checks', 'stories_detected', 'downloads_completed',
        'downloads_failed', 'total_size_bytes'
    ])

    def _update_daily_stat(self, cursor, stat_date: date, field: str, increment: int):
        """일일 통계 필드 업데이트"""
        # 필드명 화이트리스트 검증 (SQL 인젝션 방지)
        if field not in self._ALLOWED_STAT_FIELDS:
            raise ValueError(f"Invalid stat field: {field}")

        cursor.execute(f'''
            INSERT INTO daily_stats (date, {field})
            VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET
                {field} = {field} + ?,
                updated_at = CURRENT_TIMESTAMP
        ''', (stat_date.isoformat(), increment, increment))

    def update_daily_stats(
        self,
        checks: int = 0,
        stories_detected: int = 0,
        downloads_completed: int = 0,
        downloads_failed: int = 0,
        size_bytes: int = 0,
        stat_date: date = None
    ):
        """일일 통계 업데이트"""
        if stat_date is None:
            stat_date = date.today()

        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO daily_stats
                (date, total_checks, stories_detected, downloads_completed, downloads_failed, total_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_checks = total_checks + ?,
                    stories_detected = stories_detected + ?,
                    downloads_completed = downloads_completed + ?,
                    downloads_failed = downloads_failed + ?,
                    total_size_bytes = total_size_bytes + ?,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                stat_date.isoformat(),
                checks, stories_detected, downloads_completed, downloads_failed, size_bytes,
                checks, stories_detected, downloads_completed, downloads_failed, size_bytes
            ))

    def get_daily_stats(self, stat_date: date = None) -> Optional[DailyStats]:
        """일일 통계 조회"""
        if stat_date is None:
            stat_date = date.today()

        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM daily_stats WHERE date = ?
            ''', (stat_date.isoformat(),))

            row = cursor.fetchone()
            if row:
                return DailyStats(
                    id=row['id'],
                    date=datetime.fromisoformat(row['date']).date(),
                    total_checks=row['total_checks'],
                    stories_detected=row['stories_detected'],
                    downloads_completed=row['downloads_completed'],
                    downloads_failed=row['downloads_failed'],
                    total_size_bytes=row['total_size_bytes']
                )
            return None

    def get_downloads_by_user(
        self,
        username: str,
        limit: int = 100
    ) -> List[DownloadRecord]:
        """유저별 다운로드 기록 조회"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM downloads
                WHERE username = ?
                ORDER BY downloaded_at DESC
                LIMIT ?
            ''', (username, limit))

            return [self._row_to_download(row) for row in cursor.fetchall()]

    def get_recent_downloads(self, limit: int = 50) -> List[DownloadRecord]:
        """최근 다운로드 기록 조회"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM downloads
                ORDER BY downloaded_at DESC
                LIMIT ?
            ''', (limit,))

            return [self._row_to_download(row) for row in cursor.fetchall()]

    def get_download_count_by_user(self) -> Dict[str, int]:
        """유저별 다운로드 수"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT username, COUNT(*) as count
                FROM downloads
                WHERE status = 'completed'
                GROUP BY username
                ORDER BY count DESC
            ''')

            return {row['username']: row['count'] for row in cursor.fetchall()}

    def is_story_downloaded(self, story_id: str) -> bool:
        """스토리 다운로드 여부 확인"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT 1 FROM downloads
                WHERE story_id = ? AND status = 'completed'
                LIMIT 1
            ''', (story_id,))

            return cursor.fetchone() is not None

    def get_total_stats(self) -> Dict[str, Any]:
        """전체 통계"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT
                    COUNT(*) as total_downloads,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(file_size) as total_size,
                    COUNT(DISTINCT username) as unique_users
                FROM downloads
            ''')

            row = cursor.fetchone()
            return {
                'total_downloads': row['total_downloads'] or 0,
                'completed': row['completed'] or 0,
                'failed': row['failed'] or 0,
                'total_size': row['total_size'] or 0,
                'unique_users': row['unique_users'] or 0
            }

    def _row_to_download(self, row: sqlite3.Row) -> DownloadRecord:
        """Row를 DownloadRecord로 변환"""
        return DownloadRecord(
            id=row['id'],
            story_id=row['story_id'],
            username=row['username'],
            display_name=row['display_name'],
            media_type=row['media_type'],
            file_path=row['file_path'],
            file_size=row['file_size'] or 0,
            downloaded_at=datetime.fromisoformat(row['downloaded_at']) if row['downloaded_at'] else None,
            taken_at=datetime.fromisoformat(row['taken_at']) if row['taken_at'] else None,
            cloud_url=row['cloud_url'],
            status=row['status'],
            error_message=row['error_message']
        )

    def cleanup_old_records(self, days: int = 30):
        """오래된 기록 정리"""
        from datetime import timedelta
        with self._get_cursor() as cursor:
            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = cutoff - timedelta(days=days)

            cursor.execute('''
                DELETE FROM story_detections
                WHERE detected_at < ?
            ''', (cutoff.isoformat(),))

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"오래된 감지 기록 {deleted}개 삭제")

    def close(self):
        """연결 종료"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


def create_database(config) -> Optional[Database]:
    """설정에서 Database 생성"""
    db_path = getattr(config, 'db_path', 'data/story_saver.db')
    return Database(db_path=db_path)
