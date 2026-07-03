# FMK Terminal Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only macOS terminal application launched with `fmk` that displays the FMKorea `football_world` board, article bodies, and comments with arrow-key navigation.

**Architecture:** A Textual UI depends on a board service, which coordinates an async HTTP client, isolated BeautifulSoup parsers, and a SQLite JSON cache. Production networking is serialized and rate-limited; all automated tests use local HTML fixtures and injected fakes.

**Tech Stack:** Python 3.12.13 in Conda `basic-env`, Textual 8.2.x, HTTPX 0.28.x, BeautifulSoup 4.14.x, SQLite, pytest 8.3.x, pytest-asyncio 0.24.x

---

## File map

- `pyproject.toml`: package metadata, `fmk` entry point, runtime and test dependencies.
- `README.md`: Conda setup, install, key bindings, cache path, and limitations.
- `src/fmk_reader/__init__.py`: package version.
- `src/fmk_reader/__main__.py`: `python -m fmk_reader` entry point.
- `src/fmk_reader/models.py`: stable typed contracts shared by parser, service, and UI.
- `src/fmk_reader/errors.py`: typed network and parsing failures.
- `src/fmk_reader/parser.py`: FMKorea list, article, and comment HTML parsing only.
- `src/fmk_reader/cache.py`: SQLite-backed JSON cache with fresh and stale reads.
- `src/fmk_reader/client.py`: serialized HTTP requests, two-second spacing, timeouts, and status handling.
- `src/fmk_reader/service.py`: cache policy, URL construction, parsing, and stale fallback.
- `src/fmk_reader/app.py`: Textual widgets, responsive layout, key bindings, and async loading.
- `src/fmk_reader/styles.tcss`: split and narrow terminal layouts.
- `tests/fixtures/board.html`: minimal representative FMKorea board markup.
- `tests/fixtures/post.html`: representative article and nested comment markup.
- `tests/test_models.py`: model serialization tests.
- `tests/test_parser.py`: fixture-driven parsing tests.
- `tests/test_cache.py`: TTL, stale, and corrupt JSON tests.
- `tests/test_client.py`: rate limiting and HTTP error mapping tests.
- `tests/test_service.py`: cache-first loading and fallback tests.
- `tests/test_app.py`: Textual key binding and responsive layout tests.

### Task 1: Package scaffold and executable entry point

**Files:**
- Create: `pyproject.toml`
- Create: `src/fmk_reader/__init__.py`
- Create: `src/fmk_reader/__main__.py`
- Create: `src/fmk_reader/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing package smoke test**

```python
# tests/test_app.py
from fmk_reader.app import FmkReaderApp


def test_app_has_expected_title() -> None:
    app = FmkReaderApp()
    assert app.TITLE == "FMK 해외축구"
```

- [ ] **Step 2: Run the test and verify the package is missing**

Run: `conda run -n basic-env pytest tests/test_app.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'fmk_reader'`.

- [ ] **Step 3: Add package metadata and the minimal application**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "fmk-reader"
version = "0.1.0"
description = "Read FMKorea football_world in a terminal"
requires-python = ">=3.12,<3.13"
dependencies = [
  "beautifulsoup4>=4.14,<5",
  "httpx>=0.28,<0.29",
  "textual>=8.2,<9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3,<9",
  "pytest-asyncio>=0.24,<1",
]

[project.scripts]
fmk = "fmk_reader.app:main"

[tool.hatch.build.targets.wheel]
packages = ["src/fmk_reader"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

```python
# src/fmk_reader/__init__.py
__version__ = "0.1.0"
```

```python
# src/fmk_reader/app.py
from textual.app import App


class FmkReaderApp(App[None]):
    TITLE = "FMK 해외축구"


def main() -> None:
    FmkReaderApp().run()
```

```python
# src/fmk_reader/__main__.py
from fmk_reader.app import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Install the editable package in `basic-env` and rerun the test**

Run: `conda run -n basic-env python -m pip install -e '.[dev]'`

Expected: installation completes and installs Textual 8.2.x.

