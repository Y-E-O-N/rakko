"""
Instagram Story Download API

온디맨드 방식으로 스토리를 다운로드하고 R2에 업로드합니다.

사용법:
    uvicorn api:app --host 0.0.0.0 --port 8000

엔드포인트:
    GET /api/story?username=target_user
    GET /api/health
"""

import os
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.utils.config import load_config, Config
from src.utils.logger import get_logger
from src.auth.instagram_auth import InstagramAuth
from src.storage.cloud_storage import CloudStorage
from src.downloader.story_downloader import DownloadTask
from src.monitor.story_monitor import StoryItem

logger = get_logger()

# Global instances
config: Optional[Config] = None
ig_client = None
cloud_storage: Optional[CloudStorage] = None
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# Response Models
class StoryResponse(BaseModel):
    story_id: str
    type: str  # "video" or "image"
    taken_at: str
    download_url: Optional[str] = None
    local_path: Optional[str] = None
    file_size: int = 0


class DownloadResponse(BaseModel):
    success: bool
    username: str
    message: str = ""
    stories: List[StoryResponse] = []
    total_count: int = 0


class HealthResponse(BaseModel):
    status: str
    instagram_logged_in: bool
    cloud_storage_connected: bool
    timestamp: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    global config, ig_client, cloud_storage

    logger.info("API 서버 초기화 중...")

    # 설정 로드
    try:
        config = load_config()
        logger.info("설정 로드 완료")
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        raise

    # Instagram 로그인
    try:
        auth = InstagramAuth(
            username=config.ig_username,
            password=config.ig_password,
            session_file=config.session_file,
            totp_secret=config.ig_totp_secret,
            proxy=config.proxy,
            delay_min=config.api_delay_min,
            delay_max=config.api_delay_max
        )
        if auth.login():
            ig_client = auth.get_client()
            logger.info("Instagram 로그인 성공")
        else:
            logger.error("Instagram 로그인 실패")
    except Exception as e:
        logger.error(f"Instagram 인증 실패: {e}")

    # Cloud Storage 초기화
    if config.cloud_enabled:
        try:
            cloud_storage = CloudStorage(
                account_id=config.r2_account_id,
                access_key=config.r2_access_key,
                secret_key=config.r2_secret_key,
                bucket_name=config.r2_bucket,
                delete_after_upload=config.delete_after_upload,
                public_url=config.r2_public_url
            )
            logger.info("Cloud Storage 연결 완료")
        except Exception as e:
            logger.error(f"Cloud Storage 연결 실패: {e}")

    logger.info("API 서버 준비 완료")

    yield

    # 종료 시 정리
    logger.info("API 서버 종료 중...")


