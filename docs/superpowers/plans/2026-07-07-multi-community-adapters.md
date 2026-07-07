# Multi-Community Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the FMK-only startup with a `commu` launcher and URL router that reuse one read-only TUI for FMKorea, public DCInside galleries, and public Arca Live channels.

**Architecture:** A strict URL router produces a site-neutral target, then a site adapter owns URL construction, request policy, and HTML parsing. A generalized cache-first service feeds the existing Textual reader, while a launcher handles site selection, recommended URLs, and direct URL input.

**Tech Stack:** Python 3.12, Textual 8.2, httpx 0.28, Beautiful Soup 4.14, SQLite, pytest 8.3, pytest-asyncio 0.24, Ruff.

## Global Constraints

- Primary command: `commu`; compatibility alias: `fmk`.
- Supported sites: current FMKorea overseas-football board, all publicly accessible DCInside general/minor/mini galleries matching supported URL forms, and all publicly accessible Arca Live channels matching supported URL forms.
- Read-only: no login, writing, voting, recommending, subscribing, adult verification, CAPTCHA solving, browser-cookie import, or security challenge bypass.
- Images, videos, DCCons, and Arca emoticons are represented as text placeholders and are not downloaded for display.
- Only HTTPS URLs from explicit site allowlists may be fetched; cross-site redirects are rejected.
- Fetches are serialized and start at least two seconds apart. There is no automatic retry or prefetch.
- HTTP 429 and FMKorea HTTP 430 establish a local `Retry-After` cooldown that rejects new network work without sending a request.
- All remote text is rendered literally with Rich/Textual markup disabled.
- Existing FMK behavior and the complete pre-feature test suite must remain green.

---

### Task 1: Strict community targets and URL router

**Files:**
- Create: `src/fmk_reader/targets.py`
- Create: `tests/test_targets.py`
- Modify: `src/fmk_reader/errors.py`

**Interfaces:**
- Consumes: Python `urllib.parse.urlsplit`, `urlunsplit`, and existing `ReaderError` hierarchy.
- Produces: `Site`, `CommunityTarget`, `RECOMMENDED_URLS`, and `route_url(raw: str) -> CommunityTarget` for all later tasks.

- [ ] **Step 1: Write the failing URL-routing tests**

```python
# tests/test_targets.py
import pytest

from fmk_reader.errors import TargetError
from fmk_reader.targets import Site, route_url


@pytest.mark.parametrize(
    ("url", "site", "board_id", "article_id"),
    [
        ("https://www.fmkorea.com/football_world", Site.FMKOREA, "football_world", None),
        ("https://www.fmkorea.com/123456", Site.FMKOREA, "football_world", "123456"),
        ("https://gall.dcinside.com/board/lists/?id=football_new9", Site.DCINSIDE, "football_new9", None),
        ("https://gall.dcinside.com/mgallery/board/view/?id=test&no=42", Site.DCINSIDE, "test", "42"),
        ("https://gall.dcinside.com/mini/board/lists/?id=test", Site.DCINSIDE, "test", None),
        ("https://m.dcinside.com/board/football_new9/42", Site.DCINSIDE, "football_new9", "42"),
        ("https://arca.live/b/rogersfu", Site.ARCA, "rogersfu", None),
        ("https://arca.live/b/rogersfu/176096992?p=1#comment", Site.ARCA, "rogersfu", "176096992"),
    ],
)
def test_route_url_recognizes_supported_targets(url, site, board_id, article_id):
    target = route_url(url)
    assert (target.site, target.board_id, target.article_id) == (
        site,
        board_id,
        article_id,
    )
    assert target.board_url.startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://arca.live/b/rogersfu",
        "https://user:pass@arca.live/b/rogersfu",
        "https://example.com/board",
        "https://arca.live/u/login",
        "https://gall.dcinside.com/board/write/?id=football_new9",
        "https://gall.dcinside.com/board/lists/?id=../bad",
    ],
)
def test_route_url_rejects_unsafe_or_unsupported_urls(url):
    with pytest.raises(TargetError):
        route_url(url)
```

