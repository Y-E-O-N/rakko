"""
클라우드 저장소 관리 (Cloudflare R2 / S3 호환)

Cloudflare R2는 S3 호환 API를 제공하므로 boto3를 사용합니다.
- 저장 비용: $0.015/GB/월
- 다운로드(egress) 비용: 무료!
- 연 200GB 사용 시 약 $3/년
"""
import os
import threading
from pathlib import Path
from typing import Optional, Dict, List, Callable
from datetime import datetime
from dataclasses import dataclass
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from src.utils.logger import get_logger
from src.recorder.stream_recorder import RecordingTask

logger = get_logger()


@dataclass
class UploadProgress:
    """업로드 진행 상황"""
    filename: str
    total_bytes: int
    uploaded_bytes: int = 0
    
    @property
    def percentage(self) -> float:
        if self.total_bytes == 0:
            return 0
        return (self.uploaded_bytes / self.total_bytes) * 100


class ProgressCallback:
    """업로드 진행률 콜백"""
    
    def __init__(self, filename: str, total_size: int, callback: Optional[Callable] = None):
        self.filename = filename
        self.total_size = total_size
        self.uploaded = 0
        self.callback = callback
        self._lock = threading.Lock()
    
    def __call__(self, bytes_transferred: int):
        with self._lock:
            self.uploaded += bytes_transferred
            percentage = (self.uploaded / self.total_size) * 100 if self.total_size > 0 else 0
            
            if self.callback:
                self.callback(UploadProgress(
                    filename=self.filename,
                    total_bytes=self.total_size,
                    uploaded_bytes=self.uploaded
                ))
            
            # 10% 단위로 로그 출력
            if percentage % 10 < (bytes_transferred / self.total_size * 100):
                logger.debug(f"업로드 진행: {self.filename} - {percentage:.1f}%")


