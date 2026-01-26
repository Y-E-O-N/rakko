# Oracle Cloud 배포 가이드

이 문서는 Instagram Live Recorder와 Story Saver를 Oracle Cloud에 배포하는 방법을 설명합니다.

## 목차

1. [Oracle Cloud 인스턴스 생성](#1-oracle-cloud-인스턴스-생성)
2. [서버 초기 설정](#2-서버-초기-설정)
3. [GitHub Secrets 설정](#3-github-secrets-설정)
4. [설정 파일 구성](#4-설정-파일-구성)
5. [서비스 시작](#5-서비스-시작)
6. [모니터링 및 관리](#6-모니터링-및-관리)

---

## 1. Oracle Cloud 인스턴스 생성

### 1.1 Oracle Cloud 가입

1. [Oracle Cloud](https://www.oracle.com/cloud/free/) 접속
2. "Start for free" 클릭
3. 계정 생성 (신용카드 필요, 과금되지 않음)

### 1.2 인스턴스 생성

1. Oracle Cloud Console → Compute → Instances → Create Instance

2. **추천 설정 (Always Free)**:
   - **Shape**: VM.Standard.A1.Flex (ARM)
   - **OCPU**: 4
   - **Memory**: 24GB
   - **Boot Volume**: 100GB (최대 200GB까지 무료)
   - **Image**: Ubuntu 22.04

3. **SSH 키 생성**:
   ```bash
   # 로컬에서 실행
   ssh-keygen -t ed25519 -C "oracle-cloud" -f ~/.ssh/oracle_cloud
   ```
   - 공개키 (`~/.ssh/oracle_cloud.pub`) 내용을 인스턴스 생성 시 입력

4. **네트워크 설정**:
   - VCN 자동 생성 선택
   - Public IP 할당 확인

### 1.3 방화벽 설정 (선택사항)

기본적으로 SSH (22번 포트)만 열려있습니다. 추가 포트가 필요하면:

1. VCN → Security Lists → Default Security List
2. Ingress Rules 추가

---

## 2. 서버 초기 설정

### 2.1 SSH 접속

```bash
ssh -i ~/.ssh/oracle_cloud ubuntu@<서버_IP>
```

### 2.2 자동 설정 스크립트 실행

```bash
# 레포지토리 클론
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git ~/instagram-recorder
cd ~/instagram-recorder

# 설정 스크립트 실행
chmod +x deploy/setup.sh
./deploy/setup.sh
```

### 2.3 환경 변수 설정

```bash
nano ~/instagram-recorder/.env
```

```env
# 실제 값으로 수정
IG_USERNAME=your_actual_username
IG_PASSWORD=your_actual_password
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
R2_ACCOUNT_ID=your_r2_account_id
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_BUCKET_NAME=instagram-stories
```

### 2.4 설정 파일 복사

```bash
# Live Recorder
cp instagram-live-recorder/config/settings.example.yaml \
   instagram-live-recorder/config/settings.yaml

# Story Saver
cp instagram-story-saver/config/settings.example.yaml \
   instagram-story-saver/config/settings.yaml
```

### 2.5 모니터링 대상 설정

```bash
nano instagram-live-recorder/config/targets.json
nano instagram-story-saver/config/targets.json
```

```json
{
  "targets": [
    {
      "username": "target_username",
      "alias": "표시 이름",
      "priority": "normal",
      "enabled": true
    }
  ]
}
```

---

## 3. GitHub Secrets 설정

GitHub 레포지토리에서 자동 배포를 위한 Secrets 설정:

1. GitHub → Repository → Settings → Secrets and variables → Actions
2. 다음 Secrets 추가:

| Name | Value |
|------|-------|
| `ORACLE_HOST` | 서버 공인 IP |
| `ORACLE_USER` | `ubuntu` |
| `ORACLE_SSH_KEY` | SSH 개인키 전체 내용 |

### SSH 개인키 확인

```bash
# 로컬에서 실행
cat ~/.ssh/oracle_cloud
```

출력된 전체 내용 (-----BEGIN 부터 -----END 까지)을 `ORACLE_SSH_KEY`에 붙여넣기

---

## 4. 설정 파일 구성

### 4.1 저장 구조

| 프로젝트 | 저장 위치 | 용도 |
|---------|----------|------|
| Live Recorder | Oracle VM (`data/recordings/`) | 라이브 녹화 |
| Story Saver | Cloudflare R2 | 스토리 백업 |

### 4.2 현재 설정 확인

```bash
# Live Recorder - 로컬 저장
grep -A2 "cloud_storage:" instagram-live-recorder/config/settings.yaml
# enabled: false

# Story Saver - R2 저장
grep -A2 "cloud_storage:" instagram-story-saver/config/settings.yaml
# enabled: true
```

---

## 5. 서비스 시작

### 5.1 서비스 시작

```bash
sudo systemctl start instagram-live-recorder
sudo systemctl start instagram-story-saver
```

### 5.2 상태 확인

```bash
sudo systemctl status instagram-live-recorder
sudo systemctl status instagram-story-saver
```

### 5.3 부팅 시 자동 시작

```bash
sudo systemctl enable instagram-live-recorder
sudo systemctl enable instagram-story-saver
```

---

## 6. 모니터링 및 관리

### 6.1 로그 확인

```bash
# 실시간 로그
journalctl -u instagram-live-recorder -f
journalctl -u instagram-story-saver -f

# 최근 100줄
journalctl -u instagram-live-recorder -n 100
```

### 6.2 서비스 관리

```bash
# 재시작
sudo systemctl restart instagram-live-recorder

# 중지
sudo systemctl stop instagram-live-recorder

# 상태 확인
sudo systemctl status instagram-live-recorder
```

### 6.3 디스크 사용량 확인

```bash
# 전체 디스크
df -h

# 녹화 폴더 크기
du -sh ~/instagram-recorder/instagram-live-recorder/data/recordings/
```

### 6.4 오래된 녹화 삭제 (선택사항)

```bash
# 30일 이상 된 파일 삭제
find ~/instagram-recorder/instagram-live-recorder/data/recordings \
  -type f -mtime +30 -delete
```

### 6.5 Cron으로 자동 정리

```bash
crontab -e
```

```cron
# 매일 새벽 3시에 30일 이상 된 녹화 삭제
0 3 * * * find /home/ubuntu/instagram-recorder/instagram-live-recorder/data/recordings -type f -mtime +30 -delete
```

---

## 문제 해결

### 서비스가 시작되지 않음

```bash
# 상세 로그 확인
journalctl -u instagram-live-recorder -n 50 --no-pager

# 수동 실행으로 에러 확인
cd ~/instagram-recorder/instagram-live-recorder
source ../venv/bin/activate
python main.py
```

### Instagram 로그인 실패

1. 2FA 확인: `totp_secret` 설정 필요
2. Challenge 발생: 웹/앱에서 수동 확인 후 재시도
3. 세션 삭제 후 재시도:
   ```bash
   rm -f data/sessions/session.json
   ```

### 디스크 용량 부족

```bash
# 큰 파일 찾기
find ~/instagram-recorder -type f -size +100M -exec ls -lh {} \;

# 오래된 로그 삭제
find ~/instagram-recorder -name "*.log" -mtime +7 -delete
```

---

## 자동 배포 확인

GitHub에 push하면 자동으로 배포됩니다:

1. GitHub → Actions 탭에서 워크플로우 확인
2. 배포 성공 시 서비스 자동 재시작
3. 실패 시 `~/deployment-errors.log` 확인