- [ ] **Step 2: Run the routing tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_targets.py -v`

Expected: collection fails because `fmk_reader.targets` and `TargetError` do not exist.

- [ ] **Step 3: Add the target error and immutable routing model**

```python
# src/fmk_reader/errors.py
class TargetError(ReaderError):
    """Raised before network access when a community URL is unsupported."""
```

```python
# src/fmk_reader/targets.py
from dataclasses import dataclass
from enum import Enum


class Site(str, Enum):
    FMKOREA = "fmkorea"
    DCINSIDE = "dcinside"
    ARCA = "arca"

    @property
    def display_name(self) -> str:
        return {
            Site.FMKOREA: "FMKorea",
            Site.DCINSIDE: "디시인사이드",
            Site.ARCA: "아카라이브",
        }[self]


@dataclass(frozen=True, slots=True)
class CommunityTarget:
    site: Site
    board_id: str
    board_url: str
    article_id: str | None = None
    article_url: str | None = None


RECOMMENDED_URLS = {
    Site.FMKOREA: "https://www.fmkorea.com/football_world",
    Site.DCINSIDE: "https://gall.dcinside.com/board/lists/?id=football_new9",
    Site.ARCA: "https://arca.live/b/rogersfu",
}
```

Implement private `_route_fmk`, `_route_dcinside`, and `_route_arca` functions using `urlsplit`. Validate board identifiers with `re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value)`, article identifiers with `str.isdecimal()`, HTTPS scheme, no username/password, and the exact path families in the design. Canonicalize DC targets to `https://m.dcinside.com/board/<id>` and Arca targets to fragment-free `https://arca.live/b/<channel>` URLs.

- [ ] **Step 4: Run routing and model regression tests**

Run: `conda run -n basic-env pytest tests/test_targets.py tests/test_models.py -v`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the router**

```bash
git add src/fmk_reader/errors.py src/fmk_reader/targets.py tests/test_targets.py
git commit -m "feat: route supported community urls"
```

---

### Task 2: Adapter contract and FMK compatibility adapter

**Files:**
- Create: `src/fmk_reader/adapters/__init__.py`
- Create: `src/fmk_reader/adapters/base.py`
- Create: `src/fmk_reader/adapters/fmk.py`
- Create: `tests/test_adapters.py`

**Interfaces:**
- Consumes: `CommunityTarget`, `PostSummary`, `PostDetail`, `Comment`, `PageResult`, and existing `parse_board`/`parse_post` functions.
- Produces: `RequestPolicy`, `CommunityAdapter`, `adapter_for(target)`, and `FmkAdapter` used by client, service, and TUI tasks.

- [ ] **Step 1: Write failing adapter-selection and FMK-regression tests**

```python
# tests/test_adapters.py
from pathlib import Path

from fmk_reader.adapters import adapter_for
from fmk_reader.adapters.fmk import FmkAdapter
from fmk_reader.targets import route_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_adapter_for_returns_fmk_adapter():
    target = route_url("https://www.fmkorea.com/football_world")
    adapter = adapter_for(target)
    assert isinstance(adapter, FmkAdapter)
    assert adapter.site_name == "FMKorea"
    assert adapter.policy.rate_limit_statuses == frozenset({429, 430})


def test_fmk_adapter_preserves_existing_parser_behavior():
    adapter = FmkAdapter(route_url("https://www.fmkorea.com/football_world"))
    board = adapter.parse_board((FIXTURES / "board.html").read_text(), page=1)
    post = board.items[0]
    detail, comments = adapter.parse_post(
        (FIXTURES / "post.html").read_text(), post, cpage=1
    )
    assert detail.summary.post_id == post.post_id
    assert comments.page == 1
```

- [ ] **Step 2: Run the adapter tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_adapters.py -v`

Expected: collection fails because `fmk_reader.adapters` does not exist.

- [ ] **Step 3: Define the adapter protocol and request policy**

```python
# src/fmk_reader/adapters/base.py
from dataclasses import dataclass
from typing import Protocol

