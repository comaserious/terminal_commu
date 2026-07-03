from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Generic, TypeVar


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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostSummary:
        return cls(**value)


@dataclass(frozen=True, slots=True)
class PostDetail:
    summary: PostSummary
    body: str
    links: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": asdict(self.summary),
            "body": self.body,
            "links": list(self.links),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostDetail:
        return cls(
            PostSummary.from_dict(value["summary"]),
            value["body"],
            tuple(value["links"]),
        )


@dataclass(frozen=True, slots=True)
class Comment:
    comment_id: str
    author: str
    content: str
    created_at: str
    depth: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Comment:
        return cls(**value)


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageResult(Generic[T]):
    items: tuple[T, ...]
    page: int
    has_previous: bool
    has_next: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [asdict(item) for item in self.items],
            "page": self.page,
            "has_previous": self.has_previous,
            "has_next": self.has_next,
        }

    @classmethod
    def posts_from_dict(cls, value: dict[str, Any]) -> PageResult[PostSummary]:
        return cls(
            tuple(PostSummary.from_dict(item) for item in value["items"]),
            value["page"],
            value["has_previous"],
            value["has_next"],
        )

    @classmethod
    def comments_from_dict(cls, value: dict[str, Any]) -> PageResult[Comment]:
        return cls(
            tuple(Comment.from_dict(item) for item in value["items"]),
            value["page"],
            value["has_previous"],
            value["has_next"],
        )
