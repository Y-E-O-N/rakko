"""
Instagram 세션 생성 스크립트

목적:
    서버 IP가 Instagram에 의해 차단된 경우, 로컬(모바일 핫스팟 등)에서
    세션을 생성한 후 서버로 업로드하여 사용합니다.

사용법:
    1. 이 파일을 복사하여 create_session.py로 저장
    2. USERNAME과 PASSWORD를 실제 계정 정보로 수정
    3. 모바일 핫스팟에 연결 (서버와 다른 IP 사용)
    4. 스크립트 실행: python create_session.py
    5. Instagram 인증 코드 입력 (필요시)
    6. 생성된 세션 파일을 서버로 업로드:
       scp session_local.json oracle:~/instagram-story-saver/data/sessions/session.json
    7. 서버에서 서비스 재시작:
       sudo systemctl restart instagram-story-saver

주의:
    - create_session.py와 session_local.json은 .gitignore에 포함되어 있음
    - 절대 실제 계정 정보가 포함된 파일을 커밋하지 마세요
"""

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired

def challenge_code_handler(username, choice):
    """Instagram에서 보낸 인증 코드 입력"""
    code = input(f"Instagram에서 보낸 인증 코드를 입력하세요: ")
    return code

c = Client()
c.challenge_code_handler = challenge_code_handler

# 여기에 실제 계정 정보 입력
USERNAME = "your_username"
PASSWORD = "your_password"

try:
    c.login(USERNAME, PASSWORD)
    c.dump_settings('session_local.json')
    print('세션 생성 완료: session_local.json')
except ChallengeRequired as e:
    print("챌린지 필요 - Instagram 앱에서 '예, 저입니다' 확인 후 다시 실행하세요")
    print(f"또는 이메일/SMS로 인증 코드가 전송됩니다")
