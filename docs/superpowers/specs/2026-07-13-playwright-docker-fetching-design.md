# Playwright 상주 수집과 Docker 배포 설계

## 배경과 목표

현재 애플리케이션은 `httpx` 또는 사이트별 `curl_cffi` 요청으로 HTML을 받은 뒤 BeautifulSoup 어댑터로 파싱한다. SQLite TTL 캐시와 stale-cache fallback은 네트워크 장애 때 저장된 데이터를 제공한다.

이번 변경의 주된 목표는 Cloudflare 및 HTTP 403 차단을 줄이는 것이다. JavaScript를 실행할 수 있는 실제 브라우저 세션을 앱 실행 중 계속 유지하고, 컨테이너 재실행 후에도 필요한 세션 상태를 복원한다. 동시에 Windows와 macOS에서 Docker Desktop을 통해 동일한 터미널 애플리케이션을 실행할 수 있게 한다.

다음은 범위 밖이다.

- CAPTCHA 또는 Turnstile 자동 해결
- 보안 검증을 적극적으로 우회하는 로직
- 이미지와 동영상 다운로드 또는 터미널 렌더링
- 기존 BeautifulSoup 파서와 데이터 모델의 재작성
- 여러 요청을 동일 사이트 페이지에서 병렬 처리

## 선택한 접근법

Playwright를 모든 사이트의 단일 네트워크 수집 경로로 사용한다. 앱이 실행되는 동안 headless Chromium 하나와 사이트별 `BrowserContext` 및 `Page`를 유지한다. 종료 시 전체 브라우저 프로필 대신 사이트별 Playwright `storage_state`를 저장하고, 다음 실행에서 이를 복원한다.

이 접근법을 선택한 이유는 다음과 같다.

- 매 실행마다 새 세션을 만드는 방식보다 Cloudflare 쿠키와 브라우저 저장소를 재사용할 가능성이 높다.
- 전체 Chromium 사용자 프로필을 보존하는 방식보다 저장 용량이 작고 브라우저 버전 변경에 덜 취약하다.
- 기존 서비스와 파서가 이미 HTML 문자열을 경계로 분리되어 있어 네트워크 계층만 교체할 수 있다.

저장한 상태가 Cloudflare 통과를 보장하지는 않는다. 공인 IP, User-Agent 또는 Chromium 버전이 바뀌면 검증을 다시 받을 수 있다.

## 아키텍처

데이터 흐름은 다음과 같다.

```text
Textual UI
  -> CommunityService
     -> SQLite 캐시 조회
     -> PlaywrightCommunityClient.get_text(url)
        -> 사이트별 BrowserContext + Page
        -> 탐색 및 핵심 DOM 대기
        -> page.content()
     -> 기존 BeautifulSoup 어댑터
     -> SQLite 캐시 저장
```

`CommunityService`의 `TextClient` 프로토콜은 유지한다. 새 `PlaywrightCommunityClient`가 `get_text(url) -> str` 계약을 구현하므로 서비스, 모델, 캐시와 어댑터 파서는 브라우저 세부사항을 알지 못한다.

기존 `httpx` 및 `curl_cffi` 수집 분기는 제거한다. 사이트별 URL 생성과 HTML 파싱은 각 어댑터에 남긴다. 브라우저가 기다려야 할 핵심 DOM 선택자는 사이트별 어댑터 또는 별도의 명시적 페이지 정책에서 제공한다. 파싱 책임과 브라우저 제어 책임은 섞지 않는다.

## 브라우저와 페이지 수명주기

앱 시작 시 Playwright와 headless Chromium 프로세스를 하나씩 시작한다. 사이트에 처음 접근할 때 해당 사이트 전용 `BrowserContext`와 `Page`를 지연 생성한다.

- FMKorea, 디시인사이드, 아카라이브는 서로 다른 컨텍스트를 사용한다.
- 같은 사이트의 게시판과 게시글은 동일 페이지에서 순차적으로 탐색한다.
- 사이트별 잠금으로 같은 페이지에 대한 동시 탐색을 막는다.
- 사이트 선택 화면으로 돌아가도 브라우저, 컨텍스트, 페이지를 유지한다.
- `r` 새로고침은 데이터 캐시만 무시하고 브라우저 세션은 유지한다.

