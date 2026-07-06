from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from fmk_reader.cache import JsonCache
from fmk_reader.errors import FetchError, ParseError, RateLimited
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.parser import parse_board, parse_post


BOARD_URL = "https://www.fmkorea.com/football_world"
BOARD_TTL = 60.0
POST_TTL = 1800.0
COMMENTS_TTL = 120.0


class TextClient(Protocol):
    async def get_text(self, url: str) -> str: ...


class DataSource(Enum):
    NETWORK = "network"
    CACHE = "cache"
    STALE_CACHE = "stale-cache"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LoadResult(Generic[T]):
    value: T
    source: DataSource
    warning: str = ""


@dataclass(frozen=True, slots=True)
class PostPage:
    detail: PostDetail
    comments: PageResult[Comment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail.to_dict(),
            "comments": self.comments.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostPage:
        if not isinstance(value, dict):
            raise TypeError("PostPage must be a JSON object")
        expected_fields = {"detail", "comments"}
        if set(value) != expected_fields:
            missing = expected_fields - set(value)
            unexpected = set(value) - expected_fields
            details = []
            if missing:
                details.append(f"missing {', '.join(sorted(missing))}")
            if unexpected:
                details.append(f"unexpected {', '.join(sorted(unexpected))}")
            raise ValueError(
                f"PostPage has invalid fields: {'; '.join(details)}"
            )

        detail = value["detail"]
        comments = value["comments"]
        if not isinstance(detail, dict):
            raise TypeError("detail must be dict")
        if not isinstance(comments, dict):
            raise TypeError("comments must be dict")
        return cls(
            detail=PostDetail.from_dict(detail),
            comments=PageResult.comments_from_dict(comments),
        )


class BoardService:
    def __init__(self, client: TextClient, cache: JsonCache) -> None:
        self._client = client
        self._cache = cache

    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        key = f"board:{page}"
        if not refresh:
            cached = self._cached_board(key, allow_stale=False)
            if cached is not None:
                return LoadResult(value=cached, source=DataSource.CACHE)

        url = (
            BOARD_URL
            if page == 1
            else "https://www.fmkorea.com/index.php"
            f"?mid=football_world&page={page}"
        )
        try:
            html = await self._client.get_text(url)
            board = parse_board(html, page=page)
        except FetchError as exc:
            stale = self._cached_board(key, allow_stale=True)
            if stale is None:
                raise
            return LoadResult(
                value=stale,
                source=DataSource.STALE_CACHE,
                warning=_stale_warning(exc, "게시판"),
            )

        self._cache.put(key, board.to_dict())
        return LoadResult(value=board, source=DataSource.NETWORK)

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]:
        combined_key = f"post:{post.post_id}:comments:{cpage}"
        body_key = f"post:{post.post_id}:body"
        if not refresh:
            cached = self._cached_post_page(combined_key, allow_stale=False)
            if cached is not None:
                return LoadResult(value=cached, source=DataSource.CACHE)

        url = (
            post.url
            if cpage == 1
            else "https://www.fmkorea.com/index.php"
            f"?mid=football_world&document_srl={post.post_id}&cpage={cpage}"
        )
        try:
            html = await self._client.get_text(url)
            detail, comments = parse_post(html, post.url, cpage=cpage)
            if detail.summary.post_id != post.post_id:
                raise ParseError("post id mismatch")
        except FetchError as exc:
            stale_page = self._cached_post_page(
                combined_key, allow_stale=True
            )
            if stale_page is not None:
                return LoadResult(
                    value=stale_page,
                    source=DataSource.STALE_CACHE,
                    warning=_stale_warning(exc, "게시글과 댓글"),
                )

            stale_body = self._cached_post_body(body_key)
            if stale_body is None:
                raise
            empty_comments = PageResult[Comment](
                items=(),
                page=cpage,
                has_previous=cpage > 1,
                has_next=False,
            )
            return LoadResult(
                value=PostPage(detail=stale_body, comments=empty_comments),
                source=DataSource.STALE_CACHE,
                warning=_stale_warning(exc, "게시글 본문"),
            )

        result = PostPage(detail=detail, comments=comments)
        self._cache.put(combined_key, result.to_dict())
        self._cache.put(body_key, detail.to_dict())
        return LoadResult(value=result, source=DataSource.NETWORK)

    def _cached_board(
        self, key: str, *, allow_stale: bool
    ) -> PageResult[PostSummary] | None:
        hit = self._cache.get(key, BOARD_TTL, allow_stale=allow_stale)
        if hit is None:
            return None
        try:
            return PageResult.posts_from_dict(hit.value)
        except (TypeError, ValueError):
            return None

    def _cached_post_page(
        self, key: str, *, allow_stale: bool
    ) -> PostPage | None:
        hit = self._cache.get(key, COMMENTS_TTL, allow_stale=allow_stale)
        if hit is None:
            return None
        try:
            return PostPage.from_dict(hit.value)
        except (TypeError, ValueError):
            return None

    def _cached_post_body(self, key: str) -> PostDetail | None:
        hit = self._cache.get(key, POST_TTL, allow_stale=True)
        if hit is None:
            return None
        try:
            return PostDetail.from_dict(hit.value)
        except (TypeError, ValueError):
            return None


def _stale_warning(error: FetchError, subject: str) -> str:
    if isinstance(error, RateLimited) and error.retry_after is not None:
        return (
            "요청 제한으로 "
            f"{subject}의 저장된 내용을 표시합니다 "
            f"(Retry-After: {error.retry_after})."
        )
    return f"네트워크 오류로 {subject}의 저장된 내용을 표시합니다."