class CloudStorage:
    """
    Cloudflare R2 저장소 (S3 호환)
    
    R2 특징:
    - S3 호환 API
    - 저장: $0.015/GB/월
    - 다운로드(egress): 무료
    - Class A 작업 (PUT, POST, LIST): $4.50/백만 요청
    - Class B 작업 (GET): $0.36/백만 요청
    """
    
    def __init__(
        self,
        account_id: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        delete_after_upload: bool = False,
        public_url: str = ""
    ):
        self.account_id = account_id
        self.bucket_name = bucket_name
        self.delete_after_upload = delete_after_upload
        self.public_url = public_url  # 커스텀 도메인 또는 R2.dev URL
        
        # R2 엔드포인트
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        
        # S3 클라이언트 생성
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                signature_version='s3v4',
                retries={
                    'max_attempts': 5,
                    'mode': 'adaptive'
                },
                connect_timeout=30,
                read_timeout=60
            )
        )
        
        # 멀티파트 업로드 설정 (대용량 파일용)
        # - 100MB 이상 파일은 멀티파트 업로드
        # - 각 파트 크기: 50MB
        # - 최대 동시 전송: 5개
        self.transfer_config = TransferConfig(
            multipart_threshold=100 * 1024 * 1024,  # 100MB
            multipart_chunksize=50 * 1024 * 1024,   # 50MB
            max_concurrency=5,
            use_threads=True
        )
        
        # 업로드 콜백
        self._upload_callbacks: List[Callable] = []
        
        self._verify_bucket()
    
    def _verify_bucket(self):
        """버킷 존재 확인"""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"R2 버킷 연결 성공: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                logger.warning(f"버킷이 존재하지 않습니다. 생성을 시도합니다: {self.bucket_name}")
                self._create_bucket()
            elif error_code == '403':
                logger.error("버킷 접근 권한이 없습니다. API 토큰 권한을 확인하세요.")
                raise
            else:
                logger.error(f"버킷 확인 실패: {e}")
                raise
    
    def _create_bucket(self):
        """버킷 생성"""
        try:
            self.client.create_bucket(Bucket=self.bucket_name)
            logger.info(f"R2 버킷 생성됨: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'BucketAlreadyOwnedByYou':
                logger.info(f"버킷이 이미 존재합니다: {self.bucket_name}")
            else:
                logger.error(f"버킷 생성 실패: {e}")
                raise
    
    def on_upload_progress(self, callback: Callable):
        """업로드 진행률 콜백 등록"""
        self._upload_callbacks.append(callback)
    
    def upload_file(
        self,
        local_path: Path,
        remote_path: Optional[str] = None,
        metadata: Optional[Dict] = None,
        content_type: Optional[str] = None
    ) -> bool:
        """
        파일 업로드
        
        Args:
            local_path: 로컬 파일 경로
            remote_path: 원격 경로 (None이면 파일명 사용)
            metadata: 추가 메타데이터
            content_type: MIME 타입 (None이면 자동 감지)
        
        Returns:
            성공 여부
        """
        local_path = Path(local_path)
        
        if not local_path.exists():
            logger.error(f"파일을 찾을 수 없음: {local_path}")
            return False
        
        if remote_path is None:
            remote_path = local_path.name
        
        # 파일 크기
        file_size = local_path.stat().st_size
        
        try:
            extra_args = {}
            
            # 메타데이터 추가
            if metadata:
                extra_args['Metadata'] = {
                    k: str(v)[:1024] for k, v in metadata.items()  # R2 메타데이터 크기 제한
                }
            
            # Content-Type 설정
            if content_type:
                extra_args['ContentType'] = content_type
            else:
                suffix = local_path.suffix.lower()
                content_types = {
                    '.mp4': 'video/mp4',
                    '.mkv': 'video/x-matroska',
                    '.webm': 'video/webm',
                    '.ts': 'video/mp2t',
                    '.m4a': 'audio/mp4',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png'
                }
                if suffix in content_types:
                    extra_args['ContentType'] = content_types[suffix]
            
            # 업로드 시작
            logger.info(
                f"☁️ R2 업로드 시작: {local_path.name} "
                f"({self._format_size(file_size)}) -> {remote_path}"
            )
            
            # 진행률 콜백 설정
            progress_callback = None
            if self._upload_callbacks:
                def combined_callback(progress: UploadProgress):
                    for cb in self._upload_callbacks:
                        cb(progress)
                progress_callback = ProgressCallback(
                    local_path.name, 
                    file_size, 
                    combined_callback
                )
            
            # 업로드 (멀티파트 자동 처리)
            self.client.upload_file(
                str(local_path),
                self.bucket_name,
                remote_path,
                ExtraArgs=extra_args if extra_args else None,
                Config=self.transfer_config,
                Callback=progress_callback
            )
            
            logger.info(f"✅ R2 업로드 완료: {remote_path}")
            
            # 로컬 파일 삭제 옵션
            if self.delete_after_upload:
                local_path.unlink()
                logger.info(f"🗑️ 로컬 파일 삭제됨: {local_path}")
            
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code == 'EntityTooLarge':
                logger.error(f"파일이 너무 큽니다 (R2 최대: 5TB): {local_path}")
            elif error_code == 'AccessDenied':
                logger.error("업로드 권한이 없습니다. API 토큰을 확인하세요.")
            else:
                logger.error(f"R2 업로드 실패: {error_code} - {error_msg}")
            return False
            
        except Exception as e:
            logger.error(f"R2 업로드 실패: {e}")
            return False
    
    def upload_recording(self, task: RecordingTask) -> bool:
        """녹화 파일 업로드"""
        if not task.output_path.exists():
            logger.warning(f"녹화 파일이 존재하지 않음: {task.output_path}")
            return False
        
        # 원격 경로: username/YYYY-MM/filename
        # 월별로 폴더 정리
        month_folder = task.started_at.strftime('%Y-%m') if task.started_at else 'unknown'
        remote_path = f"{task.broadcast.username}/{month_folder}/{task.output_path.name}"
        
        # 메타데이터 (S3 호환 - ASCII 안전하게 인코딩)
        # R2/S3 메타데이터는 ASCII만 허용하므로 URL 인코딩 사용
        import urllib.parse
        
        def safe_metadata(value: str, max_length: int = 200) -> str:
            """메타데이터 값을 안전하게 변환"""
            if not value:
                return ""
            # ASCII가 아닌 문자를 URL 인코딩
            encoded = urllib.parse.quote(str(value)[:max_length], safe='')
            # 최대 길이 제한 (인코딩 후)
            return encoded[:500]
        
        metadata = {
            'username': safe_metadata(task.broadcast.username),
            'broadcast_id': safe_metadata(task.broadcast.broadcast_id),
            'display_name': safe_metadata(task.broadcast.display_name),
            'recorded_at': task.started_at.isoformat() if task.started_at else '',
            'ended_at': task.ended_at.isoformat() if task.ended_at else '',
            'duration_seconds': str(
                int((task.ended_at - task.started_at).total_seconds())
                if task.started_at and task.ended_at else 0
            ),
            'title': safe_metadata(task.broadcast.title),
            'viewer_count': str(task.broadcast.viewer_count)
        }
        
        return self.upload_file(task.output_path, remote_path, metadata)
    
    def download_file(
        self,
        remote_path: str,
        local_path: Path
    ) -> bool:
        """
        파일 다운로드
        
        Args:
            remote_path: R2 경로
            local_path: 저장할 로컬 경로
        
        Returns:
            성공 여부
        """
        try:
            local_path = Path(local_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"R2 다운로드: {remote_path} -> {local_path}")
            
            self.client.download_file(
                self.bucket_name,
                remote_path,
                str(local_path),
                Config=self.transfer_config
            )
            
            logger.info(f"다운로드 완료: {local_path}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404' or error_code == 'NoSuchKey':
                logger.error(f"파일을 찾을 수 없음: {remote_path}")
            else:
                logger.error(f"다운로드 실패: {e}")
            return False
    
    def list_files(
        self,
        prefix: str = "",
        max_keys: int = 1000
    ) -> List[Dict]:
        """파일 목록 조회"""
        try:
            files = []
            continuation_token = None
            
            while True:
                params = {
                    'Bucket': self.bucket_name,
                    'Prefix': prefix,
                    'MaxKeys': min(max_keys - len(files), 1000)
                }
                
                if continuation_token:
                    params['ContinuationToken'] = continuation_token
                
                response = self.client.list_objects_v2(**params)
                
                for obj in response.get('Contents', []):
                    files.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'size_formatted': self._format_size(obj['Size']),
                        'last_modified': obj['LastModified'],
                        'etag': obj.get('ETag', '').strip('"')
                    })
                
                # 페이지네이션
                if response.get('IsTruncated') and len(files) < max_keys:
                    continuation_token = response.get('NextContinuationToken')
                else:
                    break
            
            return files
            
        except ClientError as e:
            logger.error(f"파일 목록 조회 실패: {e}")
            return []
    
    def list_recordings(self, username: str = "") -> List[Dict]:
        """
        녹화 파일 목록 조회
        
        Args:
            username: 특정 유저의 녹화만 조회 (빈 문자열이면 전체)
        
        Returns:
            녹화 파일 정보 리스트
        """
        prefix = f"{username}/" if username else ""
        files = self.list_files(prefix=prefix)
        
        # 비디오 파일만 필터링
        video_extensions = ('.mp4', '.mkv', '.webm', '.ts')
        return [f for f in files if f['key'].lower().endswith(video_extensions)]
    
    def get_file_info(self, remote_path: str) -> Optional[Dict]:
        """파일 정보 및 메타데이터 조회"""
        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            
            return {
                'key': remote_path,
                'size': response['ContentLength'],
                'size_formatted': self._format_size(response['ContentLength']),
                'content_type': response.get('ContentType', ''),
                'last_modified': response.get('LastModified'),
                'metadata': response.get('Metadata', {}),
                'etag': response.get('ETag', '').strip('"')
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                return None
            logger.error(f"파일 정보 조회 실패: {e}")
            return None
    
    def get_download_url(self, remote_path: str, expires_in: int = 3600) -> str:
        """
        다운로드 URL 생성 (Presigned URL)
        
        Args:
            remote_path: R2 경로
            expires_in: URL 유효 시간 (초, 기본 1시간, 최대 7일)
        
        Returns:
            Presigned URL
        """
        try:
            # R2는 최대 7일까지 지원
            expires_in = min(expires_in, 7 * 24 * 3600)
            
            url = self.client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': remote_path
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"URL 생성 실패: {e}")
            return ""
    
    def get_public_url(self, remote_path: str) -> str:
        """
        공개 URL 반환 (퍼블릭 버킷 또는 커스텀 도메인 설정 시)
        
        Args:
            remote_path: R2 경로
        
        Returns:
            공개 URL
        """
        if self.public_url:
            return f"{self.public_url.rstrip('/')}/{remote_path}"
        return ""
    
    def delete_file(self, remote_path: str) -> bool:
        """파일 삭제"""
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            logger.info(f"R2 파일 삭제됨: {remote_path}")
            return True
        except ClientError as e:
            logger.error(f"파일 삭제 실패: {e}")
            return False
    
    def delete_files(self, remote_paths: List[str]) -> int:
        """
        여러 파일 일괄 삭제
        
        Args:
            remote_paths: 삭제할 파일 경로 리스트
        
        Returns:
            삭제된 파일 수
        """
        if not remote_paths:
            return 0
        
        try:
            # R2는 한 번에 최대 1000개 삭제 가능
            deleted_count = 0
            
            for i in range(0, len(remote_paths), 1000):
                batch = remote_paths[i:i + 1000]
                
                response = self.client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={
                        'Objects': [{'Key': key} for key in batch],
                        'Quiet': True
                    }
                )
                
                errors = response.get('Errors', [])
                deleted_count += len(batch) - len(errors)
                
                for error in errors:
                    logger.warning(f"삭제 실패: {error['Key']} - {error['Message']}")
            
            logger.info(f"R2 파일 {deleted_count}개 삭제됨")
            return deleted_count
            
        except ClientError as e:
            logger.error(f"일괄 삭제 실패: {e}")
            return 0
    
    def get_storage_usage(self) -> Dict:
        """저장소 사용량 조회"""
        try:
            files = self.list_files(max_keys=10000)
            total_size = sum(f['size'] for f in files)
            
            # 유저별 통계
            user_stats = {}
            for f in files:
                parts = f['key'].split('/')
                if len(parts) > 0:
                    username = parts[0]
                    if username not in user_stats:
                        user_stats[username] = {'count': 0, 'size': 0}
                    user_stats[username]['count'] += 1
                    user_stats[username]['size'] += f['size']
            
            # 월별 비용 추정 ($0.015/GB)
            monthly_cost = (total_size / (1024 ** 3)) * 0.015
            
            return {
                'file_count': len(files),
                'total_size_bytes': total_size,
                'total_size_formatted': self._format_size(total_size),
                'estimated_monthly_cost': f"${monthly_cost:.2f}",
                'user_stats': {
                    k: {
                        'count': v['count'],
                        'size_formatted': self._format_size(v['size'])
                    }
                    for k, v in user_stats.items()
                }
            }
        except Exception as e:
            logger.error(f"사용량 조회 실패: {e}")
            return {
                'file_count': 0,
                'total_size_bytes': 0,
                'total_size_formatted': '0 B',
                'estimated_monthly_cost': '$0.00',
                'user_stats': {}
            }
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.info("R2 연결 테스트 성공")
            return True
        except Exception as e:
            logger.error(f"R2 연결 테스트 실패: {e}")
            return False
    
    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형식으로 변환"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