정상 종료 시 다음 순서로 정리한다.

1. 사이트별 `storage_state`를 같은 디렉터리의 임시 파일에 기록한다.
2. 기록이 성공하면 원자적 교체로 기존 상태 파일을 갱신한다.
3. 페이지와 컨텍스트를 닫는다.
4. Chromium과 Playwright를 종료한다.
5. SQLite 캐시를 닫는다.

한 자원의 정리가 실패해도 나머지 자원 정리를 계속하고 오류 정보를 보존한다. 강제 종료에서는 최신 storage state 저장을 보장하지 않으며, 마지막 정상 저장본을 다음 실행에서 사용한다.

상태 파일이 없으면 새 컨텍스트를 만든다. JSON이 손상됐거나 Playwright가 상태를 거부하면 해당 사이트 파일만 무시하고 새 컨텍스트로 시작한다. 다른 사이트 상태에는 영향을 주지 않는다.

## 탐색과 응답 판정

`get_text(url)`은 사이트별 잠금 안에서 다음과 같이 실행한다.

1. URL의 scheme, host, port가 사이트 정책의 허용 origin에 속하는지 검증한다.
2. 기존 요청 간격과 로컬 `Retry-After` 쿨다운을 적용한다.
3. 유지 중인 페이지에서 `page.goto(url, wait_until="domcontentloaded")`를 호출한다.
4. 사이트와 페이지 종류에 맞는 핵심 DOM 선택자가 나타날 때까지 제한 시간 동안 기다린다.
5. DOM이 짧게 안정화된 뒤 `page.content()`를 반환한다.

광고나 추적 요청이 계속될 수 있으므로 `networkidle`은 완료 조건으로 사용하지 않는다. 탐색과 DOM 대기에는 유한한 timeout을 사용하며 무한 대기는 허용하지 않는다.

응답 상태와 DOM을 함께 검사해 다음을 차단으로 판정한다.

- HTTP 403, 429 또는 사이트 정책에 정의된 430
- `Just a moment`, `Access denied`, CAPTCHA 또는 Turnstile 화면
- 핵심 DOM이 나타나지 않은 상태에서 challenge 표시 요소가 발견된 경우

브라우저가 정상적인 JavaScript 및 쿠키 검증을 처리하도록 허용하지만 CAPTCHA를 풀거나 challenge 요소와 상호작용하는 자동화는 구현하지 않는다.

## 실패와 복구

- HTTP 429/430 응답에 `Retry-After`가 있으면 기존 로컬 쿨다운 상태에 기록한다.
- challenge 또는 403에서는 같은 컨텍스트로 페이지를 한 번만 다시 탐색해 저장된 세션을 재확인한다.
- 페이지 또는 컨텍스트가 종료되거나 손상된 경우 해당 사이트 컨텍스트만 한 번 재생성하고 요청을 다시 수행한다.
- 한 요청에서 challenge 재탐색과 컨텍스트 재생성을 포함한 복구는 각각 최대 한 번으로 제한한다.
- 복구 후에도 실패하면 `FetchError`, `AccessBlocked` 또는 `RateLimited`로 서비스 계층에 전달한다.
- 서비스는 현재 동작처럼 유효한 stale cache를 반환하고, 없으면 사용자에게 오류를 표시한다.
- 백그라운드 반복 재시도나 지수 백오프 루프는 추가하지 않는다.

브라우저 세션을 수동 초기화하는 UI 명령은 이번 범위에 포함하지 않는다. 문제 해결 문서에서 컨테이너 내부 사이트별 상태 파일을 삭제하고 재실행하는 절차를 제공한다.

## 캐시와 영속 데이터

SQLite 키, TTL과 stale-cache 정책은 유지한다.

- 게시판: 60초
- 게시글 본문: 1,800초
- 댓글을 포함한 게시글 페이지: 120초

Docker 볼륨 `/data`에는 다음 파일을 저장한다.

```text
/data/
├── cache.db
├── url-history.json
└── browser-state/
    ├── fmk.json
    ├── dcinside.json
    └── arca.json
```

