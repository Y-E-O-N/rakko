#!/usr/bin/env python3
"""
targets.txt → targets.json 업데이트 스크립트

기존 targets.json을 보존하면서 새로운 타겟을 추가합니다.

사용법:
    python update_targets.py              # txt의 타겟을 json에 추가
    python update_targets.py --replace    # json을 txt로 완전 대체
"""
import json
import sys
from pathlib import Path

def update_targets(txt_file: str = "config/targets.txt", json_file: str = "config/targets.json", replace: bool = False):
    txt_path = Path(txt_file)
    json_path = Path(json_file)

    if not txt_path.exists():
        print(f"오류: {txt_file} 파일이 없습니다.")
        return False

    # txt 파일 읽기 (한 줄씩 또는 쉼표 구분 모두 지원)
    new_targets = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 빈 줄, 주석(#) 무시
            if not line or line.startswith('#'):
                continue
            # 쉼표가 있으면 쉼표로 분리, 없으면 그대로
            if ',' in line:
                for username in line.split(','):
                    username = username.strip()
                    if username:
                        new_targets.append(username)
            else:
                new_targets.append(line)

    # 기존 json 로드
    existing_targets = []
    existing_ids = {}
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                for item in old_data.get('targets', []):
                    if isinstance(item, dict):
                        username = item.get('username', '')
                        existing_targets.append(username)
                        if item.get('user_id'):
                            existing_ids[username.lower()] = item['user_id']
                    elif isinstance(item, str):
                        existing_targets.append(item)
        except:
            pass

    # 병합 (replace=False) 또는 대체 (replace=True)
    if replace:
        final_targets = new_targets
    else:
        # 기존 + 새로운 (중복 제거)
        final_targets = existing_targets.copy()
        existing_lower = {t.lower() for t in existing_targets}
        for t in new_targets:
            if t.lower() not in existing_lower:
                final_targets.append(t)
                existing_lower.add(t.lower())

    # 중복 제거 (순서 유지)
    seen = set()
    unique_targets = []
    for t in final_targets:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_targets.append(t)

    # json 데이터 생성 (user_id 있으면 포함)
    json_targets = []
    for username in unique_targets:
        if username.lower() in existing_ids:
            json_targets.append({
                "username": username,
                "user_id": existing_ids[username.lower()]
            })
        else:
            json_targets.append(username)

    # json 저장
    data = {"targets": json_targets}
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    added = len(unique_targets) - len(existing_targets) if not replace else 0
    print(f"완료: 총 {len(unique_targets)}명 (기존 {len(existing_targets)}명 + 추가 {added}명)")
    return True

if __name__ == "__main__":
    replace = "--replace" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    txt_file = args[0] if args else "config/targets.txt"
    update_targets(txt_file, replace=replace)
