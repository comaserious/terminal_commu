# FMK Reader

FMKorea 해외축구 게시판의 공개 글, 본문, 댓글을 읽는 개인용 터미널 애플리케이션입니다. 로그인, 쓰기, 추천, 이미지 표시는 지원하지 않습니다.

## 설치

Python 3.12 이상 3.13 미만이 필요하며, Conda `basic-env`가 의도된 실행 환경입니다. 명령은 저장소 루트에서 실행합니다. 아래는 이 사용자의 최종 기본 경로 예시이며, 다른 위치에 저장소를 두었다면 첫 줄을 실제 저장소 루트로 바꾸세요.

```bash
cd /Users/hj/Desktop/project_code/terminal_community
conda activate basic-env
python -m pip install -e '.[dev]'
```

## 실행

```bash
fmk
```

## 키

- `↑` / `↓`: 목록 이동 또는 본문 스크롤
- `←` / `→`: 게시판 또는 댓글 페이지 이동
- `Enter`: 글 열기
- `Tab`: 목록과 본문 포커스 전환
- `Esc`: 좁은 화면에서 목록으로 복귀
- `r`: 새로고침
- `q`: 종료

캐시는 `~/.cache/fmk-reader/cache.db`에 저장됩니다. FMKorea 최상위 가져오기 작업은 한 번에 하나씩 실행되고 최소 2초 간격으로 시작합니다. 한 작업 안의 동일 출처 리디렉션에는 별도의 2초 간격을 두지 않습니다. 403, CAPTCHA 또는 차단 페이지는 우회하지 않습니다.