app = FastAPI(
    title="Instagram Story Download API",
    description="온디맨드 방식으로 Instagram 스토리를 다운로드합니다.",
    version="1.0.0",
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


def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """API 키 검증 (선택사항)"""
    expected_key = os.environ.get("API_KEY", "")
    if not expected_key:
        return True  # API 키 미설정 시 모든 요청 허용
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """서버 상태 확인"""
    ig_logged_in = False
    cloud_connected = False

    if ig_client:
        try:
            ig_client.get_timeline_feed()
            ig_logged_in = True
        except:
            pass

    if cloud_storage:
        try:
            cloud_connected = cloud_storage.test_connection()
        except:
            pass

    return HealthResponse(
        status="ok",
        instagram_logged_in=ig_logged_in,
        cloud_storage_connected=cloud_connected,
        timestamp=datetime.now().isoformat()
    )


@app.get("/api/story", response_model=DownloadResponse)
async def download_stories(
    username: str = Query(..., description="Instagram 사용자명"),
    _: bool = Depends(verify_api_key)
):
    """
    특정 사용자의 스토리를 다운로드합니다.

    - **username**: Instagram 사용자명 (@ 없이)
    """
    if not ig_client:
        raise HTTPException(status_code=503, detail="Instagram 클라이언트가 초기화되지 않았습니다")

    username = username.lower().strip().lstrip("@")

    if not username:
        raise HTTPException(status_code=400, detail="username은 필수입니다")

    try:
        # 사용자 정보 조회
        logger.info(f"사용자 조회 중: {username}")
        try:
            user_info = ig_client.user_info_by_username_v1(username)
        except Exception as e:
            logger.error(f"사용자 조회 실패: {e}")
            raise HTTPException(status_code=404, detail=f"사용자를 찾을 수 없습니다: {username}")

        user_id = user_info.pk
        display_name = user_info.full_name or username

        # 스토리 조회
        logger.info(f"스토리 조회 중: {username} (ID: {user_id})")
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

        logger.info(f"{len(stories)}개 스토리 발견")

        # 스토리 다운로드 및 업로드
        downloaded_stories = []
        output_dir = Path(config.output_dir) / username
        output_dir.mkdir(parents=True, exist_ok=True)

        for story in stories:
            try:
                story_item = _parse_story(story, username, display_name, user_id)
                if not story_item:
                    continue

                # 파일 다운로드
                result = await _download_and_upload_story(story_item, output_dir)
                if result:
                    downloaded_stories.append(result)

            except Exception as e:
                logger.error(f"스토리 처리 실패 (ID: {story.pk}): {e}")
                continue

        return DownloadResponse(
            success=True,
            username=username,
            message=f"{len(downloaded_stories)}개 스토리 다운로드 완료",
            stories=downloaded_stories,
            total_count=len(downloaded_stories)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"스토리 다운로드 중 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _parse_story(story, username: str, display_name: str, user_id: int) -> Optional[StoryItem]:
    """Story 객체를 StoryItem으로 변환"""
    try:
        media_type = story.media_type

        video_url = None
        image_url = None

        if media_type == 2:  # 비디오
            if story.video_url:
                video_url = str(story.video_url)

        if story.thumbnail_url:
            image_url = str(story.thumbnail_url)

        taken_at = story.taken_at
        expire_at = taken_at + timedelta(hours=24)

        return StoryItem(
            story_id=str(story.pk),
            user_id=user_id,
            username=username,
            display_name=display_name,
            media_type=media_type,
            taken_at=taken_at,
            expire_at=expire_at,
            video_url=video_url,
            thumbnail_url=image_url,
            image_url=image_url
        )
    except Exception as e:
        logger.error(f"스토리 파싱 실패: {e}")
        return None


async def _download_and_upload_story(story: StoryItem, output_dir: Path) -> Optional[StoryResponse]:
    """스토리 다운로드 및 R2 업로드"""
    import requests

    media_url = story.media_url
    if not media_url:
        logger.warning(f"미디어 URL 없음: {story.story_id}")
        return None

    # 파일명 생성
    timestamp = story.taken_at.strftime("%Y%m%d_%H%M%S")
    ext = "mp4" if story.is_video else "jpg"
    filename = f"{story.username}_{timestamp}_{story.story_id}.{ext}"
    output_path = output_dir / filename

    # 다운로드
    try:
        logger.info(f"다운로드 중: {filename}")
        response = requests.get(media_url, timeout=60, stream=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        file_size = output_path.stat().st_size
        logger.info(f"다운로드 완료: {filename} ({file_size} bytes)")

    except Exception as e:
        logger.error(f"다운로드 실패: {e}")
        return None

    # R2 업로드
    download_url = None
    if cloud_storage and config.r2_public_url:
        try:
            # 원격 경로: username/YYYY-MM/filename
            month_folder = story.taken_at.strftime('%Y-%m')
            remote_path = f"{story.username}/{month_folder}/{filename}"

            success = cloud_storage.upload_file(output_path, remote_path)
            if success:
                download_url = f"{config.r2_public_url.rstrip('/')}/{remote_path}"
                logger.info(f"R2 업로드 완료: {remote_path}")

                # 로컬 파일 삭제 (설정에 따라)
                if config.delete_after_upload:
                    output_path.unlink()

        except Exception as e:
            logger.error(f"R2 업로드 실패: {e}")

    return StoryResponse(
        story_id=story.story_id,
        type="video" if story.is_video else "image",
        taken_at=story.taken_at.isoformat(),
        download_url=download_url,
        local_path=str(output_path) if output_path.exists() else None,
        file_size=file_size
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
