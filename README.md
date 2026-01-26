# Instagram Monitor (Live Recorder & Story Saver)

Instagram 라이브 방송 자동 녹화 및 스토리 자동 저장 시스템

## 서버 정보

- **IP**: 158.179.162.210
- **User**: opc
- **경로**: /home/opc/rakko

## SSH 접속

```bash
ssh -i "C:\rakko\secret\ssh-key-2026-01-26.key" opc@158.179.162.210
```

## 관리 스크립트 (권장)

간편한 관리를 위한 메뉴 기반 스크립트:

```bash
cd /home/opc/rakko
./manage.sh
```

**기능:**
- 현재 타겟 목록 보기
- 타겟 추가 (여러 명 동시 가능: `user1, user2, user3`)
- 타겟 삭제
- 서비스 상태 확인
- 서비스 재시작
- 로그 보기

## 수동 관리 명령어

### 가상환경 활성화

```bash
cd /home/opc/rakko
source insta_env/bin/activate
```

### 서비스 관리

```bash
# 상태 확인
sudo systemctl status instagram-live-recorder
sudo systemctl status instagram-story-saver

# 시작
sudo systemctl start instagram-live-recorder
sudo systemctl start instagram-story-saver

# 중지
sudo systemctl stop instagram-live-recorder
sudo systemctl stop instagram-story-saver

# 재시작
sudo systemctl restart instagram-live-recorder instagram-story-saver

# 부팅 시 자동 시작 설정
sudo systemctl enable instagram-live-recorder instagram-story-saver

# 부팅 시 자동 시작 해제
sudo systemctl disable instagram-live-recorder instagram-story-saver
```

### 로그 확인

```bash
# 실시간 로그 보기 (Ctrl+C로 종료)
sudo journalctl -u instagram-live-recorder -f
sudo journalctl -u instagram-story-saver -f

# 최근 로그 50줄 보기
sudo journalctl -u instagram-live-recorder --no-pager -n 50
sudo journalctl -u instagram-story-saver --no-pager -n 50

# 오늘 로그만 보기
sudo journalctl -u instagram-live-recorder --since today
```

### 타겟 관리 (수동)

```bash
# 타겟 목록 보기
cat /home/opc/rakko/instagram-story-saver/config/targets.json

# 타겟 편집
nano /home/opc/rakko/instagram-story-saver/config/targets.json
nano /home/opc/rakko/instagram-live-recorder/config/targets.json

# 편집 후 서비스 재시작 필요!
sudo systemctl restart instagram-live-recorder instagram-story-saver
```

**targets.json 형식:**
```json
{
  "targets": [
    "username1",
    "username2",
    "username3"
  ]
}
```

## 설정 파일

### 모니터링 주기 변경

```bash
nano /home/opc/rakko/instagram-story-saver/config/settings.yaml
```

```yaml
monitor:
  check_interval_min: 3300   # 최소 55분 (초 단위)
  check_interval_max: 3900   # 최대 65분 (초 단위)
```

```bash
nano /home/opc/rakko/instagram-live-recorder/config/settings.yaml
```

```yaml
monitor:
  check_interval: 300  # 5분마다 체크 (초 단위)
```

### 환경 변수 (.env)

```bash
nano /home/opc/rakko/.env
```

```
IG_USERNAME=인스타그램_아이디
IG_PASSWORD=인스타그램_비밀번호
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
R2_ACCOUNT_ID=cloudflare_r2_account_id
R2_ACCESS_KEY=cloudflare_r2_access_key
R2_SECRET_KEY=cloudflare_r2_secret_key
```

## 저장 위치

### 라이브 녹화 파일
```
/home/opc/rakko/instagram-live-recorder/data/recordings/
```

### 스토리 파일
```
/home/opc/rakko/instagram-story-saver/data/stories/
```

스토리는 Cloudflare R2에 업로드 후 로컬 파일 삭제됨 (설정에 따라)

## 디스크 용량 확인

```bash
df -h
```

## 서버 시간대 변경

```bash
# 한국 시간 (KST)으로 변경
sudo timedatectl set-timezone Asia/Seoul

# 현재 시간대 확인
timedatectl
```

## 문제 해결

### 서비스가 시작되지 않을 때

```bash
# 에러 로그 확인
sudo journalctl -xeu instagram-live-recorder.service --no-pager -n 50

# SELinux 문제인 경우
sudo setenforce 0
sudo systemctl restart instagram-live-recorder instagram-story-saver
```

### 파일 업데이트 (GitHub에서)

```bash
cd /home/opc/rakko

# 특정 파일 업데이트
curl -L -o 파일경로 https://raw.githubusercontent.com/Y-E-O-N/rakko/main/파일경로

# 예: manage.sh 업데이트
curl -L -o manage.sh https://raw.githubusercontent.com/Y-E-O-N/rakko/main/manage.sh
chmod +x manage.sh
```

### 수동 실행 (디버깅용)

```bash
cd /home/opc/rakko
source insta_env/bin/activate
export $(cat .env | xargs)

# live-recorder 실행
cd instagram-live-recorder
python main.py

# story-saver 실행
cd ../instagram-story-saver
python main.py
```

## 유용한 단축키

| 키 | 설명 |
|---|---|
| Ctrl+C | 실행 중인 명령 중지 |
| Ctrl+D | SSH 세션 종료 |
| Ctrl+O | nano에서 저장 |
| Ctrl+X | nano에서 종료 |

## 로컬 PC에서 녹화 파일 다운로드

```bash
# Windows PowerShell에서
scp -i "C:\rakko\secret\ssh-key-2026-01-26.key" opc@158.179.162.210:/home/opc/rakko/instagram-live-recorder/data/recordings/* C:\Downloads\
```
