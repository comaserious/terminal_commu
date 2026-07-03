from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar


def _json_object(
    value: Any,
    *,
    name: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a JSON object")

    missing = [field for field in fields if field not in value]
    unexpected = [field for field in value if field not in fields]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ValueError(f"{name} has invalid fields: {'; '.join(details)}")
    return value


def _typed_field(value: dict[str, Any], field: str, expected: type[Any]) -> Any:
    result = value[field]
    if type(result) is not expected:
        raise TypeError(
            f"{field} must be {expected.__name__}, got {type(result).__name__}"
        )
    return result


@dataclass(frozen=True, slots=True)
class PostSummary:
    post_id: str
    title: str
    category: str
    author: str
    created_at: str
    views: str
    votes: int
    comment_count: int
    url: str
    is_notice: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "title": self.title,
            "category": self.category,
            "author": self.author,
            "created_at": self.created_at,
            "views": self.views,
            "votes": self.votes,
            "comment_count": self.comment_count,
            "url": self.url,
            "is_notice": self.is_notice,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostSummary:
        data = _json_object(
            value,
            name="PostSummary",
            fields=(
                "post_id",
                "title",
                "category",
                "author",
                "created_at",
                "views",
                "votes",
                "comment_count",
                "url",
                "is_notice",
            ),
        )
        return cls(
            post_id=_typed_field(data, "post_id", str),
            title=_typed_field(data, "title", str),
            category=_typed_field(data, "category", str),
            author=_typed_field(data, "author", str),
            created_at=_typed_field(data, "created_at", str),
            views=_typed_field(data, "views", str),
            votes=_typed_field(data, "votes", int),
            comment_count=_typed_field(data, "comment_count", int),
            url=_typed_field(data, "url", str),
            is_notice=_typed_field(data, "is_notice", bool),
        )


@dataclass(frozen=True, slots=True)
class PostDetail:
    summary: PostSummary
    body: str
    links: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "body": self.body,
            "links": list(self.links),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostDetail:
        data = _json_object(
            value,
            name="PostDetail",
            fields=("summary", "body", "links"),
        )
        links = _typed_field(data, "links", list)
        for index, link in enumerate(links):
            if type(link) is not str:
                raise TypeError(
                    f"links[{index}] must be str, got {type(link).__name__}"
                )
        return cls(
            summary=PostSummary.from_dict(_typed_field(data, "summary", dict)),
            body=_typed_field(data, "body", str),
            links=tuple(links),
        )


@dataclass(frozen=True, slots=True)
class Comment:
    comment_id: str
    author: str
    content: str
    created_at: str
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "author": self.author,
            "content": self.content,
            "created_at": self.created_at,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Comment:
        data = _json_object(
            value,
            name="Comment",
            fields=("comment_id", "author", "content", "created_at", "depth"),
        )
        return cls(
            comment_id=_typed_field(data, "comment_id", str),
            author=_typed_field(data, "author", str),
            content=_typed_field(data, "content", str),
            created_at=_typed_field(data, "created_at", str),
            depth=_typed_field(data, "depth", int),
        )


T = TypeVar("T", PostSummary, Comment)


def _page_fields(value: Any) -> tuple[list[Any], int, bool, bool]:
    data = _json_object(
        value,
        name="PageResult",
        fields=("items", "page", "has_previous", "has_next"),
    )
    return (
        _typed_field(data, "items", list),
        _typed_field(data, "page", int),
        _typed_field(data, "has_previous", bool),
        _typed_field(data, "has_next", bool),
    )


@dataclass(frozen=True, slots=True)
class PageResult(Generic[T]):
    items: tuple[T, ...]
    page: int
    has_previous: bool
    has_next: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "page": self.page,
            "has_previous": self.has_previous,
            "has_next": self.has_next,
        }

    @classmethod
    def posts_from_dict(cls, value: dict[str, Any]) -> PageResult[PostSummary]:
        items, page, has_previous, has_next = _page_fields(value)
        return cls(
            items=tuple(PostSummary.from_dict(item) for item in items),
            page=page,
            has_previous=has_previous,
            has_next=has_next,
        )

    @classmethod
    def comments_from_dict(cls, value: dict[str, Any]) -> PageResult[Comment]:
        items, page, has_previous, has_next = _page_fields(value)
        return cls(
            items=tuple(Comment.from_dict(item) for item in items),
            page=page,
            has_previous=has_previous,
            has_next=has_next,
        )
