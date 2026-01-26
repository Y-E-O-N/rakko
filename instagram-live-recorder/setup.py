#!/usr/bin/env python3
"""
Instagram Live Recorder 초기 설정 스크립트
"""
import os
import sys
import shutil
from pathlib import Path

def main():
    print("=" * 50)
    print("Instagram Live Recorder 초기 설정")
    print("=" * 50)
    print()
    
    project_root = Path(__file__).parent
    
    # 1. 설정 파일 생성
    settings_example = project_root / "config" / "settings.example.yaml"
    settings_file = project_root / "config" / "settings.yaml"
    
    if not settings_file.exists():
        if settings_example.exists():
            shutil.copy(settings_example, settings_file)
            print("✓ config/settings.yaml 생성됨")
        else:
            print("✗ settings.example.yaml을 찾을 수 없습니다")
    else:
        print("• config/settings.yaml 이미 존재함")
    
    # 2. 타겟 파일 생성
    targets_example = project_root / "config" / "targets.example.json"
    targets_file = project_root / "config" / "targets.json"
    
    if not targets_file.exists():
        if targets_example.exists():
            shutil.copy(targets_example, targets_file)
            print("✓ config/targets.json 생성됨")
        else:
            print("✗ targets.example.json을 찾을 수 없습니다")
    else:
        print("• config/targets.json 이미 존재함")
    
    # 3. 데이터 디렉토리 생성
    dirs = [
        "data/sessions",
        "data/recordings",
        "data/logs"
    ]
    
    for dir_path in dirs:
        full_path = project_root / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ {dir_path}/ 디렉토리 준비됨")
    
    print()
    print("=" * 50)
    print("다음 단계:")
    print("=" * 50)
    print()
    print("1. config/settings.yaml 파일을 편집하여 Instagram 계정 정보를 입력하세요")
    print("2. config/targets.json 파일에 모니터링할 유저를 추가하세요")
    print("3. Telegram 알림을 사용하려면 봇 토큰과 Chat ID를 설정하세요")
    print()
    print("설정이 완료되면 다음 명령으로 실행하세요:")
    print("  python main.py")
    print()
    print("로그인 테스트:")
    print("  python main.py --test-login")
    print()
    print("Telegram 테스트:")
    print("  python main.py --test-telegram")
    print()

if __name__ == "__main__":
    main()
