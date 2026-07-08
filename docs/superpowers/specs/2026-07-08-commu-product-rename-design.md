# Commu 제품 전체 이름 변경 설계

## 배경

현재 제품은 세 커뮤니티를 지원하지만 배포명, Python 모듈명, 캐시 경로,
User-Agent에 초기 FMKorea 전용 이름인 `fmk`가 남아 있다. 사용자-facing 명령은
이미 `commu`가 기본이지만 `fmk` 호환 별칭도 설치된다. 제품 정체성을 `Commu`로
통일하고 FMKorea 관련 이름은 해당 사이트 어댑터에만 남긴다.

## 목표

- 설치되는 CLI를 `commu` 하나로 제한한다.
- Python 배포명과 import 모듈명을 `commu`로 통일한다.
- 제품 공통 캐시 경로와 User-Agent에서 `fmk`를 제거한다.
- FMKorea 전용 어댑터와 사이트 식별자는 의미가 정확하므로 유지한다.
- 새 설치와 업그레이드 절차를 README에 명확히 기록한다.

## 비목표

- FMKorea 사이트 지원 제거
- `FmkAdapter`, `Site.FMKOREA`, `adapters/fmk.py` 같은 사이트 전용 이름 변경
- 기존 `fmk_reader` import 또는 `fmk` CLI 호환 shim 제공
- 기존 캐시 자동 이동 또는 삭제

## 이름 변경

다음 이름을 원자적으로 변경한다.

- 배포명: `fmk-reader`에서 `commu`
- Python package: `src/fmk_reader`에서 `src/commu`
- 모든 내부·테스트 import: `fmk_reader`에서 `commu`
- console script: `commu = "commu.app:main"`만 등록
- User-Agent: `commu/0.1 personal read-only client`
- 캐시: `~/.cache/commu/cache.db`
- README의 제품 공통 `fmk` 문구 제거

FMKorea 도메인, 표시명, 라우팅, 파서, 어댑터 이름은 사이트 전용이므로 변경하지
않는다. 따라서 코드 검색 결과에 남는 `fmk`는 FMKorea 기능을 설명하는 경우만
허용한다.

## 캐시 정책

첫 실행에서 `~/.cache/commu/cache.db`를 새로 만든다. 기존
`~/.cache/fmk-reader/`는 읽거나 이동하거나 삭제하지 않는다. 이 정책은 rename
코드를 단순하게 유지하고 손상 또는 데이터 유실 위험을 없앤다. 사용자는 필요하면
기존 디렉터리를 직접 삭제할 수 있다.

## 설치와 업그레이드

새 설치는 기존 공개 절차를 사용한다.

```bash
python -m pip install -r requirements.txt
python -m pip install --no-deps .
```

구버전 `fmk-reader`와 새 `commu`는 배포명이 다르므로 pip가 자동 교체하지 않는다.
기존 설치자는 구버전을 먼저 제거한다.

```bash
python -m pip uninstall fmk-reader
python -m pip install --no-deps .
```

README에서 `fmk` 호환 별칭 설명을 삭제하고, 업그레이드 후 `commu --help`와
`command -v commu`로 설치를 확인하도록 안내한다.

## 저장소 복구 범위

공개 설치에 필요한 `pyproject.toml`은 추적 파일이어야 한다. `.gitignore`의
`pyproject.toml` 항목을 제거한다. 이름 변경은 현재 추적된 테스트를 함께 갱신해
패키징 회귀를 검증한다. 설계 문서와 테스트 제거 같은 별도 저장소 정리 작업은 이
변경 범위에 포함하지 않는다.

## 오류 처리

- 새 캐시 디렉터리 생성 실패는 기존 `JsonCache` 초기화 오류로 명확히 실패한다.
- 구 캐시는 접근하지 않으므로 migration 실패 경로가 없다.
- 구 배포가 같은 환경에 남아 있을 수 있으므로 README에서 명시적으로 제거 명령을
  제공한다.

## 테스트

- 모든 import를 `commu`로 변경한 뒤 전체 테스트를 실행한다.
- packaging 테스트에서 배포명 `commu`, 유일한 console script `commu`, wheel
  package `src/commu`를 검증한다.
- 코드·README에서 제품 공통 `fmk-reader`, `fmk_reader`, `fmk` CLI 별칭이 사라졌는지
  검사한다.
- FMKorea 전용 `FmkAdapter`와 URL 라우팅 테스트가 계속 통과하는지 확인한다.
- 깨끗한 Python 3.12 가상환경에서 requirements 설치, wheel 설치,
  `commu --help`를 검증한다.

## 완료 조건

- `commu`만 설치되고 `fmk` console script는 생성되지 않는다.
- `import commu`가 성공하고 `import fmk_reader`는 제공되지 않는다.
- 캐시 파일이 `~/.cache/commu/cache.db`에 생성된다.
- 전체 pytest, Ruff, compileall, pip check가 통과한다.
- README 설치·업그레이드 명령이 새 이름과 일치한다.
