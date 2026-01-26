"""
Instagram 인증 및 세션 관리

보안 주의사항:
- 세션 파일(session.json)에는 인증 토큰이 포함됨
- 세션 파일 권한을 600으로 제한할 것
- 세션 파일을 Git에 커밋하지 말 것 (.gitignore에 포함)
"""
import json
import time
import os
import stat
from pathlib import Path
from typing import Optional
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    BadPassword,
    PleaseWaitFewMinutes,
    ClientError,
    ClientConnectionError
)
from src.utils.logger import get_logger

logger = get_logger()

# pyotp 사전 검증
PYOTP_AVAILABLE = False
try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    pass


class AuthenticationError(Exception):
    """인증 관련 오류"""
    pass


class InstagramAuth:
    """Instagram 인증 관리"""
    
    def __init__(
        self,
        username: str,
        password: str,
        session_file: str = "data/sessions/session.json",
        totp_secret: str = "",
        proxy: str = ""
    ):
        self.username = username
        self.password = password
        self.session_file = Path(session_file)
        self.totp_secret = totp_secret
        self.proxy = proxy
        
        # TOTP 사용 시 pyotp 필요
        if self.totp_secret and not PYOTP_AVAILABLE:
            raise AuthenticationError(
                "2FA(TOTP) 사용을 위해 pyotp가 필요합니다: pip install pyotp"
            )
        
        self.client = Client()
        self._setup_client()
    
    def _setup_client(self):
        """클라이언트 초기 설정"""
        # 프록시 설정
        if self.proxy:
            try:
                self.client.set_proxy(self.proxy)
                logger.debug(f"프록시 설정됨: {self._mask_proxy(self.proxy)}")
            except Exception as e:
                logger.warning(f"프록시 설정 실패: {e}")
        
        # 요청 딜레이 설정 (API 제한 회피)
        self.client.delay_range = [1, 3]
        
        # User-Agent 설정 (모바일 앱처럼 보이게)
        self.client.set_user_agent(
            "Instagram 275.0.0.27.98 Android "
            "(33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)"
        )
    
    def _mask_proxy(self, proxy: str) -> str:
        """프록시 URL에서 인증 정보 마스킹"""
        if '@' in proxy:
            # user:pass@host:port 형식
            parts = proxy.split('@')
            return f"***@{parts[-1]}"
        return proxy
    
    def login(self) -> bool:
        """
        로그인 수행
        
        Returns:
            로그인 성공 여부
        """
        # 세션 파일이 있으면 먼저 시도
        if self.session_file.exists():
            if self._load_session():
                logger.info(f"세션 파일로 로그인 성공: {self.username}")
                return True
        
        # 새로 로그인
        return self._fresh_login()
    
    def _load_session(self) -> bool:
        """저장된 세션으로 로그인 시도"""
        try:
            logger.info("저장된 세션으로 로그인 시도 중...")
            
            # 세션 파일 권한 확인 (Unix 계열)
            self._check_session_file_permissions()
            
            self.client.load_settings(self.session_file)
            self.client.login(self.username, self.password)
            
            # 세션 유효성 확인
            self.client.get_timeline_feed()
            return True
            
        except LoginRequired:
            logger.warning("세션이 만료됨, 새로 로그인 필요")
            self._remove_session_file()
            return False
            
        except (ClientConnectionError, ConnectionError) as e:
            logger.warning(f"네트워크 연결 오류: {e}")
            return False
            
        except Exception as e:
            logger.warning(f"세션 로드 실패: {e}")
            return False
    
    def _fresh_login(self) -> bool:
        """새로 로그인"""
        try:
            logger.info(f"새로 로그인 중: {self.username}")
            
            # TOTP 2FA 설정
            if self.totp_secret:
                self.client.totp_code = lambda: self._generate_totp()
            
            self.client.login(self.username, self.password)
            
            # 세션 저장
            self._save_session()
            
            logger.info("로그인 성공!")
            return True
            
        except TwoFactorRequired:
            logger.error(
                "2단계 인증이 필요합니다. "
                "설정 파일에 totp_secret을 추가하세요."
            )
            return False
            
        except ChallengeRequired:
            logger.error(
                "Instagram 보안 확인이 필요합니다. "
                "웹/앱에서 직접 로그인하여 확인 후 다시 시도하세요."
            )
            return False
            
        except BadPassword:
            logger.error("비밀번호가 틀립니다.")
            return False
            
        except PleaseWaitFewMinutes as e:
            logger.error(f"너무 많은 요청, 잠시 후 다시 시도하세요: {e}")
            return False
            
        except (ClientConnectionError, ConnectionError) as e:
            logger.error(f"네트워크 연결 오류: {e}")
            return False
            
        except ClientError as e:
            logger.error(f"Instagram API 오류: {e}")
            return False
            
        except Exception as e:
            # 예상치 못한 오류는 스택 트레이스 포함
            logger.exception(f"로그인 중 예상치 못한 오류: {e}")
            return False
    
    def _generate_totp(self) -> str:
        """TOTP 코드 생성"""
        if not PYOTP_AVAILABLE:
            raise AuthenticationError("pyotp 패키지가 설치되지 않았습니다")
        
        totp = pyotp.TOTP(self.totp_secret)
        code = totp.now()
        logger.debug("TOTP 코드 생성됨")
        return code
    
    def _save_session(self):
        """세션 저장 (보안 권한 설정 포함)"""
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.client.dump_settings(self.session_file)
        
        # Unix 계열에서 파일 권한을 600으로 설정 (소유자만 읽기/쓰기)
        try:
            os.chmod(self.session_file, stat.S_IRUSR | stat.S_IWUSR)
            logger.debug(f"세션 파일 권한 설정됨: 600")
        except (OSError, AttributeError):
            # Windows에서는 무시
            pass
        
        logger.info(f"세션 저장됨: {self.session_file}")
    
    def _remove_session_file(self):
        """세션 파일 안전하게 삭제"""
        try:
            if self.session_file.exists():
                # 파일 내용을 덮어쓴 후 삭제 (보안)
                with open(self.session_file, 'w') as f:
                    f.write('{}')
                self.session_file.unlink()
                logger.debug("세션 파일 삭제됨")
        except Exception as e:
            logger.warning(f"세션 파일 삭제 실패: {e}")
    
    def _check_session_file_permissions(self):
        """세션 파일 권한 확인 (Unix 계열)"""
        try:
            mode = self.session_file.stat().st_mode
            # 그룹/기타 사용자에게 권한이 있으면 경고
            if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
                logger.warning(
                    f"세션 파일 권한이 너무 개방적입니다: {oct(mode)[-3:]}\n"
                    f"보안을 위해 'chmod 600 {self.session_file}'를 실행하세요."
                )
        except (OSError, AttributeError):
            # Windows에서는 무시
            pass
    
    def get_client(self) -> Client:
        """인증된 클라이언트 반환"""
        return self.client
    
    def relogin(self) -> bool:
        """재로그인 (세션 만료 시)"""
        logger.info("재로그인 시도 중...")
        self._remove_session_file()
        return self._fresh_login()
    
    def is_logged_in(self) -> bool:
        """로그인 상태 확인"""
        try:
            self.client.get_timeline_feed()
            return True
        except LoginRequired:
            logger.debug("로그인 필요")
            return False
        except (ClientConnectionError, ConnectionError) as e:
            logger.debug(f"연결 오류로 로그인 상태 확인 불가: {e}")
            return False
        except ClientError as e:
            logger.debug(f"API 오류로 로그인 상태 확인 불가: {e}")
            return False
        except Exception as e:
            logger.warning(f"로그인 상태 확인 중 오류: {e}")
            return False


