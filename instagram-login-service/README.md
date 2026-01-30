# Instagram Session Generator

모바일에서 Instagram 세션 파일을 생성하는 서비스입니다.

## Railway 배포 방법

1. [Railway](https://railway.app/) 가입 (GitHub 계정으로)
2. New Project → Deploy from GitHub repo
3. 이 폴더를 GitHub에 푸시
4. 자동 배포됨
5. 생성된 URL로 접속

## 사용법

1. 모바일 브라우저에서 Railway URL 접속
2. Instagram 아이디/비밀번호 입력
3. Generate Session 클릭
4. session.json 파일 다운로드됨
5. Story Saver (http://158.179.162.210:8000/)에서 업로드

## 로컬 테스트

```bash
pip install -r requirements.txt
python app.py
```

http://localhost:5000 접속
