from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from fmk_reader.errors import ParseError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary


BASE_URL = "https://www.fmkorea.com"
_DOCUMENT_PATH = re.compile(r"/(?:best/)?(\d+)")


def _normalize_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return " ".join(value.split())


def _first_integer(value: str | Tag | None) -> int:
    match = re.search(r"\d[\d,]*", _normalize_text(value))
    return int(match.group(0).replace(",", "")) if match else 0


def _require(root: Tag | BeautifulSoup, selector: str, name: str) -> Tag:
    element = root.select_one(selector)
    if not isinstance(element, Tag):
        raise ParseError(f"missing {name}")
    return element


def parse_board(html: str, page: int) -> PageResult[PostSummary]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[PostSummary] = []

    for row in soup.select("table.bd_lst tbody > tr"):
        title_anchor = row.select_one("td.title > a[href]")
        if not isinstance(title_anchor, Tag):
            continue

        href = str(title_anchor.get("href", ""))
        path_match = _DOCUMENT_PATH.fullmatch(href)
        if path_match is None:
            continue

        numeric_cells = row.select("td.m_no")
        views = _normalize_text(numeric_cells[0]) if numeric_cells else ""
        votes = _first_integer(numeric_cells[1]) if len(numeric_cells) > 1 else 0
        reply_count = _first_integer(row.select_one("td.title .replyNum"))
        author = row.select_one("td.author .member_plate") or row.select_one(
            "td.author"
        )

        posts.append(
            PostSummary(
                post_id=path_match.group(1),
                title=_normalize_text(title_anchor),
                category=_normalize_text(row.select_one("td.cate")),
                author=_normalize_text(author),
                created_at=_normalize_text(row.select_one("td.time")),
                views=views,
                votes=votes,
                comment_count=reply_count,
                url=urljoin(BASE_URL, href),
                is_notice="notice" in row.get("class", []),
            )
        )

    if not posts:
        raise ParseError("missing board rows")

    has_next = any(
        "다음" in _normalize_text(anchor)
        for anchor in soup.select("form.bd_pg a.direction[href]")
    )
    return PageResult(
        items=tuple(posts),
        page=page,
        has_previous=page > 1,
        has_next=has_next,
    )


def _render_content(content: Tag) -> tuple[str, tuple[str, ...]]:
    rendered = BeautifulSoup(str(content), "html.parser")

    for lazy in rendered.select("div[id^='pi__']"):
        lazy.decompose()

    links: list[str] = []
    for anchor in rendered.select("a[href]"):
        href = str(anchor.get("href", ""))
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and parsed.netloc and href not in links:
            links.append(href)

    for line_break in rendered.select("br"):
        line_break.replace_with("\n")
    for image in rendered.select("img"):
        image.replace_with("[이미지 생략]")
    for video in rendered.select("video, iframe"):
        video.replace_with("[동영상 생략]")

    lines = (
        normalized
        for line in rendered.get_text("\n").splitlines()
        if (normalized := _normalize_text(line))
    )
    return "\n".join(lines), tuple(links)


def _comment_page(href: str) -> int | None:
    values = parse_qs(urlparse(href).query).get("cpage")
    if not values or not values[0].isdigit():
        return None
    return int(values[0])


def parse_post(
    html: str,
    url: str,
    cpage: int,
) -> tuple[PostDetail, PageResult[Comment]]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".rd[data-docsrl]")
    if not isinstance(root, Tag):
        raise ParseError("missing post title or root")

    title = _require(root, ".rd_hd .np_18px_span", "post title")
    body = _require(root, ".rd_body article .xe_content", "post body")
    rendered_body, links = _render_content(body)
    stats = root.select(".rd_hd .btm_area .side.fr b")

    summary = PostSummary(
        post_id=str(root.get("data-docsrl", "")),
        title=_normalize_text(title),
        category=_normalize_text(soup.select_one(".tl_srch a.category")),
        author=_normalize_text(
            root.select_one(".rd_hd .btm_area .side .member_plate")
        ),
        created_at=_normalize_text(root.select_one(".rd_hd .date")),
        views=_normalize_text(stats[0]) if stats else "0",
        votes=_first_integer(stats[1]) if len(stats) > 1 else 0,
        comment_count=_first_integer(stats[2]) if len(stats) > 2 else 0,
        url=url,
        is_notice=False,
    )
    detail = PostDetail(summary=summary, body=rendered_body, links=links)

    comments: list[Comment] = []
    for item in soup.select(".fdb_lst_ul > li.fdb_itm"):
        style = str(item.get("style", ""))
        margin = re.search(r"margin-left\s*:\s*(\d+)\s*%", style, re.IGNORECASE)
        depth = int(margin.group(1)) // 2 if margin else 0
        comment_id = str(item.get("id", ""))
        if comment_id.startswith("comment_"):
            comment_id = comment_id.removeprefix("comment_")

        comments.append(
            Comment(
                comment_id=comment_id,
                author=_normalize_text(item.select_one(".meta .member_plate")),
                content=_normalize_text(
                    item.select_one(".comment-content .xe_content")
                ),
                created_at=_normalize_text(item.select_one(".meta .date")),
                depth=depth,
            )
        )

    linked_pages = {
        linked_page
        for anchor in soup.select(".fdb_lst .bd_pg a[href*='cpage=']")
        if (linked_page := _comment_page(str(anchor.get("href", "")))) is not None
    }
    comment_page = PageResult(
        items=tuple(comments),
        page=cpage,
        has_previous=cpage > 1,
        has_next=any(linked_page > cpage for linked_page in linked_pages),
    )
    return detail, comment_page
