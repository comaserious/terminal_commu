from pathlib import Path

import pytest

from commu.errors import ParseError
from commu.parser import parse_board, parse_post


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_board_extracts_posts_and_paging() -> None:
    result = parse_board(fixture("board.html"), page=1)

    assert [post.post_id for post in result.items] == ["100", "200"]
    assert result.items[0].to_dict() == {
        "post_id": "100",
        "title": "일반 글",
        "category": "토트넘",
        "author": "작성자",
        "created_at": "16:45",
        "views": "20",
        "votes": 3,
        "comment_count": 2,
        "url": "https://www.fmkorea.com/100",
        "is_notice": False,
    }
    assert result.items[1].to_dict() == {
        "post_id": "200",
        "title": "공지 글",
        "category": "공지",
        "author": "운영진",
        "created_at": "01.05",
        "views": "3백만",
        "votes": 0,
        "comment_count": 0,
        "url": "https://www.fmkorea.com/200",
        "is_notice": True,
    }
    assert result.page == 1
    assert result.has_previous is False
    assert result.has_next is True


def test_parse_board_accepts_only_supported_document_links() -> None:
    html = """
    <table class="bd_lst"><tbody>
      <tr><td class="title"><a href="/index.php?mid=football_world&amp;document_srl=300">query</a></td></tr>
      <tr><td class="title"><a href="https://evil.example/301">external</a></td></tr>
      <tr><td class="title"><a href="/index.php?mid=football_world&amp;document_srl=abc">nonnumeric</a></td></tr>
      <tr><td class="title"><a href="/index.php?mid=baseball&amp;document_srl=302">wrong mid</a></td></tr>
    </tbody></table>
    """

    result = parse_board(html, page=2)

    assert [post.post_id for post in result.items] == ["300"]
    assert result.items[0].url == "https://www.fmkorea.com/300"
    assert result.has_previous is True


def test_parse_board_defaults_missing_views_to_zero() -> None:
    html = """
    <table class="bd_lst"><tbody><tr>
      <td class="title"><a href="/400">no views</a></td>
      <td class="m_no m_no_voted">5</td>
    </tr></tbody></table>
    """

    result = parse_board(html, page=1)

    assert result.items[0].views == "0"
    assert result.items[0].votes == 5


def test_parse_board_skips_rows_with_empty_titles() -> None:
    html = """
    <table class="bd_lst"><tbody>
      <tr><td class="title"><a href="/500"><span> </span></a></td></tr>
      <tr><td class="title"><a href="/501">valid title</a></td></tr>
    </tbody></table>
    """

    result = parse_board(html, page=1)

    assert [post.post_id for post in result.items] == ["501"]


def test_parse_board_rejects_table_with_only_empty_titles() -> None:
    html = """
    <table class="bd_lst"><tbody>
      <tr><td class="title"><a href="/500"> </a></td></tr>
      <tr><td class="title"><a href="/best/501"><span></span></a></td></tr>
    </tbody></table>
    """

    with pytest.raises(ParseError, match="^missing board rows$"):
        parse_board(html, page=1)


def test_parse_post_extracts_body_links_comments_and_paging() -> None:
    detail, comments = parse_post(
        fixture("post.html"),
        "https://www.fmkorea.com/100",
        cpage=1,
    )

    assert detail.summary.to_dict() == {
        "post_id": "100",
        "title": "일반 글",
        "category": "토트넘",
        "author": "작성자",
        "created_at": "2026.01.05 16:45",
        "views": "20",
        "votes": 3,
        "comment_count": 2,
        "url": "https://www.fmkorea.com/100",
        "is_notice": False,
    }
    assert "[이미지 생략]" in detail.body
    assert "[동영상 생략]" in detail.body
    assert "지연 로딩 문구" not in detail.body
    assert detail.links == (
        "https://example.com/news",
        "https://example.com/other",
    )
    assert [comment.to_dict() for comment in comments.items] == [
        {
            "comment_id": "10",
            "author": "댓글러",
            "content": "첫 댓글",
            "created_at": "1 분 전",
            "depth": 0,
        },
        {
            "comment_id": "11",
            "author": "답글러",
            "content": "답글\n[이미지 생략]\n[동영상 생략]",
            "created_at": "방금",
            "depth": 2,
        },
    ]
    assert comments.page == 1
    assert comments.has_previous is False
    assert comments.has_next is True


def test_parse_post_normalizes_links_and_removes_lazy_content() -> None:
    detail, _ = parse_post(
        fixture("post.html"),
        "https://www.fmkorea.com/100",
        cpage=1,
    )

    assert "지연 로딩 문구" not in detail.body
    assert detail.links == (
        "https://example.com/news",
        "https://example.com/other",
    )


def test_parse_post_skips_malformed_comments_and_preserves_media() -> None:
    _, comments = parse_post(
        fixture("post.html"),
        "https://www.fmkorea.com/100",
        cpage=1,
    )

    assert [comment.comment_id for comment in comments.items] == ["10", "11"]
    assert comments.items[1].content == "답글\n[이미지 생략]\n[동영상 생략]"


def test_parse_post_keeps_comment_with_optional_author_and_date() -> None:
    html = """
    <div class="rd" data-docSrl="100">
      <div class="rd_hd"><span class="np_18px_span">제목</span></div>
      <div class="rd_body"><article><div class="xe_content">본문</div></article></div>
    </div>
    <div class="fdb_lst"><ul class="fdb_lst_ul">
      <li class="fdb_itm" id="comment_13">
        <div class="comment-content"><div class="xe_content">메타 없음</div></div>
      </li>
    </ul></div>
    """

    _, comments = parse_post(html, "https://www.fmkorea.com/100", cpage=1)

    assert comments.items[0].author == ""
    assert comments.items[0].created_at == ""
    assert comments.items[0].content == "메타 없음"


def test_parse_post_comment_page_has_previous() -> None:
    _, comments = parse_post(
        fixture("post.html"),
        "https://www.fmkorea.com/100",
        cpage=2,
    )

    assert comments.page == 2
    assert comments.has_previous is True
    assert comments.has_next is False


def test_parse_post_requires_post_root() -> None:
    with pytest.raises(ParseError, match="^missing post root$"):
        parse_post("<html></html>", "https://www.fmkorea.com/100", cpage=1)


def test_parse_post_requires_post_title() -> None:
    html = """
    <div class="rd" data-docSrl="100">
      <div class="rd_body"><article><div class="xe_content">본문</div></article></div>
    </div>
    """

    with pytest.raises(ParseError, match="^missing post title$"):
        parse_post(html, "https://www.fmkorea.com/100", cpage=1)


def test_parse_post_requires_nonempty_post_body() -> None:
    html = """
    <div class="rd" data-docSrl="100">
      <div class="rd_hd"><span class="np_18px_span">제목</span></div>
      <div class="rd_body"><article><div class="xe_content"> </div></article></div>
    </div>
    """

    with pytest.raises(ParseError, match="^missing post body$"):
        parse_post(html, "https://www.fmkorea.com/100", cpage=1)


@pytest.mark.parametrize("post_id", ["", "not-a-number"])
def test_parse_post_requires_numeric_post_id(post_id: str) -> None:
    html = f"""
    <div class="rd" data-docSrl="{post_id}">
      <div class="rd_hd"><span class="np_18px_span">제목</span></div>
      <div class="rd_body"><article><div class="xe_content">본문</div></article></div>
    </div>
    """

    with pytest.raises(ParseError, match="^invalid post id$"):
        parse_post(html, "https://www.fmkorea.com/100", cpage=1)
