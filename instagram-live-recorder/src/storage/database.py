"""
SQLite 데이터베이스 - 녹화 이력 및 통계 저장

테이블:
- recordings: 녹화 이력
- daily_stats: 일일 통계
- live_detections: 라이브 감지 이력
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class RecordingRecord:
    """녹화 기록"""
    id: Optional[int] = None
    broadcast_id: str = ""
    username: str = ""
    display_name: str = ""
    title: str = ""
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    file_path: str = ""
    file_size: int = 0
    status: str = "completed"  # completed, failed, interrupted
    error_message: str = ""
    cloud_uploaded: bool = False
    cloud_url: str = ""
    retry_count: int = 0
    created_at: Optional[datetime] = None


@dataclass
class DailyStats:
    """일일 통계"""
    date: str = ""
    total_checks: int = 0
    lives_detected: int = 0
    recordings_completed: int = 0
    recordings_failed: int = 0
    total_duration_seconds: int = 0
    total_size_bytes: int = 0


class Database:
    """SQLite 데이터베이스 관리"""

    def __init__(self, db_path: str = "data/recorder.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """스레드별 연결 가져오기"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    @contextmanager
    def _cursor(self):
        """커서 컨텍스트 매니저"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def _init_db(self):
        """데이터베이스 초기화"""
        with self._cursor() as cursor:
            # 녹화 이력 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broadcast_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    title TEXT,
                    started_at TIMESTAMP,
                    ended_at TIMESTAMP,
                    duration_seconds INTEGER DEFAULT 0,
                    file_path TEXT,
                    file_size INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    error_message TEXT,
                    cloud_uploaded BOOLEAN DEFAULT FALSE,
                    cloud_url TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 일일 통계 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    total_checks INTEGER DEFAULT 0,
                    lives_detected INTEGER DEFAULT 0,
                    recordings_completed INTEGER DEFAULT 0,
                    recordings_failed INTEGER DEFAULT 0,
                    total_duration_seconds INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 라이브 감지 이력 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broadcast_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    title TEXT,
                    viewer_count INTEGER DEFAULT 0,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    recorded BOOLEAN DEFAULT FALSE
                )
            ''')

            # 인덱스 생성
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_recordings_username ON recordings(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_recordings_started_at ON recordings(started_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_detections_username ON live_detections(username)')

        logger.info(f"데이터베이스 초기화 완료: {self.db_path}")

    # ==================== 녹화 기록 ====================

    def add_recording(self, record: RecordingRecord) -> int:
        """녹화 기록 추가"""
        with self._cursor() as cursor:
            cursor.execute('''
                INSERT INTO recordings (
                    broadcast_id, username, display_name, title,
                    started_at, ended_at, duration_seconds,
                    file_path, file_size, status, error_message,
                    cloud_uploaded, cloud_url, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.broadcast_id,
                record.username,
                record.display_name,
                record.title,
                record.started_at,
                record.ended_at,
                record.duration_seconds,
                record.file_path,
                record.file_size,
                record.status,
                record.error_message,
                record.cloud_uploaded,
                record.cloud_url,
                record.retry_count
            ))
            return cursor.lastrowid

    def update_recording(self, record_id: int, **kwargs):
        """녹화 기록 업데이트"""
        if not kwargs:
            return

        set_clause = ', '.join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [record_id]

        with self._cursor() as cursor:
            cursor.execute(
                f'UPDATE recordings SET {set_clause} WHERE id = ?',
                values
            )

    def get_recording(self, record_id: int) -> Optional[RecordingRecord]:
        """녹화 기록 조회"""
        with self._cursor() as cursor:
            cursor.execute('SELECT * FROM recordings WHERE id = ?', (record_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_recording(row)
        return None

    def get_recordings_by_username(
        self,
        username: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[RecordingRecord]:
        """유저별 녹화 기록 조회"""
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT * FROM recordings
                WHERE username = ?
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
            ''', (username, limit, offset))
            return [self._row_to_recording(row) for row in cursor.fetchall()]

    def get_recent_recordings(
        self,
        limit: int = 50,
        status: str = None
    ) -> List[RecordingRecord]:
        """최근 녹화 기록 조회"""
        with self._cursor() as cursor:
            if status:
                cursor.execute('''
                    SELECT * FROM recordings
                    WHERE status = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                ''', (status, limit))
            else:
                cursor.execute('''
                    SELECT * FROM recordings
                    ORDER BY started_at DESC
                    LIMIT ?
                ''', (limit,))
            return [self._row_to_recording(row) for row in cursor.fetchall()]

    def get_failed_recordings_for_retry(
        self,
        max_retries: int = 3,
        since_hours: int = 24
    ) -> List[RecordingRecord]:
        """재시도할 실패한 녹화 조회"""
        since = datetime.now() - timedelta(hours=since_hours)
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT * FROM recordings
                WHERE status = 'failed'
                AND retry_count < ?
                AND started_at > ?
                ORDER BY started_at DESC
            ''', (max_retries, since))
            return [self._row_to_recording(row) for row in cursor.fetchall()]

    def _row_to_recording(self, row: sqlite3.Row) -> RecordingRecord:
        """Row를 RecordingRecord로 변환"""
        return RecordingRecord(
            id=row['id'],
            broadcast_id=row['broadcast_id'],
            username=row['username'],
            display_name=row['display_name'],
            title=row['title'],
            started_at=self._parse_datetime(row['started_at']),
            ended_at=self._parse_datetime(row['ended_at']),
            duration_seconds=row['duration_seconds'],
            file_path=row['file_path'],
            file_size=row['file_size'],
            status=row['status'],
            error_message=row['error_message'] or "",
            cloud_uploaded=bool(row['cloud_uploaded']),
            cloud_url=row['cloud_url'] or "",
            retry_count=row['retry_count'],
            created_at=self._parse_datetime(row['created_at'])
        )

    # ==================== 라이브 감지 ====================

    def add_live_detection(
        self,
        broadcast_id: str,
        username: str,
        display_name: str = "",
        title: str = "",
        viewer_count: int = 0
    ) -> int:
        """라이브 감지 기록 추가"""
        with self._cursor() as cursor:
            cursor.execute('''
                INSERT INTO live_detections (
                    broadcast_id, username, display_name, title, viewer_count
                ) VALUES (?, ?, ?, ?, ?)
            ''', (broadcast_id, username, display_name, title, viewer_count))
            return cursor.lastrowid

    def mark_live_recorded(self, broadcast_id: str):
        """라이브 녹화 완료 표시"""
        with self._cursor() as cursor:
            cursor.execute('''
                UPDATE live_detections
                SET recorded = TRUE
                WHERE broadcast_id = ?
            ''', (broadcast_id,))

    # ==================== 일일 통계 ====================

    def update_daily_stats(
        self,
        checks: int = 0,
        lives_detected: int = 0,
        completed: int = 0,
        failed: int = 0,
        duration: int = 0,
        size: int = 0
    ):
        """오늘의 통계 업데이트 (증분)"""
        today = datetime.now().strftime('%Y-%m-%d')

        with self._cursor() as cursor:
            cursor.execute('''
                INSERT INTO daily_stats (
                    date, total_checks, lives_detected,
                    recordings_completed, recordings_failed,
                    total_duration_seconds, total_size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_checks = total_checks + excluded.total_checks,
                    lives_detected = lives_detected + excluded.lives_detected,
                    recordings_completed = recordings_completed + excluded.recordings_completed,
                    recordings_failed = recordings_failed + excluded.recordings_failed,
                    total_duration_seconds = total_duration_seconds + excluded.total_duration_seconds,
                    total_size_bytes = total_size_bytes + excluded.total_size_bytes,
                    updated_at = CURRENT_TIMESTAMP
            ''', (today, checks, lives_detected, completed, failed, duration, size))

    def get_daily_stats(self, date: str = None) -> Optional[DailyStats]:
        """일일 통계 조회"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        with self._cursor() as cursor:
            cursor.execute(
                'SELECT * FROM daily_stats WHERE date = ?',
                (date,)
            )
            row = cursor.fetchone()
            if row:
                return DailyStats(
                    date=row['date'],
                    total_checks=row['total_checks'],
                    lives_detected=row['lives_detected'],
                    recordings_completed=row['recordings_completed'],
                    recordings_failed=row['recordings_failed'],
                    total_duration_seconds=row['total_duration_seconds'],
                    total_size_bytes=row['total_size_bytes']
                )
        return None

    def get_stats_range(
        self,
        start_date: str,
        end_date: str
    ) -> List[DailyStats]:
        """기간별 통계 조회"""
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT * FROM daily_stats
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
            ''', (start_date, end_date))
            return [
                DailyStats(
                    date=row['date'],
                    total_checks=row['total_checks'],
                    lives_detected=row['lives_detected'],
                    recordings_completed=row['recordings_completed'],
                    recordings_failed=row['recordings_failed'],
                    total_duration_seconds=row['total_duration_seconds'],
                    total_size_bytes=row['total_size_bytes']
                )
                for row in cursor.fetchall()
            ]

    def get_total_stats(self) -> Dict[str, Any]:
        """전체 통계 조회"""
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT
                    COUNT(*) as total_recordings,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(duration_seconds) as total_duration,
                    SUM(file_size) as total_size,
                    COUNT(DISTINCT username) as unique_users
                FROM recordings
            ''')
            row = cursor.fetchone()

            return {
                'total_recordings': row['total_recordings'] or 0,
                'completed': row['completed'] or 0,
                'failed': row['failed'] or 0,
                'total_duration_seconds': row['total_duration'] or 0,
                'total_size_bytes': row['total_size'] or 0,
                'unique_users': row['unique_users'] or 0
            }

    # ==================== 유틸리티 ====================

    def _parse_datetime(self, value) -> Optional[datetime]:
        """datetime 파싱"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except:
            return None

    def close(self):
        """연결 종료"""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


def create_database(config) -> Database:
    """설정에서 데이터베이스 생성"""
    db_path = getattr(config, 'db_path', 'data/recorder.db')
    return Database(db_path)
