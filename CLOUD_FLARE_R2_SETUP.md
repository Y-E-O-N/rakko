# Cloudflare R2 설정 가이드 ☁️

Instagram Live Recorder의 녹화 파일을 Cloudflare R2에 자동으로 백업하는 방법을 안내합니다.

## 왜 Cloudflare R2인가?

| 항목 | Cloudflare R2 | AWS S3 | Google Cloud Storage |
|------|--------------|--------|---------------------|
| **저장 비용** | $0.015/GB/월 | $0.023/GB/월 | $0.020/GB/월 |
| **다운로드 비용** | **무료!** | $0.09/GB | $0.12/GB |
| **연 200GB 예상 비용** | **~$3** | ~$22+ | ~$28+ |

R2의 가장 큰 장점은 **다운로드(egress) 비용이 무료**라는 점입니다. 녹화한 영상을 자주 다운로드하더라도 추가 비용이 없어요.

---

## 1단계: Cloudflare 계정 생성

1. [Cloudflare 회원가입](https://dash.cloudflare.com/sign-up) 페이지 접속
2. 이메일과 비밀번호 입력
3. 이메일 인증 완료

> 💡 R2는 무료 플랜에서도 사용 가능합니다.

---

## 2단계: R2 활성화 및 버킷 생성

### 2.1 R2 활성화

1. [Cloudflare Dashboard](https://dash.cloudflare.com) 로그인
2. 왼쪽 메뉴에서 **R2 Object Storage** 클릭
3. 처음이라면 "Get started" 또는 "구독하기" 클릭
4. **결제 정보 입력** (필수, 하지만 무료 티어 내에서는 과금되지 않음)

### 2.2 버킷 생성

1. R2 페이지에서 **"버킷 만들기"** 클릭
2. 버킷 설정:
   - **버킷 이름**: `instagram-lives` (원하는 이름으로 변경 가능)
   - **위치**: `Automatic` (자동) 또는 가까운 지역 선택
3. **"버킷 만들기"** 클릭

![R2 버킷 생성](https://developers.cloudflare.com/assets/r2-bucket-creation_hu2a6b6f5d7a3c6f4f2a6b6f5d7a3c6f4f_12345_1200x0_resize_q75_box.jpg)

---

## 3단계: API 토큰 생성

### 3.1 Account ID 확인

1. R2 페이지 오른쪽 상단에서 **Account ID** 복사
   - 또는 URL에서 확인: `https://dash.cloudflare.com/[ACCOUNT_ID]/r2/overview`

```
예시: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

### 3.2 API 토큰 생성

1. R2 페이지에서 **"R2 API 토큰 관리"** 클릭 (오른쪽 사이드바)
2. **"API 토큰 만들기"** 클릭
3. 토큰 설정:
   - **토큰 이름**: `instagram-recorder` (식별용)
   - **권한**: 
     - ✅ **객체 읽기 및 쓰기** (Object Read & Write)
   - **TTL**: 선택사항 (만료 기간)
   - **버킷 선택**: 
     - `instagram-lives` (특정 버킷만 허용) 또는
     - `모든 버킷에 적용` (향후 버킷 추가 시 편리)

4. **"API 토큰 만들기"** 클릭

5. 생성된 정보 **반드시 저장**:
   ```
   Access Key ID: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   Secret Access Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   ⚠️ **Secret Access Key는 이 화면에서만 확인 가능합니다!** 분실 시 새로 생성해야 합니다.

---

## 4단계: 프로그램 설정

`config/settings.yaml` 파일을 열고 다음 섹션을 수정합니다:

```yaml
# 클라우드 저장소 설정 (Cloudflare R2)
cloud_storage:
  # R2 사용 여부
  enabled: true
  
  # 제공자 (현재 r2만 지원)
  provider: "r2"
  
  # Cloudflare R2 설정
  r2:
    # Cloudflare Account ID (대시보드에서 확인)
    account_id: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    
    # API 토큰 - Access Key ID
    access_key_id: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    
    # API 토큰 - Secret Access Key
    secret_access_key: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    
    # 버킷 이름
    bucket_name: "instagram-lives"
    
    # 업로드 후 로컬 파일 삭제 여부
    # true: R2 업로드 성공 후 로컬 파일 삭제 (디스크 공간 절약)
    # false: 로컬에도 파일 유지 (기본값)
    delete_after_upload: false
```

---

## 5단계: 연결 테스트

설정 완료 후 연결 테스트:

```bash
python -c "
from src.utils.config import load_config
from src.storage.cloud_storage import create_cloud_storage

config = load_config('config/settings.yaml')
storage = create_cloud_storage(config)

if storage:
    print('✅ R2 연결 성공!')
    
    # 사용량 확인
    usage = storage.get_storage_usage()
    print(f'파일 수: {usage[\"file_count\"]}')
    print(f'사용량: {usage[\"total_size_formatted\"]}')
    print(f'예상 월 비용: {usage[\"estimated_monthly_cost\"]}')
else:
    print('❌ R2 연결 실패')
"
```

---

## 파일 구조

R2에 저장되는 파일 구조:

```
instagram-lives/                    # 버킷
├── username1/                      # 유저별 폴더
│   ├── 2024-01/                   # 월별 폴더
│   │   ├── username1_20240115_143022.mp4
│   │   └── username1_20240120_201530.mp4
│   └── 2024-02/
│       └── username1_20240205_183045.mp4
├── username2/
│   └── 2024-01/
│       └── username2_20240118_220100.mp4
└── ...
```

---

## 저장된 파일 확인하기

### 방법 1: Cloudflare Dashboard

1. [R2 Dashboard](https://dash.cloudflare.com) 접속
2. R2 → 버킷 선택 → 파일 목록 확인

### 방법 2: 프로그램에서 조회

```python
# 전체 파일 목록
files = storage.list_files()
for f in files:
    print(f"{f['key']} - {f['size_formatted']}")

# 특정 유저의 녹화만 조회
recordings = storage.list_recordings(username="target_user")

# 저장소 사용량
usage = storage.get_storage_usage()
print(f"총 {usage['file_count']}개 파일, {usage['total_size_formatted']}")
print(f"유저별 통계: {usage['user_stats']}")
```

### 방법 3: 다운로드 URL 생성

```python
# 1시간 유효한 다운로드 링크 생성
url = storage.get_download_url(
    "username/2024-01/username_20240115_143022.mp4",
    expires_in=3600
)
print(f"다운로드 링크: {url}")
```

---

## 고급 설정

### 퍼블릭 액세스 설정 (선택사항)

영상을 공개 URL로 접근하고 싶다면:

1. R2 버킷 설정 → **설정** 탭
2. **R2.dev 하위 도메인** 활성화
3. 생성된 URL을 settings.yaml에 추가:

```yaml
r2:
  # ... 기존 설정 ...
  public_url: "https://pub-xxxxx.r2.dev"
```

⚠️ **주의**: 퍼블릭 설정 시 누구나 URL을 알면 영상에 접근할 수 있습니다.

### 수명 주기 규칙 (자동 삭제)

오래된 파일을 자동 삭제하려면:

1. R2 버킷 → **설정** → **수명 주기 규칙**
2. 규칙 추가:
   - 조건: 객체 수명 > 365일
   - 작업: 객체 삭제

---

## 비용 계산

### R2 가격 정책 (2024년 기준)

| 항목 | 무료 티어 | 유료 |
|------|----------|------|
| 저장 | 10GB/월 | $0.015/GB/월 |
| Class A 작업 (쓰기) | 100만/월 | $4.50/백만 |
| Class B 작업 (읽기) | 1000만/월 | $0.36/백만 |
| 다운로드 | **무제한 무료** | **무료** |

### 예상 비용 (월 10회 녹화, 평균 1GB/회)

```
저장: 10GB × $0.015 = $0.15/월
쓰기: ~10회 (무료 티어 내)
읽기: ~10회 (무료 티어 내)
다운로드: 무료

총: 약 $0.15/월 ≈ $1.8/년
```

### 연 200GB 저장 시

```
저장: 200GB × $0.015 = $3/월
연간: 약 $36/년

하지만! 무료 티어 10GB 적용 시:
(200 - 10) × $0.015 = $2.85/월 ≈ $34/년
```

> 💡 오래된 파일을 주기적으로 삭제하면 비용을 더 줄일 수 있습니다.

---

## 문제 해결

### "Access Denied" 오류

- API 토큰 권한 확인: "객체 읽기 및 쓰기" 권한 필요
- 토큰이 특정 버킷에만 제한되어 있는지 확인

### "Bucket not found" 오류

- 버킷 이름 철자 확인
- Account ID가 정확한지 확인

### 업로드가 느림

- 대용량 파일은 멀티파트 업로드가 자동 적용됨
- 인터넷 연결 상태 확인

### 연결 타임아웃

- 방화벽 설정 확인
- 프록시 설정이 있다면 `settings.yaml`에 추가

---

## 참고 링크

- [Cloudflare R2 문서](https://developers.cloudflare.com/r2/)
- [R2 가격 정책](https://developers.cloudflare.com/r2/pricing/)
- [R2 API 참조](https://developers.cloudflare.com/r2/api/s3/)