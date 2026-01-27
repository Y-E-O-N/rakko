#!/usr/bin/env python3
"""
User ID 조회 스크립트

targets.json의 username을 user_id로 변환하여 저장합니다.
Rate limit을 피하기 위해 천천히 조회합니다.

사용법:
    python resolve_user_ids.py                    # 기본 설정으로 실행
    python resolve_user_ids.py --delay 10         # 딜레이 10초
    python resolve_user_ids.py --batch 5          # 5명마다 긴 휴식
    python resolve_user_ids.py --resume           # 중단된 곳부터 재개
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

def resolve_user_ids(
    targets_file: str = "config/targets.json",
    delay: float = 15.0,
    batch_size: int = 10,
    batch_delay: float = 30.0,
    resume: bool = False
):
    """User ID 조회 및 저장"""

    # 환경 변수 로드 (c:\rakko\.env 우선)
    env_paths = ["c:/rakko/.env", "../.env", ".env", "config/.env"]
    for env_path in env_paths:
        if Path(env_path).exists():
            load_dotenv(env_path)
            print(f"환경 변수 로드: {env_path}")
            break

    # Instagram 로그인 정보
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    session_file = os.getenv("IG_SESSION_FILE", "data/sessions/session.json")

    if not username or not password:
        print("오류: IG_USERNAME, IG_PASSWORD 환경 변수가 필요합니다.")
        print("  .env 파일을 확인하거나 환경 변수를 설정하세요.")
        return False

    # targets.json 로드
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

    # Instagram 로그인
    try:
        from instagrapi import Client
        from instagrapi.exceptions import ClientError, UserNotFound
    except ImportError:
        print("오류: instagrapi 패키지가 필요합니다.")
        print("  pip install instagrapi")
        return False

    client = Client()

    # 세션 파일로 로그인 시도
    session_path = Path(session_file)
    if session_path.exists():
        try:
            client.load_settings(session_path)
            client.login(username, password)
            print(f"세션 파일로 로그인 성공: {client.username}")
        except Exception as e:
            print(f"세션 로그인 실패, 새로 로그인: {e}")
            client.login(username, password)
    else:
        client.login(username, password)
        print(f"로그인 성공: {client.username}")

    # 세션 저장
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client.dump_settings(session_path)

    print()
    print("=" * 50)
    print("user_id 조회 시작")
    print("Ctrl+C로 중단 가능 (진행 상황 저장됨)")
    print("=" * 50)
    print()

    resolved = 0
    failed = 0

    try:
        for idx, (i, uname, existing) in enumerate(needs_resolve):
            try:
                # user_id 조회
                user_info = client.user_info_by_username_v1(uname)
                user_id = user_info.pk

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

            except UserNotFound:
                failed += 1
                print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 사용자 없음")
            except ClientError as e:
                if "feedback_required" in str(e):
                    print(f"\nRate limit 감지! 30초 대기 후 재시도...")
                    time.sleep(30)
                    try:
                        user_info = client.user_info_by_username_v1(uname)
                        user_id = user_info.pk
                        if existing:
                            existing['user_id'] = user_id
                            targets[i] = existing
                        else:
                            targets[i] = {'username': uname, 'user_id': user_id}
                        resolved += 1
                        print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> {user_id}")
                    except Exception as e2:
                        failed += 1
                        print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 실패: {e2}")
                else:
                    failed += 1
                    print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 실패: {e}")
            except Exception as e:
                failed += 1
                print(f"[{idx+1}/{len(needs_resolve)}] {uname} -> 실패: {e}")

            # 진행 상황 저장 (10명마다)
            if (idx + 1) % 10 == 0:
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
    parser = argparse.ArgumentParser(description="User ID 조회 스크립트")
    parser.add_argument('--targets', default='config/targets.json', help='targets.json 경로')
    parser.add_argument('--delay', type=float, default=15.0, help='조회 간 딜레이 (초)')
    parser.add_argument('--batch', type=int, default=10, help='배치 크기')
    parser.add_argument('--batch-delay', type=float, default=30.0, help='배치 간 딜레이 (초)')
    parser.add_argument('--resume', action='store_true', help='중단된 곳부터 재개')

    args = parser.parse_args()

    resolve_user_ids(
        targets_file=args.targets,
        delay=args.delay,
        batch_size=args.batch,
        batch_delay=args.batch_delay,
        resume=args.resume
    )