from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.targets import CommunityTarget, Site


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
```

- [ ] **Step 4: Implement `FmkAdapter` as a thin compatibility layer**

`FmkAdapter` must delegate parsing to the existing parser, preserve the exact FMK URLs and page semantics, validate returned article IDs, and create a minimal direct-article `PostSummary` when `target.article_id` is present. Do not copy parser logic into the adapter.

```python
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
```

Implement `adapter_for` with explicit imports and an exhaustive `Site` match. DCInside and Arca branches should raise `NotImplementedError` until their tasks add concrete adapters; no generic fallback.

- [ ] **Step 5: Run adapter and all FMK parser tests**

Run: `conda run -n basic-env pytest tests/test_adapters.py tests/test_parser.py -v`

Expected: all selected tests pass with no parser regressions.

- [ ] **Step 6: Commit the adapter boundary**

```bash
git add src/fmk_reader/adapters tests/test_adapters.py
git commit -m "refactor: isolate fmk site adapter"
```

---

### Task 3: Adapter-aware HTTP policy and local cooldown

**Files:**
- Modify: `src/fmk_reader/client.py`
- Modify: `src/fmk_reader/errors.py`
- Modify: `tests/test_client.py`

**Interfaces:**
- Consumes: `RequestPolicy` from Task 2 and caller-owned `httpx.AsyncClient`.
- Produces: `CommunityHttpClient(raw, policy, ...)`, generic `RateLimited(site_name, retry_after)`, and a temporary `FmkHttpClient` wrapper with the old constructor for intermediate compatibility.

- [ ] **Step 1: Add failing 430 and cooldown tests**

```python
@pytest.mark.asyncio
async def test_fmk_430_sets_cooldown_and_second_request_is_local():
    requests = []
    now = [100.0]

    def handler(request):
        requests.append(request)
        return httpx.Response(430, headers={"Retry-After": "300"})

    raw = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = CommunityHttpClient(raw, FMK_POLICY, clock=lambda: now[0])
    with pytest.raises(RateLimited) as first:
        await client.get_text("https://www.fmkorea.com/football_world")
    assert first.value.retry_after == "300"

    now[0] += 1
    with pytest.raises(RateLimited, match="299"):
        await client.get_text("https://www.fmkorea.com/football_world")
    assert len(requests) == 1
    await raw.aclose()


@pytest.mark.asyncio
async def test_policy_rejects_redirect_outside_allowed_origins():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "https://example.com"})
    )
    async with httpx.AsyncClient(transport=transport) as raw:
        client = CommunityHttpClient(raw, FMK_POLICY)
        with pytest.raises(FetchError, match="cross-origin"):
            await client.get_text("https://www.fmkorea.com/football_world")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_client.py -k '430 or policy' -v`

Expected: tests fail because 430 is a generic `FetchError` and cooldown requests are not rejected locally.

- [ ] **Step 3: Generalize errors and client behavior**

```python
class RateLimited(FetchError):
    def __init__(self, site_name: str, retry_after: str | None = None) -> None:
        message = f"{site_name} 요청 제한"
        if retry_after:
            message += f" (Retry-After: {retry_after})"
        super().__init__(message)
        self.site_name = site_name
        self.retry_after = retry_after
```

Rename the implementation to `CommunityHttpClient`. Accept `RequestPolicy` in
the constructor, build site headers from it, and use its allowed origins and
status sets. Before spacing logic, compute remaining cooldown with
`math.ceil(self._retry_not_before - self._clock())`; if positive, raise
`RateLimited(policy.site.display_name, str(remaining))` without sleeping or
sending. Preserve two-second spacing for non-cooldown work. Keep
the following wrapper until Task 7 migrates the application, then remove it:

```python
class FmkHttpClient(CommunityHttpClient):
    def __init__(self, raw: httpx.AsyncClient, **kwargs: Any) -> None:
        super().__init__(raw, FMK_POLICY, **kwargs)