Run: `conda run -n basic-env pytest tests/test_app.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the scaffold**

```bash
git add pyproject.toml src/fmk_reader tests/test_app.py
git commit -m "chore: scaffold fmk terminal reader"
```

### Task 2: Stable domain models and JSON conversion

**Files:**
- Create: `src/fmk_reader/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing round-trip tests**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run the model tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'fmk_reader.models'`.

- [ ] **Step 3: Implement frozen models and explicit conversion**

```python
# src/fmk_reader/models.py
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
        return {"summary": asdict(self.summary), "body": self.body, "links": list(self.links)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PostDetail:
        return cls(PostSummary.from_dict(value["summary"]), value["body"], tuple(value["links"]))


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
        return cls(tuple(PostSummary.from_dict(item) for item in value["items"]), value["page"], value["has_previous"], value["has_next"])

    @classmethod
    def comments_from_dict(cls, value: dict[str, Any]) -> PageResult[Comment]:
        return cls(tuple(Comment.from_dict(item) for item in value["items"]), value["page"], value["has_previous"], value["has_next"])
```

- [ ] **Step 4: Run model tests**

Run: `conda run -n basic-env pytest tests/test_models.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit the models**

```bash
git add src/fmk_reader/models.py tests/test_models.py
git commit -m "feat: add reader domain models"
```

### Task 3: Fixture-driven FMKorea parser

**Files:**
- Create: `src/fmk_reader/errors.py`
- Create: `src/fmk_reader/parser.py`
- Create: `tests/fixtures/board.html`
- Create: `tests/fixtures/post.html`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Add compact HTML fixtures captured from the observed public DOM structure**

```html
<!-- tests/fixtures/board.html -->
<table class="bd_lst"><tbody>
<tr><td class="cate"><a>토트넘</a></td><td class="title"><a href="/100">일반 글</a><a class="replyNum">2</a></td><td class="author"><a class="member_plate">작성자</a></td><td class="time">16:45</td><td class="m_no">20</td><td class="m_no m_no_voted">3</td></tr>
<tr class="notice"><td class="cate"><a>공지</a></td><td class="title"><a href="/200"><span>공지 글</span></a></td><td class="author"><a class="member_plate">운영진</a></td><td class="time">01.05</td><td class="m_no">3백만</td><td class="m_no m_no_voted">&nbsp;</td></tr>
</tbody></table>
<form class="bd_pg"><a class="this">1</a><a class="direction" href="/index.php?mid=football_world&amp;page=2">다음</a></form>
```

```html
<!-- tests/fixtures/post.html -->
<div class="tl_srch"><a class="category">토트넘</a></div>
<div class="rd" data-docSrl="100"><div class="rd_hd"><span class="date">2026.07.03 16:45</span><h1><span class="np_18px_span">일반 글</span></h1><div class="btm_area"><div class="side"><a class="member_plate">작성자</a></div><div class="side fr"><span>조회 수 <b>20</b></span><span>추천 수 <b>3</b></span><span>댓글 <b>2</b></span></div></div></div>
<div class="rd_body"><article><div class="xe_content">첫 줄<br><img src="ignored.jpg"><a href="https://example.com/news">기사 링크</a><iframe src="ignored"></iframe></div></article></div></div>
<div class="fdb_lst"><div class="fdb_tag"><b>2</b></div><ul class="fdb_lst_ul">
<li id="comment_10" class="fdb_itm"><div class="meta"><a class="member_plate">댓글러</a><span class="date">1 분 전</span></div><div class="comment-content"><div class="xe_content">첫 댓글</div></div></li>
<li id="comment_11" class="fdb_itm re" style="margin-left:4%"><div class="meta"><a class="member_plate">답글러</a><span class="date">방금</span></div><div class="comment-content"><div class="xe_content">답글</div></div></li>
</ul><div class="bd_pg"><a href="?cpage=1">1</a><a href="?cpage=2">2</a></div></div>
```

- [ ] **Step 2: Write parser tests**

```python
# tests/test_parser.py
from pathlib import Path

import pytest

from fmk_reader.errors import ParseError
from fmk_reader.parser import parse_board, parse_post

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_board_rows_and_paging() -> None:
    page = parse_board((FIXTURES / "board.html").read_text(), page=1)
    assert [item.post_id for item in page.items] == ["100", "200"]
    assert page.items[0].comment_count == 2
    assert page.items[1].is_notice is True
    assert page.has_next is True


def test_parse_post_replaces_media_and_reads_nested_comments() -> None:
    detail, comments = parse_post((FIXTURES / "post.html").read_text(), "https://www.fmkorea.com/100", cpage=1)
    assert detail.summary.title == "일반 글"
    assert "[이미지 생략]" in detail.body
    assert "[동영상 생략]" in detail.body
    assert detail.links == ("https://example.com/news",)
    assert [comment.depth for comment in comments.items] == [0, 2]
    assert comments.has_next is True


def test_missing_title_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="post title"):
        parse_post("<html></html>", "https://www.fmkorea.com/100", cpage=1)
```

- [ ] **Step 3: Run parser tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_parser.py -v`

Expected: FAIL because `fmk_reader.errors` and `fmk_reader.parser` do not exist.

- [ ] **Step 4: Implement explicit selectors and media replacement**

```python
# src/fmk_reader/errors.py
class ReaderError(Exception):
    pass


class ParseError(ReaderError):
    pass


class FetchError(ReaderError):
    pass


class RateLimited(FetchError):
    def __init__(self, retry_after: str | None) -> None:
        self.retry_after = retry_after
        super().__init__("FMKorea request was rate limited")


class AccessBlocked(FetchError):
    pass
```

```python
# src/fmk_reader/parser.py
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from fmk_reader.errors import ParseError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary

BASE_URL = "https://www.fmkorea.com"


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _integer(text: str) -> int:
    match = re.search(r"[\d,]+", text)
    return int(match.group().replace(",", "")) if match else 0


def _required(root: BeautifulSoup | Tag, selector: str, label: str) -> Tag:
    node = root.select_one(selector)
    if not isinstance(node, Tag):
        raise ParseError(f"missing {label}")
    return node


def parse_board(html: str, page: int) -> PageResult[PostSummary]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[PostSummary] = []
    for row in soup.select("table.bd_lst tbody > tr"):
        link = row.select_one("td.title > a[href]")
        if not isinstance(link, Tag):
            continue
        match = re.fullmatch(r"/(?:best/)?(\d+)", link.get("href", ""))
        if not match:
            continue
        cells = row.select("td.m_no")
        items.append(PostSummary(
            post_id=match.group(1),
            title=_text(link),
            category=_text(row.select_one("td.cate")),
            author=_text(row.select_one("td.author .member_plate")),
            created_at=_text(row.select_one("td.time")),
            views=_text(cells[0]) if cells else "0",
            votes=_integer(_text(row.select_one("td.m_no_voted"))),
            comment_count=_integer(_text(row.select_one("a.replyNum"))),
            url=urljoin(BASE_URL, link["href"]),
            is_notice="notice" in row.get("class", []),
        ))
    if not items:
        raise ParseError("missing board rows")
    next_link = next((a for a in soup.select("form.bd_pg a.direction[href]") if "다음" in _text(a)), None)
    return PageResult(tuple(items), page, page > 1, next_link is not None)


def _render_content(node: Tag) -> tuple[str, tuple[str, ...]]:
    fragment = BeautifulSoup(str(node), "html.parser")
    for lazy in fragment.select("div[id^='pi__']"):
        lazy.decompose()
    for image in fragment.select("img"):
        image.replace_with("[이미지 생략]")
    for video in fragment.select("video, iframe"):
        video.replace_with("[동영상 생략]")
    links = tuple(dict.fromkeys(a["href"] for a in fragment.select("a[href^='http']")))
    lines = [line.strip() for line in fragment.get_text("\n", strip=True).splitlines() if line.strip()]
    return "\n".join(lines), links


def parse_post(html: str, url: str, cpage: int) -> tuple[PostDetail, PageResult[Comment]]:
    soup = BeautifulSoup(html, "html.parser")
    root = _required(soup, ".rd[data-docsrl]", "post root")
    title = _text(_required(root, ".rd_hd .np_18px_span", "post title"))
    post_id = str(root["data-docsrl"])
    stats = root.select(".rd_hd .btm_area .side.fr b")
    body, links = _render_content(_required(root, ".rd_body article .xe_content", "post body"))
    summary = PostSummary(
        post_id=post_id,
        title=title,
        category=_text(soup.select_one(".tl_srch a.category")),
        author=_text(root.select_one(".rd_hd .btm_area .side .member_plate")),
        created_at=_text(root.select_one(".rd_hd .date")),
        views=_text(stats[0]) if len(stats) > 0 else "0",
        votes=_integer(_text(stats[1])) if len(stats) > 1 else 0,
        comment_count=_integer(_text(stats[2])) if len(stats) > 2 else 0,
        url=url,
        is_notice=False,
    )
    comments: list[Comment] = []
    for item in soup.select(".fdb_lst_ul > li.fdb_itm"):
        style = item.get("style", "")
        margin = re.search(r"margin-left:\s*(\d+)%", style)
        comments.append(Comment(
            comment_id=item.get("id", "comment_0").removeprefix("comment_"),
            author=_text(item.select_one(".meta .member_plate")),
            content=_text(item.select_one(".comment-content .xe_content")),
            created_at=_text(item.select_one(".meta .date")),
            depth=int(margin.group(1)) // 2 if margin else 0,
        ))
    comment_pages = [_integer(parse_qs(urlparse(a.get("href", "")).query).get("cpage", ["0"])[0]) for a in soup.select(".fdb_lst .bd_pg a[href*='cpage=']")]
    comments_page = PageResult(tuple(comments), cpage, cpage > 1, any(number > cpage for number in comment_pages))
    return PostDetail(summary, body, links), comments_page
```

- [ ] **Step 5: Run parser tests**

Run: `conda run -n basic-env pytest tests/test_parser.py -v`

Expected: 3 passed.

- [ ] **Step 6: Commit parser and fixtures**

```bash
git add src/fmk_reader/errors.py src/fmk_reader/parser.py tests/fixtures tests/test_parser.py
git commit -m "feat: parse FMKorea board posts and comments"
```

### Task 4: SQLite JSON cache with TTL and stale reads

**Files:**
- Create: `src/fmk_reader/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write cache behavior tests**

```python
# tests/test_cache.py
from fmk_reader.cache import JsonCache


def test_cache_distinguishes_fresh_and_stale(tmp_path) -> None:
    now = [100.0]
    cache = JsonCache(tmp_path / "cache.db", clock=lambda: now[0])
    cache.put("board:1", {"page": 1})
    assert cache.get("board:1", ttl=60).is_stale is False
    now[0] = 161.0
    assert cache.get("board:1", ttl=60) is None
    stale = cache.get("board:1", ttl=60, allow_stale=True)
    assert stale is not None and stale.is_stale is True


def test_corrupt_json_is_ignored(tmp_path) -> None:
    cache = JsonCache(tmp_path / "cache.db", clock=lambda: 100.0)
    cache.connection.execute("INSERT INTO cache_entries VALUES (?, ?, ?)", ("bad", 100.0, "{"))
    cache.connection.commit()
    assert cache.get("bad", ttl=60, allow_stale=True) is None
```

- [ ] **Step 2: Run cache tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_cache.py -v`

Expected: FAIL because `fmk_reader.cache` does not exist.

- [ ] **Step 3: Implement the cache**

```python
# src/fmk_reader/cache.py
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class CacheHit:
    value: dict[str, Any]
    fetched_at: float
    is_stale: bool


class JsonCache:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, fetched_at REAL NOT NULL, payload TEXT NOT NULL)")
        self.connection.commit()

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO cache_entries VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload",
            (key, self.clock(), json.dumps(value, ensure_ascii=False)),
        )
        self.connection.commit()

    def get(self, key: str, ttl: float, allow_stale: bool = False) -> CacheHit | None:
        row = self.connection.execute("SELECT fetched_at, payload FROM cache_entries WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        fetched_at, payload = row
        is_stale = self.clock() - fetched_at > ttl
        if is_stale and not allow_stale:
            return None
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            self.connection.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
            self.connection.commit()
            return None
        return CacheHit(value, fetched_at, is_stale)

    def close(self) -> None:
        self.connection.close()
```

- [ ] **Step 4: Run cache tests**

Run: `conda run -n basic-env pytest tests/test_cache.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit the cache**

```bash
git add src/fmk_reader/cache.py tests/test_cache.py
git commit -m "feat: add sqlite response cache"
```

### Task 5: Serialized and rate-limited HTTP client

**Files:**
- Create: `src/fmk_reader/client.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write HTTP status and spacing tests**

```python
# tests/test_client.py
import httpx
import pytest

from fmk_reader.client import FmkHttpClient
from fmk_reader.errors import AccessBlocked, RateLimited


@pytest.mark.asyncio
async def test_requests_wait_for_two_second_spacing() -> None:
    now = [10.0]
    sleeps: list[float] = []
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    async with httpx.AsyncClient(transport=transport) as raw:
        client = FmkHttpClient(raw, clock=lambda: now[0], sleep=sleep)
        await client.get_text("https://www.fmkorea.com/football_world")
        await client.get_text("https://www.fmkorea.com/100")
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_429_and_403_are_typed_errors() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(403)])
    transport = httpx.MockTransport(lambda request: next(responses))
    async with httpx.AsyncClient(transport=transport) as raw:
        client = FmkHttpClient(raw, sleep=lambda seconds: _done())
        with pytest.raises(RateLimited) as limited:
            await client.get_text("https://www.fmkorea.com/football_world")
        assert limited.value.retry_after == "30"
        with pytest.raises(AccessBlocked):
            await client.get_text("https://www.fmkorea.com/football_world")


