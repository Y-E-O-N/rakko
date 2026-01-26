"""
Instagram 라이브 모니터링 서비스
"""
import time
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from instagrapi import Client
from instagrapi.types import User
from instagrapi.exceptions import ClientError, ClientConnectionError
from src.utils.logger import get_logger
from src.utils.config import TargetUser, save_targets

logger = get_logger()


@dataclass
class LiveBroadcast:
    """라이브 방송 정보"""
    broadcast_id: str
    user_id: int
    username: str
    display_name: str
    title: str
    viewer_count: int
    started_at: datetime
    dash_playback_url: str
    dash_abr_playback_url: str
    cover_frame_url: str
    
    # 내부 상태
    is_recording: bool = False
    recording_started_at: Optional[datetime] = None


@dataclass
class MonitorState:
    """모니터 상태"""
    is_running: bool = False
    last_check: Optional[datetime] = None
    active_lives: Dict[str, LiveBroadcast] = field(default_factory=dict)
    total_checks: int = 0
    total_lives_found: int = 0


class LiveMonitor:
    """라이브 방송 모니터링"""
    
    def __init__(
        self,
        client: Client,
        targets: List[TargetUser],
        batch_size: int = 50,
        batch_delay: int = 10,
        targets_file: str = "config/targets.json"
    ):
        self.client = client
        self.targets = targets
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.targets_file = targets_file
        
        self.state = MonitorState()
        self._callbacks: Dict[str, List[Callable]] = {
            'on_live_start': [],
            'on_live_end': [],
            'on_error': []
        }
        
        # 동시성 제어
        self._lock = threading.RLock()
        self._targets_lock = threading.Lock()
        
        # User ID 캐시 초기화
        self._resolve_user_ids()
    
    def _resolve_user_ids(self):
        """유저네임을 User ID로 변환 (캐시)"""
        needs_resolve = [t for t in self.targets if t.user_id is None]
        
        if not needs_resolve:
            return
        
        logger.info(f"{len(needs_resolve)}개 유저의 ID를 조회합니다...")
        
        resolved_count = 0
        for i, target in enumerate(needs_resolve):
            try:
                user_info = self.client.user_info_by_username_v1(target.username)
                target.user_id = user_info.pk
                resolved_count += 1
                logger.debug(f"  {target.username} -> {target.user_id}")
                
                # API 제한 회피
                if (i + 1) % 10 == 0:
                    time.sleep(2)
                    
            except ClientError as e:
                logger.warning(f"유저 ID 조회 실패 (API 오류): {target.username} - {e}")
            except Exception as e:
                logger.warning(f"유저 ID 조회 실패: {target.username} - {e}")
        
        # 업데이트된 ID 저장 (스레드 안전)
        if resolved_count > 0:
            with self._targets_lock:
                try:
                    save_targets(self.targets, self.targets_file)
                except Exception as e:
                    logger.warning(f"타겟 저장 실패: {e}")
        
        logger.info(f"유저 ID 조회 완료: {resolved_count}/{len(needs_resolve)} 성공")
    
    def on(self, event: str, callback: Callable):
        """
        이벤트 콜백 등록
        
        Events:
            - on_live_start: 라이브 시작 시 (LiveBroadcast)
            - on_live_end: 라이브 종료 시 (LiveBroadcast)
            - on_error: 에러 발생 시 (Exception)
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _emit(self, event: str, *args, **kwargs):
        """이벤트 발생"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"콜백 실행 에러 ({event}): {e}")
    
    def check_all_lives(self) -> List[LiveBroadcast]:
        """
        모든 타겟의 라이브 상태 확인
        
        Returns:
            현재 라이브 중인 방송 리스트
        """
        with self._lock:
            self.state.total_checks += 1
            self.state.last_check = datetime.now()
        
        active_broadcasts = []
        checked_user_ids = set()
        
        # 우선순위별로 정렬 (high -> normal -> low)
        priority_order = {'high': 0, 'normal': 1, 'low': 2}
        sorted_targets = sorted(
            self.targets,
            key=lambda t: priority_order.get(t.priority, 1)
        )
        
        # 배치로 나누어 체크
        for i in range(0, len(sorted_targets), self.batch_size):
            batch = sorted_targets[i:i + self.batch_size]
            
            for target in batch:
                if target.user_id is None or target.user_id in checked_user_ids:
                    continue
                
                checked_user_ids.add(target.user_id)
                
                try:
                    broadcast = self._check_user_live(target)
                    if broadcast:
                        active_broadcasts.append(broadcast)
                        self._handle_live_found(broadcast)
                        
                except ClientConnectionError as e:
                    logger.warning(f"네트워크 오류 ({target.username}): {e}")
                    self._emit('on_error', e)
                except ClientError as e:
                    logger.warning(f"API 오류 ({target.username}): {e}")
                    self._emit('on_error', e)
                except Exception as e:
                    logger.error(f"라이브 체크 실패 ({target.username}): {e}")
                    self._emit('on_error', e)
            
            # 배치 간 딜레이
            if i + self.batch_size < len(sorted_targets):
                time.sleep(self.batch_delay)
        
        # 종료된 라이브 처리
        self._handle_ended_lives(active_broadcasts)
        
        return active_broadcasts
    
    def _check_user_live(self, target: TargetUser) -> Optional[LiveBroadcast]:
        """개별 유저의 라이브 상태 확인"""
        try:
            # 유저의 라이브 정보 가져오기
            broadcast_info = self.client.user_info(target.user_id)
            
            # 라이브 중인지 확인
            if not hasattr(broadcast_info, 'is_live') or not broadcast_info.is_live:
                return None
            
            # 라이브 상세 정보 가져오기
            live_info = self._get_live_info(target.user_id)
            if not live_info:
                return None
            
            return LiveBroadcast(
                broadcast_id=str(live_info.get('id', '')),
                user_id=target.user_id,
                username=target.username,
                display_name=target.display_name,
                title=live_info.get('broadcast_message', ''),
                viewer_count=live_info.get('viewer_count', 0),
                started_at=datetime.fromtimestamp(
                    live_info.get('published_time', time.time())
                ),
                dash_playback_url=live_info.get('dash_playback_url', ''),
                dash_abr_playback_url=live_info.get('dash_abr_playback_url', ''),
                cover_frame_url=live_info.get('cover_frame_url', '')
            )
            
        except ClientError as e:
            # 404는 정상 (라이브 없음), 다른 에러는 warning
            if '404' not in str(e):
                logger.debug(f"라이브 체크 API 오류 ({target.username}): {e}")
            return None
        except Exception as e:
            logger.debug(f"라이브 체크 에러 ({target.username}): {e}")
            return None
    
    def _get_live_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """라이브 스트림 정보 가져오기"""
        try:
            # 직접 API 호출로 라이브 정보 가져오기
            result = self.client.private_request(
                f"live/{user_id}/info/",
                params={}
            )
            return result
        except ClientError as e:
            # 404는 라이브가 없는 것이므로 정상
            if '404' not in str(e):
                logger.warning(f"라이브 정보 조회 API 오류 (user_id={user_id}): {e}")
            return None
        except Exception as e:
            logger.warning(f"라이브 정보 조회 실패 (user_id={user_id}): {e}")
            return None
    
    def _handle_live_found(self, broadcast: LiveBroadcast):
        """라이브 발견 처리"""
        broadcast_id = broadcast.broadcast_id
        
        with self._lock:
            # 이미 알고 있는 라이브인지 확인
            if broadcast_id in self.state.active_lives:
                # 기존 라이브 정보 업데이트 (시청자 수 등)
                existing = self.state.active_lives[broadcast_id]
                existing.viewer_count = broadcast.viewer_count
                return
            
            # 새로운 라이브
            self.state.active_lives[broadcast_id] = broadcast
            self.state.total_lives_found += 1
        
        logger.info(
            f"🔴 라이브 감지: {broadcast.display_name} (@{broadcast.username})"
        )
        
        self._emit('on_live_start', broadcast)
    
    def _handle_ended_lives(self, current_broadcasts: List[LiveBroadcast]):
        """종료된 라이브 처리"""
        current_ids = {b.broadcast_id for b in current_broadcasts}
        ended_broadcasts = []
        
        with self._lock:
            for broadcast_id, broadcast in list(self.state.active_lives.items()):
                if broadcast_id not in current_ids:
                    ended_broadcasts.append(broadcast)
                    del self.state.active_lives[broadcast_id]
        
        # 락 밖에서 콜백 실행 (데드락 방지)
        for broadcast in ended_broadcasts:
            logger.info(
                f"⚫ 라이브 종료: {broadcast.display_name} (@{broadcast.username})"
            )
            self._emit('on_live_end', broadcast)
    
    def get_active_lives(self) -> List[LiveBroadcast]:
        """현재 활성 라이브 목록"""
        with self._lock:
            return list(self.state.active_lives.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """모니터링 통계"""
        with self._lock:
            return {
                'is_running': self.state.is_running,
                'last_check': self.state.last_check,
                'total_checks': self.state.total_checks,
                'total_lives_found': self.state.total_lives_found,
                'active_lives_count': len(self.state.active_lives),
                'targets_count': len(self.targets)
            }


class LiveMonitorV2(LiveMonitor):
    """
    개선된 라이브 모니터 - 팔로잉 피드 기반
    
    개별 유저 체크 대신 팔로잉 피드에서 라이브를 한 번에 확인
    API 호출 횟수를 크게 줄일 수 있음
    """
    
    def check_all_lives(self) -> List[LiveBroadcast]:
        """팔로잉 피드에서 라이브 확인"""
        with self._lock:
            self.state.total_checks += 1
            self.state.last_check = datetime.now()
        
        active_broadcasts = []
        target_usernames = {t.username.lower() for t in self.targets}
        
        try:
            # 방법 1: reels_tray에서 라이브 확인 (스토리 트레이)
            broadcasts = self._get_lives_from_reels_tray()
            
            for broadcast in broadcasts:
                username = broadcast.get('user', {}).get('username', '').lower()
                
                if username in target_usernames:
                    live = self._parse_broadcast(broadcast)
                    if live:
                        active_broadcasts.append(live)
                        self._handle_live_found(live)
            
        except ClientConnectionError as e:
            logger.warning(f"네트워크 오류로 라이브 피드 조회 실패: {e}")
            # 폴백: 기존 방식으로 체크
            return super().check_all_lives()
        except ClientError as e:
            logger.warning(f"API 오류로 라이브 피드 조회 실패: {e}")
            return super().check_all_lives()
        except Exception as e:
            logger.error(f"라이브 피드 조회 실패: {e}")
            # 폴백: 기존 방식으로 체크
            return super().check_all_lives()
        
        # 종료된 라이브 처리
        self._handle_ended_lives(active_broadcasts)
        
        return active_broadcasts
    
    def _get_lives_from_reels_tray(self) -> List[Dict]:
        """Reels tray에서 라이브 목록 가져오기"""
        try:
            result = self.client.private_request("feed/reels_tray/")
            broadcasts = result.get('broadcasts', [])
            return broadcasts
        except ClientError as e:
            if '404' not in str(e) and '400' not in str(e):
                logger.warning(f"Reels tray API 오류: {e}")
            return []
        except Exception as e:
            logger.debug(f"Reels tray 조회 실패: {e}")
            return []
    
    def _parse_broadcast(self, data: Dict) -> Optional[LiveBroadcast]:
        """API 응답을 LiveBroadcast로 변환"""
        try:
            user = data.get('user', {})
            username = user.get('username', '')
            
            if not username:
                return None
            
            # 타겟에서 display_name 찾기
            target = next(
                (t for t in self.targets if t.username.lower() == username.lower()),
                None
            )
            display_name = target.display_name if target else username
            
            return LiveBroadcast(
                broadcast_id=str(data.get('id', '')),
                user_id=user.get('pk', 0),
                username=username,
                display_name=display_name,
                title=data.get('broadcast_message', ''),
                viewer_count=data.get('viewer_count', 0),
                started_at=datetime.fromtimestamp(
                    data.get('published_time', time.time())
                ),
                dash_playback_url=data.get('dash_playback_url', ''),
                dash_abr_playback_url=data.get('dash_abr_playback_url', ''),
                cover_frame_url=data.get('cover_frame_url', '')
            )
        except Exception as e:
            logger.debug(f"브로드캐스트 파싱 실패: {e}")
            return None
