# 보안 가이드

## 개요

Instagram Live Recorder는 민감한 인증 정보를 다루므로 보안에 주의가 필요합니다.
이 문서는 보안 모범 사례와 잠재적 위험을 설명합니다.

---

## GitHub 배포 보안

### 1. Repository Secrets 설정

GitHub에 push하면 자동 배포되는 환경에서는 **절대로 코드에 시크릿을 포함하지 마세요**.

Repository Settings → Secrets and variables → Actions에서 설정:

| Secret 이름 | 설명 | 필수 |
|------------|------|------|
| `IG_USERNAME` | Instagram 사용자명 | ✅ |
| `IG_PASSWORD` | Instagram 비밀번호 | ✅ |
| `IG_TOTP_SECRET` | 2FA TOTP 시크릿 | ❌ |
| `DISCORD_WEBHOOK_URL` | Discord 알림 Webhook | ❌ |
| `R2_ACCOUNT_ID` | Cloudflare Account ID | ❌ |
| `R2_ACCESS_KEY_ID` | R2 Access Key | ❌ |
| `R2_SECRET_ACCESS_KEY` | R2 Secret Key | ❌ |
| `R2_BUCKET_NAME` | R2 버킷 이름 | ❌ |

### 2. .gitignore 필수 항목

다음 파일들은 **절대로 Git에 커밋되면 안 됩니다**:

```gitignore
# 민감한 파일
.env
config/settings.yaml
config/targets.json
data/sessions/
*.db
```

### 3. Branch Protection 권장

- `main` 브랜치 보호 규칙 설정
- Force push 금지
- PR 리뷰 필수 (팀 프로젝트인 경우)

---

## 민감 정보 보호

### 1. 설정 파일 (settings.yaml)

⚠️ **절대로 Git에 커밋하지 마세요!**

```yaml
# ❌ 나쁜 예 - 직접 값 입력
instagram:
  username: "my_real_username"
  password: "my_real_password"

# ✅ 좋은 예 - 환경 변수 사용
instagram:
  username: "${IG_USERNAME}"
  password: "${IG_PASSWORD}"
```

### 2. 환경 변수 사용

**로컬 개발 환경:**

```bash
# Linux/macOS - ~/.bashrc 또는 ~/.zshrc
export IG_USERNAME="your_username"
export IG_PASSWORD="your_password"
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."

# Windows PowerShell
$env:IG_USERNAME = "your_username"
$env:IG_PASSWORD = "your_password"
```

**서버 배포 환경:**

```bash
# systemd service 파일에서
[Service]
Environment="IG_USERNAME=your_username"
Environment="IG_PASSWORD=your_password"

# 또는 EnvironmentFile 사용 (권장)
EnvironmentFile=/etc/instagram-recorder/env
```

### 3. 세션 파일

- 위치: `data/sessions/session.json`
- **파일 권한**: 600 (소유자만 읽기/쓰기)
- Instagram 인증 토큰이 포함되어 있음
- 유출 시 계정 무단 접근 가능

```bash
# 권한 확인 및 설정 (Linux/macOS)
chmod 600 data/sessions/session.json
chmod 700 data/sessions/
```

---

## 파일/폴더 권한

| 경로 | 권장 권한 | 설명 |
|------|----------|------|
| `config/settings.yaml` | 600 | 인증 정보 참조 |
| `config/targets.json` | 600 | 모니터링 대상 |
| `data/sessions/` | 700 | 세션 파일 디렉토리 |
| `data/sessions/*.json` | 600 | 세션 파일 |
| `data/recordings/` | 755 | 녹화 파일 |
| `data/logs/` | 755 | 로그 디렉토리 |
| `data/*.db` | 600 | 데이터베이스 |

---

## 네트워크 보안

### 1. HTTPS 사용

- 모든 Instagram API 통신은 HTTPS
- 클라우드 스토리지(R2)도 HTTPS 사용
- Discord Webhook도 HTTPS

### 2. 프록시 설정 시 주의

```yaml
# ❌ 나쁜 예 - 인증 정보가 로그에 노출될 수 있음
advanced:
  proxy: "http://user:password@proxy.example.com:8080"

# ✅ 권장 - 환경 변수 사용
advanced:
  proxy: "${PROXY_URL}"
```

---

## 입력 검증

### 1. 타겟 유저네임

- Instagram 유저네임 규칙에 따라 검증
- 영문, 숫자, 밑줄(_), 점(.)만 허용
- 최대 30자

### 2. 스트림 URL

- Instagram 관련 도메인만 허용:
  - `instagram.com`
  - `cdninstagram.com`
  - `fbcdn.net`
  - `akamaized.net`
- 위험한 문자(`;`, `|`, `&`, `$`, `` ` ``) 차단
- HTTPS/HTTP만 허용

---

## 로깅 보안

### 로그에 포함되지 않는 정보

- ✅ 비밀번호
- ✅ API 키/시크릿
- ✅ 세션 토큰
- ✅ 스트림 URL (마스킹됨)
- ✅ Webhook URL (마스킹됨)

### 로그 파일 관리

```yaml
logging:
  level: "INFO"  # DEBUG 시 더 많은 정보 노출 주의
  file: "data/logs/recorder.log"
  max_size_mb: 10
  backup_count: 5  # 오래된 로그 자동 삭제
```

---

## Instagram 계정 보안

### 1. 전용 계정 사용 권장

- 메인 계정 대신 녹화 전용 계정 생성
- 팔로잉 목록을 모니터링 대상으로 설정

### 2. 2단계 인증 (2FA)

- 가능하면 2FA 활성화
- TOTP 시크릿을 GitHub Secrets에 안전하게 보관
- 백업 코드 별도 저장

### 3. API 제한 회피

```yaml
monitor:
  check_interval: 300  # 5분 (최소 60초)
  batch_size: 50       # 한 번에 체크할 유저 수
  batch_delay: 10      # 배치 간 대기 시간
```

---

## Cloudflare R2 보안

### 1. API 토큰 권한

- 최소 권한 원칙 적용
- 필요한 버킷에만 접근 허용
- 읽기/쓰기 권한만 부여 (관리자 권한 불필요)

### 2. 버킷 설정

- 퍼블릭 액세스: 필요한 경우에만 활성화
- 수명 주기 규칙: 오래된 파일 자동 삭제

---

## 배포 전 체크리스트

### 필수 확인사항

- [ ] `config/settings.yaml`이 `.gitignore`에 포함됨
- [ ] `config/targets.json`이 `.gitignore`에 포함됨
- [ ] `.env` 파일이 `.gitignore`에 포함됨
- [ ] `data/` 디렉토리가 `.gitignore`에 포함됨
- [ ] GitHub Secrets에 필수 환경변수 설정됨
- [ ] 코드에 하드코딩된 시크릿 없음

### 서버 배포 시

- [ ] 서버 환경변수 또는 시크릿 관리자 설정
- [ ] 세션 파일 권한 600 설정
- [ ] 로그 레벨 INFO 이상 (프로덕션)
- [ ] R2 API 토큰 최소 권한
- [ ] 방화벽 설정 (필요한 포트만 개방)

---

## 취약점 보고

보안 취약점을 발견하시면:

1. 공개 이슈 대신 비공개로 연락
2. 상세한 재현 방법 제공
3. 가능하면 패치 제안

---

## 업데이트 이력

- 2024-01: 초기 보안 가이드 작성
- 2024-01: 환경 변수 지원 추가
- 2024-01: URL 검증 로직 추가
- 2026-01: GitHub 배포 보안 가이드 추가
- 2026-01: Discord Webhook 지원 추가
- 2026-01: .gitignore 강화
