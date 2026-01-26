# Instagram Story Saver - 아키텍처 문서

## 목차
1. [프로젝트 개요](#프로젝트-개요)
2. [전체 구조](#전체-구조)
3. [디렉토리 구조](#디렉토리-구조)
4. [모듈별 상세 설명](#모듈별-상세-설명)
5. [파일간 연관성](#파일간-연관성)
6. [작동 원리](#작동-원리)
7. [데이터 흐름](#데이터-흐름)
8. [설정 시스템](#설정-시스템)
9. [이벤트 시스템](#이벤트-시스템)
10. [보안 아키텍처](#보안-아키텍처)

---

## 프로젝트 개요

Instagram Story Saver는 지정된 Instagram 유저의 스토리를 자동으로 감지하고 저장하는 Python 애플리케이션입니다.

### 주요 기능
- Instagram 스토리 실시간 모니터링
- 자동 다운로드 (이미지/비디오)
- 중복 다운로드 방지
- Discord/Telegram 알림
- Cloudflare R2 클라우드 백업
- SQLite 데이터베이스 기록
- 일일 요약 리포트

### 기술 스택
- **언어**: Python 3.11+
- **Instagram API**: instagrapi
- **스케줄링**: APScheduler
- **데이터베이스**: SQLite
- **클라우드**: Cloudflare R2 (S3 호환)
- **알림**: Discord Webhook, Telegram Bot API

---

## 전체 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│                   (InstagramStorySaver)                         │
│    ┌─────────────────────────────────────────────────────────┐  │
│    │                    APScheduler                           │  │
│    │         (check_stories, daily_summary)                   │  │
│    └─────────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   src/auth    │  │  src/monitor  │  │ src/downloader│
│               │  │               │  │               │
│ InstagramAuth │→│ StoryMonitor  │→│StoryDownloader│
│SessionManager │  │ DownloadHist.│  │ DownloadTask  │
└───────────────┘  └───────────────┘  └───────┬───────┘
                                              │
        ┌───────────────────┬─────────────────┤
        │                   │                 │
        ▼                   ▼                 ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ src/notifier  │  │  src/storage  │  │  src/storage  │
│               │  │   (database)  │  │    (cloud)    │
│DiscordNotifier│  │   Database    │  │ CloudStorage  │
│TelegramNotif. │  │ DownloadRecord│  │  (R2 Upload)  │
└───────────────┘  └───────────────┘  └───────────────┘
        │                   │                 │
        └───────────────────┴─────────────────┘
                            │
                            ▼
                   ┌───────────────┐
                   │  src/utils    │
                   │               │
                   │    Config     │
                   │    Logger     │
                   └───────────────┘
```

---

## 디렉토리 구조

```
instagram-story-saver/
├── main.py                          # 애플리케이션 진입점
├── requirements.txt                 # Python 의존성
├── .gitignore                       # Git 제외 파일
│
├── config/                          # 설정 파일
│   ├── settings.example.yaml        # 설정 템플릿
│   ├── settings.yaml               # 실제 설정 (gitignore)
│   ├── targets.example.json        # 타겟 유저 템플릿
│   └── targets.json                # 실제 타겟 목록 (gitignore)
│
├── src/                            # 소스 코드
│   ├── __init__.py
│   │
│   ├── utils/                      # 유틸리티 모듈
│   │   ├── __init__.py
│   │   ├── config.py               # 설정 로더
│   │   └── logger.py               # 로깅 설정
│   │
│   ├── auth/                       # 인증 모듈
│   │   ├── __init__.py
│   │   └── instagram_auth.py       # Instagram 로그인/세션 관리
│   │
│   ├── monitor/                    # 모니터링 모듈
│   │   ├── __init__.py
│   │   └── story_monitor.py        # 스토리 감지
│   │
│   ├── downloader/                 # 다운로더 모듈
│   │   ├── __init__.py
│   │   └── story_downloader.py     # 미디어 다운로드
│   │
│   ├── notifier/                   # 알림 모듈
│   │   ├── __init__.py
│   │   ├── discord_notifier.py     # Discord 알림
│   │   └── telegram_notifier.py    # Telegram 알림
│   │
│   └── storage/                    # 저장소 모듈
│       ├── __init__.py
│       ├── database.py             # SQLite 데이터베이스
│       └── cloud_storage.py        # Cloudflare R2 업로드
│
├── data/                           # 데이터 디렉토리 (gitignore)
│   ├── sessions/                   # 세션 파일
│   │   └── session.json
│   ├── stories/                    # 다운로드된 스토리
│   │   └── {username}/
│   ├── logs/                       # 로그 파일
│   │   └── story_saver.log
│   ├── download_history.json       # 다운로드 기록
│   └── story_saver.db              # SQLite 데이터베이스
│
├── docs/                           # 문서
│   ├── ARCHITECTURE.md             # 아키텍처 문서 (이 파일)
│   └── SECURITY.md                 # 보안 가이드
│
├── scripts/                        # 스크립트
│   └── deploy.sh                   # 배포 스크립트
│
└── .github/
    └── workflows/
        └── deploy.yml              # GitHub Actions CI/CD
```

---

## 모듈별 상세 설명

### 1. main.py - 메인 애플리케이션

**역할**: 전체 애플리케이션 오케스트레이션

**주요 클래스**:
```python
class InstagramStorySaver:
    """Instagram 스토리 자동 저장기"""

    # 주요 컴포넌트
    config: Config              # 설정
    auth: InstagramAuth         # 인증
    session_manager: SessionManager  # 세션 관리
    monitor: StoryMonitor       # 스토리 모니터
    downloader: StoryDownloader # 다운로더
    notifier: DiscordNotifier   # 알림
    database: Database          # 데이터베이스
    cloud_storage: CloudStorage # 클라우드 저장소
    scheduler: BlockingScheduler # 스케줄러
```

**핵심 메서드**:
| 메서드 | 설명 |
|--------|------|
| `initialize()` | 모든 컴포넌트 초기화 |
| `start()` | 모니터링 시작 (스케줄러 실행) |
| `stop()` | 안전한 종료 |
| `_check_stories()` | 스토리 체크 (스케줄러 호출) |
| `_send_daily_summary()` | 일일 요약 전송 |
| `_register_callbacks()` | 이벤트 콜백 등록 |

**CLI 옵션**:
```bash
python main.py                  # 정상 실행
python main.py --test-login     # 로그인 테스트
python main.py --test-discord   # Discord 알림 테스트
python main.py --once           # 한 번만 체크
python main.py -c path/to/config.yaml  # 설정 파일 지정
```

---

### 2. src/utils/config.py - 설정 관리

**역할**: YAML 설정 파일 로드 및 환경 변수 처리

**주요 클래스**:
```python
@dataclass
class TargetUser:
    """모니터링 대상 유저"""
    username: str
    user_id: Optional[int]
    alias: Optional[str]
    priority: str  # high, normal, low
    enabled: bool

@dataclass
class Config:
    """전체 설정"""
    # Instagram, Monitor, Downloader, Cloud, Notifications 등
```

**환경 변수 지원**:
```yaml
# settings.yaml에서 환경 변수 참조
instagram:
  username: "${IG_USERNAME}"
  password: "${IG_PASSWORD}"
```

**지원 환경 변수**:
| 변수명 | 설명 |
|--------|------|
| `IG_USERNAME` | Instagram 사용자명 |
| `IG_PASSWORD` | Instagram 비밀번호 |
| `IG_TOTP_SECRET` | 2FA TOTP 시크릿 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot 토큰 |
| `TELEGRAM_CHAT_ID` | Telegram 채팅 ID |
| `R2_ACCOUNT_ID` | Cloudflare Account ID |
| `R2_ACCESS_KEY` | R2 Access Key |
| `R2_SECRET_KEY` | R2 Secret Key |

---

### 3. src/auth/instagram_auth.py - Instagram 인증

**역할**: Instagram 로그인 및 세션 관리

**주요 클래스**:
```python
class InstagramAuth:
    """Instagram 인증 관리"""

    def login() -> bool          # 로그인 (세션 우선)
    def relogin() -> bool        # 강제 재로그인
    def is_logged_in() -> bool   # 로그인 상태 확인
    def get_client() -> Client   # instagrapi Client 반환

class SessionManager:
    """세션 상태 관리 및 자동 복구"""

    def ensure_logged_in() -> bool  # 로그인 보장
    def handle_api_error(error)     # API 에러 처리
```

**로그인 플로우**:
```
1. 세션 파일 존재 확인
   └─ 존재 → 세션 로드 시도
      └─ 성공 → 완료
      └─ 실패 (만료) → 새 로그인
   └─ 없음 → 새 로그인

2. 새 로그인
   └─ TOTP 설정 있음 → 2FA 코드 생성
   └─ 로그인 시도
      └─ 성공 → 세션 저장, 권한 설정 (600)
      └─ 실패 → 에러 반환
```

**에러 처리**:
| 에러 | 처리 |
|------|------|
| `LoginRequired` | 세션 만료, 재로그인 |
| `TwoFactorRequired` | TOTP 필요 |
| `ChallengeRequired` | 수동 보안 확인 필요 |
| `BadPassword` | 비밀번호 오류 |
| `PleaseWaitFewMinutes` | 쿨다운 대기 |

---

### 4. src/monitor/story_monitor.py - 스토리 모니터링

**역할**: 타겟 유저의 스토리 감지

**주요 클래스**:
```python
@dataclass
class StoryItem:
    """스토리 아이템 정보"""
    story_id: str
    username: str
    display_name: str
    media_type: int      # 1: 이미지, 2: 비디오
    video_url: str
    image_url: str
    taken_at: datetime
    expire_at: datetime

class DownloadHistory:
    """다운로드 기록 관리 (중복 방지)"""

    def is_downloaded(story_id) -> bool  # 다운로드 여부
    def mark_downloaded(story_id)        # 다운로드 완료 표시
    def cleanup()                        # 만료 기록 정리

class StoryMonitor:
    """스토리 모니터링 (개별 유저 조회)"""

class StoryMonitorV2(StoryMonitor):
    """개선된 모니터 - Reels Tray 기반"""
```

**모니터링 방식 비교**:
| 방식 | StoryMonitor | StoryMonitorV2 |
|------|--------------|----------------|
| API 호출 | 유저당 1회 | 전체 1회 |
| 효율성 | 낮음 | 높음 |
| 커버리지 | 모든 타겟 | 팔로잉만 |
| Fallback | - | StoryMonitor로 폴백 |

**이벤트**:
| 이벤트 | 발생 시점 |
|--------|----------|
| `on_new_story` | 새 스토리 감지 |
| `on_error` | 에러 발생 |

---

### 5. src/downloader/story_downloader.py - 미디어 다운로드

**역할**: 스토리 미디어 파일 다운로드

**주요 클래스**:
```python
@dataclass
class DownloadTask:
    """다운로드 작업"""
    story: StoryItem
    output_path: Path
    status: str  # pending, downloading, completed, failed
    file_size: int
    error_message: str

class StoryDownloader:
    """스토리 다운로더"""

    def download(story) -> DownloadTask  # 다운로드 시작
    def stop_all()                       # 모든 다운로드 중지
    def get_stats() -> Dict              # 통계 조회
```

**다운로드 플로우**:
```
1. download(story) 호출
   └─ 중복 체크 (active_downloads)
   └─ 동시 다운로드 수 확인
      └─ 초과 → 대기열에 추가
      └─ 미만 → 즉시 시작

2. _start_download(story)
   └─ 디스크 공간 확인
   └─ URL 보안 검증
   └─ 출력 경로 생성
   └─ ThreadPoolExecutor로 백그라운드 다운로드

3. _download_file(task)
   └─ 재시도 로직 (max_retries)
   └─ 청크 단위 스트리밍 다운로드
   └─ 원자적 쓰기 (.tmp → 최종 파일)
   └─ 이벤트 발생 (complete/failed)
```

**이벤트**:
| 이벤트 | 발생 시점 |
|--------|----------|
| `on_download_start` | 다운로드 시작 |
| `on_download_complete` | 다운로드 완료 |
| `on_download_failed` | 다운로드 실패 |

**보안 기능**:
- URL 도메인 화이트리스트 검증
- HTTPS 강제
- 디스크 공간 모니터링

---

### 6. src/notifier/ - 알림 모듈

#### discord_notifier.py

**역할**: Discord Webhook을 통한 알림

**주요 클래스**:
```python
class DiscordNotifier:
    """Discord 알림 서비스"""

    def notify_new_story(story)           # 새 스토리 알림
    def notify_download_complete(task)    # 다운로드 완료 알림
    def notify_download_failed(task)      # 다운로드 실패 알림
    def notify_daily_summary(stats)       # 일일 요약
    def notify_startup(target_count)      # 시작 알림
    def notify_shutdown(stats)            # 종료 알림
    def notify_error(message)             # 에러 알림
```

**특징**:
- 비동기 메시지 큐 (백그라운드 전송)
- Rich Embed 메시지
- 색상 코드: 빨강(에러), 초록(성공), 파랑(정보)
- 재시도 로직

#### telegram_notifier.py

**역할**: Telegram Bot API를 통한 알림

동일한 인터페이스, Telegram 전용 포맷팅

---

### 7. src/storage/ - 저장소 모듈

#### database.py

**역할**: SQLite 데이터베이스 관리

**테이블 구조**:
```sql
-- 다운로드 기록
CREATE TABLE downloads (
    id INTEGER PRIMARY KEY,
    story_id TEXT UNIQUE,
    username TEXT,
    display_name TEXT,
    media_type TEXT,      -- 'video' or 'image'
    file_path TEXT,
    file_size INTEGER,
    downloaded_at TIMESTAMP,
    taken_at TIMESTAMP,
    cloud_url TEXT,
    status TEXT,          -- 'completed' or 'failed'
    error_message TEXT
);

-- 일일 통계
CREATE TABLE daily_stats (
    id INTEGER PRIMARY KEY,
    date DATE UNIQUE,
    total_checks INTEGER,
    stories_detected INTEGER,
    downloads_completed INTEGER,
    downloads_failed INTEGER,
    total_size_bytes INTEGER
);

-- 스토리 감지 기록
CREATE TABLE story_detections (
    id INTEGER PRIMARY KEY,
    story_id TEXT UNIQUE,
    username TEXT,
    display_name TEXT,
    media_type TEXT,
    taken_at TIMESTAMP,
    detected_at TIMESTAMP
);
```

**주요 메서드**:
```python
class Database:
    def add_download(record)          # 다운로드 기록 추가
    def add_story_detection(story)    # 감지 기록 추가
    def update_daily_stats(...)       # 일일 통계 업데이트
    def get_daily_stats(date)         # 일일 통계 조회
    def is_story_downloaded(id)       # 다운로드 여부 확인
    def get_total_stats()             # 전체 통계
```

**보안**: SQL 인젝션 방지를 위한 필드명 화이트리스트 적용

#### cloud_storage.py

**역할**: Cloudflare R2 클라우드 업로드

**주요 클래스**:
```python
class CloudStorage:
    """Cloudflare R2 저장소"""

    def upload_story(task)     # 스토리 업로드
    def upload_file(path, key) # 파일 업로드
    def delete_file(key)       # 파일 삭제
    def get_public_url(key)    # 공개 URL 반환
```

**특징**:
- boto3 S3 호환 API 사용
- 멀티파트 업로드 지원 (대용량 파일)
- 업로드 후 로컬 삭제 옵션

---

## 파일간 연관성

### 의존성 그래프

```
main.py
├── src/utils/config.py          [설정 로드]
├── src/utils/logger.py          [로깅]
├── src/auth/instagram_auth.py   [인증]
│   └── src/utils/logger.py
├── src/monitor/story_monitor.py [모니터링]
│   ├── src/utils/logger.py
│   └── src/utils/config.py      [TargetUser, save_targets]
├── src/downloader/story_downloader.py [다운로드]
│   ├── src/utils/logger.py
│   └── src/monitor/story_monitor.py [StoryItem, DownloadHistory]
├── src/notifier/discord_notifier.py [Discord 알림]
│   └── src/utils/logger.py
├── src/notifier/telegram_notifier.py [Telegram 알림]
│   └── src/utils/logger.py
├── src/storage/database.py      [데이터베이스]
│   └── src/utils/logger.py
└── src/storage/cloud_storage.py [클라우드]
    └── src/utils/logger.py
```

### 데이터 타입 공유

| 타입 | 정의 위치 | 사용 위치 |
|------|----------|----------|
| `Config` | config.py | main.py, 모든 모듈 |
| `TargetUser` | config.py | monitor, main.py |
| `StoryItem` | story_monitor.py | downloader, notifier, main.py |
| `DownloadTask` | story_downloader.py | notifier, storage, main.py |
| `DownloadHistory` | story_monitor.py | downloader |
| `DownloadRecord` | database.py | main.py |

---

## 작동 원리

### 초기화 시퀀스

```
1. 설정 로드 (config.py)
   ├─ YAML 파일 파싱
   ├─ 환경 변수 치환
   └─ 타겟 유저 로드 (targets.json)

2. 로거 설정 (logger.py)
   └─ 파일 로테이션 설정

3. 다운로드 히스토리 로드 (story_monitor.py)
   └─ JSON 파일에서 기록 복원

4. Instagram 로그인 (instagram_auth.py)
   ├─ 세션 로드 시도
   └─ 실패 시 새 로그인

5. 모니터 초기화 (story_monitor.py)
   └─ 유저 ID 조회 (username → user_id)

6. 다운로더 초기화 (story_downloader.py)
   ├─ 출력 디렉토리 생성
   └─ ThreadPoolExecutor 시작

7. 데이터베이스 초기화 (database.py)
   └─ 테이블 생성 (없으면)

8. 알림 서비스 초기화 (discord/telegram)
   └─ 워커 스레드 시작

9. 클라우드 저장소 초기화 (cloud_storage.py)
   └─ boto3 클라이언트 생성

10. 이벤트 콜백 등록
    └─ 모니터 ↔ 다운로더 ↔ 알림 연결
```

### 메인 루프

```
┌─────────────────────────────────────────────────┐
│                 APScheduler                      │
│                                                  │
│  ┌──────────────────┐  ┌──────────────────────┐ │
│  │  check_stories   │  │   daily_summary      │ │
│  │  (30분 간격)      │  │   (매일 23:00)       │ │
│  └────────┬─────────┘  └──────────┬───────────┘ │
└───────────┼──────────────────────┼──────────────┘
            │                      │
            ▼                      ▼
     ┌──────────────┐       ┌──────────────┐
     │ _check_stories│       │_send_daily_  │
     │              │       │   summary    │
     └──────┬───────┘       └──────┬───────┘
            │                      │
            ▼                      ▼
    ┌───────────────┐      ┌───────────────┐
    │세션 유효성 확인 │      │ DB에서 통계   │
    │(SessionManager)│      │   조회        │
    └───────┬───────┘      └───────┬───────┘
            │                      │
            ▼                      ▼
    ┌───────────────┐      ┌───────────────┐
    │ 스토리 체크   │      │ 알림 서비스   │
    │ (StoryMonitor)│      │   전송        │
    └───────┬───────┘      └───────────────┘
            │
            ▼ (새 스토리 발견)
    ┌───────────────┐
    │  on_new_story │
    │   콜백 실행   │
    └───────┬───────┘
            │
    ┌───────┴───────────┬───────────────┐
    │                   │               │
    ▼                   ▼               ▼
┌─────────┐      ┌─────────┐     ┌─────────┐
│DB 기록  │      │  알림   │     │다운로드 │
│(감지)   │      │  전송   │     │  시작   │
└─────────┘      └─────────┘     └────┬────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
                    ▼ (완료)                            ▼ (실패)
            ┌───────────────┐                  ┌───────────────┐
            │on_download_   │                  │on_download_   │
            │   complete    │                  │   failed      │
            └───────┬───────┘                  └───────┬───────┘
                    │                                   │
    ┌───────────────┼───────────────┐                   │
    │               │               │                   │
    ▼               ▼               ▼                   ▼
┌─────────┐  ┌─────────┐    ┌─────────┐         ┌─────────┐
│DB 기록  │  │  알림   │    │클라우드 │         │DB 기록  │
│(완료)   │  │  전송   │    │ 업로드  │         │(실패)   │
└─────────┘  └─────────┘    └─────────┘         └─────────┘
```

---

## 데이터 흐름

### 스토리 감지부터 저장까지

```
Instagram API
     │
     ▼
┌─────────────────┐
│  Reels Tray API │  ← StoryMonitorV2._get_reels_tray()
│  또는           │
│  user_stories() │  ← StoryMonitor._check_user_stories()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   StoryItem     │  ← story_monitor.py
│   객체 생성      │
│  ─────────────  │
│  story_id       │
│  username       │
│  media_url      │
│  taken_at       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  중복 체크      │  ← DownloadHistory.is_downloaded()
│  (history.json) │
└────────┬────────┘
         │ 새 스토리
         ▼
┌─────────────────┐
│ on_new_story    │  ← main.py 콜백
│    이벤트       │
└────────┬────────┘
         │
    ┌────┴────┬─────────────┐
    │         │             │
    ▼         ▼             ▼
┌───────┐ ┌───────┐   ┌───────────┐
│ DB    │ │ 알림  │   │ 다운로드  │
│ 기록  │ │ 전송  │   │   시작    │
└───────┘ └───────┘   └─────┬─────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  URL 검증     │  ← validate_media_url()
                    │  (보안 체크)   │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ HTTP 다운로드 │  ← requests.Session
                    │ (스트리밍)    │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ 파일 저장     │
                    │ data/stories/ │
                    │ {username}/   │
                    └───────┬───────┘
                            │
               ┌────────────┴────────────┐
               │                         │
               ▼                         ▼
        ┌───────────┐            ┌───────────┐
        │ 클라우드  │            │ 히스토리  │
        │ 업로드    │            │ 기록      │
        │ (선택적)  │            │ (JSON)    │
        └───────────┘            └───────────┘
```

### 설정 데이터 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                    환경 변수                                 │
│  IG_USERNAME, IG_PASSWORD, DISCORD_WEBHOOK_URL, etc.       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│               config/settings.yaml                          │
│  ───────────────────────────────────────────────────────── │
│  instagram:                                                 │
│    username: "${IG_USERNAME}"   ← 환경 변수 치환            │
│    password: "${IG_PASSWORD}"                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│            config.py - load_config()                        │
│  ───────────────────────────────────────────────────────── │
│  1. YAML 파일 로드                                          │
│  2. _resolve_value()로 환경 변수 치환                        │
│  3. Config 객체 생성 및 검증                                 │
│  4. load_targets()로 타겟 유저 로드                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Config 객체                                │
│  ───────────────────────────────────────────────────────── │
│  ig_username, ig_password, check_interval, targets, ...    │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┬───────────────┐
         │               │               │               │
         ▼               ▼               ▼               ▼
   InstagramAuth    StoryMonitor   StoryDownloader   Notifier
```

---

## 설정 시스템

### 설정 우선순위

```
1. 환경 변수 (최우선)
   └─ IG_USERNAME=xxx 형태로 설정

2. YAML 파일 내 환경 변수 참조
   └─ username: "${IG_USERNAME}"

3. YAML 파일 직접 값
   └─ check_interval: 1800

4. 기본값 (Config 클래스)
   └─ check_interval: int = 1800
```

### 설정 검증

```python
# Config.__post_init__()에서 수행

# 필수 값 확인
if not self.ig_username:
    errors.append("instagram.username은 필수입니다")

# 범위 검증
if self.check_interval < 300:  # 최소 5분
    errors.append("check_interval은 최소 300초 이상")

# 조건부 검증
if self.cloud_enabled and not self.r2_account_id:
    errors.append("R2 사용 시 account_id 필수")
```

---

## 이벤트 시스템

### 이벤트 기반 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Event Emitter 패턴                        │
│                                                             │
│  class StoryMonitor:                                        │
│      _callbacks = {'on_new_story': [], 'on_error': []}     │
│                                                             │
│      def on(event, callback):                               │
│          _callbacks[event].append(callback)                 │
│                                                             │
│      def _emit(event, *args):                               │
│          for cb in _callbacks[event]:                       │
│              cb(*args)                                      │
└─────────────────────────────────────────────────────────────┘
```

### 이벤트 흐름

```
StoryMonitor                    main.py                     다른 컴포넌트
─────────────                   ───────                     ───────────────
     │                              │                              │
     │  on('on_new_story', cb)      │                              │
     │ ◄────────────────────────────│                              │
     │                              │                              │
     │ [새 스토리 감지]              │                              │
     │                              │                              │
     │  _emit('on_new_story', story)│                              │
     │ ─────────────────────────────►                              │
     │                              │                              │
     │                              │  notifier.notify_new_story() │
     │                              │ ────────────────────────────►│
     │                              │                              │
     │                              │  downloader.download()       │
     │                              │ ────────────────────────────►│
     │                              │                              │
     │                              │  database.add_detection()    │
     │                              │ ────────────────────────────►│
```

---

## 보안 아키텍처

### 민감 정보 보호

```
┌─────────────────────────────────────────────────────────────┐
│                     보안 레이어                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 환경 변수                                                │
│     └─ 비밀번호, API 키 등은 환경 변수로 관리                 │
│                                                             │
│  2. .gitignore                                              │
│     └─ settings.yaml, targets.json, session.json 제외       │
│                                                             │
│  3. 파일 권한                                                │
│     └─ 세션 파일: chmod 600 (소유자만 읽기/쓰기)             │
│                                                             │
│  4. 로그 마스킹                                              │
│     └─ Config.mask_sensitive()로 민감정보 마스킹             │
│                                                             │
│  5. URL 검증                                                 │
│     └─ validate_media_url()로 허용 도메인만 다운로드         │
│                                                             │
│  6. SQL 인젝션 방지                                          │
│     └─ 파라미터 바인딩 + 필드명 화이트리스트                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### URL 검증 (다운로드 보안)

```python
# story_downloader.py

ALLOWED_DOMAINS = (
    'instagram.com',
    'cdninstagram.com',
    'fbcdn.net',
    'akamaized.net',
    'akamaihd.net',
)

def validate_media_url(url: str) -> bool:
    parsed = urlparse(url)

    # HTTPS 강제
    if parsed.scheme != 'https':
        raise SecurityError("HTTPS만 허용")

    # 도메인 화이트리스트
    domain = parsed.netloc.lower()
    if not any(domain.endswith(d) for d in ALLOWED_DOMAINS):
        raise SecurityError(f"허용되지 않은 도메인: {domain}")

    return True
```

### SQL 인젝션 방지

```python
# database.py

# 허용된 필드명 화이트리스트
_ALLOWED_STAT_FIELDS = frozenset([
    'total_checks', 'stories_detected', 'downloads_completed',
    'downloads_failed', 'total_size_bytes'
])

def _update_daily_stat(self, cursor, stat_date, field, increment):
    # 필드명 검증
    if field not in self._ALLOWED_STAT_FIELDS:
        raise ValueError(f"Invalid stat field: {field}")

    # 안전한 쿼리 실행
    cursor.execute(f'''
        INSERT INTO daily_stats (date, {field}) VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET {field} = {field} + ?
    ''', (stat_date.isoformat(), increment, increment))
```

---

## 확장 포인트

### 새 알림 서비스 추가

```python
# src/notifier/slack_notifier.py (예시)

class SlackNotifier:
    def __init__(self, webhook_url: str, ...):
        ...

    def notify_new_story(self, story: StoryItem): ...
    def notify_download_complete(self, task: DownloadTask): ...
    def notify_download_failed(self, task: DownloadTask): ...
    def notify_daily_summary(self, stats: Dict): ...
    def stop(self): ...
```

### 새 클라우드 저장소 추가

```python
# src/storage/s3_storage.py (예시)

class S3Storage:
    def __init__(self, bucket: str, ...):
        ...

    def upload_story(self, task: DownloadTask): ...
    def upload_file(self, local_path: Path, key: str): ...
    def get_public_url(self, key: str) -> str: ...
```

---

## 트러블슈팅

### 일반적인 문제

| 문제 | 원인 | 해결 |
|------|------|------|
| 로그인 실패 | 세션 만료 | 세션 파일 삭제 후 재시도 |
| 2FA 오류 | TOTP 시크릿 미설정 | pyotp 설치, TOTP 설정 |
| 스토리 없음 | 타겟이 팔로잉 아님 | StoryMonitorV2 폴백 확인 |
| 다운로드 실패 | 디스크 부족 | 공간 확보 |
| 알림 안옴 | Webhook URL 오류 | --test-discord로 테스트 |

### 로그 확인

```bash
# 실시간 로그
tail -f data/logs/story_saver.log

# 에러만 확인
grep ERROR data/logs/story_saver.log

# 특정 유저
grep "username" data/logs/story_saver.log
```

---

## 버전 정보

- 문서 버전: 1.0
- 최종 수정: 2026-01
- Python 요구 버전: 3.11+
