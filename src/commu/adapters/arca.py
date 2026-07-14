from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from commu.adapters.base import PagePolicy, RequestPolicy
from commu.errors import ParseError
from commu.models import Comment, PageResult, PostDetail, PostSummary
from commu.targets import CommunityTarget, Site


_BASE_URL = "https://arca.live"

def _normalize_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return " ".join(value.split())


def _first_integer(value: str | Tag | None) -> int:
    match = re.search(r"\d[\d,]*", _normalize_text(value))
    return int(match.group(0).replace(",", "")) if match else 0


def _required(root: BeautifulSoup | Tag, selector: str, message: str) -> Tag:
    element = root.select_one(selector)
    if not isinstance(element, Tag):
        raise ParseError(message)
    return element


def _article_identity(href: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(urljoin(_BASE_URL, href.strip()))
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "arca.live"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    segments = parsed.path.strip("/").split("/")
    if (
        len(segments) != 3
        or segments[0] != "b"
        or not segments[1]
        or not segments[2].isdecimal()
    ):
        return None
    return segments[1], segments[2]


def _canonical_article_url(board_id: str, post_id: str) -> str:
    return f"{_BASE_URL}/b/{board_id}/{post_id}"


def _render_content(content: Tag) -> tuple[str, tuple[str, ...]]:
    rendered = BeautifulSoup(str(content), "html.parser")
    links: list[str] = []
    for anchor in rendered.select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        parsed = urlsplit(href)
        if parsed.scheme in {"http", "https"} and parsed.netloc and href not in links:
            links.append(href)

    for line_break in rendered.select("br"):
        line_break.replace_with("\n")
    for media in rendered.select("img, video, iframe"):
        classes = media.get("class", [])
        if "arca-emoticon" in classes:
            placeholder = "[이모티콘]"
        elif media.name == "img":
            placeholder = "[이미지]"
        else:
            placeholder = "[동영상]"
        media.replace_with(placeholder)

    lines = (
        normalized
        for line in rendered.get_text("\n").splitlines()
        if (normalized := _normalize_text(line))
    )
    return "\n".join(lines), tuple(links)


def _row_title(row: Tag) -> str:
    title = row.select_one(".col-title .title")
    if not isinstance(title, Tag):
        title = row.select_one(".col-title b")
    return _normalize_text(title)


def _author(root: Tag) -> str:
    node = root.select_one(".user-info [data-filter]")
    if not isinstance(node, Tag):
        return _normalize_text(root.select_one(".user-info"))
    return _normalize_text(str(node.get("data-filter", ""))) or _normalize_text(node)


def _article_title(head: Tag) -> str:
    node = head.select_one(".title-row .title")
    if not isinstance(node, Tag):
        return ""
    rendered = BeautifulSoup(str(node), "html.parser")
    for badge in rendered.select(".category-badge"):
        badge.decompose()
    return _normalize_text(rendered)


def _labeled_value(root: Tag, label: str) -> str:
    for head in root.select(".head"):
        if _normalize_text(head) != label:
            continue
        sibling = head.find_next_sibling()
        if isinstance(sibling, Tag) and "body" in sibling.get("class", []):
            return _normalize_text(sibling)
    return ""


def _comment_depth(item: Tag) -> int:
    wrapper = item.find_parent(class_="comment-wrapper")
    if not isinstance(wrapper, Tag):
        return 0
    raw_depth = str(item.get("data-depth", wrapper.get("data-depth", "")))
    if raw_depth.isdecimal():
        return int(raw_depth)
    nested_depth = len(wrapper.find_parents(class_="comment-wrapper"))
    if nested_depth:
        return nested_depth
    classes = set(item.get("class", [])) | set(wrapper.get("class", []))
    if classes.intersection({"reply", "comment-reply", "child"}):
        return 1
    return 0


def _linked_board_page(href: str, board_id: str) -> int | None:
    try:
        parsed = urlsplit(urljoin(_BASE_URL, href.strip()))
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "arca.live"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/b/{board_id}"
    ):
        return None
    values = parse_qs(parsed.query).get("p", [])
    if len(values) != 1 or not values[0].isdecimal():
        return None
    return int(values[0])