async def _done() -> None:
    return None
```

- [ ] **Step 2: Run client tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_client.py -v`

Expected: FAIL because `fmk_reader.client` does not exist.

- [ ] **Step 3: Implement the client**

```python
# src/fmk_reader/client.py
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from fmk_reader.errors import AccessBlocked, FetchError, RateLimited


class FmkHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        min_interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._last_started: float | None = None
        self._lock = asyncio.Lock()

    async def get_text(self, url: str) -> str:
        async with self._lock:
            if self._last_started is not None:
                delay = self.min_interval - (self.clock() - self._last_started)
                if delay > 0:
                    await self.sleep(delay)
            self._last_started = self.clock()
            try:
                response = await self.client.get(url)
            except httpx.TimeoutException as error:
                raise FetchError("FMKorea request timed out") from error
            except httpx.HTTPError as error:
                raise FetchError("FMKorea request failed") from error
        if response.status_code == 429:
            raise RateLimited(response.headers.get("Retry-After"))
        if response.status_code == 403:
            raise AccessBlocked("FMKorea denied access")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise FetchError(f"FMKorea returned HTTP {response.status_code}") from error
        lower = response.text.lower()
        if "captcha" in lower or "access denied" in lower:
            raise AccessBlocked("FMKorea returned a challenge page")
        return response.text


def make_httpx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"User-Agent": "fmk-reader/0.1 personal read-only client", "Accept-Language": "ko-KR,ko;q=0.9"},
    )
```

