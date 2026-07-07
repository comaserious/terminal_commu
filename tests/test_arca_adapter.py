from pathlib import Path

import pytest

from fmk_reader.adapters import adapter_for
from fmk_reader.adapters.arca import ArcaAdapter
from fmk_reader.errors import ParseError
from fmk_reader.models import PostSummary
from fmk_reader.targets import route_url


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def adapter() -> ArcaAdapter:
    return ArcaAdapter(route_url("https://arca.live/b/rogersfu"))


def test_arca_board_keeps_channel_rows_and_rejects_foreign_service_notice() -> None:
    page = adapter().parse_board(fixture("arca_board.html"), page=1)

    assert [post.post_id for post in page.items] == [
        "6457546",
        "176096992",
        "176096991",
    ]
    assert page.items[0].is_notice is True
    assert all("/b/rogersfu/" in post.url for post in page.items)
    assert page.items[1].url == "https://arca.live/b/rogersfu/176096992"
    assert page.items[1].category == "일반"
    assert page.items[1].author == "첫글러"
    assert page.items[1].views == "61"
    assert page.items[1].votes == 5
    assert page.items[1].comment_count == 2
    assert (page.has_previous, page.has_next) == (False, True)


def test_arca_post_reads_comments_replies_and_exact_placeholders() -> None:
    arca = adapter()
    post = arca.parse_board(fixture("arca_board.html"), 1).items[1]

    detail, comments = arca.parse_post(fixture("arca_post.html"), post, 1)

    assert detail.summary.post_id == "176096992"
    assert detail.summary.title == "새로운 이야기"
    assert detail.summary.author == "첫글러"
    assert detail.summary.created_at == "2026-07-07 04:11:37"
    assert detail.summary.views == "61"
    assert detail.summary.votes == 5
    assert detail.summary.comment_count == 2
    assert detail.body == "본문 첫줄\n[이미지]\n[동영상]\n참고 링크"
    assert detail.links == ("https://example.test/reference",)
    assert [comment.comment_id for comment in comments.items] == ["7001", "7002"]
    assert [comment.depth for comment in comments.items] == [0, 1]
    assert comments.items[1].content == "답글\n[이모티콘]"
    assert [comment.author for comment in comments.items] == ["댓글러", "답글러"]

    rendered = "\n".join(
        [detail.body, *(comment.content for comment in comments.items)]
    )
    assert "media.example.test" not in rendered
    assert "photo-alt-hash" not in rendered


def test_arca_urls_direct_post_policy_and_routing() -> None:
    arca = adapter()
    post = PostSummary(
        post_id="176096992",
        title="title",
        category="",
        author="",
        created_at="",
        views="0",
        votes=0,
        comment_count=0,
        url="https://evil.example/b/rogersfu/176096992?unsafe=1",
        is_notice=False,
    )

    assert arca.board_url(1) == "https://arca.live/b/rogersfu"
    assert arca.board_url(2) == "https://arca.live/b/rogersfu?p=2"
    assert arca.post_url(post, 1) == "https://arca.live/b/rogersfu/176096992"
    assert arca.post_url(post, 2) == "https://arca.live/b/rogersfu/176096992"
    assert arca.direct_post() is None

    direct = ArcaAdapter(
        route_url("https://arca.live/b/rogersfu/176096992?ignored=1")
    ).direct_post()
    assert direct is not None
    assert direct.url == "https://arca.live/b/rogersfu/176096992"

    policy = arca.policy
    assert policy.allowed_origins == frozenset({("https", "arca.live", 443)})
    assert policy.rate_limit_statuses == frozenset({429})
    assert policy.blocked_statuses == frozenset({403})
    assert policy.min_interval == 2.0
    assert isinstance(adapter_for(route_url("https://arca.live/b/rogersfu")), ArcaAdapter)


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html></html>", "아카라이브 게시판 목록 구조를 찾을 수 없습니다"),
        (
            '<div class="article-list"></div>',
            "아카라이브 게시글 목록 구조를 찾을 수 없습니다",
        ),
    ],
)
def test_arca_board_requires_expected_container_and_valid_rows(
    html: str, message: str
) -> None:
    with pytest.raises(ParseError, match=f"^{message}$"):
        adapter().parse_board(html, 1)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '<div class="article-link"><a href="https://arca.live/b/rogersfu/176096992?p=1">',
            '<div class="article-link"><a>',
            "아카라이브 게시글 정보 구조를 찾을 수 없습니다",
        ),
        (
            "새로운 이야기</div>",
            "</div>",
            "아카라이브 게시글 제목 구조를 찾을 수 없습니다",
        ),
        (
            '<div class="fr-view article-content">',
            '<div class="fr-view missing-content">',
            "아카라이브 게시글 본문 구조를 찾을 수 없습니다",
        ),
    ],
)
def test_arca_post_requires_identity_title_and_body(
    old: str, new: str, message: str
) -> None:
    html = fixture("arca_post.html").replace(old, new, 1)
    post = adapter().parse_board(fixture("arca_board.html"), 1).items[1]

    with pytest.raises(ParseError, match=f"^{message}$"):
        adapter().parse_post(html, post, 1)


def test_arca_post_rejects_mismatched_channel_and_article_identity() -> None:
    html = fixture("arca_post.html").replace(
        "https://arca.live/b/rogersfu/176096992?p=1",
        "https://arca.live/b/other/999?p=1",
        1,
    )
    post = adapter().parse_board(fixture("arca_board.html"), 1).items[1]

    with pytest.raises(
        ParseError,
        match="^아카라이브 게시글 정보가 요청과 일치하지 않습니다$",
    ):
        adapter().parse_post(html, post, 1)


@pytest.mark.parametrize(
    "href",
    [
        "http://arca.live/b/rogersfu/176096992",
        "https://example.test/b/rogersfu/176096992",
    ],
)
def test_arca_board_rejects_http_and_cross_origin_article_rows(href: str) -> None:
    html = fixture("arca_board.html").replace(
        "/b/rogersfu/176096992?p=1&amp;mode=best",
        href,
        1,
    )

    page = adapter().parse_board(html, 1)

    assert "176096992" not in {post.post_id for post in page.items}


@pytest.mark.parametrize(
    "href",
    [
        "http://arca.live/b/rogersfu/176096992?p=1",
        "https://example.test/b/rogersfu/176096992?p=1",
    ],
)
def test_arca_post_rejects_http_and_cross_origin_identity_links(href: str) -> None:
    html = fixture("arca_post.html").replace(
        "https://arca.live/b/rogersfu/176096992?p=1",
        href,
        1,
    )
    post = adapter().parse_board(fixture("arca_board.html"), 1).items[1]

    with pytest.raises(
        ParseError,
        match="^아카라이브 게시글 정보 구조를 찾을 수 없습니다$",
    ):
        adapter().parse_post(html, post, 1)


def test_arca_comment_preserves_nested_wrapper_depth_beyond_one() -> None:
    html = fixture("arca_post.html").replace(
        '<div class="comment-wrapper reply" data-depth="1">',
        '<div class="comment-wrapper"><div class="comment-wrapper">'
        '<div class="comment-wrapper reply">',
        1,
    ).replace(
        "        </div>\n      </div>\n    </div>\n  </body>",
        "        </div></div></div>\n      </div>\n    </div>\n  </body>",
        1,
    )
    post = adapter().parse_board(fixture("arca_board.html"), 1).items[1]

    _, comments = adapter().parse_post(html, post, 1)

    assert comments.items[1].depth == 2