@dataclass(frozen=True, slots=True)
class ArcaAdapter:
    target: CommunityTarget

    site_name: ClassVar[str] = "아카라이브"
    policy: ClassVar[RequestPolicy] = RequestPolicy(
        site=Site.ARCA,
        user_agent="commu/0.1 personal read-only client",
        allowed_origins=frozenset({("https", "arca.live", 443)}),
        rate_limit_statuses=frozenset({429}),
        blocked_statuses=frozenset({403}),
        min_interval=2.0,
        page_policy=PagePolicy(
            board_selector=".article-list",
            post_selector=".article-content",
            challenge_selectors=(
                "#challenge-form",
                "iframe[src*='turnstile']",
            ),
        ),
    )
    def board_url(self, page: int) -> str:
        if page == 1:
            return self.target.board_url
        return f"{self.target.board_url}?p={page}"

    def post_url(self, post: PostSummary, cpage: int) -> str:
        return _canonical_article_url(self.target.board_id, post.post_id)

    def direct_post(self) -> PostSummary | None:
        if self.target.article_id is None:
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
            url=_canonical_article_url(self.target.board_id, self.target.article_id),
            is_notice=False,
        )

    def parse_board(self, html: str, page: int) -> PageResult[PostSummary]:
        soup = BeautifulSoup(html, "html.parser")
        container = _required(
            soup,
            ".article-list",
            "아카라이브 게시판 목록 구조를 찾을 수 없습니다",
        )
        posts: list[PostSummary] = []
        for row in container.select(".vrow[href]"):
            identity = _article_identity(str(row.get("href", "")))
            if identity is None or identity[0] != self.target.board_id:
                continue
            title = _row_title(row)
            if not title:
                continue
            board_id, post_id = identity
            posts.append(
                PostSummary(
                    post_id=post_id,
                    title=title,
                    category=_normalize_text(
                        row.select_one(".col-title .badges .badge")
                    ),
                    author=_author(row),
                    created_at=_normalize_text(row.select_one(".col-time time")),
                    views=str(_first_integer(row.select_one(".col-view"))),
                    votes=_first_integer(row.select_one(".col-rate")),
                    comment_count=_first_integer(row.select_one(".col-title .info")),
                    url=_canonical_article_url(board_id, post_id),
                    is_notice="notice" in row.get("class", []),
                )
            )

        if not posts:
            raise ParseError("아카라이브 게시글 목록 구조를 찾을 수 없습니다")
        linked_pages = {
            linked_page
            for anchor in soup.select(".pagination-wrapper .page-link[href]")
            if (
                linked_page := _linked_board_page(
                    str(anchor.get("href", "")), self.target.board_id
                )
            )
            is not None
        }
        return PageResult(
            items=tuple(posts),
            page=page,
            has_previous=page > 1,
            has_next=any(linked_page > page for linked_page in linked_pages),
        )

    def parse_post(
        self,
        html: str,
        post: PostSummary,
        cpage: int,
    ) -> tuple[PostDetail, PageResult[Comment]]:
        soup = BeautifulSoup(html, "html.parser")
        identity_link = soup.select_one(".article-link a[href]")
        identity = (
            _article_identity(str(identity_link.get("href", "")))
            if isinstance(identity_link, Tag)
            else None
        )
        if identity is None:
            raise ParseError("아카라이브 게시글 정보 구조를 찾을 수 없습니다")
        if identity != (self.target.board_id, post.post_id):
            raise ParseError("아카라이브 게시글 정보가 요청과 일치하지 않습니다")

        head = _required(
            soup,
            ".article-head",
            "아카라이브 게시글 제목 구조를 찾을 수 없습니다",
        )
        title = _article_title(head)
        if not title:
            raise ParseError("아카라이브 게시글 제목 구조를 찾을 수 없습니다")
        body_node = _required(
            soup,
            ".article-content",
            "아카라이브 게시글 본문 구조를 찾을 수 없습니다",
        )
        body, links = _render_content(body_node)
        if not body:
            raise ParseError("아카라이브 게시글 본문 구조를 찾을 수 없습니다")

        info = head.select_one(".article-info")
        views = _labeled_value(info, "조회수") if isinstance(info, Tag) else ""
        votes = _first_integer(_labeled_value(info, "추천")) if isinstance(info, Tag) else 0
        comment_count = (
            _first_integer(info.select_one(".comment-count"))
            if isinstance(info, Tag)
            else 0
        )
        summary = PostSummary(
            post_id=post.post_id,
            title=title,
            category=_normalize_text(head.select_one(".category-badge")),
            author=_author(head),
            created_at=_normalize_text(head.select_one(".article-info time")),
            views=views,
            votes=votes,
            comment_count=comment_count,
            url=_canonical_article_url(self.target.board_id, post.post_id),
            is_notice=post.is_notice,
        )

        comments: list[Comment] = []
        for item in soup.select(".comment-wrapper .comment-item"):
            match = re.fullmatch(r"c_(\d+)", str(item.get("id", "")))
            content_node = item.select_one(".message .text")
            if match is None or not isinstance(content_node, Tag):
                continue
            content, _ = _render_content(content_node)
            if not content:
                continue
            comments.append(
                Comment(
                    comment_id=match.group(1),
                    author=_author(item),
                    content=content,
                    created_at=_normalize_text(item.select_one(".info-row time")),
                    depth=_comment_depth(item),
                )
            )

        return PostDetail(summary=summary, body=body, links=links), PageResult(
            items=tuple(comments),
            page=cpage,
            has_previous=cpage > 1,
            has_next=False,
        )
