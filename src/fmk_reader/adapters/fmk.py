from dataclasses import dataclass
from typing import ClassVar

from fmk_reader.adapters.base import RequestPolicy
from fmk_reader.errors import ParseError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.parser import parse_board, parse_post
from fmk_reader.targets import CommunityTarget, Site


@dataclass(frozen=True, slots=True)
class FmkAdapter:
    target: CommunityTarget

    site_name: ClassVar[str] = "FMKorea"
    policy: ClassVar[RequestPolicy] = RequestPolicy(
        site=Site.FMKOREA,
        user_agent="fmk-reader/0.1 personal read-only client",
        allowed_origins=frozenset({("https", "www.fmkorea.com", 443)}),
        rate_limit_statuses=frozenset({429, 430}),
    )

    def board_url(self, page: int) -> str:
        if page == 1:
            return self.target.board_url
        return (
            "https://www.fmkorea.com/index.php"
            f"?mid={self.target.board_id}&page={page}"
        )

    def post_url(self, post: PostSummary, cpage: int) -> str:
        if cpage == 1:
            return post.url
        return (
            "https://www.fmkorea.com/index.php"
            f"?mid={self.target.board_id}"
            f"&document_srl={post.post_id}&cpage={cpage}"
        )

    def direct_post(self) -> PostSummary | None:
        if self.target.article_id is None or self.target.article_url is None:
            return None
        return PostSummary(
            post_id=self.target.article_id,
            title=f"글 {self.target.article_id}",
            category="",
            author="",
            created_at="",
            views="",
            votes=0,
            comment_count=0,
            url=self.target.article_url,
            is_notice=False,
        )

    def parse_board(self, html: str, page: int) -> PageResult[PostSummary]:
        return parse_board(html, page=page)

    def parse_post(
        self, html: str, post: PostSummary, cpage: int
    ) -> tuple[PostDetail, PageResult[Comment]]:
        detail, comments = parse_post(html, post.url, cpage=cpage)
        if detail.summary.post_id != post.post_id:
            raise ParseError("post id mismatch")
        return detail, comments