```

Keep `make_httpx_client(policy: RequestPolicy = FMK_POLICY)` during the same
transition. It must build headers from the selected policy rather than hardcode
FMK strings.

- [ ] **Step 4: Run the complete client suite**

Run: `conda run -n basic-env pytest tests/test_client.py -v`

Expected: all client tests pass, including one-request proof for cooldown.

- [ ] **Step 5: Commit HTTP policy support**

```bash
git add src/fmk_reader/client.py src/fmk_reader/errors.py tests/test_client.py
git commit -m "feat: enforce site request policies"
```

---

### Task 4: DCInside adapter using public mobile HTML

**Files:**
- Create: `src/fmk_reader/adapters/dcinside.py`
- Create: `tests/test_dcinside_adapter.py`
- Create: `tests/fixtures/dc_board.html`
- Create: `tests/fixtures/dc_post.html`
- Modify: `src/fmk_reader/adapters/__init__.py`

**Interfaces:**
- Consumes: `CommunityAdapter`, `RequestPolicy`, common models, and DC targets from Task 1.
- Produces: `DcinsideAdapter` capable of canonical mobile list/article fetches and parsing server-rendered comments.

- [ ] **Step 1: Add minimal, sanitized DC fixtures**

Build `dc_board.html` from representative `.gall-detail-lnktb` rows and
`dc_post.html` from `.gallview-tit-box`, article body, and
`.all-comment-lst`. Include exactly: one notice, two ordinary posts, one ad row
that must be ignored, one image, one DCCon, a top-level comment, and one reply.
Use invented short Korean test text rather than copying full live posts.

- [ ] **Step 2: Write failing DC parser tests**

```python
def test_dc_board_filters_ads_and_builds_mobile_urls(fixture):
    target = route_url("https://gall.dcinside.com/board/lists/?id=football_new9")
    adapter = DcinsideAdapter(target)
    page = adapter.parse_board(fixture("dc_board.html"), page=1)
    assert [post.post_id for post in page.items] == ["47", "6244511", "6244510"]
    assert page.items[0].is_notice is True
    assert page.items[1].url == "https://m.dcinside.com/board/football_new9/6244511"
    assert page.has_previous is False


def test_dc_post_reads_body_comments_replies_and_media_placeholders(fixture):
    adapter = DcinsideAdapter(route_url("https://m.dcinside.com/board/football_new9"))
    post = adapter.parse_board(fixture("dc_board.html"), 1).items[1]
    detail, comments = adapter.parse_post(fixture("dc_post.html"), post, 1)
    assert detail.summary.post_id == "6244511"
    assert "[이미지]" in detail.body
    assert [comment.depth for comment in comments.items] == [0, 1]
    assert "[디시콘]" in comments.items[1].content
```

- [ ] **Step 3: Run DC tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_dcinside_adapter.py -v`

Expected: collection fails because `DcinsideAdapter` does not exist.

- [ ] **Step 4: Implement strict DC list and article parsing**

Use Beautiful Soup and semantic selectors scoped to mobile containers. Parse
metadata defensively and raise `ParseError("디시인사이드 ... 구조를 찾을 수 없습니다")`
when required title, article identity, list container, or body is absent.
Replace `img` inside body/comments according to class: `written_dccon` becomes
`[디시콘]`; other images become `[이미지]`; video becomes `[동영상]`. Do not
retain media URLs in body text. Set reply depth from the reply class/parent
metadata exposed in the fixture.

The request policy must use a fixed mobile browser User-Agent, allow only
`https://m.dcinside.com:443` redirects after canonicalization, use status 429
as rate limiting, status 403 as blocked, and keep the two-second interval.

- [ ] **Step 5: Run DC, routing, and model tests**

