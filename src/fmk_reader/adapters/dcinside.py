from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from fmk_reader.adapters.base import RequestPolicy
from fmk_reader.errors import ParseError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.targets import CommunityTarget, Site


_BASE_URL = "https://m.dcinside.com"
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Mobile) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)


def _normalize_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return " ".join(value.split())


def _first_integer(value: str | Tag | None) -> int:
    match = re.search(r"\d[\d,]*", _normalize_text(value))
    return int(match.group(0).replace(",", "")) if match else 0


def _required(
    root: BeautifulSoup | Tag,
    selector: str,
    message: str,
) -> Tag:
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
        or parsed.hostname != "m.dcinside.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    segments = parsed.path.strip("/").split("/")
    if (
        len(segments) != 3
        or segments[0] != "board"
        or not segments[1]
        or not segments[2].isdecimal()
    ):
        return None
    return segments[1], segments[2]


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
    for image in rendered.select("img"):
        classes = image.get("class", [])
        placeholder = "[디시콘]" if "written_dccon" in classes else "[이미지]"
        image.replace_with(placeholder)
    for video in rendered.select("video, iframe"):
        video.replace_with("[동영상]")

    lines = (
        normalized
        for line in rendered.get_text("\n").splitlines()
        if (normalized := _normalize_text(line))
    )
    return "\n".join(lines), tuple(links)


def _labeled_integer(root: Tag, label: str) -> int:
    for item in root.select("li"):
        text = _normalize_text(item)
        if text.startswith(label):
            return _first_integer(item)
    return 0


def _comment_id(item: Tag) -> str | None:
    number = str(item.get("no", ""))
    if number.isdecimal():
        return number
    match = re.fullmatch(r"comment_cnt_(\d+)", str(item.get("id", "")))
    return match.group(1) if match else None


def _linked_comment_page(
    href: str,
    board_id: str,
    post_id: str,
) -> int | None:
    try:
        parsed = urlsplit(href.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "m.dcinside.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or _article_identity(href) != (board_id, post_id)
    ):
        return None
    values = parse_qs(parsed.query).get("cpage", [])
    if len(values) != 1 or not values[0].isdecimal():
        return None
    return int(values[0])