def create_cloud_storage(config) -> Optional[CloudStorage]:
    """설정에서 CloudStorage 생성"""
    if not config.cloud_enabled:
        logger.info("클라우드 저장소가 비활성화되어 있습니다")
        return None
    
    if config.cloud_provider != "r2":
        logger.warning(f"지원하지 않는 클라우드 제공자: {config.cloud_provider}")
        return None
    
    if not all([config.r2_account_id, config.r2_access_key, config.r2_secret_key]):
        logger.warning(
            "R2 설정이 불완전합니다. 필요한 설정:\n"
            "  - r2.account_id\n"
            "  - r2.access_key_id\n"
            "  - r2.secret_access_key\n"
            "클라우드 저장소가 비활성화됩니다."
        )
        return None
    
    try:
        storage = CloudStorage(
            account_id=config.r2_account_id,
            access_key=config.r2_access_key,
            secret_key=config.r2_secret_key,
            bucket_name=config.r2_bucket,
            delete_after_upload=config.delete_after_upload,
            public_url=getattr(config, 'r2_public_url', '')
        )
        
        # 연결 테스트
        if not storage.test_connection():
            logger.warning("R2 연결 실패. 설정을 확인하세요.")
            return None
        
        return storage
        
    except Exception as e:
        logger.error(f"CloudStorage 초기화 실패: {e}")
        return None