Run: `conda run -n basic-env pytest tests/test_dcinside_adapter.py tests/test_targets.py tests/test_models.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit DCInside support**

```bash
git add src/fmk_reader/adapters tests/test_dcinside_adapter.py tests/fixtures/dc_board.html tests/fixtures/dc_post.html
git commit -m "feat: add dcinside read adapter"
```

---

### Task 5: Arca Live adapter

**Files:**
- Create: `src/fmk_reader/adapters/arca.py`
- Create: `tests/test_arca_adapter.py`
- Create: `tests/fixtures/arca_board.html`
- Create: `tests/fixtures/arca_post.html`
- Modify: `src/fmk_reader/adapters/__init__.py`

**Interfaces:**
- Consumes: `CommunityAdapter`, `RequestPolicy`, common models, and Arca targets from Task 1.
- Produces: `ArcaAdapter` for public channel lists, bodies, server-rendered comments, and replies.

- [ ] **Step 1: Add minimal, sanitized Arca fixtures**

Build `arca_board.html` from `.article-list .vrow` and `arca_post.html` from
`.article-head`, `.article-content`, and `.comment-wrapper`. Include one service
notice that links to another channel and must be ignored, one channel notice,
two ordinary posts, an image, an emoticon, a top-level comment, and a reply.
Use invented short text.

- [ ] **Step 2: Write failing Arca tests**

```python
def test_arca_board_keeps_channel_rows_and_rejects_foreign_service_notice(fixture):
    adapter = ArcaAdapter(route_url("https://arca.live/b/rogersfu"))
    page = adapter.parse_board(fixture("arca_board.html"), page=1)
    assert [post.post_id for post in page.items] == ["6457546", "176096992", "176096991"]
    assert page.items[0].is_notice is True
    assert all("/b/rogersfu/" in post.url for post in page.items)


def test_arca_post_reads_comments_and_placeholders(fixture):
    adapter = ArcaAdapter(route_url("https://arca.live/b/rogersfu"))
    post = adapter.parse_board(fixture("arca_board.html"), 1).items[1]
    detail, comments = adapter.parse_post(fixture("arca_post.html"), post, 1)
    assert detail.summary.post_id == "176096992"
    assert "[이미지]" in detail.body
    assert comments.items[1].depth == 1
    assert "[이모티콘]" in comments.items[1].content
```

- [ ] **Step 3: Run Arca tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_arca_adapter.py -v`

Expected: collection fails because `ArcaAdapter` does not exist.

- [ ] **Step 4: Implement Arca URL generation and parsing**

Use `?p=<page>` for channel pagination and preserve only the channel and numeric
article identity in canonical URLs. Require `.article-list`, article title,
numeric article identity, and `.article-content`. Ignore cross-channel service
notices. Convert article media and comment media to the approved placeholders.
Read author, date, view/vote/comment counts when present; use empty strings or
zero only for optional metadata, never for required identity/title/body.

The policy allows only `https://arca.live:443`, treats 429 as rate limiting and
403 as blocked, and uses the common two-second interval.

- [ ] **Step 5: Run Arca, routing, and model tests**

Run: `conda run -n basic-env pytest tests/test_arca_adapter.py tests/test_targets.py tests/test_models.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Arca support**

```bash
git add src/fmk_reader/adapters tests/test_arca_adapter.py tests/fixtures/arca_board.html tests/fixtures/arca_post.html
git commit -m "feat: add arca live read adapter"
```

---

### Task 6: Generic cache-first community service

**Files:**
- Modify: `src/fmk_reader/service.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_cache.py`

**Interfaces:**
- Consumes: one `CommunityAdapter`, `CommunityHttpClient`, and `JsonCache`.
- Produces: `CommunityService(adapter, client, cache)`, unchanged `LoadResult`/`PostPage` shapes, and version-two site-separated cache behavior for the TUI.

- [ ] **Step 1: Add failing cache-key and adapter-delegation tests**

```python
@pytest.mark.asyncio
async def test_service_uses_adapter_urls_and_site_namespaced_cache(tmp_path):
    adapter = FakeAdapter(
        target=CommunityTarget(
            site=Site.ARCA,
            board_id="rogersfu",
            board_url="https://arca.live/b/rogersfu",
        )
    )
    client = FakeClient("<board />")
    cache = JsonCache(tmp_path / "cache.db")
    service = CommunityService(adapter, client, cache)
    result = await service.load_board(2)
    assert client.urls == [adapter.board_url(2)]
    assert result.source is DataSource.NETWORK
    assert cache.get("v2:arca:rogersfu:board:2", 60) is not None
    cache.close()


