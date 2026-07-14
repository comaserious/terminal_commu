# Commu

FMKorea, 디시인사이드, 아카라이브의 공개 게시글을 터미널에서 읽는 애플리케이션입니다. 목록, 본문, 댓글을 키보드로 탐색할 수 있습니다.

Commu는 읽기 전용입니다. 로그인, 글쓰기, 추천, 구독을 지원하지 않으며 CAPTCHA나 JavaScript/WASM 보안 검증을 우회하지 않습니다.

## 주요 기능

- FMKorea 해외축구 게시판 지원
- 디시인사이드 일반·마이너·미니 갤러리 지원
- 아카라이브 공개 채널 지원
- 게시글 목록, 본문, 댓글과 답글 표시
- 시작 메뉴의 추천 URL 또는 직접 URL 입력
- 직접 입력한 URL의 최근 기록
- `commu <URL>`을 통한 게시판·게시글 바로 열기
- 사이트와 게시판이 분리된 로컬 캐시
- 이미지·동영상을 다운로드하지 않는 텍스트 전용 화면

## 요구사항

- Python 3.12 이상
- Textual 화면을 표시할 수 있는 터미널
- 선택한 커뮤니티에 접속할 수 있는 네트워크 환경

Conda는 필수가 아닙니다. 아래 설치 방법은 Python 기본 기능인 `venv`를 사용합니다.

## 설치

GitHub 저장소 상단의 **Code** 버튼에서 HTTPS 주소를 복사해 `git clone`으로 내려받거나, **Download ZIP**을 선택해 압축을 풉니다. 이후 터미널에서 저장소 폴더로 이동합니다.

### macOS / Linux

```bash
cd terminal_community
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

### Windows PowerShell

```powershell
cd terminal_community
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu
```

새 터미널을 열면 가상환경을 다시 활성화해야 합니다.

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

### Docker

[Docker Desktop](https://www.docker.com/products/docker-desktop/) 또는 Docker Compose v2를 지원하는 호환 Docker Engine이 필요합니다. Docker Desktop에서도 저장소 폴더가 파일 공유 대상이어야 합니다. 저장소 루트에서 다음 명령을 실행하세요.

```bash
# 첫 실행 또는 소스 변경 후 재빌드
docker compose run --rm --build commu

# 이후 실행
docker compose run --rm commu
```

앱은 `q`를 눌러 종료합니다. `--rm`은 실행 컨테이너만 삭제하며 named volume `commu-data`는 유지합니다. 따라서 캐시, URL 기록, browser storage state는 컨테이너의 `/data`에 남아 다음 실행에서도 사용됩니다.

#### 직접 Docker 실행

Compose 대신 직접 이미지를 빌드하고 실행하려면 저장소에 포함된 `docker/seccomp_profile.json`을 Playwright Chromium용 seccomp 프로필로 지정합니다.

macOS / Linux:

```bash
docker build -t commu .
docker run --rm -it --init --shm-size=1gb \
  --security-opt seccomp=docker/seccomp_profile.json \
  -v commu-data:/data \
  commu
```

Windows PowerShell:

```powershell
docker build -t commu .
docker run --rm -it --init --shm-size=1gb `
  --security-opt seccomp=docker/seccomp_profile.json `
  -v commu-data:/data `
  commu
```

