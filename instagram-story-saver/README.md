# Instagram Story Saver

지정된 Instagram 유저의 스토리를 자동으로 감지하고 원본 품질로 저장합니다.

## 주요 기능

- 🔍 **자동 모니터링**: 지정된 유저들의 스토리를 주기적으로 확인
- 📥 **화질 선택**: 최고 화질부터 특정 해상도까지 선택 가능
- 🔄 **중복 방지**: 이미 다운로드한 스토리는 자동으로 스킵
- 📱 **Telegram 알림**: 새 스토리 감지 및 다운로드 상태 알림
- ☁️ **클라우드 백업**: Cloudflare R2로 자동 백업 (선택사항)
- 🔐 **보안**: 환경 변수 지원, 세션 파일 권한 관리
- ⚙️ **완전한 설정**: 모든 동작 파라미터를 config에서 조절 가능

## 설치

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 설정 파일 생성

```bash
cp config/settings.example.yaml config/settings.yaml
cp config/targets.example.json config/targets.json
```

### 3. 설정 수정

`config/settings.yaml`에서 Instagram 계정 정보를 입력합니다.

```yaml
instagram:
  username: "your_username"
  password: "your_password"
```

### 4. 모니터링 대상 추가

`config/targets.json`에 스토리를 저장할 유저들을 추가합니다.

```json
{
  "targets": [
    {
      "username": "instagram_user",
      "alias": "별명 (선택)",
      "priority": "high",
      "enabled": true
    }
  ]
}
```

## 실행

### 기본 실행

```bash
python main.py
```

### 옵션

```bash
# 설정 파일 경로 지정
python main.py -c /path/to/settings.yaml

# 한 번만 체크하고 종료
python main.py --once

# 로그인 테스트
python main.py --test-login

# Telegram 알림 테스트
python main.py --test-telegram
```

## 환경 변수 지원

민감한 정보는 환경 변수로 관리할 수 있습니다:

```bash
export IG_USERNAME="your_username"
export IG_PASSWORD="your_password"
export IG_TOTP_SECRET="your_totp_secret"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export R2_ACCOUNT_ID="your_account_id"
export R2_ACCESS_KEY="your_access_key"
export R2_SECRET_KEY="your_secret_key"
```

설정 파일에서 `${환경변수명}` 형식으로 참조할 수 있습니다:

```yaml
instagram:
  username: "${IG_USERNAME}"
  password: "${IG_PASSWORD}"
```

## 저장 구조

```
data/
├── stories/
│   ├── user1/
│   │   ├── user1_20240115_143022_12345.jpg
│   │   └── user1_20240115_150133_12346.mp4
│   └── user2/
│       └── ...
├── sessions/
│   └── session.json
├── logs/
│   └── story_saver.log
└── download_history.json
```

## 알림 설정

### Telegram Bot 만들기

1. [@BotFather](https://t.me/BotFather)에게 `/newbot` 명령
2. Bot 이름 입력
3. Bot Token 저장
4. Chat ID 확인: [@userinfobot](https://t.me/userinfobot)에게 메시지 전송

## 설정 가이드

### Instagram API 설정

```yaml
instagram:
  api_delay_min: 1.0      # API 요청 간 최소 딜레이 (초)
  api_delay_max: 3.0      # API 요청 간 최대 딜레이 (초)
  api_cooldown_seconds: 300  # API 제한 시 쿨다운 (초)
  api_max_failures: 3     # 연속 실패 허용 횟수
```

### 체크 주기

스토리는 24시간 후 만료되므로 30분~1시간 주기를 권장합니다:

```yaml
monitor:
  check_interval: 1800  # 30분 (초 단위)
  story_expire_hours: 24
```

### 미디어 타입 필터

```yaml
downloader:
  download_videos: true   # 비디오 스토리 다운로드
  download_images: true   # 이미지 스토리 다운로드
  save_thumbnails: false  # 비디오 썸네일 저장
```

### 화질 설정

```yaml
downloader:
  # 비디오 화질: highest(기본), lowest, 1080p, 720p, 480p, 360p
  video_quality: "highest"
  # 이미지 화질: highest(기본), lowest
  image_quality: "highest"
```

| 옵션 | 설명 |
|------|------|
| `highest` | 최고 화질 (기본값) |
| `lowest` | 최저 화질 (용량 절약) |
| `720p` 등 | 해당 해상도 이하 중 최고 화질 |

### 다운로드 설정

```yaml
downloader:
  max_concurrent: 3           # 최대 동시 다운로드 수
  timeout_connect: 10         # 연결 타임아웃 (초)
  timeout_read: 60            # 읽기 타임아웃 (초)
  chunk_size: 8192            # 다운로드 청크 크기
  max_retries: 3              # 재시도 횟수
  disk_check_interval_mb: 10  # 디스크 체크 간격 (MB)
  queue_check_interval: 1.0   # 대기열 체크 간격 (초)
```

### 클라우드 업로드 설정

```yaml
cloud_storage:
  multipart_threshold_mb: 50  # 멀티파트 업로드 임계값
  multipart_chunksize_mb: 25  # 멀티파트 청크 크기
  max_concurrency: 5          # 업로드 동시성
  max_retries: 5              # 재시도 횟수
```

### Telegram 알림 설정

```yaml
notifications:
  telegram:
    queue_size: 100       # 메시지 큐 크기
    max_retries: 3        # 메시지 재시도 횟수
    message_delay: 0.5    # 메시지 간 딜레이 (초)
```

### 중복 방지

```yaml
advanced:
  duplicate_check_hours: 24  # 이 시간 내 같은 스토리 다시 다운로드 안 함
```

## 보안 주의사항

- `config/settings.yaml`을 Git에 커밋하지 마세요
- 환경 변수 사용을 권장합니다
- 세션 파일 권한을 600으로 설정하세요
- 별도의 Instagram 계정 사용을 권장합니다

## 문제 해결

### 로그인 실패

- 비밀번호 확인
- 2FA 설정 시 `totp_secret` 추가
- Instagram 앱/웹에서 보안 확인 필요 여부 체크

### API 제한

- `check_interval`을 늘리세요 (최소 300초)
- `batch_size`를 줄이세요
- `api_delay_min`, `api_delay_max`를 늘리세요

### 스토리가 감지되지 않음

- 모니터링 계정이 해당 유저를 팔로우하고 있어야 합니다
- 비공개 계정의 경우 팔로우 승인이 필요합니다

## 라이선스

MIT License