@dataclass(frozen=True, slots=True)
class DcinsideAdapter:
    target: CommunityTarget

    site_name: ClassVar[str] = "디시인사이드"
    policy: ClassVar[RequestPolicy] = RequestPolicy(
        site=Site.DCINSIDE,
        user_agent=_MOBILE_USER_AGENT,
        allowed_origins=frozenset({("https", "m.dcinside.com", 443)}),
        rate_limit_statuses=frozenset({429}),
        blocked_statuses=frozenset({403}),
        min_interval=2.0,
    )

    def board_url(self, page: int) -> str:
        if page == 1:
            return self.target.board_url
        return f"{self.target.board_url}?page={page}"

    def post_url(self, post: PostSummary, cpage: int) -> str:
        canonical = f"{_BASE_URL}/board/{self.target.board_id}/{post.post_id}"
        if cpage == 1:
            return canonical
        return f"{canonical}?cpage={cpage}"

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
        soup = BeautifulSoup(html, "html.parser")
        container = _required(
            soup,
            "ul.gall-detail-lst",
            "디시인사이드 게시판 목록 구조를 찾을 수 없습니다",
        )
        posts: list[PostSummary] = []
        for row in container.select(".gall-detail-lnktb"):
            parent = row.find_parent("li")
            if isinstance(parent, Tag) and "ad" in parent.get("class", []):
                continue
            anchor = row.select_one("a.lt[href]")
            if not isinstance(anchor, Tag):
                continue
            identity = _article_identity(str(anchor.get("href", "")))
            if identity is None or identity[0] != self.target.board_id:
                continue
            post_id = identity[1]
            title = _normalize_text(row.select_one(".subjectin"))
            if not title:
                continue

            info = row.select("ul.ginfo > li")
            author_node = (
                parent.select_one(".blockInfo[data-name]")
                if isinstance(parent, Tag)
                else None
            )
            author = (
                str(author_node.get("data-name", "")).strip()
                if isinstance(author_node, Tag)
                else ""
            )
            if not author and info:
                author = _normalize_text(info[0])
            created_at = _normalize_text(info[1]) if len(info) > 1 else ""
            category = _normalize_text(row.select_one(".sp-lst"))
            posts.append(
                PostSummary(
                    post_id=post_id,
                    title=title,
                    category=category,
                    author=author,
                    created_at=created_at,
                    views=str(_labeled_integer(row, "조회")),
                    votes=_labeled_integer(row, "추천"),
                    comment_count=_first_integer(row.select_one("a.rt .ct")),
                    url=(f"{_BASE_URL}/board/{self.target.board_id}/{post_id}"),
                    is_notice=(
                        isinstance(parent, Tag) and "notice" in parent.get("class", [])
                    )
                    or category == "공지",
                )
            )

        if not posts:
            raise ParseError("디시인사이드 게시글 목록 구조를 찾을 수 없습니다")
        has_next = any(
            _normalize_text(anchor) == "다음" or "btn-next" in anchor.get("class", [])
            for anchor in soup.select(".paging a[href], a.btn-next[href]")
        )
        return PageResult(
            items=tuple(posts),
            page=page,
            has_previous=page > 1,
            has_next=has_next,
        )

    def parse_post(
        self,
        html: str,
        post: PostSummary,
        cpage: int,
    ) -> tuple[PostDetail, PageResult[Comment]]:
        soup = BeautifulSoup(html, "html.parser")
        identity_meta = soup.select_one('meta[property="og:url"][content]')
        identity = (
            _article_identity(str(identity_meta.get("content", "")))
            if isinstance(identity_meta, Tag)
            else None
        )
        if identity is None:
            raise ParseError("디시인사이드 게시글 정보 구조를 찾을 수 없습니다")
        if identity != (self.target.board_id, post.post_id):
            raise ParseError("디시인사이드 게시글 정보가 요청과 일치하지 않습니다")

        title_node = _required(
            soup,
            ".gallview-tit-box > .tit",
            "디시인사이드 게시글 제목 구조를 찾을 수 없습니다",
        )
        title = _normalize_text(title_node)
        if not title:
            raise ParseError("디시인사이드 게시글 제목 구조를 찾을 수 없습니다")
        body_node = _required(
            soup,
            ".gall-thum-btm .thum-txt .thum-txtin",
            "디시인사이드 게시글 본문 구조를 찾을 수 없습니다",
        )
        body, links = _render_content(body_node)
        if not body:
            raise ParseError("디시인사이드 게시글 본문 구조를 찾을 수 없습니다")

        stats = soup.select_one(".gall-thum-btm-inner > ul.ginfo2")
        views = str(_labeled_integer(stats, "조회수")) if stats else "0"
        votes = _labeled_integer(stats, "추천") if stats else 0
        comment_count = _labeled_integer(stats, "댓글") if stats else 0
        title_box = title_node.find_parent(class_="gallview-tit-box")
        author = _normalize_text(
            title_box.select_one(".ginfo-area .nick")
            if isinstance(title_box, Tag)
            else None
        )
        date_items = (
            title_box.select(".btm .ginfo2 > li") if isinstance(title_box, Tag) else []
        )
        created_at = _normalize_text(date_items[1]) if len(date_items) > 1 else ""
        canonical_url = f"{_BASE_URL}/board/{self.target.board_id}/{post.post_id}"
        summary = PostSummary(
            post_id=post.post_id,
            title=title,
            category=post.category,
            author=author,
            created_at=created_at,
            views=views,
            votes=votes,
            comment_count=comment_count,
            url=canonical_url,
            is_notice=post.is_notice,
        )

        comments: list[Comment] = []
        for item in soup.select(".all-comment .all-comment-lst > li"):
            comment_id = _comment_id(item)
            content_node = item.select_one(":scope > .txt")
            if comment_id is None or not isinstance(content_node, Tag):
                continue
            content, _ = _render_content(content_node)
            if not content:
                continue
            classes = item.get("class", [])
            has_parent = bool(str(item.get("data-parent", "")).strip())
            depth = int("comment-add" in classes or "reply" in classes or has_parent)
            comments.append(
                Comment(
                    comment_id=comment_id,
                    author=_normalize_text(
                        item.select_one(":scope > .ginfo-area .nick")
                    ),
                    content=content,
                    created_at=_normalize_text(item.select_one(":scope > .date")),
                    depth=depth,
                )
            )

        linked_pages = {
            linked_page
            for anchor in soup.select(
                ".all-comment > .comment-paging a[href*='cpage=']"
            )
            if (
                linked_page := _linked_comment_page(
                    str(anchor.get("href", "")),
                    self.target.board_id,
                    post.post_id,
                )
            )
            is not None
        }
        return PostDetail(summary=summary, body=body, links=links), PageResult(
            items=tuple(comments),
            page=cpage,
            has_previous=cpage > 1,
            has_next=any(linked_page > cpage for linked_page in linked_pages),
        )
