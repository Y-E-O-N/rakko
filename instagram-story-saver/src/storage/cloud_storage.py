"""
클라우드 저장소 관리 (Cloudflare R2 / S3 호환)
"""
import os
import threading
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, List, Callable
from datetime import datetime
from dataclasses import dataclass
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from src.utils.logger import get_logger
from src.downloader.story_downloader import DownloadTask

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


class CloudStorage:
    """Cloudflare R2 저장소"""
    
    def __init__(
        self,
        account_id: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        delete_after_upload: bool = False,
        public_url: str = "",
        multipart_threshold_mb: int = 50,
        multipart_chunksize_mb: int = 25,
        max_concurrency: int = 5,
        connect_timeout: int = 30,
        read_timeout: int = 60,
        max_retries: int = 5
    ):
        self.account_id = account_id
        self.bucket_name = bucket_name
        self.delete_after_upload = delete_after_upload
        self.public_url = public_url
        
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                signature_version='s3v4',
                retries={'max_attempts': max_retries, 'mode': 'adaptive'},
                connect_timeout=connect_timeout,
                read_timeout=read_timeout
            )
        )
        
        self.transfer_config = TransferConfig(
            multipart_threshold=multipart_threshold_mb * 1024 * 1024,
            multipart_chunksize=multipart_chunksize_mb * 1024 * 1024,
            max_concurrency=max_concurrency,
            use_threads=True
        )
        
        self._upload_callbacks: List[Callable] = []
        self._verify_bucket()
    
    def _verify_bucket(self):
        """버킷 확인"""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"R2 버킷 연결 성공: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                self._create_bucket()
            else:
                raise
    
    def _create_bucket(self):
        """버킷 생성"""
        try:
            self.client.create_bucket(Bucket=self.bucket_name)
            logger.info(f"R2 버킷 생성됨: {self.bucket_name}")
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') != 'BucketAlreadyOwnedByYou':
                raise
    
    def upload_file(
        self,
        local_path: Path,
        remote_path: Optional[str] = None,
        metadata: Optional[Dict] = None,
        content_type: Optional[str] = None
    ) -> bool:
        """파일 업로드"""
        local_path = Path(local_path)
        
        if not local_path.exists():
            logger.error(f"파일을 찾을 수 없음: {local_path}")
            return False
        
        if remote_path is None:
            remote_path = local_path.name
        
        file_size = local_path.stat().st_size
        
        try:
            extra_args = {}
            
            if metadata:
                extra_args['Metadata'] = {
                    k: str(v)[:500] for k, v in metadata.items()  # S3 메타데이터 값 제한
                }
            
            if content_type:
                extra_args['ContentType'] = content_type
            else:
                suffix = local_path.suffix.lower()
                content_types = {
                    '.mp4': 'video/mp4',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.webp': 'image/webp',
                }
                if suffix in content_types:
                    extra_args['ContentType'] = content_types[suffix]
            
            logger.info(f"☁️ R2 업로드 시작: {local_path.name} ({self._format_size(file_size)})")
            
            self.client.upload_file(
                str(local_path),
                self.bucket_name,
                remote_path,
                ExtraArgs=extra_args if extra_args else None,
                Config=self.transfer_config
            )
            
            logger.info(f"✅ R2 업로드 완료: {remote_path}")
            
            if self.delete_after_upload:
                local_path.unlink()
                logger.info(f"🗑️ 로컬 파일 삭제됨: {local_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"R2 업로드 실패: {e}")
            return False
    
    def upload_story(self, task: DownloadTask) -> bool:
        """스토리 파일 업로드"""
        if not task.output_path.exists():
            return False
        
        story = task.story
        
        # 원격 경로: username/YYYY-MM/filename
        month_folder = story.taken_at.strftime('%Y-%m')
        remote_path = f"{story.username}/{month_folder}/{task.output_path.name}"
        
        def safe_metadata(value: str, max_length: int = 200) -> str:
            if not value:
                return ""
            encoded = urllib.parse.quote(str(value)[:max_length], safe='')
            return encoded[:500]
        
        metadata = {
            'username': safe_metadata(story.username),
            'story_id': safe_metadata(story.story_id),
            'display_name': safe_metadata(story.display_name),
            'taken_at': story.taken_at.isoformat(),
            'media_type': 'video' if story.is_video else 'image'
        }
        
        return self.upload_file(task.output_path, remote_path, metadata)
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            return True
        except Exception as e:
            logger.error(f"R2 연결 테스트 실패: {e}")
            return False
    
    def _format_size(self, size_bytes: int) -> str:
        if size_bytes <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


def create_cloud_storage(config) -> Optional[CloudStorage]:
    """설정에서 CloudStorage 생성"""
    if not config.cloud_enabled:
        return None
    
    if config.cloud_provider != "r2":
        logger.warning(f"지원하지 않는 클라우드 제공자: {config.cloud_provider}")
        return None
    
    if not all([config.r2_account_id, config.r2_access_key, config.r2_secret_key]):
        logger.warning("R2 설정이 불완전합니다")
        return None
    
    try:
        storage = CloudStorage(
            account_id=config.r2_account_id,
            access_key=config.r2_access_key,
            secret_key=config.r2_secret_key,
            bucket_name=config.r2_bucket,
            delete_after_upload=config.delete_after_upload,
            public_url=config.r2_public_url,
            multipart_threshold_mb=config.cloud_multipart_threshold_mb,
            multipart_chunksize_mb=config.cloud_multipart_chunksize_mb,
            max_concurrency=config.cloud_max_concurrency,
            connect_timeout=config.cloud_connect_timeout,
            read_timeout=config.cloud_read_timeout,
            max_retries=config.cloud_max_retries
        )
        
        if not storage.test_connection():
            return None
        
        return storage
        
    except Exception as e:
        logger.error(f"CloudStorage 초기화 실패: {e}")
        return None