@pytest.mark.asyncio
async def test_same_article_id_on_two_sites_has_distinct_cache_keys(tmp_path):
    cache = JsonCache(tmp_path / "cache.db")
    dc = CommunityTarget(Site.DCINSIDE, "g", "https://m.dcinside.com/board/g")
    arca = CommunityTarget(Site.ARCA, "g", "https://arca.live/b/g")
    await seed_post(CommunityService(FakeAdapter(dc), FakeClient("dc"), cache), "42")
    await seed_post(CommunityService(FakeAdapter(arca), FakeClient("arca"), cache), "42")
    assert cache.get("v2:dcinside:g:post:42:comments:1", 120) is not None
    assert cache.get("v2:arca:g:post:42:comments:1", 120) is not None
    cache.close()


async def seed_post(service: CommunityService, post_id: str) -> None:
    post = PostSummary(
        post_id=post_id,
        title="테스트 글",
        category="",
        author="작성자",
        created_at="오늘",
        views="1",
        votes=0,
        comment_count=0,
        url=f"{service.adapter.target.board_url.rstrip('/')}/{post_id}",
        is_notice=False,
    )
    await service.load_post(post)
```

The test fake must implement the exact Task 2 protocol and return small common
models; it must not branch on production implementation details.

- [ ] **Step 2: Run service tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_service.py -k 'adapter or namespaced or distinct' -v`

Expected: tests fail because `BoardService` still constructs FMK URLs and old cache keys.

- [ ] **Step 3: Replace FMK-specific service behavior**

```python
class CommunityService:
    def __init__(
        self,
        adapter: CommunityAdapter,
        client: TextClient,
        cache: JsonCache,
    ) -> None:
        self.adapter = adapter
        self._client = client
        self._cache = cache

    def _key(self, *parts: object) -> str:
        prefix = (
            f"v2:{self.adapter.target.site.value}:"
            f"{self.adapter.target.board_id}"
        )
        return ":".join((prefix, *(str(part) for part in parts)))
```

Delegate list/post URL construction and parsing to the adapter. Before either
post cache write, require `detail.summary.post_id` to match the requested post;
the adapter must already have validated the board identity and response origin.
Retain the current TTLs, stale list/page fallback,
body-only fallback, transaction-safe cache writes, and rule that parse errors do
not use stale cache. Keep this explicit compatibility wrapper only until Task 7
migrates the app:

```python
class BoardService(CommunityService):
    def __init__(self, client: TextClient, cache: JsonCache) -> None:
        target = route_url("https://www.fmkorea.com/football_world")
        super().__init__(FmkAdapter(target), client, cache)
```

- [ ] **Step 4: Make stale warnings site-neutral**

Use the typed error text directly. For `RateLimited`, include the adapter's site
name and `Retry-After`; for other fetch errors, say that stored content is shown
because the active community could not be reached. Do not label parse errors as
network failures.

- [ ] **Step 5: Run service, cache, and full regression tests**

Run: `conda run -n basic-env pytest tests/test_service.py tests/test_cache.py -v`

Expected: all focused tests pass.

Run: `conda run -n basic-env pytest -q`

Expected: the complete suite passes with no failures.

- [ ] **Step 6: Commit the generic service**

```bash
git add src/fmk_reader/service.py tests/test_service.py tests/test_cache.py
git commit -m "refactor: generalize cached community service"
```

---

### Task 7: `commu` launcher, direct URL startup, and shared reader