- [ ] **Step 4: Run client tests**

Run: `conda run -n basic-env pytest tests/test_client.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit the client**

```bash
git add src/fmk_reader/client.py tests/test_client.py
git commit -m "feat: add polite FMKorea http client"
```

### Task 6: Cache-first board service and stale fallback

**Files:**
- Create: `src/fmk_reader/service.py`
- Create: `tests/test_service.py`

- [ ] **Step 1: Write service tests with fakes**

```python
# tests/test_service.py
from pathlib import Path

import pytest

from fmk_reader.cache import JsonCache
from fmk_reader.errors import RateLimited
from fmk_reader.service import BoardService, DataSource

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self, html: str, error: Exception | None = None) -> None:
        self.html = html
        self.error = error
        self.calls = 0

    async def get_text(self, url: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return self.html


@pytest.mark.asyncio
async def test_fresh_board_cache_avoids_network(tmp_path) -> None:
    now = [100.0]
    cache = JsonCache(tmp_path / "cache.db", clock=lambda: now[0])
    client = FakeClient((FIXTURES / "board.html").read_text())
    service = BoardService(client, cache)
    first = await service.load_board(1)
    second = await service.load_board(1)
    assert first.source is DataSource.NETWORK
    assert second.source is DataSource.CACHE
    assert client.calls == 1


@pytest.mark.asyncio
async def test_rate_limit_uses_stale_cache(tmp_path) -> None:
    now = [100.0]
    cache = JsonCache(tmp_path / "cache.db", clock=lambda: now[0])
    warm = BoardService(FakeClient((FIXTURES / "board.html").read_text()), cache)
    await warm.load_board(1)
    now[0] = 200.0
    limited = BoardService(FakeClient("", RateLimited("30")), cache)
    result = await limited.load_board(1)
    assert result.source is DataSource.STALE_CACHE
    assert "30" in result.warning
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_service.py -v`

Expected: FAIL because `fmk_reader.service` does not exist.

- [ ] **Step 3: Implement cache policy and URL construction**

```python
# src/fmk_reader/service.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar

from fmk_reader.cache import JsonCache
from fmk_reader.errors import FetchError, RateLimited
from fmk_reader.models import PageResult, PostDetail, PostSummary
from fmk_reader.parser import parse_board, parse_post

BOARD_URL = "https://www.fmkorea.com/football_world"
BOARD_TTL = 60.0
POST_TTL = 1800.0
COMMENTS_TTL = 120.0


class TextClient(Protocol):
    async def get_text(self, url: str) -> str:
        raise NotImplementedError


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
    comments: PageResult

    def to_dict(self) -> dict:
        return {"detail": self.detail.to_dict(), "comments": self.comments.to_dict()}

    @classmethod
    def from_dict(cls, value: dict) -> PostPage:
        return cls(PostDetail.from_dict(value["detail"]), PageResult.comments_from_dict(value["comments"]))


class BoardService:
    def __init__(self, client: TextClient, cache: JsonCache) -> None:
        self.client = client
        self.cache = cache

    async def load_board(self, page: int, refresh: bool = False) -> LoadResult[PageResult[PostSummary]]:
        key = f"board:{page}"
        if not refresh and (hit := self.cache.get(key, BOARD_TTL)):
            return LoadResult(PageResult.posts_from_dict(hit.value), DataSource.CACHE)
        url = BOARD_URL if page == 1 else f"https://www.fmkorea.com/index.php?mid=football_world&page={page}"
        try:
            parsed = parse_board(await self.client.get_text(url), page)
        except FetchError as error:
            stale = self.cache.get(key, BOARD_TTL, allow_stale=True)
            if stale is None:
                raise
            wait = f"; Retry-After {error.retry_after}초" if isinstance(error, RateLimited) and error.retry_after else ""
            return LoadResult(PageResult.posts_from_dict(stale.value), DataSource.STALE_CACHE, f"네트워크 오류로 이전 목록 표시{wait}")
        self.cache.put(key, parsed.to_dict())
        return LoadResult(parsed, DataSource.NETWORK)

    async def load_post(self, post: PostSummary, cpage: int = 1, refresh: bool = False) -> LoadResult[PostPage]:
        key = f"post:{post.post_id}:comments:{cpage}"
        body_key = f"post:{post.post_id}:body"
        ttl = COMMENTS_TTL
        if not refresh and (hit := self.cache.get(key, ttl)):
            return LoadResult(PostPage.from_dict(hit.value), DataSource.CACHE)
        url = post.url if cpage == 1 else f"https://www.fmkorea.com/index.php?mid=football_world&document_srl={post.post_id}&cpage={cpage}"
        try:
            detail, comments = parse_post(await self.client.get_text(url), post.url, cpage)
            value = PostPage(detail, comments)
        except FetchError as error:
            stale = self.cache.get(key, ttl, allow_stale=True)
            if stale is not None:
                return LoadResult(PostPage.from_dict(stale.value), DataSource.STALE_CACHE, "네트워크 오류로 이전 본문과 댓글 표시")
            body = self.cache.get(body_key, POST_TTL, allow_stale=True)
            if body is not None:
                empty_comments = PageResult((), cpage, cpage > 1, False)
                return LoadResult(PostPage(PostDetail.from_dict(body.value), empty_comments), DataSource.STALE_CACHE, "댓글을 가져오지 못해 저장된 본문만 표시")
            raise
        self.cache.put(key, value.to_dict())
        self.cache.put(body_key, detail.to_dict())
        return LoadResult(value, DataSource.NETWORK)
```

- [ ] **Step 4: Run service tests**

Run: `conda run -n basic-env pytest tests/test_service.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run all non-UI tests**

Run: `conda run -n basic-env pytest tests/test_models.py tests/test_parser.py tests/test_cache.py tests/test_client.py tests/test_service.py -q`

Expected: 11 passed.

- [ ] **Step 6: Commit the service**

```bash
git add src/fmk_reader/service.py tests/test_service.py
git commit -m "feat: add cache-first board service"
```

### Task 7: Split-pane Textual UI and arrow-key reading

**Files:**
- Modify: `src/fmk_reader/app.py`
- Create: `src/fmk_reader/styles.tcss`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Replace the smoke test with interaction tests using a fake service**

```python
# tests/test_app.py
from fmk_reader.app import FmkReaderApp
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.service import DataSource, LoadResult, PostPage


POSTS = PageResult((PostSummary("100", "첫 글", "토트넘", "작성자", "16:45", "20", 3, 1, "https://www.fmkorea.com/100", False), PostSummary("101", "둘째 글", "맨유", "작성자2", "16:46", "10", 1, 0, "https://www.fmkorea.com/101", False)), 1, False, True)


class FakeService:
    async def load_board(self, page: int, refresh: bool = False):
        return LoadResult(POSTS, DataSource.CACHE)

    async def load_post(self, post: PostSummary, cpage: int = 1, refresh: bool = False):
        detail = PostDetail(post, "본문 내용", ())
        comments = PageResult((Comment("1", "댓글러", "댓글 내용", "방금", 0),), cpage, False, True)
        return LoadResult(PostPage(detail, comments), DataSource.CACHE)


async def test_arrow_and_enter_load_selected_post() -> None:
    app = FmkReaderApp(service=FakeService())
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert "둘째 글" in str(app.query_one("#article-title").renderable)
        assert "댓글 내용" in str(app.query_one("#article-content").renderable)


async def test_narrow_screen_enters_and_leaves_reading_mode() -> None:
    app = FmkReaderApp(service=FakeService())
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#main").has_class("reading")
        assert app.query_one("#article-pane").has_focus
        await pilot.press("escape")
        assert not app.query_one("#main").has_class("reading")
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `conda run -n basic-env pytest tests/test_app.py -v`

Expected: FAIL because the minimal app does not accept a service or compose widgets.

- [ ] **Step 3: Implement the UI, production dependency wiring, and lifecycle**

```python
# src/fmk_reader/app.py
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from fmk_reader.cache import JsonCache
from fmk_reader.client import FmkHttpClient, make_httpx_client
from fmk_reader.errors import ReaderError
from fmk_reader.models import PostSummary
from fmk_reader.service import BoardService, DataSource, LoadResult, PostPage


class PostItem(ListItem):
    def __init__(self, post: PostSummary) -> None:
        self.post = post
        super().__init__(Label(f"[{post.category}] {post.title}\n추천 {post.votes} · 댓글 {post.comment_count} · {post.created_at}"))


class ArticlePane(VerticalScroll):
    can_focus = True


class FmkReaderApp(App[None]):
    TITLE = "FMK 해외축구"
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("left", "previous_page", "이전 페이지"),
        ("right", "next_page", "다음 페이지"),
        ("r", "refresh", "새로고침"),
        ("escape", "back", "목록"),
        ("q", "quit", "종료"),
    ]

    def __init__(self, service: BoardService | None = None) -> None:
        super().__init__()
        self.raw_client = None
        self.cache = None
        if service is None:
            self.raw_client = make_httpx_client()
            self.cache = JsonCache(Path.home() / ".cache/fmk-reader/cache.db")
            service = BoardService(FmkHttpClient(self.raw_client), self.cache)
        self.service = service
        self.board_page = 1
        self.comment_page = 1
        self.board_has_previous = False
        self.board_has_next = False
        self.comments_have_previous = False
        self.comments_have_next = False
        self.current_post: PostSummary | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(id="post-list")
            with ArticlePane(id="article-pane"):
                yield Static("글을 선택하세요", id="article-title")
                yield Static("", id="article-meta")
                yield Static("", id="article-content")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#post-list", ListView).focus()
        self.load_board()

    async def on_unmount(self) -> None:
        if self.raw_client is not None:
            await self.raw_client.aclose()
        if self.cache is not None:
            self.cache.close()

    @work(exclusive=True, group="board")
    async def load_board(self, refresh: bool = False) -> None:
        try:
            result = await self.service.load_board(self.board_page, refresh)
        except ReaderError as error:
            self.notify(str(error), severity="error")
            return
        view = self.query_one("#post-list", ListView)
        await view.clear()
        await view.extend(PostItem(post) for post in result.value.items)
        view.index = 0
        self.board_has_previous = result.value.has_previous
        self.board_has_next = result.value.has_next
        self.sub_title = f"{self.board_page}페이지 · {result.source.value}"
        if result.warning:
            self.notify(result.warning, severity="warning")

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, PostItem):
            self.current_post = event.item.post
            self.comment_page = 1
            self.query_one("#main").add_class("reading")
            if self.query_one("#main").has_class("narrow"):
                self.query_one("#article-pane", ArticlePane).focus()
            self.load_post()

    @work(exclusive=True, group="post")
    async def load_post(self, refresh: bool = False) -> None:
        if self.current_post is None:
            return
        try:
            result: LoadResult[PostPage] = await self.service.load_post(self.current_post, self.comment_page, refresh)
        except ReaderError as error:
            self.notify(str(error), severity="error")
            return
        page = result.value
        self.comments_have_previous = page.comments.has_previous
        self.comments_have_next = page.comments.has_next
        self.query_one("#article-title", Static).update(Text(page.detail.summary.title, style="bold yellow"))
        self.query_one("#article-meta", Static).update(f"{page.detail.summary.author} · 조회 {page.detail.summary.views} · 추천 {page.detail.summary.votes} · 댓글 {page.detail.summary.comment_count}")
        comments = "\n".join(f"{'  ' * comment.depth}└ {comment.author}  {comment.content}" for comment in page.comments.items)
        links = "\n".join(page.detail.links)
        self.query_one("#article-content", Static).update(f"{page.detail.body}\n\n링크\n{links}\n\n댓글 {self.comment_page}페이지\n{comments}")
        if result.warning:
            self.notify(result.warning, severity="warning")

    def action_previous_page(self) -> None:
        if self.query_one("#post-list").has_focus and self.board_has_previous:
            self.board_page -= 1
            self.load_board()
        elif self.comments_have_previous:
            self.comment_page -= 1
            self.load_post()

    def action_next_page(self) -> None:
        if self.query_one("#post-list").has_focus and self.board_has_next:
            self.board_page += 1
            self.load_board()
        elif self.current_post is not None and self.comments_have_next:
            self.comment_page += 1
            self.load_post()

    def action_refresh(self) -> None:
        if self.current_post is not None and self.query_one("#article-pane").has_focus:
            self.load_post(refresh=True)
        else:
            self.load_board(refresh=True)

    def action_back(self) -> None:
        self.query_one("#main").remove_class("reading")
        self.query_one("#post-list", ListView).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#main").set_class(event.size.width < 100, "narrow")


