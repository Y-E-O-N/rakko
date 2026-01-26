#!/bin/bash
# Instagram Live Recorder 배포 스크립트
#
# 사용법:
#   ./scripts/deploy.sh
#
# 필수 환경변수:
#   IG_USERNAME, IG_PASSWORD
#
# 선택 환경변수:
#   IG_TOTP_SECRET, DISCORD_WEBHOOK_URL
#   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

set -e

echo "=========================================="
echo "Instagram Live Recorder 배포"
echo "=========================================="

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 함수: 에러 출력
error() {
    echo -e "${RED}[ERROR] $1${NC}"
    exit 1
}

# 함수: 성공 출력
success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

# 함수: 경고 출력
warn() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

# 1. 환경변수 검증
echo ""
echo "1. 환경변수 검증..."

if [ -z "$IG_USERNAME" ]; then
    error "IG_USERNAME 환경변수가 설정되지 않았습니다"
fi
success "IG_USERNAME 설정됨"

if [ -z "$IG_PASSWORD" ]; then
    error "IG_PASSWORD 환경변수가 설정되지 않았습니다"
fi
success "IG_PASSWORD 설정됨"

if [ -z "$DISCORD_WEBHOOK_URL" ]; then
    warn "DISCORD_WEBHOOK_URL이 설정되지 않음 - 알림 비활성화"
fi

if [ -z "$R2_ACCOUNT_ID" ]; then
    warn "R2 환경변수가 설정되지 않음 - 클라우드 백업 비활성화"
fi

# 2. 디렉토리 생성
echo ""
echo "2. 디렉토리 생성..."

mkdir -p data/sessions
mkdir -p data/recordings
mkdir -p data/logs
mkdir -p config

success "디렉토리 생성 완료"

# 3. 설정 파일 생성
echo ""
echo "3. 설정 파일 생성..."

if [ ! -f "config/settings.yaml" ]; then
    cp config/settings.example.yaml config/settings.yaml
    success "settings.yaml 생성됨"
else
    warn "settings.yaml 이미 존재함 - 스킵"
fi

if [ ! -f "config/targets.json" ]; then
    cp config/targets.example.json config/targets.json
    success "targets.json 생성됨"
else
    warn "targets.json 이미 존재함 - 스킵"
fi

# 4. 파일 권한 설정 (보안)
echo ""
echo "4. 파일 권한 설정..."

chmod 600 config/settings.yaml 2>/dev/null || true
chmod 600 config/targets.json 2>/dev/null || true
chmod 700 data/sessions 2>/dev/null || true

success "파일 권한 설정 완료"

# 5. Python 의존성 설치
echo ""
echo "5. Python 의존성 확인..."

if command -v pip &> /dev/null; then
    pip install -r requirements.txt --quiet
    success "의존성 설치 완료"
else
    warn "pip를 찾을 수 없음 - 수동 설치 필요"
fi

# 6. FFmpeg 확인
echo ""
echo "6. FFmpeg 확인..."

if command -v ffmpeg &> /dev/null; then
    success "FFmpeg 설치됨"
else
    warn "FFmpeg가 설치되지 않음 - 녹화에 필요할 수 있음"
fi

# 7. 설정 테스트
echo ""
echo "7. 설정 테스트..."

python -c "from src.utils.config import load_config; c = load_config(); print(f'타겟 유저: {len(c.targets)}명')" 2>/dev/null && success "설정 파일 검증 완료" || error "설정 파일 검증 실패"

echo ""
echo "=========================================="
echo -e "${GREEN}배포 완료!${NC}"
echo "=========================================="
echo ""
echo "실행 방법:"
echo "  python main.py"
echo ""
echo "테스트:"
echo "  python main.py --test-login"
echo "  python main.py --test-discord"
echo ""
