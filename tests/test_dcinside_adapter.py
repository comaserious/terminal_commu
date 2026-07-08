from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from commu.adapters import adapter_for
from commu.adapters.dcinside import DcinsideAdapter
from commu.errors import ParseError
from commu.models import PostSummary
from commu.targets import route_url


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def adapter() -> DcinsideAdapter:
    return DcinsideAdapter(route_url("https://m.dcinside.com/board/football_new9"))


def test_dc_board_filters_ads_and_builds_mobile_urls() -> None:
    target = route_url("https://gall.dcinside.com/board/lists/?id=football_new9")
    page = DcinsideAdapter(target).parse_board(fixture("dc_board.html"), page=1)

    assert [post.post_id for post in page.items] == ["47", "6244511", "6244510"]
    assert page.items[0].is_notice is True
    assert page.items[1].url == ("https://m.dcinside.com/board/football_new9/6244511")
    assert page.items[1].author == "축구팬"
    assert page.items[1].views == "31"
    assert page.items[1].votes == 7
    assert page.items[1].comment_count == 2
    assert page.has_previous is False
    assert page.has_next is True


def test_dc_post_reads_body_comments_replies_and_media_placeholders() -> None:
    dc = adapter()
    post = dc.parse_board(fixture("dc_board.html"), 1).items[1]

    detail, comments = dc.parse_post(fixture("dc_post.html"), post, 1)

    assert detail.summary.post_id == "6244511"
    assert detail.summary.title == "오늘의 축구 이야기"
    assert detail.summary.views == "31"
    assert detail.summary.votes == 7
    assert "[이미지]" in detail.body
    assert "[동영상]" in detail.body
    assert "media.example.test" not in detail.body
    assert detail.links == ("https://example.test/reference",)
    assert [comment.depth for comment in comments.items] == [0, 1]
    assert "[디시콘]" in comments.items[1].content
    assert [comment.comment_id for comment in comments.items] == ["9001", "9002"]
    assert [comment.author for comment in comments.items] == ["첫님", "답글러"]
    assert [comment.created_at for comment in comments.items] == [
        "07.07 14:03",
        "07.07 14:04",
    ]
    assert comments.items[0].content == "첫님 댓글\n사용자 링크"

    rendered = "\n".join(
        [detail.body, *(comment.content for comment in comments.items)]
    )
    for media_value in (
        "https://media.example.test/photo.jpg",
        "https://media.example.test/movie.mp4",
        "https://media.example.test/dccon.png",
        "photo-alt-hash",
        "dccon-alt-hash",
    ):
        assert media_value not in rendered


def test_dc_comment_paging_uses_only_valid_same_article_controls() -> None:
    dc = adapter()
    html = fixture("dc_post.html")
    post = dc.parse_board(fixture("dc_board.html"), 1).items[1]
    without_controls = BeautifulSoup(html, "html.parser")
    paging = without_controls.select_one(".all-comment > .comment-paging")
    assert paging is not None
    paging.decompose()

    _, user_link_only = dc.parse_post(str(without_controls), post, 1)
    _, first_page = dc.parse_post(html, post, 1)
    _, later_page = dc.parse_post(html, post, 2)

    assert (user_link_only.has_previous, user_link_only.has_next) == (False, False)
    assert (first_page.has_previous, first_page.has_next) == (False, True)
    assert (later_page.has_previous, later_page.has_next) == (True, False)


def test_dc_adapter_builds_canonical_fetch_urls_and_direct_post() -> None:
    dc = adapter()
    post = PostSummary(
        post_id="6244511",
        title="title",
        category="",
        author="",
        created_at="",
        views="0",
        votes=0,
        comment_count=0,
        url="https://m.dcinside.com/board/football_new9/6244511",
        is_notice=False,
    )

    assert dc.board_url(1) == "https://m.dcinside.com/board/football_new9"
    assert dc.board_url(2) == "https://m.dcinside.com/board/football_new9?page=2"
    assert dc.post_url(post, 1) == post.url
    assert dc.post_url(post, 2) == f"{post.url}?cpage=2"
    assert dc.direct_post() is None

    direct = DcinsideAdapter(
        route_url("https://m.dcinside.com/board/football_new9/6244511")
    ).direct_post()
    assert direct is not None
    assert direct.post_id == "6244511"
    assert direct.url == "https://m.dcinside.com/board/football_new9/6244511"


def test_dc_adapter_exposes_mobile_only_request_policy() -> None:
    policy = adapter().policy

    assert "Mobile" in policy.user_agent
    assert policy.allowed_origins == frozenset({("https", "m.dcinside.com", 443)})
    assert policy.rate_limit_statuses == frozenset({429})
    assert policy.blocked_statuses == frozenset({403})
    assert policy.min_interval == 2.0


def test_adapter_for_returns_dcinside_adapter() -> None:
    selected = adapter_for(
        route_url("https://gall.dcinside.com/mini/board/lists/?id=football_new9")
    )

    assert isinstance(selected, DcinsideAdapter)


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html></html>", "디시인사이드 게시판 목록 구조를 찾을 수 없습니다"),
        (
            '<ul class="gall-detail-lst"></ul>',
            "디시인사이드 게시글 목록 구조를 찾을 수 없습니다",
        ),
    ],
)
def test_dc_board_requires_expected_container_and_valid_rows(
    html: str, message: str
) -> None:
    with pytest.raises(ParseError, match=f"^{message}$"):
        adapter().parse_board(html, 1)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '<meta property="og:url" content="https://m.dcinside.com/board/football_new9/6244511">',
            "",
            "디시인사이드 게시글 정보 구조를 찾을 수 없습니다",
        ),
        (
            '<span class="tit">오늘의 축구 이야기</span>',
            '<span class="tit"></span>',
            "디시인사이드 게시글 제목 구조를 찾을 수 없습니다",
        ),
        (
            '<div class="thum-txtin">',
            '<div class="missing-body">',
            "디시인사이드 게시글 본문 구조를 찾을 수 없습니다",
        ),
    ],
)
def test_dc_post_requires_identity_title_and_body(
    old: str, new: str, message: str
) -> None:
    html = fixture("dc_post.html").replace(old, new, 1)
    post = adapter().parse_board(fixture("dc_board.html"), 1).items[1]

    with pytest.raises(ParseError, match=f"^{message}$"):
        adapter().parse_post(html, post, 1)


def test_dc_post_rejects_mismatched_article_and_board_identity() -> None:
    html = fixture("dc_post.html").replace(
        "/board/football_new9/6244511",
        "/board/other_board/999",
        1,
    )
    post = adapter().parse_board(fixture("dc_board.html"), 1).items[1]

    with pytest.raises(
        ParseError,
        match="^디시인사이드 게시글 정보가 요청과 일치하지 않습니다$",
    ):
        adapter().parse_post(html, post, 1)
