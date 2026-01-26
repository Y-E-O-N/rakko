"""
Instagram 스토리 모니터링 서비스
"""
import time
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from instagrapi import Client
from instagrapi.types import Story
from instagrapi.exceptions import ClientError, ClientConnectionError
from src.utils.logger import get_logger
from src.utils.config import TargetUser, save_targets

logger = get_logger()


@dataclass
class StoryItem:
    """스토리 아이템 정보"""
    story_id: str
    user_id: int
    username: str
    display_name: str
    media_type: int  # 1: 이미지, 2: 비디오
    taken_at: datetime
    expire_at: datetime
    
    # 미디어 URL
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    
    # 추가 정보
    caption: str = ""
    mentions: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    
    # 상태
    is_downloaded: bool = False
    download_path: Optional[Path] = None
    
    @property
    def is_video(self) -> bool:
        return self.media_type == 2
    
    @property
    def is_image(self) -> bool:
        return self.media_type == 1
    
    @property
    def media_url(self) -> str:
        """다운로드할 URL 반환"""
        if self.is_video and self.video_url:
            return self.video_url
        return self.image_url or self.thumbnail_url or ""
    
    @property
    def file_extension(self) -> str:
        """파일 확장자"""
        if self.is_video:
            return "mp4"
        return "jpg"
    
    @property
    def time_remaining(self) -> timedelta:
        """남은 시간 (음수 방지)"""
        remaining = self.expire_at - datetime.now()
        if remaining.total_seconds() < 0:
            return timedelta(0)
        return remaining
    
    @property
    def is_expired(self) -> bool:
        """만료 여부"""
        return datetime.now() > self.expire_at


@dataclass
class MonitorState:
    """모니터 상태"""
    is_running: bool = False
    last_check: Optional[datetime] = None
    total_checks: int = 0
    total_stories_found: int = 0
    total_new_stories: int = 0