컨테이너에서는 `COMMU_DATA_DIR=/data`가 기본값이고 named volume `commu-data`가 그 경로에 연결됩니다. 자세한 파일 구조와 초기화 방법은 [캐시와 브라우저 상태](#캐시와-브라우저-상태)를 참고하세요.

### 기존 버전에서 업그레이드

이전 배포명과 새 배포명이 다르므로 구버전을 제거한 뒤 다시 설치합니다.

```bash
python -m pip uninstall fmk-reader
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu --help
```

## 실행

인자 없이 실행하면 커뮤니티와 접속 방식을 고르는 시작 메뉴가 열립니다.

```bash
commu
```

시작 메뉴에서 `↑` / `↓`로 이동하고 `Enter`로 선택합니다. 사이트를 고른 뒤 추천 게시판을 열거나 URL을 직접 입력할 수 있습니다. 이전에 직접 입력했던 URL이 있으면 같은 사이트의 최근 URL로 함께 표시되며, 선택하면 바로 연결됩니다. URL 입력 단계의 `Esc`는 접속 방식 선택으로, 접속 방식 선택 단계의 `Esc`는 사이트 선택으로 돌아갑니다.

URL을 인자로 전달하면 시작 메뉴를 건너뜁니다. 게시판 URL은 목록을, 게시글 URL은 해당 글의 본문과 댓글을 바로 엽니다.

```bash
commu https://www.fmkorea.com/football_world
commu https://gall.dcinside.com/board/lists/?id=football_new9
commu https://arca.live/b/rogersfu
```

## 추천 URL

- FMKorea: `https://www.fmkorea.com/football_world`
- 디시인사이드: `https://gall.dcinside.com/board/lists/?id=football_new9`
- 아카라이브: `https://arca.live/b/rogersfu`

## 지원 URL

HTTPS URL만 지원합니다. `<gallery>`, `<channel>`은 영문자, 숫자, `_`, `-`로 이루어진 1~80자 식별자이고 `<article>`은 숫자입니다.

- FMKorea 목록: `https://www.fmkorea.com/football_world`
- FMKorea 게시글: `https://www.fmkorea.com/<article>`
- 디시인사이드 일반 갤러리 목록/게시글: `https://gall.dcinside.com/board/lists/?id=<gallery>`, `https://gall.dcinside.com/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 마이너 갤러리 목록/게시글: `https://gall.dcinside.com/mgallery/board/lists/?id=<gallery>`, `https://gall.dcinside.com/mgallery/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 미니 갤러리 목록/게시글: `https://gall.dcinside.com/mini/board/lists/?id=<gallery>`, `https://gall.dcinside.com/mini/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 모바일 목록/게시글: `https://m.dcinside.com/board/<gallery>`, `https://m.dcinside.com/board/<gallery>/<article>`
- 아카라이브 목록/게시글: `https://arca.live/b/<channel>`, `https://arca.live/b/<channel>/<article>`

## 키보드 조작

- `↑` / `↓`: 시작 메뉴·글 목록 이동 또는 본문 스크롤
- `←` / `→`: 목록에서는 게시판 페이지, 본문에서는 댓글 페이지 이동
- `Enter`: 항목 선택 또는 글 열기
- `Tab`: 목록과 본문 사이에서 포커스 이동
- `Esc`: 이전 시작 메뉴 단계나 글 목록으로 돌아가기
- `r`: 현재 목록 또는 글 새로고침
- `s`: 현재 리더를 닫고 사이트 선택 메뉴 열기
- `q`: 종료

## 캐시와 브라우저 상태

기본 데이터 디렉터리는 `~/.cache/commu/`입니다. `COMMU_DATA_DIR` 환경 변수를 설정하면 전체 데이터 루트가 바뀌며, Docker 이미지에서는 `/data`로 설정됩니다.

```text
<COMMU_DATA_DIR>/
├── cache.db
├── url-history.json
└── browser-state/
    ├── fmk.json
    ├── dcinside.json
    └── arca.json
```

기본 설정에서는 게시판·게시글 캐시가 `~/.cache/commu/cache.db`에, 직접 입력한 URL 기록이 `~/.cache/commu/url-history.json`에 저장됩니다. 캐시 키에는 사이트와 게시판 식별자가 포함되어 서로 다른 커뮤니티의 같은 글 번호가 충돌하지 않습니다. 이전 `~/.cache/fmk-reader/` 캐시는 재사용하거나 자동 삭제하지 않습니다.

`browser-state/*.json`은 Playwright의 쿠키와 origin storage를 포함할 수 있는 민감한 파일입니다. 공개 저장소에 커밋하거나 다른 사람과 공유하지 마세요. 사이트 하나의 브라우저 상태만 초기화하려면 Commu를 종료한 뒤 해당 파일 하나만 삭제합니다. 예를 들어 Docker의 아카라이브 상태만 초기화하려면 다음 명령을 사용합니다.

```bash
# macOS / Linux
docker compose run --rm --entrypoint sh commu -c 'rm -f /data/browser-state/arca.json'
```

```powershell
# Windows PowerShell
docker compose run --rm --entrypoint sh commu `
  -c 'rm -f /data/browser-state/arca.json'
```

`fmk.json` 또는 `dcinside.json`도 같은 방식으로 삭제할 수 있습니다. 반면 다음 명령은 캐시, URL 기록, 모든 브라우저 상태를 포함한 named volume 전체를 영구 삭제하는 파괴적 초기화입니다. 실행 중인 Commu 컨테이너가 없어야 하며, 필요한 데이터가 없는지 먼저 확인하세요.

```bash
docker volume rm commu-data
```

호스트에서 실행할 때도 같은 원칙으로 `<COMMU_DATA_DIR>/browser-state/<site>.json` 하나를 삭제하면 해당 사이트 상태만 초기화할 수 있습니다.

## 미디어

이미지와 동영상은 다운로드하거나 터미널에 표시하지 않고 다음 텍스트로 나타냅니다.

- FMKorea: `[이미지 생략]`, `[동영상 생략]`
- 디시인사이드: `[이미지]`, `[동영상]`, `[디시콘]`
- 아카라이브: `[이미지]`, `[동영상]`, `[이모티콘]`

## 네트워크 및 접근 정책

사이트별 요청은 직렬화되며 최초 탐색과 제한된 복구 탐색(goto/reload)은 최소 2초 간격으로 시작합니다. Playwright가 브라우저 내부에서 처리하는 개별 리디렉션 hop에는 별도 간격을 적용하지 않습니다. 봇 탐지를 방지하기 위해 각 탐색 간격에 0~1초의 랜덤 지터(jitter)가 추가됩니다. 모든 사이트의 HTTP 429와 FMKorea의 HTTP 430 응답은 `Retry-After` 값에 따라 로컬 쿨다운을 설정합니다. 쿨다운 중에는 새 요청을 보내거나 자동 재시도하지 않습니다.

### Playwright 접근 범위

Commu는 사이트별 headless Chromium 세션으로 공개 페이지를 렌더링하고, 정상 종료할 때 사이트별 storage state를 저장해 다음 실행에서 다시 사용합니다. 이 상태는 접근 성공을 보장하는 우회 수단이 아닙니다. CAPTCHA, Turnstile, JavaScript/WASM challenge를 해결하거나 우회하지 않으며 Cloudflare 또는 각 사이트의 접근 허용을 보장하지 않습니다.

FMKorea는 정보가 더 풍부한 `www.fmkorea.com` 데스크톱 페이지를 먼저 요청하며, Chromium의 기본 데스크톱 User-Agent를 사용합니다. 데스크톱 페이지가 challenge 재로딩 한 번 뒤에도 접근 차단 상태일 때만 같은 브라우저 세션에서 경로와 query를 유지한 `m.fmkorea.com` URL을 한 번 요청합니다. 모바일 fallback도 차단되거나, rate limit·timeout·cross-origin 오류가 발생하면 추가 origin 전환 없이 종료하고 사용 가능한 캐시를 표시합니다.

브라우저 동작은 무한 재시도하지 않도록 제한되어 있습니다. 탐색과 필요한 콘텐츠 선택자 대기는 각각 최대 10초이며, challenge 페이지가 감지되면 같은 세션에서 재로딩을 최대 한 번만 시도합니다. 브라우저 세션이 고장난 경우의 세션 재생성도 최대 한 번이고, FMKorea의 데스크톱 접근 차단 뒤 모바일 origin 전환도 최대 한 번입니다. 이 복구 예산은 한 요청 전체에서 공유됩니다. 그 뒤에도 접근할 수 없으면 명시적인 접근 차단 또는 가져오기 오류를 표시하고, 사용 가능한 캐시가 있으면 캐시 내용을 표시합니다.

## 문제 해결

### `commu` 명령을 찾을 수 없음

가상환경이 활성화됐는지 확인하고 패키지를 다시 설치합니다.

```bash
python -m pip install .
```

### Python 버전 오류

```bash
python --version
```

Python 3.12가 아니라면 Python 3.12로 새 가상환경을 만드세요.

### HTTP 403, 429 또는 430

커뮤니티 서버가 접근을 거부하거나 요청 간격을 제한한 상태입니다. `r`을 반복해서 누르지 말고 `Retry-After`가 표시되면 해당 시간만큼 기다리세요. 저장된 캐시가 있으면 Commu가 캐시 내용을 표시합니다.

## 개발 및 테스트

저장소 루트에서 개발 의존성을 editable 모드로 설치합니다.

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
```