**Files:**
- Create: `src/fmk_reader/launcher.py`
- Modify: `src/fmk_reader/app.py`
- Modify: `src/fmk_reader/__main__.py`
- Modify: `src/fmk_reader/styles.tcss`
- Modify: `pyproject.toml`
- Modify: `tests/test_app.py`
- Create: `tests/test_launcher.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `route_url`, `RECOMMENDED_URLS`, `adapter_for`, `CommunityHttpClient`, and `CommunityService`.
- Produces: `CommunityReaderApp(target: CommunityTarget | None = None, service: ReaderService | None = None)`, `parse_cli(argv)`, `main(argv=None)`, `commu` primary command, and `fmk` alias.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_parse_cli_without_url_opens_launcher():
    assert parse_cli([]) is None


def test_parse_cli_routes_direct_url():
    target = parse_cli(["https://arca.live/b/rogersfu"])
    assert target is not None
    assert target.site is Site.ARCA


def test_project_exposes_primary_and_compatibility_commands():
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    assert scripts == {
        "commu": "fmk_reader.app:main",
        "fmk": "fmk_reader.app:main",
    }
```

- [ ] **Step 2: Write failing launcher interaction tests**

```python
@pytest.mark.asyncio
async def test_launcher_recommended_arca_flow_returns_target():
    app = CommunityReaderApp(resource_factory=FakeResourceFactory())
    async with app.run_test() as pilot:
        await pilot.press("down", "down", "enter")
        await pilot.press("enter")
        await pilot.pause()
        assert app.target == route_url("https://arca.live/b/rogersfu")


@pytest.mark.asyncio
async def test_launcher_direct_url_validation_stays_local():
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)
    async with app.run_test() as pilot:
        await pilot.press("enter", "down", "enter")
        app.query_one("#target-url", Input).value = "https://example.com"
        await pilot.press("enter")
        assert factory.created == []
        assert app.query_one("#launcher-error", Static).renderable
```

- [ ] **Step 3: Run CLI/launcher tests and verify RED**

Run: `conda run -n basic-env pytest tests/test_cli.py tests/test_launcher.py -v`

Expected: collection fails because launcher and CLI parsing do not exist.

- [ ] **Step 4: Implement the launcher as an isolated Textual screen**

`LauncherScreen` must use `OptionList` for the three sites and the two access
methods, plus one initially hidden `Input(id="target-url")` and literal
`Static(id="launcher-error", markup=False)`. Up/Down/Enter come from
`OptionList`; Escape moves from URL input to access method and from access method
to site choice. The screen returns a validated `CommunityTarget` through its
callback and never creates network resources itself.

- [ ] **Step 5: Generalize app lifecycle and direct-article startup**

Rename the visible class to `CommunityReaderApp` and title to `Commu`. Preserve
`FmkReaderApp = CommunityReaderApp` for import compatibility. Add an injectable
resource factory whose production result owns raw client, cache, adapter, and
service. Resource creation happens only after target validation. Switching via
new `s` binding must cancel workers, close the old raw client, leave the shared
cache consistent, clear reader state, and reopen the launcher.

```python
@dataclass(slots=True)
class ReaderResources:
    raw_client: httpx.AsyncClient
    cache: JsonCache
    adapter: CommunityAdapter
    service: CommunityService


class ResourceFactory(Protocol):
    def __call__(self, target: CommunityTarget) -> ReaderResources: ...
```

The production factory creates `adapter_for(target)`, an httpx client with no
ambient cookies, `CommunityHttpClient(raw, adapter.policy)`, the shared cache
path `~/.cache/fmk-reader/cache.db`, and `CommunityService`. Test factories must
return caller-owned fakes so app shutdown does not close external resources.

For a direct article target, use `adapter.direct_post()`, show its loading state,
and call `load_post`. Escape from that article first loads/returns to the
inferred board. Board targets preserve existing list-first behavior. Keep all
existing worker request IDs, success-only page commits, coalescing, literal
markup handling, and responsive layout tests.

- [ ] **Step 6: Add CLI parsing and both entry points**

```python
def parse_cli(argv: Sequence[str]) -> CommunityTarget | None:
    parser = argparse.ArgumentParser(prog="commu")
    parser.add_argument("url", nargs="?")
    args = parser.parse_args(list(argv))
    return None if args.url is None else route_url(args.url)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    CommunityReaderApp(target=parse_cli(arguments)).run()
```