class SessionManager:
    """세션 상태 관리 및 자동 복구"""
    
    def __init__(self, auth: InstagramAuth):
        self.auth = auth
        self.consecutive_failures = 0
        self.max_failures = 3
        self.last_success = time.time()
        self.cooldown_until = 0  # 쿨다운 종료 시간
    
    def ensure_logged_in(self) -> bool:
        """로그인 상태 보장"""
        # 쿨다운 중인지 확인
        if time.time() < self.cooldown_until:
            remaining = int(self.cooldown_until - time.time())
            logger.debug(f"쿨다운 중: {remaining}초 남음")
            return False
        
        if self.auth.is_logged_in():
            self.consecutive_failures = 0
            self.last_success = time.time()
            return True
        
        self.consecutive_failures += 1
        
        if self.consecutive_failures >= self.max_failures:
            cooldown_seconds = 60 * 5  # 5분
            self.cooldown_until = time.time() + cooldown_seconds
            logger.error(
                f"연속 {self.max_failures}회 로그인 실패, "
                f"{cooldown_seconds // 60}분 후 다시 시도합니다."
            )
            self.consecutive_failures = 0
            return False
        
        return self.auth.relogin()
    
    def handle_api_error(self, error: Exception) -> bool:
        """
        API 에러 처리
        
        Returns:
            재시도 가능 여부
        """
        error_str = str(error).lower()
        
        if isinstance(error, LoginRequired) or "login_required" in error_str:
            logger.warning("세션 만료, 재로그인 시도")
            return self.auth.relogin()
        
        if isinstance(error, PleaseWaitFewMinutes) or "please wait" in error_str or "rate limit" in error_str:
            cooldown_seconds = 60 * 5
            self.cooldown_until = time.time() + cooldown_seconds
            logger.warning(f"API 제한, {cooldown_seconds // 60}분 대기")
            return False  # 즉시 재시도하지 않음
        
        if isinstance(error, ChallengeRequired) or "challenge" in error_str:
            logger.error("보안 확인 필요, 수동 조치 필요")
            return False
        
        if isinstance(error, (ClientConnectionError, ConnectionError)):
            logger.warning(f"네트워크 오류: {error}")
            time.sleep(10)  # 짧은 대기 후 재시도 가능
            return True
        
        logger.error(f"알 수 없는 API 에러: {error}")
        return False
