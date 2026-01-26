#!/bin/bash
# Instagram Monitor 관리 스크립트

RAKKO_DIR="/home/opc/rakko"
TARGETS_FILE="$RAKKO_DIR/instagram-story-saver/config/targets.json"
LIVE_TARGETS_FILE="$RAKKO_DIR/instagram-live-recorder/config/targets.json"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_menu() {
    echo ""
    echo -e "${GREEN}=== Instagram Monitor 관리 ===${NC}"
    echo "1) 현재 타겟 목록 보기"
    echo "2) 타겟 추가"
    echo "3) 타겟 삭제"
    echo "4) 서비스 상태 확인"
    echo "5) 서비스 재시작"
    echo "6) 로그 보기 (live-recorder)"
    echo "7) 로그 보기 (story-saver)"
    echo "8) 종료"
    echo ""
    read -p "선택: " choice
}

show_targets() {
    echo ""
    echo -e "${YELLOW}현재 타겟 목록:${NC}"
    cat "$TARGETS_FILE" | grep -oP '"[^"]+(?=",?)' | tr -d '"' | grep -v "targets" | nl
    echo ""
}

add_target() {
    echo "추가할 Instagram 유저네임 입력 (여러 명: 쉼표 또는 공백으로 구분)"
    echo "예: user1, user2, user3"
    read -p "> " input

    if [ -z "$input" ]; then
        echo -e "${RED}유저네임을 입력하세요${NC}"
        return
    fi

    # 쉼표와 공백을 구분자로 사용
    usernames=$(echo "$input" | tr ',' ' ' | tr -s ' ')
    added_count=0

    for username in $usernames; do
        # 공백 제거
        username=$(echo "$username" | xargs)

        if [ -z "$username" ]; then
            continue
        fi

        # 현재 목록 확인
        if grep -q "\"$username\"" "$TARGETS_FILE"; then
            echo -e "${YELLOW}이미 존재: $username${NC}"
            continue
        fi

        # story-saver에 추가
        python3 << EOF
import json
with open('$TARGETS_FILE', 'r') as f:
    data = json.load(f)
data['targets'].append('$username')
with open('$TARGETS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
EOF

        # live-recorder에 추가
        python3 << EOF
import json
with open('$LIVE_TARGETS_FILE', 'r') as f:
    data = json.load(f)
data['targets'].append('$username')
with open('$LIVE_TARGETS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
EOF

        echo -e "${GREEN}추가됨: $username${NC}"
        ((added_count++))
    done

    echo ""
    echo -e "${GREEN}총 ${added_count}명 추가 완료${NC}"

    if [ $added_count -gt 0 ]; then
        read -p "서비스를 재시작할까요? (y/n): " restart
        if [ "$restart" = "y" ]; then
            restart_services
        fi
    fi
}

remove_target() {
    show_targets
    read -p "삭제할 Instagram 유저네임: " username
    if [ -z "$username" ]; then
        echo -e "${RED}유저네임을 입력하세요${NC}"
        return
    fi

    # story-saver에서 삭제
    python3 << EOF
import json
with open('$TARGETS_FILE', 'r') as f:
    data = json.load(f)
if '$username' in data['targets']:
    data['targets'].remove('$username')
    with open('$TARGETS_FILE', 'w') as f:
        json.dump(data, f, indent=2)
    print('story-saver에서 삭제됨')
else:
    print('찾을 수 없음: $username')
EOF

    # live-recorder에서 삭제
    python3 << EOF
import json
with open('$LIVE_TARGETS_FILE', 'r') as f:
    data = json.load(f)
if '$username' in data['targets']:
    data['targets'].remove('$username')
    with open('$LIVE_TARGETS_FILE', 'w') as f:
        json.dump(data, f, indent=2)
    print('live-recorder에서 삭제됨')
else:
    print('찾을 수 없음: $username')
EOF

    echo -e "${GREEN}삭제 완료: $username${NC}"
    read -p "서비스를 재시작할까요? (y/n): " restart
    if [ "$restart" = "y" ]; then
        restart_services
    fi
}

check_status() {
    echo ""
    echo -e "${YELLOW}=== 서비스 상태 ===${NC}"
    echo ""
    echo -e "${GREEN}[Live Recorder]${NC}"
    sudo systemctl status instagram-live-recorder --no-pager -l | head -10
    echo ""
    echo -e "${GREEN}[Story Saver]${NC}"
    sudo systemctl status instagram-story-saver --no-pager -l | head -10
}

restart_services() {
    echo "서비스 재시작 중..."
    sudo systemctl restart instagram-live-recorder
    sudo systemctl restart instagram-story-saver
    echo -e "${GREEN}재시작 완료${NC}"
}

show_logs_live() {
    echo -e "${YELLOW}Live Recorder 로그 (Ctrl+C로 종료):${NC}"
    sudo journalctl -u instagram-live-recorder -f
}

show_logs_story() {
    echo -e "${YELLOW}Story Saver 로그 (Ctrl+C로 종료):${NC}"
    sudo journalctl -u instagram-story-saver -f
}

# 메인 루프
while true; do
    show_menu
    case $choice in
        1) show_targets ;;
        2) add_target ;;
        3) remove_target ;;
        4) check_status ;;
        5) restart_services ;;
        6) show_logs_live ;;
        7) show_logs_story ;;
        8) echo "종료합니다."; exit 0 ;;
        *) echo -e "${RED}잘못된 선택입니다${NC}" ;;
    esac
done
