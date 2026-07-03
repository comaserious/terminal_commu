from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary


def make_post() -> PostSummary:
    return PostSummary(
        post_id="123",
        title="테스트 글",
        category="토트넘",
        author="작성자",
        created_at="16:45",
        views="20",
        votes=3,
        comment_count=1,
        url="https://www.fmkorea.com/123",
        is_notice=False,
    )


def test_page_result_round_trip() -> None:
    post = make_post()
    page = PageResult(items=(post,), page=1, has_previous=False, has_next=True)
    assert PageResult.posts_from_dict(page.to_dict()) == page


def test_post_detail_and_comment_are_immutable() -> None:
    detail = PostDetail(
        summary=PostSummary("1", "제목", "맨유", "닉", "16:00", "2", 1, 1, "https://www.fmkorea.com/1", False),
        body="본문\n[이미지 생략]",
        links=("https://example.com",),
    )
    comment = Comment("9", "댓글러", "내용", "1 분 전", 2)
    assert detail.body.endswith("[이미지 생략]")
    assert comment.depth == 2


@pytest.mark.parametrize(
    ("model", "field", "replacement"),
    [
        (make_post(), "title", "변경"),
        (PostDetail(make_post(), "본문", ()), "body", "변경"),
        (Comment("9", "댓글러", "내용", "1 분 전", 2), "content", "변경"),
        (PageResult((make_post(),), 1, False, True), "page", 2),
    ],
)
def test_models_are_immutable(model: Any, field: str, replacement: Any) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, replacement)


def test_post_detail_round_trip_has_exact_json_shape() -> None:
    post = make_post()
    detail = PostDetail(post, "본문\n[이미지 생략]", ("https://example.com",))

    value = detail.to_dict()

    assert value == {
        "summary": post.to_dict(),
        "body": "본문\n[이미지 생략]",
        "links": ["https://example.com"],
    }
    assert PostDetail.from_dict(value) == detail


def test_comment_page_round_trip() -> None:
    comment = Comment("9", "댓글러", "내용", "1 분 전", 2)
    page = PageResult((comment,), 2, True, False)

    assert PageResult.comments_from_dict(page.to_dict()) == page


def test_comment_round_trip_has_exact_json_shape() -> None:
    comment = Comment("9", "댓글러", "내용", "1 분 전", 2)

    value = comment.to_dict()

    assert value == {
        "comment_id": "9",
        "author": "댓글러",
        "content": "내용",
        "created_at": "1 분 전",
        "depth": 2,
    }
    assert Comment.from_dict(value) == comment


def test_post_detail_rejects_string_links() -> None:
    value = {
        "summary": make_post().to_dict(),
        "body": "본문",
        "links": "https://example.com",
    }

    with pytest.raises(TypeError, match="links"):
        PostDetail.from_dict(value)


def test_page_result_rejects_non_list_items() -> None:
    value = {
        "items": {},
        "page": 1,
        "has_previous": False,
        "has_next": True,
    }

    with pytest.raises(TypeError, match="items"):
        PageResult.posts_from_dict(value)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("votes", True),
        ("is_notice", 0),
    ],
)
def test_post_summary_rejects_wrong_scalar_types(field: str, invalid_value: Any) -> None:
    value = make_post().to_dict()
    value[field] = invalid_value

    with pytest.raises(TypeError, match=field):
        PostSummary.from_dict(value)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("page", True),
        ("has_next", 1),
    ],
)
def test_page_result_rejects_wrong_scalar_types(field: str, invalid_value: Any) -> None:
    value = PageResult((make_post(),), 1, False, True).to_dict()
    value[field] = invalid_value

    with pytest.raises(TypeError, match=field):
        PageResult.posts_from_dict(value)
