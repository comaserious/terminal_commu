from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary


def test_page_result_round_trip() -> None:
    post = PostSummary(
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
