from __future__ import annotations

from commu.targets import Site


APP_TITLE = "OpsFlow Console"
LAUNCHER_TITLE = "업무 데이터 소스 선택"
LAUNCHER_CAPTION = (
    "KPI 수집기 · 감사 로그 활성 · 백그라운드 분석 대기"
)
RECOMMENDED_ACCESS_LABEL = "자동 업무 피드 동기화"
DIRECT_ACCESS_LABEL = "외부 업무 리소스 연결"
URL_PLACEHOLDER = "업무 리소스 HTTPS 엔드포인트"
IDLE_TITLE = "검토할 업무 항목을 선택하세요"
IDLE_META = "실시간 업무 큐가 대기 중입니다"
IDLE_BODY = (
    "좌측 업무 큐에서 항목을 선택하면 상세 리포트와 검토 메모가 "
    "표시됩니다."
)
ACTIVATION_TITLE = "데이터 파이프라인 준비 중"
ACTIVATION_META = "세션 격리 · 요청 정책 검증 · 캐시 인덱스 스캔"
LOAD_FAILURE_META = "업무 항목 동기화 실패"

_SOURCE_NAMES = {
    Site.FMKOREA: "시장 동향 리포트",
    Site.DCINSIDE: "VOC 리스크 분석",
    Site.ARCA: "제품 피드백 큐",
}


def site_choice_label(site: Site) -> str:
    return _SOURCE_NAMES[site]


def source_label(site: Site, board_id: str) -> str:
    return f"{_SOURCE_NAMES[site]} · {board_id}"


def post_row(
    *,
    category: str,
    title: str,
    votes: int,
    comment_count: int,
    created_at: str,
) -> str:
    return (
        f"[{category}] {title}\n"
        f"우선순위 {votes} · 검토 {comment_count} · 업데이트 {created_at}"
    )


def article_meta(
    *,
    author: str,
    created_at: str,
    views: str,
    votes: int,
    comment_count: int,
) -> str:
    return (
        f"담당 {author} · 수집 {created_at} · 조회 {views} "
        f"· 중요도 {votes} · 검토 {comment_count}"
    )


def activation_body() -> str:
    return "\n".join(
        (
            "데이터 파이프라인 준비 중",
            "[auth] 세션 격리 채널 확인",
            "[cache] 캐시 인덱스 스캔",
            "[policy] 요청 정책과 감사 로그 연결",
        )
    )


def loading_body(post_id: str) -> str:
    return "\n".join(
        (
            f"업무 항목 {post_id} 동기화 중",
            "[sync] 원격 변경분 스캔",
            "[normalize] 본문 텍스트 정규화",
            "[audit] 감사 로그 타임라인 기록",
            "[render] 검토 가능한 리포트 화면 생성",
        )
    )


def board_status(page: int, source: str) -> str:
    return f"업무 큐 {page}페이지 · {source}"


def post_status(post_id: str, comment_page: int, source: str) -> str:
    return f"업무 항목 {post_id} · 검토 메모 {comment_page}페이지 · {source}"


def loading_status(post_id: str) -> str:
    return f"업무 항목 {post_id} · 동기화 중"


def link_heading() -> str:
    return "참고 리소스"


def comments_heading(page: int) -> str:
    return f"검토 메모 {page}페이지"
