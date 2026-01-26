#!/bin/bash
#
# Instagram Recorder 서버 초기 설정 스크립트
# Oracle Cloud Ubuntu에서 실행
#
set -e

echo "=========================================="
echo "Instagram Recorder 서버 설정"
echo "=========================================="

# 변수 설정
REPO_URL="https://github.com/Y-E-O-N/rakko.git"
APP_DIR="/home/ubuntu/instagram-recorder"
VENV_DIR="$APP_DIR/venv"

# 1. 시스템 패키지 업데이트
echo ""
echo "[1/7] 시스템 패키지 업데이트..."
sudo apt update && sudo apt upgrade -y

# 2. 필수 패키지 설치
echo ""
echo "[2/7] 필수 패키지 설치..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    ffmpeg \
    curl \
    htop

# yt-dlp 설치 (최신 버전)
echo "yt-dlp 설치..."
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp

# 3. 프로젝트 클론
echo ""
echo "[3/7] 프로젝트 클론..."
if [ -d "$APP_DIR" ]; then
    echo "기존 디렉토리 존재, git pull 실행..."
    cd $APP_DIR
    git pull origin main
else
    git clone $REPO_URL $APP_DIR
    cd $APP_DIR
fi

# 4. Python 가상환경 설정
echo ""
echo "[4/7] Python 가상환경 설정..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv $VENV_DIR
fi
source $VENV_DIR/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install -r instagram-live-recorder/requirements.txt
pip install -r instagram-story-saver/requirements.txt

# 5. 디렉토리 생성
echo ""
echo "[5/7] 필요한 디렉토리 생성..."
mkdir -p $APP_DIR/logs
mkdir -p $APP_DIR/instagram-live-recorder/data/recordings
mkdir -p $APP_DIR/instagram-live-recorder/data/sessions
mkdir -p $APP_DIR/instagram-live-recorder/data/logs
mkdir -p $APP_DIR/instagram-story-saver/data/stories
mkdir -p $APP_DIR/instagram-story-saver/data/sessions
mkdir -p $APP_DIR/instagram-story-saver/data/logs

# 6. 환경 변수 파일 생성 (템플릿)
echo ""
echo "[6/7] 환경 변수 파일 확인..."
if [ ! -f "$APP_DIR/.env" ]; then
    cat > $APP_DIR/.env << 'ENVEOF'
# Instagram 계정
IG_USERNAME=your_instagram_username
IG_PASSWORD=your_instagram_password

# Discord Webhook
DISCORD_WEBHOOK_URL=your_discord_webhook_url

# Cloudflare R2 (스토리 저장용)
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=instagram-stories
ENVEOF
    echo "⚠️  .env 파일이 생성되었습니다. 실제 값을 입력하세요!"
    echo "    nano $APP_DIR/.env"
else
    echo ".env 파일이 이미 존재합니다."
fi

# 7. Systemd 서비스 설치
echo ""
echo "[7/7] Systemd 서비스 설치..."
sudo cp $APP_DIR/deploy/instagram-live-recorder.service /etc/systemd/system/
sudo cp $APP_DIR/deploy/instagram-story-saver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable instagram-live-recorder
sudo systemctl enable instagram-story-saver

echo ""
echo "=========================================="
echo "설정 완료!"
echo "=========================================="
echo ""
echo "다음 단계:"
echo "1. .env 파일 수정: nano $APP_DIR/.env"
echo "2. settings.yaml 파일 확인"
echo "3. targets.json에 모니터링 대상 추가"
echo "4. 서비스 시작:"
echo "   sudo systemctl start instagram-live-recorder"
echo "   sudo systemctl start instagram-story-saver"
echo ""
echo "로그 확인:"
echo "   journalctl -u instagram-live-recorder -f"
echo "   journalctl -u instagram-story-saver -f"
echo ""