class DownloadHistory:
    """다운로드 기록 관리 (중복 방지)"""
    
    def __init__(self, history_file: str, expire_hours: int = 24):
        self.history_file = Path(history_file)
        self.expire_hours = expire_hours
        self._history: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._load()
    
    def _load(self):
        """기록 파일 로드"""
        if not self.history_file.exists():
            return
        
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            now = datetime.now()
            cutoff = now - timedelta(hours=self.expire_hours)
            
            for story_id, timestamp_str in data.get('downloads', {}).items():
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp > cutoff:
                        self._history[story_id] = timestamp
                except (ValueError, TypeError):
                    # 잘못된 날짜 형식 무시
                    pass
                    
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"다운로드 기록 로드 실패: {e}")
    
    def _save(self):
        """기록 파일 저장 (원자적 쓰기)"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'downloads': {
                    story_id: ts.isoformat()
                    for story_id, ts in self._history.items()
                },
                'last_updated': datetime.now().isoformat()
            }
            
            # 원자적 쓰기: 임시 파일에 쓴 후 이름 변경
            temp_file = self.history_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            temp_file.rename(self.history_file)
                
        except Exception as e:
            logger.warning(f"다운로드 기록 저장 실패: {e}")
            # 임시 파일 정리
            temp_file = self.history_file.with_suffix('.tmp')
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
    
    def is_downloaded(self, story_id: str) -> bool:
        """이미 다운로드했는지 확인"""
        with self._lock:
            if story_id not in self._history:
                return False
            
            # 만료 확인
            download_time = self._history[story_id]
            if datetime.now() - download_time > timedelta(hours=self.expire_hours):
                del self._history[story_id]
                return False
            
            return True
    
    def mark_downloaded(self, story_id: str):
        """다운로드 완료 표시"""
        with self._lock:
            self._history[story_id] = datetime.now()
            self._save()
    
    def cleanup(self):
        """만료된 기록 정리"""
        with self._lock:
            now = datetime.now()
            cutoff = now - timedelta(hours=self.expire_hours)
            
            expired = [
                story_id for story_id, ts in self._history.items()
                if ts < cutoff
            ]
            
            for story_id in expired:
                del self._history[story_id]
            
            if expired:
                self._save()
                logger.debug(f"만료된 기록 {len(expired)}개 정리됨")


class StoryMonitor:
    """스토리 모니터링"""
    
    # 해상도 매핑 (높이 기준)
    QUALITY_MAP = {
        '1080p': 1080,
        '720p': 720,
        '480p': 480,
        '360p': 360,
        '240p': 240,
    }
    
    def __init__(
        self,
        client: Client,
        targets: List[TargetUser],
        history: DownloadHistory,
        batch_size: int = 20,
        batch_delay: int = 5,
        targets_file: str = "config/targets.json",
        download_videos: bool = True,
        download_images: bool = True,
        video_quality: str = "highest",
        image_quality: str = "highest",
        story_expire_hours: int = 24,
        user_id_resolve_delay: float = 2.0,
        user_id_resolve_batch: int = 10
    ):
        self.client = client
        self.targets = targets
        self.history = history
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.targets_file = targets_file
        self.download_videos = download_videos
        self.download_images = download_images
        self.video_quality = video_quality.lower()
        self.image_quality = image_quality.lower()
        self.story_expire_hours = story_expire_hours
        self.user_id_resolve_delay = user_id_resolve_delay
        self.user_id_resolve_batch = user_id_resolve_batch
        
        self.state = MonitorState()
        self._callbacks: Dict[str, List[Callable]] = {
            'on_new_story': [],
            'on_error': []
        }
        
        self._lock = threading.RLock()
        self._targets_lock = threading.Lock()
        
        self._resolve_user_ids()
    
    def _select_video_url(self, video_versions: List[Dict]) -> str:
        """화질 설정에 따라 비디오 URL 선택"""
        if not video_versions:
            return ""
        
        if self.video_quality == "highest":
            return video_versions[0].get('url', '')
        elif self.video_quality == "lowest":
            return video_versions[-1].get('url', '')
        elif self.video_quality in self.QUALITY_MAP:
            target_height = self.QUALITY_MAP[self.video_quality]
            # 목표 해상도 이하 중 가장 높은 것 선택
            for version in video_versions:
                height = version.get('height', 0)
                if height <= target_height:
                    return version.get('url', '')
            # 없으면 가장 낮은 화질
            return video_versions[-1].get('url', '')
        else:
            # 알 수 없는 옵션이면 최고 화질
            return video_versions[0].get('url', '')
    
    def _select_image_url(self, image_versions: List[Dict]) -> str:
        """화질 설정에 따라 이미지 URL 선택"""
        if not image_versions:
            return ""
        
        if self.image_quality == "highest":
            return image_versions[0].get('url', '')
        elif self.image_quality == "lowest":
            return image_versions[-1].get('url', '')
        else:
            # 알 수 없는 옵션이면 최고 화질
            return image_versions[0].get('url', '')
    
    def _resolve_user_ids(self):
        """유저네임을 User ID로 변환"""
        needs_resolve = [t for t in self.targets if t.user_id is None]
        
        if not needs_resolve:
            return
        
        logger.info(f"{len(needs_resolve)}개 유저의 ID를 조회합니다...")
        
        resolved_count = 0
        for i, target in enumerate(needs_resolve):
            try:
                user_info = self.client.user_info_by_username(target.username)
                target.user_id = user_info.pk
                resolved_count += 1
                logger.debug(f"  {target.username} -> {target.user_id}")
                
                # 배치마다 딜레이
                if (i + 1) % self.user_id_resolve_batch == 0:
                    time.sleep(self.user_id_resolve_delay)
                    
            except ClientError as e:
                logger.warning(f"유저 ID 조회 실패: {target.username} - {e}")
            except Exception as e:
                logger.warning(f"유저 ID 조회 실패: {target.username} - {e}")
        
        if resolved_count > 0:
            with self._targets_lock:
                try:
                    save_targets(self.targets, self.targets_file)
                except Exception as e:
                    logger.warning(f"타겟 저장 실패: {e}")
        
        logger.info(f"유저 ID 조회 완료: {resolved_count}/{len(needs_resolve)} 성공")
    
    def on(self, event: str, callback: Callable):
        """이벤트 콜백 등록"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _emit(self, event: str, *args, **kwargs):
        """이벤트 발생"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"콜백 실행 에러 ({event}): {e}")
    
    def check_all_stories(self) -> List[StoryItem]:
        """모든 타겟의 스토리 확인"""
        with self._lock:
            self.state.total_checks += 1
            self.state.last_check = datetime.now()
        
        new_stories = []
        
        # 우선순위별 정렬
        priority_order = {'high': 0, 'normal': 1, 'low': 2}
        sorted_targets = sorted(
            self.targets,
            key=lambda t: priority_order.get(t.priority, 1)
        )
        
        # 배치로 나누어 체크
        for i in range(0, len(sorted_targets), self.batch_size):
            batch = sorted_targets[i:i + self.batch_size]
            
            for target in batch:
                if target.user_id is None:
                    continue
                
                try:
                    stories = self._check_user_stories(target)
                    
                    for story in stories:
                        # 중복 체크
                        if self.history.is_downloaded(story.story_id):
                            continue
                        
                        # 미디어 타입 필터
                        if story.is_video and not self.download_videos:
                            continue
                        if story.is_image and not self.download_images:
                            continue
                        
                        new_stories.append(story)
                        
                        with self._lock:
                            self.state.total_new_stories += 1
                        
                        logger.info(
                            f"📸 새 스토리: {story.display_name} "
                            f"({'비디오' if story.is_video else '이미지'})"
                        )
                        
                        self._emit('on_new_story', story)
                        
                except ClientConnectionError as e:
                    logger.warning(f"네트워크 오류 ({target.username}): {e}")
                    self._emit('on_error', e)
                except ClientError as e:
                    logger.warning(f"API 오류 ({target.username}): {e}")
                    self._emit('on_error', e)
                except Exception as e:
                    logger.error(f"스토리 체크 실패 ({target.username}): {e}")
                    self._emit('on_error', e)
            
            # 배치 간 딜레이
            if i + self.batch_size < len(sorted_targets):
                time.sleep(self.batch_delay)
        
        with self._lock:
            self.state.total_stories_found += len(new_stories)
        
        return new_stories
    
    def _check_user_stories(self, target: TargetUser) -> List[StoryItem]:
        """개별 유저의 스토리 확인"""
        stories = []
        
        try:
            user_stories = self.client.user_stories(target.user_id)
            
            for story in user_stories:
                story_item = self._parse_story(story, target)
                if story_item and not story_item.is_expired:
                    stories.append(story_item)
                    
        except Exception as e:
            logger.debug(f"스토리 조회 에러 ({target.username}): {e}")
        
        return stories
    
    def _parse_story(self, story: Story, target: TargetUser) -> Optional[StoryItem]:
        """Story 객체를 StoryItem으로 변환"""
        try:
            # 미디어 타입: 1=이미지, 2=비디오
            media_type = story.media_type
            
            # URL 추출
            video_url = None
            thumbnail_url = None
            image_url = None
            
            if media_type == 2:  # 비디오
                if story.video_url:
                    video_url = str(story.video_url)
                if story.thumbnail_url:
                    thumbnail_url = str(story.thumbnail_url)
            else:  # 이미지
                if story.thumbnail_url:
                    image_url = str(story.thumbnail_url)
            
            # 만료 시간
            taken_at = story.taken_at
            expire_at = taken_at + timedelta(hours=self.story_expire_hours)
            
            # 캡션, 멘션, 해시태그
            caption = ""
            mentions = []
            hashtags = []
            
            if hasattr(story, 'caption') and story.caption:
                caption = story.caption.text if hasattr(story.caption, 'text') else str(story.caption)
            
            return StoryItem(
                story_id=str(story.pk),
                user_id=target.user_id,
                username=target.username,
                display_name=target.display_name,
                media_type=media_type,
                taken_at=taken_at,
                expire_at=expire_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
                image_url=image_url,
                caption=caption,
                mentions=mentions,
                hashtags=hashtags
            )
            
        except Exception as e:
            logger.debug(f"스토리 파싱 실패: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """모니터링 통계"""
        with self._lock:
            return {
                'is_running': self.state.is_running,
                'last_check': self.state.last_check,
                'total_checks': self.state.total_checks,
                'total_stories_found': self.state.total_stories_found,
                'total_new_stories': self.state.total_new_stories,
                'targets_count': len(self.targets)
            }


class StoryMonitorV2(StoryMonitor):
    """
    개선된 스토리 모니터 - Reels Tray 기반
    
    팔로잉의 모든 스토리를 한 번에 가져와서 API 호출 최소화
    """
    
    def check_all_stories(self) -> List[StoryItem]:
        """Reels Tray에서 스토리 확인"""
        with self._lock:
            self.state.total_checks += 1
            self.state.last_check = datetime.now()
        
        new_stories = []
        target_usernames = {t.username.lower(): t for t in self.targets}
        
        try:
            # Reels Tray에서 모든 스토리 가져오기
            reels = self._get_reels_tray()
            
            for reel in reels:
                username = reel.get('user', {}).get('username', '').lower()
                
                if username not in target_usernames:
                    continue
                
                target = target_usernames[username]
                
                # 스토리 아이템들 처리
                items = reel.get('items', [])
                for item in items:
                    story = self._parse_reel_item(item, target)
                    
                    if not story or story.is_expired:
                        continue
                    
                    # 중복 체크
                    if self.history.is_downloaded(story.story_id):
                        continue
                    
                    # 미디어 타입 필터
                    if story.is_video and not self.download_videos:
                        continue
                    if story.is_image and not self.download_images:
                        continue
                    
                    new_stories.append(story)
                    
                    with self._lock:
                        self.state.total_new_stories += 1
                    
                    logger.info(
                        f"📸 새 스토리: {story.display_name} "
                        f"({'비디오' if story.is_video else '이미지'})"
                    )
                    
                    self._emit('on_new_story', story)
            
        except ClientConnectionError as e:
            logger.warning(f"네트워크 오류로 스토리 피드 조회 실패: {e}")
            return super().check_all_stories()
        except ClientError as e:
            logger.warning(f"API 오류로 스토리 피드 조회 실패: {e}")
            return super().check_all_stories()
        except Exception as e:
            logger.error(f"스토리 피드 조회 실패: {e}")
            return super().check_all_stories()
        
        with self._lock:
            self.state.total_stories_found += len(new_stories)
        
        return new_stories
    
    def _get_reels_tray(self) -> List[Dict]:
        """Reels Tray 가져오기"""
        try:
            result = self.client.private_request("feed/reels_tray/")
            return result.get('tray', [])
        except Exception as e:
            logger.debug(f"Reels tray 조회 실패: {e}")
            return []
    
    def _parse_reel_item(self, item: Dict, target: TargetUser) -> Optional[StoryItem]:
        """Reel 아이템을 StoryItem으로 변환"""
        try:
            story_id = str(item.get('pk', item.get('id', '')))
            media_type = item.get('media_type', 1)
            
            # 시간
            taken_at_ts = item.get('taken_at', time.time())
            taken_at = datetime.fromtimestamp(taken_at_ts)
            expire_at = taken_at + timedelta(hours=self.story_expire_hours)
            
            # URL 추출 (화질 설정 적용)
            video_url = None
            thumbnail_url = None
            image_url = None
            
            if media_type == 2:  # 비디오
                video_versions = item.get('video_versions', [])
                if video_versions:
                    video_url = self._select_video_url(video_versions)
                
                image_versions = item.get('image_versions2', {}).get('candidates', [])
                if image_versions:
                    thumbnail_url = image_versions[0].get('url', '')
            else:  # 이미지
                image_versions = item.get('image_versions2', {}).get('candidates', [])
                if image_versions:
                    image_url = self._select_image_url(image_versions)
            
            return StoryItem(
                story_id=story_id,
                user_id=target.user_id,
                username=target.username,
                display_name=target.display_name,
                media_type=media_type,
                taken_at=taken_at,
                expire_at=expire_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
                image_url=image_url
            )
            
        except Exception as e:
            logger.debug(f"Reel 아이템 파싱 실패: {e}")
            return None
