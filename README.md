# OpsFlow Console

일하기 싫은 직장인을 위한 업무 위장형 터미널 콘솔입니다. 겉으로는 KPI, VOC, 리포트 큐를 처리하는 운영 도구처럼 보이지만, 실제로는 FMKorea, 디시인사이드, 아카라이브의 공개 게시글을 터미널에서 읽습니다. 목록, 본문, 댓글을 키보드로 탐색할 수 있습니다.

OpsFlow Console은 읽기 전용입니다. 로그인, 글쓰기, 추천, 구독을 지원하지 않으며 CAPTCHA나 JavaScript/WASM 보안 검증을 우회하지 않습니다.

## 주요 기능

- FMKorea 해외축구 게시판 지원
- 디시인사이드 일반·마이너·미니 갤러리 지원
- 아카라이브 공개 채널 지원
- 게시글 목록, 본문, 댓글과 답글 표시
- 업무 데이터 소스처럼 보이는 시작 메뉴
- 자동 업무 피드 동기화 또는 외부 업무 리소스 연결
- 로딩 중 업무 로그처럼 보이는 상태 화면
- `commu <URL>`을 통한 게시판·게시글 바로 열기
- 사이트와 게시판이 분리된 로컬 캐시
- 이미지·동영상을 다운로드하지 않는 텍스트 전용 화면

## 요구사항

- Python 3.12 이상 3.13 미만
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

### 기존 버전에서 업그레이드

이전 배포명과 새 배포명이 다르므로 구버전을 제거한 뒤 다시 설치합니다.

```bash
python -m pip uninstall fmk-reader
python -m pip install -r requirements.txt
python -m pip install --no-deps .
commu --help
```

## 실행

인자 없이 실행하면 업무 데이터 소스와 접속 방식을 고르는 시작 메뉴가 열립니다.

```bash
commu
```

시작 메뉴에서 `↑` / `↓`로 이동하고 `Enter`로 선택합니다. 업무 데이터 소스를 고른 뒤 자동 업무 피드를 동기화하거나 외부 업무 리소스 URL을 직접 입력할 수 있습니다. URL 입력 단계의 `Esc`는 접속 방식 선택으로, 접속 방식 선택 단계의 `Esc`는 데이터 소스 선택으로 돌아갑니다.

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

## 캐시와 미디어

캐시는 `~/.cache/commu/cache.db`에 저장됩니다. 캐시 키에는 사이트와 게시판 식별자가 포함되어 서로 다른 커뮤니티의 같은 글 번호가 충돌하지 않습니다. 이전 `~/.cache/fmk-reader/` 캐시는 재사용하거나 자동 삭제하지 않습니다.

이미지와 동영상은 다운로드하거나 터미널에 표시하지 않고 다음 텍스트로 나타냅니다.

- FMKorea: `[이미지 생략]`, `[동영상 생략]`
- 디시인사이드: `[이미지]`, `[동영상]`, `[디시콘]`
- 아카라이브: `[이미지]`, `[동영상]`, `[이모티콘]`

## 네트워크 및 접근 정책

사이트별 요청은 직렬화되며 리디렉션을 포함한 각 HTTP 요청은 최소 2초 간격으로 시작합니다. 모든 사이트의 HTTP 429와 FMKorea의 HTTP 430 응답은 `Retry-After` 값에 따라 로컬 쿨다운을 설정합니다. 쿨다운 중에는 새 요청을 보내거나 자동 재시도하지 않습니다.

403, CAPTCHA, JavaScript/WASM challenge 등 차단 페이지는 우회하지 않습니다. 브라우저 쿠키나 challenge 토큰도 사용하지 않습니다. 사용 가능한 캐시가 없으면 오류가 표시됩니다.

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

커뮤니티 서버가 접근을 거부하거나 요청 간격을 제한한 상태입니다. `r`을 반복해서 누르지 말고 `Retry-After`가 표시되면 해당 시간만큼 기다리세요. 저장된 캐시가 있으면 OpsFlow Console이 캐시 내용을 표시합니다.

### CAPTCHA 또는 challenge 페이지

OpsFlow Console은 보안 검증을 우회하지 않습니다. 일반 브라우저를 사용하거나 제한이 해제된 뒤 다시 시도하세요.

## 개발 및 테스트

저장소 루트에서 개발 의존성을 editable 모드로 설치합니다.

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
```
