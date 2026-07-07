# Commu

FMKorea 해외축구 게시판, 디시인사이드 갤러리, 아카라이브 채널의 공개 글 목록, 본문, 댓글을 읽는 개인용 터미널 애플리케이션입니다. 로그인, 글쓰기, 추천, 구독 같은 상태 변경 기능은 지원하지 않습니다.

## 설치

Python 3.12 이상 3.13 미만과 Conda `basic-env`를 사용합니다. 아래 경로가 다르면 첫 줄을 실제 저장소 경로로 바꾸세요.

```bash
cd /Users/hj/Desktop/project_code/terminal_community
conda activate basic-env
python -m pip install -e '.[dev]'
```

## 실행

인자 없이 실행하면 커뮤니티와 접속 방식을 고르는 런처가 열립니다.

```bash
commu
```

런처에서 `↑` / `↓`로 항목을 이동하고 `Enter`로 선택합니다. 사이트를 고른 뒤 추천 게시판을 열거나 URL을 직접 입력할 수 있습니다. URL 직접 입력 단계의 `Esc`는 접속 방식 선택으로, 접속 방식 선택 단계의 `Esc`는 사이트 선택으로 돌아갑니다.

URL을 인자로 넘기면 런처를 건너뜁니다. 게시판 URL은 목록을, 게시글 URL은 해당 글의 본문과 댓글을 바로 엽니다.

```bash
commu https://arca.live/b/rogersfu
commu https://gall.dcinside.com/board/lists/?id=football_new9
```

기존 `fmk` 명령도 `commu`와 같은 호환 별칭으로 계속 사용할 수 있습니다.

## 추천 URL

- FMKorea: `https://www.fmkorea.com/football_world`
- 디시인사이드: `https://gall.dcinside.com/board/lists/?id=football_new9`
- 아카라이브: `https://arca.live/b/rogersfu`

## 지원 URL

HTTPS URL만 지원합니다. `<gallery>`, `<channel>`은 영문자, 숫자, `_`, `-`로 이루어진 1~80자 식별자이고, `<article>`은 숫자입니다.

- FMKorea 목록: `https://www.fmkorea.com/football_world`
- FMKorea 게시글: `https://www.fmkorea.com/<article>`
- 디시인사이드 일반 갤러리 목록/게시글: `https://gall.dcinside.com/board/lists/?id=<gallery>`, `https://gall.dcinside.com/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 마이너 갤러리 목록/게시글: `https://gall.dcinside.com/mgallery/board/lists/?id=<gallery>`, `https://gall.dcinside.com/mgallery/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 미니 갤러리 목록/게시글: `https://gall.dcinside.com/mini/board/lists/?id=<gallery>`, `https://gall.dcinside.com/mini/board/view/?id=<gallery>&no=<article>`
- 디시인사이드 모바일 목록/게시글: `https://m.dcinside.com/board/<gallery>`, `https://m.dcinside.com/board/<gallery>/<article>`
- 아카라이브 목록/게시글: `https://arca.live/b/<channel>`, `https://arca.live/b/<channel>/<article>`

## 리더 키

- `↑` / `↓`: 글 목록 이동 또는 본문 스크롤
- `←` / `→`: 목록에 포커스가 있으면 게시판 페이지, 본문에 포커스가 있으면 댓글 페이지 이동
- `Enter`: 선택한 글 열기
- `Tab`: 목록과 본문 사이에서 포커스 이동
- `Esc`: 목록으로 돌아가기. 게시글 URL로 바로 시작했다면 해당 게시판 목록 열기
- `r`: 현재 목록 또는 글 새로고침
- `s`: 현재 리더를 닫고 사이트 선택 런처 열기
- `q`: 종료

## 캐시, 미디어, 접근 정책

캐시는 `~/.cache/fmk-reader/cache.db`에 저장됩니다. 버전 2 키에는 사이트와 게시판 식별자가 포함되어 서로 다른 커뮤니티의 같은 글 번호가 충돌하지 않습니다. 버전 1 캐시는 재사용하지 않으므로 업그레이드 뒤 첫 실행에서는 각 목록을 다시 가져올 수 있습니다.

이미지와 동영상은 다운로드하거나 터미널에 표시하지 않고 사이트별 텍스트로 나타냅니다. FMKorea는 `[이미지 생략]`, `[동영상 생략]`, 디시인사이드는 `[이미지]`, `[동영상]`, `[디시콘]`, 아카라이브는 `[이미지]`, `[동영상]`, `[이모티콘]`을 사용합니다.

사이트별 네트워크 요청은 직렬화되며, 리디렉션을 포함한 각 외부 HTTP 요청의 시작 시각은 최소 2초 간격을 둡니다. 모든 사이트의 HTTP 429와 FMKorea의 HTTP 430 응답은 `Retry-After`가 있으면 로컬 쿨다운을 설정합니다. 쿨다운 중에는 새 요청을 보내지 않으며 자동 재시도도 하지 않습니다.

403, CAPTCHA, JavaScript/WASM 챌린지 또는 기타 차단 페이지는 우회하지 않습니다. 브라우저 쿠키를 가져오거나 챌린지 토큰을 만들지 않으며, 사용 가능한 오래된 캐시가 없으면 오류를 표시합니다.