상태 파일에는 쿠키와 웹 저장소가 포함될 수 있으므로 비밀정보로 취급한다. 이미지에 포함하거나 로그에 내용을 출력하지 않는다. 볼륨은 사용자 머신에만 존재하며 저장소에 커밋하지 않는다.

Docker 밖에서 직접 실행하는 경우에도 하나의 데이터 루트 아래 동일한 구조를 사용한다. `COMMU_DATA_DIR` 환경 변수가 있으면 그 경로를 사용하고, 없으면 `~/.cache/commu`를 사용한다. Docker 이미지는 `COMMU_DATA_DIR=/data`를 설정한다. 기존 `~/.cache/commu/cache.db`와 `url-history.json`은 이동 없이 계속 사용하며 브라우저 상태만 `browser-state/` 하위에 추가한다.

## Docker 배포

Chromium과 필요한 시스템 라이브러리가 포함된 버전 고정 Playwright Python 이미지를 기반으로 한다. 애플리케이션은 컨테이너 안에서 root가 아닌 사용자로 실행하고 `commu`를 기본 명령으로 지정한다.

기본 실행 예시는 다음과 같다.

```bash
docker build -t commu .
docker run --rm -it --init --shm-size=1gb -v commu-data:/data commu
```

- `-it`는 Textual TUI 입력과 색상 출력을 유지한다.
- `--init`은 Chromium 자식 프로세스 회수를 돕는다.
- `--shm-size=1gb`는 Chromium 공유 메모리 부족으로 인한 충돌 위험을 낮춘다.
- `commu-data` named volume은 캐시와 브라우저 상태를 컨테이너 재실행 후에도 유지한다.
- 포트나 GUI 창은 노출하지 않는다.

README에는 macOS/Linux 셸과 Windows PowerShell 실행 예시, Docker Desktop 요구사항, 볼륨 초기화 방법과 세션 상태의 보안 특성을 설명한다.

## 테스트 전략

Playwright 자체는 테스트에서 가짜 브라우저 객체 또는 좁은 래퍼 경계를 통해 대체한다. 네트워크가 필요한 실제 사이트 검증은 기본 자동 테스트와 분리한다.

단위 테스트는 다음을 검증한다.

- 사이트별 컨텍스트 및 페이지의 지연 생성과 재사용
- 서로 다른 사이트의 컨텍스트와 storage state 분리
- 허용되지 않은 origin 및 cross-origin redirect 차단
- 요청 직렬화, 최소 간격, `Retry-After` 쿨다운
- `domcontentloaded`, 핵심 DOM 대기와 HTML 반환
- 403/429/430 및 challenge DOM 감지
- challenge 재탐색과 손상된 컨텍스트 복구가 각각 한 번으로 제한됨
- 손상되거나 호환되지 않는 상태 파일을 사이트별로 무시함
- 임시 파일을 이용한 storage state 원자적 저장
- 일부 종료 작업 실패 후에도 나머지 자원 정리가 진행됨

서비스 회귀 테스트는 기존 캐시 hit, refresh, stale-cache fallback, 파서 호출과 TTL을 유지하는지 검증한다. 기존 어댑터 fixture 테스트로 `page.content()` 형태의 HTML이 현재 모델로 변환되는지 확인한다.

Docker 검증은 이미지 빌드, 비대화형 프로세스 시작, 일반 사용자 실행과 `/data` 쓰기 가능 여부를 확인한다. 실제 커뮤니티에 접속하는 smoke test는 수동 또는 별도 opt-in 테스트로 두고, Cloudflare 정책 변화 때문에 CI 성공 조건으로 삼지 않는다.

## 완료 기준

- 세 사이트가 모두 Playwright 단일 수집 경로를 사용한다.
- 앱 실행 중 사이트별 브라우저 세션과 페이지가 재사용된다.
- 정상 종료 후 사이트별 storage state가 `/data/browser-state`에 저장되고 다음 실행에서 복원된다.
- 기존 BeautifulSoup 파서, SQLite TTL 및 stale-cache 동작이 유지된다.
- Windows와 macOS의 Docker Desktop에서 동일한 이미지가 `docker run -it`로 실행된다.
- 차단 및 복구 로직이 무한 대기나 무제한 재시도를 만들지 않는다.
- 단위·회귀 테스트와 Docker 빌드 검증이 통과한다.
