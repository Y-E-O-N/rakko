"""
Instagram Story API

스토리 URL을 조회하여 반환합니다.

사용법:
    uvicorn api:app --host 0.0.0.0 --port 8000

엔드포인트:
    GET /api/story?username=target_user
    GET /api/health
    POST /api/login
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, Security, UploadFile, File
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import json
from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    TwoFactorRequired,
    PleaseWaitFewMinutes
)

from src.utils.config import load_config, Config
from src.utils.logger import get_logger

logger = get_logger()

# Global instances
config: Optional[Config] = None
ig_client: Optional[Client] = None
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# Request/Response Models
class LoginRequest(BaseModel):
    username: str
    password: str
    proxy: str = ""  # Optional proxy URL


class CookieLoginRequest(BaseModel):
    sessionid: str
    ds_user_id: str
    csrftoken: str = ""


class LoginResponse(BaseModel):
    success: bool
    message: str


class StoryResponse(BaseModel):
    story_id: str
    type: str  # "video" or "image"
    taken_at: str
    download_url: str
    thumbnail_url: Optional[str] = None


class DownloadResponse(BaseModel):
    success: bool
    username: str
    message: str = ""
    stories: List[StoryResponse] = []
    total_count: int = 0


class HealthResponse(BaseModel):
    status: str
    instagram_logged_in: bool
    timestamp: str


def try_login_with_session() -> bool:
    """저장된 세션으로 로그인 시도"""
    global ig_client, config

    session_file = Path(config.session_file)
    if not session_file.exists():
        return False

    try:
        client = Client()
        client.load_settings(session_file)
        client.login(config.ig_username, config.ig_password)
        client.get_timeline_feed()  # 세션 유효성 확인
        ig_client = client
        logger.info("세션 파일로 Instagram 로그인 성공")
        return True
    except Exception as e:
        logger.warning(f"세션 로그인 실패: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    global config, ig_client

    logger.info("API 서버 초기화 중...")

    # 설정 로드
    try:
        config = load_config()
        logger.info("설정 로드 완료")
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        raise

    # 저장된 세션으로 로그인 시도
    try_login_with_session()

    logger.info("API 서버 준비 완료")

    yield

    logger.info("API 서버 종료 중...")


app = FastAPI(
    title="Instagram Story API",
    description="Instagram 스토리 URL을 조회합니다.",
    version="2.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """웹 UI 제공"""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Instagram Story API", "docs": "/docs"}


def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """API 키 검증 (선택사항)"""
    expected_key = os.environ.get("API_KEY", "")
    if not expected_key:
        return True
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """서버 상태 확인"""
    ig_logged_in = False

    if ig_client:
        try:
            ig_client.get_timeline_feed()
            ig_logged_in = True
        except:
            pass

    return HealthResponse(
        status="ok",
        instagram_logged_in=ig_logged_in,
        timestamp=datetime.now().isoformat()
    )


@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Instagram 로그인 및 세션 생성"""
    global ig_client, config

    username = request.username.strip()
    password = request.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username과 password는 필수입니다")

    try:
        # 새 클라이언트로 로그인
        client = Client()
        client.delay_range = [1, 3]

        logger.info(f"Instagram 로그인 시도: {username}")
        client.login(username, password)

        # 세션 저장
        session_file = Path(config.session_file)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        client.dump_settings(session_file)

        # 파일 권한 설정
        try:
            os.chmod(session_file, 0o600)
        except:
            pass

        # 글로벌 클라이언트 업데이트
        ig_client = client

        logger.info(f"Instagram 로그인 성공: {username}")
        return LoginResponse(success=True, message="로그인 성공!")

    except BadPassword as e:
        error_msg = str(e)
        logger.error(f"로그인 실패 (BadPassword): {error_msg}")
        # IP 블랙리스트 관련 메시지 확인
        if "blacklist" in error_msg.lower() or "ip" in error_msg.lower():
            raise HTTPException(status_code=403, detail="서버 IP가 Instagram에 의해 차단되었습니다. 로컬에서 세션을 생성해서 업로드하세요.")
        raise HTTPException(status_code=401, detail=f"비밀번호 오류: {error_msg}")
    except TwoFactorRequired as e:
        logger.error(f"로그인 실패 (2FA 필요): {e}")
        raise HTTPException(status_code=400, detail="2단계 인증이 필요합니다. 앱에서 인증 후 다시 시도하세요.")
    except ChallengeRequired as e:
        logger.error(f"로그인 실패 (Challenge 필요): {e}")
        raise HTTPException(status_code=400, detail="Instagram 보안 확인이 필요합니다. 앱에서 확인 후 다시 시도하세요.")
    except PleaseWaitFewMinutes as e:
        logger.error(f"로그인 실패 (Rate Limit): {e}")
        raise HTTPException(status_code=429, detail="너무 많은 요청입니다. 잠시 후 다시 시도하세요.")
    except Exception as e:
        logger.error(f"로그인 실패 (Unknown): {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"로그인 실패: {str(e)}")


@app.post("/api/login-with-cookies", response_model=LoginResponse)
async def login_with_cookies(request: CookieLoginRequest):
    """웹 쿠키로 세션 생성"""
    global ig_client, config
    import uuid as uuid_module

    sessionid = request.sessionid.strip()
    ds_user_id = request.ds_user_id.strip()
    csrftoken = request.csrftoken.strip() if request.csrftoken else ""

    if not sessionid or not ds_user_id:
        raise HTTPException(status_code=400, detail="sessionid와 ds_user_id는 필수입니다")

    try:
        # 세션 데이터 구성
        session_data = {
            "uuids": {
                "phone_id": str(uuid_module.uuid4()),
                "uuid": str(uuid_module.uuid4()),
                "client_session_id": str(uuid_module.uuid4()),
                "advertising_id": str(uuid_module.uuid4()),
                "android_device_id": f"android-{uuid_module.uuid4().hex[:16]}",
                "request_id": str(uuid_module.uuid4()),
                "tray_session_id": str(uuid_module.uuid4()),
            },
            "mid": "",
            "ig_u_rur": "",
            "ig_www_claim": "",
            "authorization_data": {
                "ds_user_id": ds_user_id,
                "sessionid": sessionid,
            },
            "cookies": {
                "sessionid": sessionid,
                "ds_user_id": ds_user_id,
                "csrftoken": csrftoken,
            },
            "last_login": datetime.now().timestamp(),
            "device_settings": {
                "app_version": "269.0.0.18.75",
                "android_version": 31,
                "android_release": "12",
                "dpi": "480dpi",
                "resolution": "1080x2168",
                "manufacturer": "samsung",
                "device": "a]52q",
                "model": "SM-A526B",
                "cpu": "qcom",
                "version_code": "422022788",
            },
            "user_agent": "Instagram 269.0.0.18.75 Android (31/12; 480dpi; 1080x2168; samsung; SM-A526B; a52q; qcom; ko_KR; 422022788)",
        }

        # 세션 파일 저장
        session_file = Path(config.session_file)
        session_file.parent.mkdir(parents=True, exist_ok=True)

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

        try:
            os.chmod(session_file, 0o600)
        except:
            pass

        logger.info(f"쿠키로 세션 파일 생성됨: ds_user_id={ds_user_id}")

        # 세션으로 로그인 시도
        client = Client()
        client.load_settings(session_file)

        # 세션 유효성 확인
        try:
            client.get_timeline_feed()
            ig_client = client
            logger.info("쿠키 세션으로 Instagram 로그인 성공")
            return LoginResponse(success=True, message="쿠키 로그인 성공!")
        except Exception as e:
            logger.warning(f"세션 검증 실패, 재로그인 시도: {e}")
            # 설정된 username/password로 재로그인 시도
            if config.ig_username and config.ig_password:
                client.login(config.ig_username, config.ig_password)
                client.dump_settings(session_file)
                ig_client = client
                logger.info("재로그인으로 Instagram 로그인 성공")
                return LoginResponse(success=True, message="세션 갱신 성공!")
            raise

    except Exception as e:
        logger.error(f"쿠키 로그인 실패: {e}")
        raise HTTPException(status_code=500, detail=f"로그인 실패: {str(e)}")


@app.post("/api/upload-session", response_model=LoginResponse)
async def upload_session(file: UploadFile = File(...)):
    """세션 파일 업로드로 로그인"""
    global ig_client, config

    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="JSON 파일만 업로드 가능합니다")

    try:
        # 파일 내용 읽기
        content = await file.read()
        session_data = json.loads(content.decode('utf-8'))

        # 세션 파일 저장
        session_file = Path(config.session_file)
        session_file.parent.mkdir(parents=True, exist_ok=True)

        with open(session_file, 'w') as f:
            json.dump(session_data, f)

        # 파일 권한 설정
        try:
            os.chmod(session_file, 0o600)
        except:
            pass

        logger.info(f"세션 파일 업로드됨: {file.filename}")

        # 세션으로 로그인 시도
        client = Client()
        client.load_settings(session_file)
        client.login(config.ig_username, config.ig_password)
        client.get_timeline_feed()  # 세션 유효성 확인

        ig_client = client
        logger.info("업로드된 세션으로 Instagram 로그인 성공")

        return LoginResponse(success=True, message="세션 업로드 및 로그인 성공!")

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="유효하지 않은 JSON 파일입니다")
    except Exception as e:
        logger.error(f"세션 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=f"세션 로그인 실패: {str(e)}")


@app.get("/api/story", response_model=DownloadResponse)
async def get_stories(
    username: str = Query(..., description="Instagram 사용자명"),
    _: bool = Depends(verify_api_key)
):
    """특정 사용자의 스토리 URL을 조회합니다."""
    if not ig_client:
        raise HTTPException(status_code=503, detail="Instagram에 로그인되어 있지 않습니다")

    username = username.lower().strip().lstrip("@")

    if not username:
        raise HTTPException(status_code=400, detail="username은 필수입니다")

    try:
        # 사용자 정보 조회
        try:
            user_info = ig_client.user_info_by_username_v1(username)
        except Exception as e:
            logger.error(f"사용자 조회 실패: {e}")
            raise HTTPException(status_code=404, detail=f"사용자를 찾을 수 없습니다: {username}")

        user_id = user_info.pk

        # 스토리 조회
        try:
            stories = ig_client.user_stories(user_id)
        except Exception as e:
            logger.error(f"스토리 조회 실패: {e}")
            raise HTTPException(status_code=500, detail=f"스토리 조회 실패: {str(e)}")

        if not stories:
            return DownloadResponse(
                success=True,
                username=username,
                message="현재 스토리가 없습니다",
                stories=[],
                total_count=0
            )

        # 스토리 URL 추출
        story_responses = []
        for story in stories:
            try:
                media_type = story.media_type

                if media_type == 2:  # 비디오
                    download_url = str(story.video_url) if story.video_url else None
                else:  # 이미지
                    download_url = str(story.thumbnail_url) if story.thumbnail_url else None

                if not download_url:
                    continue

                thumbnail_url = str(story.thumbnail_url) if story.thumbnail_url else None

                story_responses.append(StoryResponse(
                    story_id=str(story.pk),
                    type="video" if media_type == 2 else "image",
                    taken_at=story.taken_at.isoformat(),
                    download_url=download_url,
                    thumbnail_url=thumbnail_url
                ))

            except Exception as e:
                logger.error(f"스토리 파싱 실패 (ID: {story.pk}): {e}")
                continue

        return DownloadResponse(
            success=True,
            username=username,
            message=f"{len(story_responses)}개 스토리 발견",
            stories=story_responses,
            total_count=len(story_responses)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"스토리 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
