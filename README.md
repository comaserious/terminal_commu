# FMK Reader

FMKorea 해외축구 게시판의 공개 글, 본문, 댓글을 읽는 개인용 터미널 애플리케이션입니다. 로그인, 쓰기, 추천, 이미지 표시는 지원하지 않습니다.

## 설치

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

캐시는 `~/.cache/fmk-reader/cache.db`에 저장됩니다. 요청은 한 번에 하나씩, 최소 2초 간격으로 실행됩니다. 403, CAPTCHA 또는 차단 페이지는 우회하지 않습니다.
