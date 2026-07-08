from pathlib import Path

import pytest

from commu.adapters import adapter_for
from commu.adapters.arca import ArcaAdapter
from commu.adapters.fmk import FmkAdapter
from commu.errors import ParseError
from commu.models import PostSummary
from commu.targets import route_url


FIXTURES = Path(__file__).parent / "fixtures"


def test_adapter_for_returns_fmk_adapter() -> None:
    target = route_url("https://www.fmkorea.com/football_world")

    adapter = adapter_for(target)

    assert isinstance(adapter, FmkAdapter)
    assert adapter.site_name == "FMKorea"
    assert adapter.policy.rate_limit_statuses == frozenset({429, 430})


def test_adapter_for_returns_arca_adapter() -> None:
    arca = route_url("https://arca.live/b/rogersfu")

    assert isinstance(adapter_for(arca), ArcaAdapter)


def test_fmk_adapter_preserves_existing_parser_behavior() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))
    board = adapter.parse_board(
        (FIXTURES / "board.html").read_text(encoding="utf-8"), page=1
    )
    post = board.items[0]

    detail, comments = adapter.parse_post(
        (FIXTURES / "post.html").read_text(encoding="utf-8"), post, cpage=1
    )

    assert detail.summary.post_id == post.post_id
    assert comments.page == 1


def test_fmk_adapter_preserves_board_and_comment_page_urls() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))
    post = _post("100")

    assert adapter.board_url(1) == "https://www.fmkorea.com/football_world"
    assert adapter.board_url(2) == (
        "https://www.fmkorea.com/index.php?mid=football_world&page=2"
    )
    assert adapter.post_url(post, 1) == post.url
    assert adapter.post_url(post, 2) == (
        "https://www.fmkorea.com/index.php"
        "?mid=football_world&document_srl=100&cpage=2"
    )


def test_fmk_adapter_exposes_strict_request_policy() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))

    assert adapter.policy.user_agent == (
        "fmk-reader/0.1 personal read-only client"
    )
    assert adapter.policy.allowed_origins == frozenset(
        {("https", "www.fmkorea.com", 443)}
    )
    assert adapter.policy.blocked_statuses == frozenset({403})
    assert adapter.policy.min_interval == 2.0


def test_fmk_adapter_creates_direct_article_summary() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/123"))

    post = adapter.direct_post()

    assert post == PostSummary(
        post_id="123",
        title="글 123",
        category="",
        author="",
        created_at="",
        views="",
        votes=0,
        comment_count=0,
        url="https://www.fmkorea.com/123",
        is_notice=False,
    )


def test_fmk_adapter_has_no_direct_post_for_board_target() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))

    assert adapter.direct_post() is None


def test_fmk_adapter_rejects_mismatched_parsed_article_id() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))

    with pytest.raises(ParseError, match="^FMKorea: post id mismatch$"):
        adapter.parse_post(
            (FIXTURES / "post.html").read_text(encoding="utf-8"),
            _post("999"),
            cpage=1,
        )


def test_fmk_adapter_rejects_board_html_from_another_board() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))
    html = (FIXTURES / "board.html").read_text(encoding="utf-8").replace(
        "https://www.fmkorea.com/football_world",
        "https://www.fmkorea.com/baseball",
        1,
    )

    with pytest.raises(
        ParseError,
        match="^FMKorea: returned board 'baseball' does not match 'football_world'$",
    ):
        adapter.parse_board(html, page=1)


def test_fmk_adapter_rejects_direct_article_html_from_another_board() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/100"))
    post = adapter.direct_post()
    assert post is not None
    html = (FIXTURES / "post.html").read_text(encoding="utf-8").replace(
        "mid=football_world",
        "mid=baseball",
        1,
    )

    with pytest.raises(
        ParseError,
        match="^FMKorea: returned board 'baseball' does not match 'football_world'$",
    ):
        adapter.parse_post(html, post, cpage=1)


def test_fmk_adapter_requires_a_trustworthy_board_marker() -> None:
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/100"))
    post = adapter.direct_post()
    assert post is not None
    html = (FIXTURES / "post.html").read_text(encoding="utf-8").replace(
        "/index.php?mid=football_world&amp;category=1798914341",
        "#",
        1,
    )

    with pytest.raises(
        ParseError,
        match="^FMKorea: returned page has no trustworthy board identity$",
    ):
        adapter.parse_post(html, post, cpage=1)


def _post(post_id: str) -> PostSummary:
    return PostSummary(
        post_id=post_id,
        title="title",
        category="",
        author="",
        created_at="",
        views="0",
        votes=0,
        comment_count=0,
        url=f"https://www.fmkorea.com/{post_id}",
        is_notice=False,
    )
