from pathlib import Path

import pytest

from fmk_reader.errors import ParseError
from fmk_reader.parser import parse_board, parse_post


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_board_extracts_posts_and_paging() -> None:
    result = parse_board(fixture("board.html"), page=1)

    assert [post.post_id for post in result.items] == ["100", "200"]
    assert result.items[0].comment_count == 2
    assert result.items[1].is_notice is True
    assert result.has_next is True


def test_parse_post_extracts_body_links_comments_and_paging() -> None:
    detail, comments = parse_post(
        fixture("post.html"),
        "https://www.fmkorea.com/100",
        cpage=1,
    )

    assert detail.summary.title == "일반 글"
    assert "[이미지 생략]" in detail.body
    assert "[동영상 생략]" in detail.body
    assert detail.links == ("https://example.com/news",)
    assert [comment.depth for comment in comments.items] == [0, 2]
    assert comments.has_next is True


def test_parse_post_requires_post_title() -> None:
    with pytest.raises(ParseError, match="post title"):
        parse_post("<html></html>", "https://www.fmkorea.com/100", cpage=1)
