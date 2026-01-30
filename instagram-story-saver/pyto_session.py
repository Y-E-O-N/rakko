"""
Instagram Session Creator for Pyto (iOS)

사용법:
1. Pyto 앱 설치: https://apps.apple.com/app/pyto/id1436650069
2. 이 스크립트를 Pyto에 복사
3. 실행 전 instagrapi 설치: Pyto 설정 > PyPI > instagrapi 검색 후 설치
4. 스크립트 실행
5. 출력된 JSON을 복사해서 웹 UI에 붙여넣기
"""

import sys

# instagrapi 설치 확인
try:
    from instagrapi import Client
except ImportError:
    print("=" * 50)
    print("instagrapi가 설치되어 있지 않습니다!")
    print()
    print("설치 방법:")
    print("1. Pyto 앱 하단 메뉴에서 'PyPI' 탭 선택")
    print("2. 검색창에 'instagrapi' 입력")
    print("3. 'instagrapi' 패키지 설치")
    print("4. 이 스크립트 다시 실행")
    print("=" * 50)
    sys.exit(1)

import json

def create_session():
    print("=" * 50)
    print("Instagram Session Creator")
    print("=" * 50)
    print()

    # 사용자 입력
    username = input("Instagram 사용자명: ").strip()
    password = input("Instagram 비밀번호: ").strip()

    if not username or not password:
        print("사용자명과 비밀번호를 입력하세요!")
        return

    print()
    print("로그인 중...")

    try:
        client = Client()
        client.delay_range = [1, 3]
        client.login(username, password)

        # 세션을 딕셔너리로 가져오기
        settings = client.get_settings()
        session_json = json.dumps(settings, indent=2, default=str)

        print()
        print("=" * 50)
        print("로그인 성공!")
        print("=" * 50)
        print()
        print("아래 JSON을 전체 복사하세요:")
        print("(길게 눌러서 '전체 선택' 후 복사)")
        print()
        print("-" * 50)
        print(session_json)
        print("-" * 50)
        print()
        print("복사 후:")
        print("1. 웹 브라우저에서 http://158.179.162.210:8000/ 접속")
        print("2. 'Paste Session JSON' 버튼 클릭")
        print("3. JSON 붙여넣기")
        print("4. 'Submit JSON' 클릭")

    except Exception as e:
        print()
        print("=" * 50)
        print(f"로그인 실패: {e}")
        print("=" * 50)
        print()
        print("해결 방법:")
        print("- 비밀번호 확인")
        print("- Instagram 앱에서 보안 확인이 필요할 수 있음")
        print("- 잠시 후 다시 시도")

if __name__ == "__main__":
    create_session()