Set both `commu` and `fmk` scripts to the same entry point. Update package
description and visible strings from FMK-specific wording to community-reader
wording without renaming the import package in this feature. Migrate all app and
test imports to `CommunityHttpClient` and `CommunityService`, then remove the
temporary `FmkHttpClient` and `BoardService` wrappers introduced by Tasks 3 and
6. Keep only `FmkReaderApp = CommunityReaderApp` as public import compatibility.

- [ ] **Step 7: Run launcher, CLI, app, and full tests**

Run: `conda run -n basic-env pytest tests/test_cli.py tests/test_launcher.py tests/test_app.py -v`

Expected: all focused interaction tests pass.

Run: `conda run -n basic-env pytest -q`

Expected: the complete suite passes with no warnings or failures.

- [ ] **Step 8: Commit the launcher and command**

```bash
git add src/fmk_reader/app.py src/fmk_reader/launcher.py src/fmk_reader/__main__.py src/fmk_reader/styles.tcss pyproject.toml tests/test_app.py tests/test_launcher.py tests/test_cli.py
git commit -m "feat: add commu multi-site launcher"
```

---

### Task 8: Documentation, package installation, and conservative live verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-07-multi-community-adapters-design.md` only if implementation revealed a verified mismatch.

**Interfaces:**
- Consumes: all user-visible behavior from Tasks 1-7.
- Produces: copyable installation/usage instructions and final verification evidence.

- [ ] **Step 1: Update README with exact commands and supported URL forms**

Document:

```bash
cd /Users/hj/Desktop/project_code/terminal_community
conda activate basic-env
python -m pip install -e '.[dev]'
commu
commu https://arca.live/b/rogersfu
commu https://gall.dcinside.com/board/lists/?id=football_new9
```

Describe launcher keys, reader keys including `s`, recommended URLs, direct
board/article URL families, the `fmk` compatibility alias, version-two cache,
media placeholders, two-second spacing, 429/430 cooldown, and no-bypass policy.

- [ ] **Step 2: Run all offline quality gates**

Run: `conda run -n basic-env pytest -q`

Expected: all tests pass without warnings or live requests.

Run: `conda run -n basic-env ruff check .`

Expected: `All checks passed!`

Run: `conda run -n basic-env python -m compileall -q src tests`

Expected: exit code 0 and no output.

Run: `git diff --check`

Expected: exit code 0 and no output.

- [ ] **Step 3: Verify package entry points in `basic-env`**

Run: `conda run -n basic-env python -m pip install -e '.[dev]'`

Expected: editable installation succeeds.

Run: `conda run -n basic-env which commu`

Expected: `/Users/hj/miniforge3/envs/basic-env/bin/commu`.

Run: `conda run -n basic-env which fmk`

Expected: `/Users/hj/miniforge3/envs/basic-env/bin/fmk`.

- [ ] **Step 4: Perform one bounded live read per site**

Run each target once in a PTY and exit with `q` after list rendering:

```bash
conda run -n basic-env commu https://www.fmkorea.com/football_world
conda run -n basic-env commu https://gall.dcinside.com/board/lists/?id=football_new9
conda run -n basic-env commu https://arca.live/b/rogersfu
```

Expected: each either renders a parsed list or produces its typed rate-limit /
access error. Do not retry a failed target. For one accessible post per site,
verify Enter shows body and comments/placeholders; stop if the site returns a
challenge. Confirm `q` exits cleanly.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/superpowers/specs/2026-07-07-multi-community-adapters-design.md
git commit -m "docs: explain multi-community usage"
```

- [ ] **Step 6: Run final verification and inspect repository state**

Run: `conda run -n basic-env pytest -q`

Expected: all tests pass.

Run: `conda run -n basic-env python -c "from fmk_reader.app import CommunityReaderApp; print(CommunityReaderApp.TITLE)"`

Expected: `Commu`.

Run: `git status --short --branch`

Expected: branch header only; no modified or untracked files.
