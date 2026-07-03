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


def _require_text(root: Tag | BeautifulSoup, selector: str, name: str) -> str:
    text = _normalize_text(_require(root, selector, name))
    if not text:
        raise ParseError(f"missing {name}")
    return text


def _numeric_attribute(element: Tag, attribute: str, name: str) -> str:
    value = str(element.get(attribute, ""))
    if re.fullmatch(r"\d+", value) is None:
        raise ParseError(f"invalid {name}")
    return value


def _post_identity(href: str) -> tuple[str, str] | None:
    parsed = urlparse(urljoin(BASE_URL, href.strip()))
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "www.fmkorea.com":
        return None

    path_match = _DOCUMENT_PATH.fullmatch(parsed.path)
    if path_match is not None:
        post_id = path_match.group(1)
    elif parsed.path == "/index.php":
        query = parse_qs(parsed.query)
        mids = query.get("mid", [])
        document_ids = query.get("document_srl", [])
        if mids != ["football_world"] or len(document_ids) != 1:
            return None
        post_id = document_ids[0]
        if not post_id.isdigit():
            return None
    else:
        return None

    return post_id, f"{BASE_URL}/{post_id}"


def parse_board(html: str, page: int) -> PageResult[PostSummary]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[PostSummary] = []

    for row in soup.select("table.bd_lst tbody > tr"):
        title_anchor = row.select_one("td.title > a[href]")
        if not isinstance(title_anchor, Tag):
            continue

        identity = _post_identity(str(title_anchor.get("href", "")))
        if identity is None:
            continue

        post_id, canonical_url = identity
        views = _normalize_text(row.select_one("td.m_no:not(.m_no_voted)")) or "0"
        votes = _first_integer(row.select_one("td.m_no_voted"))
        reply_count = _first_integer(row.select_one("td.title .replyNum"))
        author = row.select_one("td.author .member_plate") or row.select_one(
            "td.author"
        )

        posts.append(
            PostSummary(
                post_id=post_id,
                title=_normalize_text(title_anchor),
                category=_normalize_text(row.select_one("td.cate")),
                author=_normalize_text(author),
                created_at=_normalize_text(row.select_one("td.time")),
                views=views,
                votes=votes,
                comment_count=reply_count,
                url=canonical_url,
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
        href = str(anchor.get("href", "")).strip()
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


def _post_stats(root: Tag) -> tuple[str, int, int]:
    views = "0"
    votes = 0
    comment_count = 0
    for span in root.select(".rd_hd .btm_area .side.fr span"):
        value = span.select_one("b")
        if value is None:
            continue
        label = _normalize_text(span)
        if label.startswith("조회 수"):
            views = _normalize_text(value) or "0"
        elif label.startswith("추천 수"):
            votes = _first_integer(value)
        elif label.startswith("댓글"):
            comment_count = _first_integer(value)
    return views, votes, comment_count


def parse_post(
    html: str,
    url: str,
    cpage: int,
) -> tuple[PostDetail, PageResult[Comment]]:
    soup = BeautifulSoup(html, "html.parser")
    root = _require(soup, ".rd[data-docsrl]", "post root")
    post_id = _numeric_attribute(root, "data-docsrl", "post id")
    title = _require_text(root, ".rd_hd .np_18px_span", "post title")
    body = _require(root, ".rd_body article .xe_content", "post body")
    rendered_body, links = _render_content(body)
    if not rendered_body:
        raise ParseError("missing post body")
    views, votes, comment_count = _post_stats(root)

    summary = PostSummary(
        post_id=post_id,
        title=title,
        category=_normalize_text(soup.select_one(".tl_srch a.category")),
        author=_normalize_text(
            root.select_one(".rd_hd .btm_area .side .member_plate")
        ),
        created_at=_normalize_text(root.select_one(".rd_hd .date")),
        views=views,
        votes=votes,
        comment_count=comment_count,
        url=url,
        is_notice=False,
    )
    detail = PostDetail(summary=summary, body=rendered_body, links=links)

    comments: list[Comment] = []
    for item in soup.select(".fdb_lst_ul > li.fdb_itm"):
        id_match = re.fullmatch(r"comment_(\d+)", str(item.get("id", "")))
        if id_match is None:
            continue
        content_node = item.select_one(".comment-content .xe_content")
        if not isinstance(content_node, Tag):
            continue
        comment_content, _ = _render_content(content_node)
        if not comment_content:
            continue

        style = str(item.get("style", ""))
        margin = re.search(r"margin-left\s*:\s*(\d+)\s*%", style, re.IGNORECASE)
        depth = int(margin.group(1)) // 2 if margin else 0

        comments.append(
            Comment(
                comment_id=id_match.group(1),
                author=_normalize_text(item.select_one(".meta .member_plate")),
                content=comment_content,
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
