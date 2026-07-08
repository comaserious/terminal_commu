from dataclasses import dataclass
from typing import Protocol

from commu.models import Comment, PageResult, PostDetail, PostSummary
from commu.targets import CommunityTarget, Site


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    site: Site
    user_agent: str
    allowed_origins: frozenset[tuple[str, str, int]]
    rate_limit_statuses: frozenset[int]
    blocked_statuses: frozenset[int] = frozenset({403})
    min_interval: float = 2.0


class CommunityAdapter(Protocol):
    target: CommunityTarget
    policy: RequestPolicy
    site_name: str

    def board_url(self, page: int) -> str: ...

    def post_url(self, post: PostSummary, cpage: int) -> str: ...

    def direct_post(self) -> PostSummary | None: ...

    def parse_board(self, html: str, page: int) -> PageResult[PostSummary]: ...

    def parse_post(
        self, html: str, post: PostSummary, cpage: int
    ) -> tuple[PostDetail, PageResult[Comment]]: ...