def main() -> None:
    FmkReaderApp().run()
```

```css
/* src/fmk_reader/styles.tcss */
#main { height: 1fr; }
#post-list { width: 38%; border-right: solid $primary; }
#article-pane { width: 62%; padding: 0 2; }
#article-title { margin-bottom: 1; }
#article-meta { color: $text-muted; margin-bottom: 1; }
#main.narrow #post-list { width: 100%; display: block; }
#main.narrow #article-pane { width: 100%; display: none; }
#main.narrow.reading #post-list { display: none; }
#main.narrow.reading #article-pane { display: block; }
PostItem { height: auto; padding: 0 1; }
```

- [ ] **Step 4: Run UI tests**

Run: `conda run -n basic-env pytest tests/test_app.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run the full automated suite**

Run: `conda run -n basic-env pytest -q`

Expected: 13 passed.

- [ ] **Step 6: Commit the UI**

```bash
git add src/fmk_reader/app.py src/fmk_reader/styles.tcss tests/test_app.py
git commit -m "feat: add split-pane terminal reader UI"
```

### Task 8: Documentation, local launch, and conservative smoke verification

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-07-03-fmk-terminal-reader-design.md` only if implementation reveals a verified mismatch

- [ ] **Step 1: Write the user documentation**

````markdown
# FMK Reader

FMKorea 해외축구 게시판의 공개 글, 본문, 댓글을 읽는 개인용 터미널 애플리케이션입니다. 로그인, 쓰기, 추천, 이미지 표시는 지원하지 않습니다.

## 설치

```bash
cd /Users/hj/Desktop/project_code/terminal_community
conda activate basic-env
python -m pip install -e '.[dev]'
```

## 실행

```bash
fmk
```

## 키

- `↑` / `↓`: 목록 이동 또는 본문 스크롤
- `←` / `→`: 게시판 또는 댓글 페이지 이동
- `Enter`: 글 열기
- `Tab`: 목록과 본문 포커스 전환
- `Esc`: 좁은 화면에서 목록으로 복귀
- `r`: 새로고침
- `q`: 종료

캐시는 `~/.cache/fmk-reader/cache.db`에 저장됩니다. 요청은 한 번에 하나씩, 최소 2초 간격으로 실행됩니다. 403, CAPTCHA 또는 차단 페이지는 우회하지 않습니다.
````

- [ ] **Step 2: Verify installation and command discovery in `basic-env`**

Run: `conda run -n basic-env python -m pip install -e '.[dev]'`

Expected: editable install succeeds.

Run: `conda run -n basic-env which fmk`

Expected: path ends with `/envs/basic-env/bin/fmk`.

- [ ] **Step 3: Run all automated checks without network access**

Run: `conda run -n basic-env pytest -q`

Expected: 13 passed and no request reaches `fmkorea.com`.

- [ ] **Step 4: Perform one manual smoke session**

Run: `conda run -n basic-env fmk`

Expected:

1. The board list appears and the status shows `network` or `cache`.
2. Pressing `↓` changes the selected row.
3. Pressing `Enter` shows title, body text, media placeholders, and comments.
4. Pressing `Tab`, arrow keys, `Esc`, `r`, and `q` follows the documented behavior.
5. If FMKorea responds with 429 or 403, the app shows a warning and does not retry repeatedly.

- [ ] **Step 5: Confirm the cache and clean Git state**

Run: `test -f "$HOME/.cache/fmk-reader/cache.db" && echo cache-ok`

Expected: `cache-ok` after a successful live read.

Run: `git status --short`

Expected: only `README.md` is uncommitted.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md docs/superpowers/specs/2026-07-03-fmk-terminal-reader-design.md
git commit -m "docs: add install and usage guide"
```

### Task 9: Final verification

**Files:**
- Verify only; modify the smallest responsible file if a check exposes a defect.

- [ ] **Step 1: Run the complete test suite from the documented environment**

Run: `conda run -n basic-env pytest -q`

Expected: 13 passed.

- [ ] **Step 2: Verify package metadata and CLI import**

Run: `conda run -n basic-env python -c "import fmk_reader; from fmk_reader.app import FmkReaderApp; print(fmk_reader.__version__, FmkReaderApp.TITLE)"`

Expected: `0.1.0 FMK 해외축구`.

- [ ] **Step 3: Review commits and working tree**

Run: `git log --oneline --decorate -10`

Expected: focused commits for scaffold, models, parser, cache, client, service, UI, and documentation.

Run: `git status --short --branch`

Expected: branch header only with no modified or untracked files.
