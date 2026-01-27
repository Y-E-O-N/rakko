#!/usr/bin/env python3
"""
웹 스크래핑으로 Instagram User ID 조회 (로그인 불필요)

Instagram API를 사용하지 않고 웹사이트에서 user_id를 가져옵니다.
Rate limit 걱정 없이 사용 가능합니다.

사용법:
    python resolve_user_ids_web.py
    python resolve_user_ids_web.py --delay 3
"""
import json
import time
import re
import argparse
from pathlib import Path
from datetime import datetime
import urllib.request
import urllib.parse

# User-Agent 설정 (브라우저처럼 보이게)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def get_user_id_from_instagram(username: str) -> int | None:
    """Instagram web_profile_info API로 user_id 조회 (로그인 불필요)"""
    try:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-IG-App-ID': '936619743392459',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
        }
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            text = data.decode('utf-8', errors='ignore')

        import json
        j = json.loads(text)
        user_id = j.get('data', {}).get('user', {}).get('id')

        if user_id:
            return int(user_id)
        return None

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"    사용자 없음 (404)")
        elif e.code == 429:
            print(f"    Rate limit (429) - 잠시 후 재시도...")
        else:
            print(f"    HTTP 오류: {e.code}")
        return None
    except Exception as e:
        print(f"    조회 실패: {e}")
        return None


def get_user_id(username: str) -> int | None:
    """Instagram 프로필에서 user_id 조회"""
    return get_user_id_from_instagram(username)


def resolve_user_ids_web(
    targets_file: str = "config/targets.json",
    delay: float = 2.0,
    batch_size: int = 20,
    batch_delay: float = 10.0
):
    """웹 스크래핑으로 User ID 조회 및 저장"""

    targets_path = Path(targets_file)
    if not targets_path.exists():
        print(f"오류: {targets_file} 파일이 없습니다.")
        return False

    with open(targets_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    targets = data.get('targets', [])
    print(f"총 {len(targets)}명의 타겟")

    # user_id가 없는 타겟 찾기
    needs_resolve = []
    for i, target in enumerate(targets):
        if isinstance(target, str):
            needs_resolve.append((i, target, None))
        elif isinstance(target, dict):
            if not target.get('user_id'):
                needs_resolve.append((i, target.get('username'), target))

    if not needs_resolve:
        print("모든 타겟의 user_id가 이미 있습니다.")
        return True

    print(f"user_id 조회 필요: {len(needs_resolve)}명")
    print(f"예상 시간: 약 {len(needs_resolve) * delay / 60:.1f}분")
    print()
    print("=" * 50)
    print("웹 스크래핑으로 user_id 조회 시작")
    print("Instagram 로그인 불필요!")
    print("Ctrl+C로 중단 가능 (진행 상황 저장됨)")
    print("=" * 50)
    print()

    resolved = 0
    failed = 0
    failed_users = []

    try:
        for idx, (i, uname, existing) in enumerate(needs_resolve):
            try:
                user_id = get_user_id(uname)

                if user_id:
                    # targets 업데이트
                    if existing:
                        existing['user_id'] = user_id
                        targets[i] = existing
                    else:
                        targets[i] = {
                            'username': uname,
                            'user_id': user_id
                        }

                    resolved += 1
                    print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> {user_id}")
                else:
                    failed += 1
                    failed_users.append(uname)
                    print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 실패")

            except Exception as e:
                failed += 1
                failed_users.append(uname)
                print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 오류: {e}")

            # 진행 상황 저장 (20명마다)
            if (idx + 1) % 20 == 0:
                save_targets(targets_path, targets)
                print(f"  (진행 상황 저장됨)")

            # 딜레이
            if idx + 1 < len(needs_resolve):
                if (idx + 1) % batch_size == 0:
                    print(f"  배치 완료, {batch_delay}초 휴식...")
                    time.sleep(batch_delay)
                else:
                    time.sleep(delay)

    except KeyboardInterrupt:
        print("\n\n중단됨. 진행 상황 저장 중...")

    # 최종 저장
    save_targets(targets_path, targets)

    print()
    print("=" * 50)
    print(f"완료: {resolved}명 성공, {failed}명 실패")
    print(f"저장됨: {targets_path}")

    if failed_users:
        print()
        print(f"실패한 사용자 ({len(failed_users)}명):")
        for u in failed_users[:10]:
            print(f"  - {u}")
        if len(failed_users) > 10:
            print(f"  ... 외 {len(failed_users) - 10}명")

    print("=" * 50)

    return True


def save_targets(path: Path, targets: list):
    """targets.json 저장"""
    data = {
        'targets': targets,
        'last_updated': datetime.now().isoformat()
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="웹 스크래핑으로 User ID 조회")
    parser.add_argument('--targets', default='config/targets.json', help='targets.json 경로')
    parser.add_argument('--delay', type=float, default=2.0, help='조회 간 딜레이 (초)')
    parser.add_argument('--batch', type=int, default=20, help='배치 크기')
    parser.add_argument('--batch-delay', type=float, default=10.0, help='배치 간 딜레이 (초)')

    args = parser.parse_args()

    resolve_user_ids_web(
        targets_file=args.targets,
        delay=args.delay,
        batch_size=args.batch,
        batch_delay=args.batch_delay
    )
