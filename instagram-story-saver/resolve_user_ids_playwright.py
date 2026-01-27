#!/usr/bin/env python3
"""
Playwright로 Instagram User ID 조회 (브라우저 기반)

실제 브라우저를 사용해서 Instagram 페이지를 로드하고 user_id를 추출합니다.
API rate limit을 우회할 수 있습니다.

사용법:
    python resolve_user_ids_playwright.py
    python resolve_user_ids_playwright.py --delay 3
    python resolve_user_ids_playwright.py --headed  # 브라우저 창 보이기
"""
import json
import time
import re
import argparse
from pathlib import Path
from datetime import datetime


def get_user_id_playwright(page, username: str) -> int | None:
    """Playwright로 Instagram 프로필에서 user_id 추출"""
    try:
        url = f"https://www.instagram.com/{username}/"
        page.goto(url, timeout=30000)
        page.wait_for_load_state('networkidle', timeout=15000)

        html = page.content()

        # 로그인 페이지 체크
        if 'login' in page.url.lower() and username not in page.url.lower():
            print(f"    로그인 페이지로 리다이렉트됨")
            return None

        # 방법 1: profilePage_숫자 패턴
        match = re.search(r'profilePage_(\d+)', html)
        if match:
            return int(match.group(1))

        # 방법 2: "user_id":"숫자" 패턴
        match = re.search(r'"user_id":\s*"?(\d+)"?', html)
        if match:
            return int(match.group(1))

        # 방법 3: owner id 패턴
        match = re.search(r'"owner":\s*\{[^}]*"id":\s*"(\d+)"', html)
        if match:
            return int(match.group(1))

        return None

    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "not found" in error_msg.lower():
            print(f"    사용자 없음")
        elif "timeout" in error_msg.lower():
            print(f"    타임아웃")
        else:
            print(f"    오류: {error_msg[:50]}")
        return None


def resolve_user_ids_playwright(
    targets_file: str = "config/targets.json",
    delay: float = 2.0,
    batch_size: int = 20,
    batch_delay: float = 10.0,
    headed: bool = False
):
    """Playwright로 User ID 조회 및 저장"""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("오류: playwright 패키지가 필요합니다.")
        print("  pip install playwright")
        print("  playwright install chromium")
        return False

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
    print(f"예상 시간: 약 {len(needs_resolve) * (delay + 3) / 60:.1f}분")
    print()
    print("=" * 50)
    print("Playwright 브라우저로 user_id 조회 시작")
    print("실제 브라우저 사용 - API rate limit 우회!")
    print("Ctrl+C로 중단 가능 (진행 상황 저장됨)")
    print("=" * 50)
    print()

    resolved = 0
    failed = 0
    failed_users = []

    with sync_playwright() as p:
        # 브라우저 실행
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        try:
            for idx, (i, uname, existing) in enumerate(needs_resolve):
                try:
                    user_id = get_user_id_playwright(page, uname)

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

        finally:
            browser.close()

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
    parser = argparse.ArgumentParser(description="Playwright로 User ID 조회")
    parser.add_argument('--targets', default='config/targets.json', help='targets.json 경로')
    parser.add_argument('--delay', type=float, default=2.0, help='조회 간 딜레이 (초)')
    parser.add_argument('--batch', type=int, default=20, help='배치 크기')
    parser.add_argument('--batch-delay', type=float, default=10.0, help='배치 간 딜레이 (초)')
    parser.add_argument('--headed', action='store_true', help='브라우저 창 표시')

    args = parser.parse_args()

    resolve_user_ids_playwright(
        targets_file=args.targets,
        delay=args.delay,
        batch_size=args.batch,
        batch_delay=args.batch_delay,
        headed=args.headed
    )
