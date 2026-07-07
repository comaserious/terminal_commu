from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from fmk_reader.adapters.base import RequestPolicy
from fmk_reader.adapters.fmk import FmkAdapter
from fmk_reader.cache import JsonCache
from fmk_reader.errors import AccessBlocked, FetchError, ParseError, RateLimited
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.parser import parse_board, parse_post
from fmk_reader.service import (
    CommunityService,
    DataSource,
    PostPage,
)
from fmk_reader.targets import CommunityTarget, Site, route_url


FIXTURES = Path(__file__).parent / "fixtures"
FMK_CACHE_PREFIX = "v2:fmkorea:football_world"
FMK_BOARD_URL = "https://www.fmkorea.com/football_world"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fmk_service(client: FakeClient, cache: JsonCache) -> CommunityService:
    target = route_url(FMK_BOARD_URL)
    return CommunityService(FmkAdapter(target), client, cache)


class FakeClient:
    def __init__(self, *results: str | Exception) -> None:
        self.results = list(results)
        self.urls: list[str] = []

    async def get_text(self, url: str) -> str:
        self.urls.append(url)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeAdapter:
    def __init__(
        self,
        target: CommunityTarget,
        *,
        parsed_post_id: str | None = None,
    ) -> None:
        self.target = target
        self.policy = RequestPolicy(
            site=target.site,
            user_agent="fake-reader",
            allowed_origins=frozenset(),
            rate_limit_statuses=frozenset(),
        )
        self.site_name = target.site.display_name
        self.parsed_post_id = parsed_post_id
        self.board_parse_calls: list[tuple[str, int]] = []
        self.post_parse_calls: list[tuple[str, PostSummary, int]] = []

    def board_url(self, page: int) -> str:
        return (
            self.target.board_url
            if page == 1
            else f"{self.target.board_url}?page={page}"
        )

    def post_url(self, post: PostSummary, cpage: int) -> str:
        return f"{self.target.board_url}/{post.post_id}?comments={cpage}"

    def direct_post(self) -> PostSummary | None:
        return None

    def parse_board(self, html: str, page: int) -> PageResult[PostSummary]:
        self.board_parse_calls.append((html, page))
        return PageResult(
            items=(self._post("42"),),
            page=page,
            has_previous=page > 1,
            has_next=False,
        )

    def parse_post(
        self,
        html: str,
        post: PostSummary,
        cpage: int,
    ) -> tuple[PostDetail, PageResult[Comment]]:
        self.post_parse_calls.append((html, post, cpage))
        summary = self._post(self.parsed_post_id or post.post_id)
        return (
            PostDetail(summary=summary, body=html, links=()),
            PageResult(
                items=(),
                page=cpage,
                has_previous=cpage > 1,
                has_next=False,
            ),
        )

    def _post(self, post_id: str) -> PostSummary:
        return PostSummary(
            post_id=post_id,
            title="테스트 글",
            category="",
            author="작성자",
            created_at="오늘",
            views="1",
            votes=0,
            comment_count=0,
            url=f"{self.target.board_url.rstrip('/')}/{post_id}",
            is_notice=False,
        )


async def seed_post(
    service: CommunityService,
    post_id: str,
) -> PostSummary:
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
    return post


async def test_service_uses_adapter_urls_and_site_namespaced_cache(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        CommunityTarget(
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
    assert adapter.board_parse_calls == [("<board />", 2)]
    assert result.source is DataSource.NETWORK
    assert cache.get("v2:arca:rogersfu:board:2", 60) is not None
    cache.close()


async def test_same_article_id_on_two_sites_has_distinct_cache_keys(
    tmp_path: Path,
) -> None:
    cache = JsonCache(tmp_path / "cache.db")
    dc_adapter = FakeAdapter(
        CommunityTarget(Site.DCINSIDE, "g", "https://m.dcinside.com/board/g")
    )
    arca_adapter = FakeAdapter(CommunityTarget(Site.ARCA, "g", "https://arca.live/b/g"))
    dc_client = FakeClient("dc")
    arca_client = FakeClient("arca")

    dc_post = await seed_post(CommunityService(dc_adapter, dc_client, cache), "42")
    arca_post = await seed_post(
        CommunityService(arca_adapter, arca_client, cache), "42"
    )

    assert dc_client.urls == [dc_adapter.post_url(dc_post, 1)]
    assert arca_client.urls == [arca_adapter.post_url(arca_post, 1)]
    assert dc_adapter.post_parse_calls == [("dc", dc_post, 1)]
    assert arca_adapter.post_parse_calls == [("arca", arca_post, 1)]
    assert cache.get("v2:dcinside:g:post:42:comments:1", 120) is not None
    assert cache.get("v2:arca:g:post:42:comments:1", 120) is not None
    cache.close()


async def test_service_rejects_adapter_post_id_mismatch_before_cache_writes(
    tmp_path: Path,
) -> None:
    cache = JsonCache(tmp_path / "cache.db")
    adapter = FakeAdapter(
        CommunityTarget(Site.ARCA, "g", "https://arca.live/b/g"),
        parsed_post_id="999",
    )
    service = CommunityService(adapter, FakeClient("mismatch"), cache)

    with pytest.raises(ParseError, match="post id mismatch"):
        await seed_post(service, "42")

    assert cache.get("v2:arca:g:post:42:comments:1", 120) is None
    assert cache.get("v2:arca:g:post:42:body", 1800) is None
    cache.close()


async def test_rate_limit_stale_warning_uses_adapter_site_and_retry_after(
    cache: JsonCache,
    clock: list[float],
) -> None:
    adapter = FakeAdapter(CommunityTarget(Site.ARCA, "g", "https://arca.live/b/g"))
    client = FakeClient("fresh", RateLimited("wrong site", "45"))
    service = CommunityService(adapter, client, cache)
    await service.load_board(1)
    clock[0] = 161.0

    result = await service.load_board(1)

    assert adapter.site_name in result.warning
    assert "wrong site" not in result.warning
    assert "Retry-After: 45" in result.warning


async def test_fetch_error_stale_warning_includes_typed_error_text(
    cache: JsonCache,
    clock: list[float],
) -> None:
    adapter = FakeAdapter(
        CommunityTarget(Site.DCINSIDE, "g", "https://m.dcinside.com/board/g")
    )
    client = FakeClient("fresh", FetchError("socket closed"))
    service = CommunityService(adapter, client, cache)
    await service.load_board(1)
    clock[0] = 161.0

    result = await service.load_board(1)

    assert "socket closed" in result.warning
    assert "현재 커뮤니티에 연결할 수 없어" in result.warning


@pytest.fixture
def clock() -> list[float]:
    return [100.0]


@pytest.fixture
def cache(tmp_path: Path, clock: list[float]) -> Iterator[JsonCache]:
    with closing(
        JsonCache(tmp_path / "service-cache.db", clock=lambda: clock[0])
    ) as result:
        yield result


def board_post() -> PostSummary:
    return parse_board(fixture("board.html"), page=1).items[0]


async def test_load_board_fetches_once_then_returns_exact_cached_model(
    cache: JsonCache,
) -> None:
    client = FakeClient(fixture("board.html"))
    service = fmk_service(client, cache)
    expected = parse_board(fixture("board.html"), page=1)

    first = await service.load_board(1)
    second = await service.load_board(1)

    assert first.value == expected
    assert first.source is DataSource.NETWORK
    assert first.warning == ""
    assert second.value == expected
    assert second.source is DataSource.CACHE
    assert second.warning == ""
    assert client.urls == [FMK_BOARD_URL]


async def test_expired_board_uses_stale_cache_after_rate_limit(
    cache: JsonCache,
    clock: list[float],
) -> None:
    client = FakeClient(fixture("board.html"), RateLimited("FMKorea", "30"))
    service = fmk_service(client, cache)
    expected = (await service.load_board(1)).value
    clock[0] = 161.0

    result = await service.load_board(1)

    assert result.value == expected
    assert result.source is DataSource.STALE_CACHE
    assert "30" in result.warning
    assert re.search(r"[가-힣]", result.warning)


async def test_refresh_bypasses_fresh_board_cache_and_replaces_it(
    cache: JsonCache,
) -> None:
    original = fixture("board.html")
    updated = original.replace("일반 글", "새로운 글", 1)
    client = FakeClient(original, updated)
    service = fmk_service(client, cache)

    await service.load_board(1)
    refreshed = await service.load_board(1, refresh=True)
    cached = await service.load_board(1)

    assert refreshed.source is DataSource.NETWORK
    assert refreshed.value.items[0].title == "새로운 글"
    assert cached.source is DataSource.CACHE
    assert cached.value == refreshed.value
    assert client.urls == [FMK_BOARD_URL, FMK_BOARD_URL]


async def test_load_board_uses_exact_page_urls(cache: JsonCache) -> None:
    client = FakeClient(fixture("board.html"), fixture("board.html"))
    service = fmk_service(client, cache)

    await service.load_board(1)
    await service.load_board(2)

    assert client.urls == [
        "https://www.fmkorea.com/football_world",
        "https://www.fmkorea.com/index.php?mid=football_world&page=2",
    ]


@pytest.mark.parametrize(
    ("cpage", "expected_url"),
    [
        (1, "https://www.fmkorea.com/100"),
        (
            2,
            "https://www.fmkorea.com/index.php?mid=football_world"
            "&document_srl=100&cpage=2",
        ),
    ],
)
async def test_load_post_uses_exact_url_and_caches_combined_and_body(
    cache: JsonCache,
    cpage: int,
    expected_url: str,
) -> None:
    post = board_post()
    client = FakeClient(fixture("post.html"))
    service = fmk_service(client, cache)
    expected_detail, expected_comments = parse_post(
        fixture("post.html"), post.url, cpage
    )

    result = await service.load_post(post, cpage=cpage)

    assert result.value == PostPage(
        detail=expected_detail,
        comments=expected_comments,
    )
    assert result.source is DataSource.NETWORK
    assert client.urls == [expected_url]
    combined = cache.get(
        f"{FMK_CACHE_PREFIX}:post:{post.post_id}:comments:{cpage}", ttl=120.0
    )
    body = cache.get(f"{FMK_CACHE_PREFIX}:post:{post.post_id}:body", ttl=1800.0)
    assert combined is not None
    assert combined.value == result.value.to_dict()
    assert body is not None
    assert body.value == result.value.detail.to_dict()


async def test_fresh_post_page_cache_avoids_network(cache: JsonCache) -> None:
    post = board_post()
    client = FakeClient(fixture("post.html"))
    service = fmk_service(client, cache)
    expected = await service.load_post(post)

    cached = await service.load_post(post)

    assert cached.value == expected.value
    assert cached.source is DataSource.CACHE
    assert client.urls == [post.url]


async def test_load_post_rejects_mismatched_response_before_cache_write(
    cache: JsonCache,
) -> None:
    post = board_post()
    valid_html = fixture("post.html")
    mismatched_html = valid_html.replace('data-docSrl="100"', 'data-docSrl="999"', 1)
    client = FakeClient(valid_html, mismatched_html)
    service = fmk_service(client, cache)
    original = await service.load_post(post)

    with pytest.raises(ParseError, match="post id mismatch"):
        await service.load_post(post, refresh=True)

    combined = cache.get(
        f"{FMK_CACHE_PREFIX}:post:{post.post_id}:comments:1", ttl=120.0
    )
    body = cache.get(f"{FMK_CACHE_PREFIX}:post:{post.post_id}:body", ttl=1800.0)
    assert combined is not None
    assert combined.value == original.value.to_dict()
    assert body is not None
    assert body.value == original.value.detail.to_dict()


async def test_expired_combined_post_cache_is_stale_fallback(
    cache: JsonCache,
    clock: list[float],
) -> None:
    post = board_post()
    client = FakeClient(fixture("post.html"), FetchError("offline"))
    service = fmk_service(client, cache)
    expected = (await service.load_post(post)).value
    clock[0] = 221.0

    result = await service.load_post(post)

    assert result.value == expected
    assert result.source is DataSource.STALE_CACHE
    assert re.search(r"[가-힣]", result.warning)


async def test_cached_body_is_fallback_with_empty_requested_comment_page(
    cache: JsonCache,
) -> None:
    post = board_post()
    client = FakeClient(fixture("post.html"), FetchError("offline"))
    service = fmk_service(client, cache)
    original = await service.load_post(post, cpage=1)

    result = await service.load_post(post, cpage=2)

    assert result.value.detail == original.value.detail
    assert result.value.comments == PageResult[Comment](
        items=(),
        page=2,
        has_previous=True,
        has_next=False,
    )
    assert result.source is DataSource.STALE_CACHE
    assert re.search(r"[가-힣]", result.warning)


@pytest.mark.parametrize(
    "error",
    [
        FetchError("offline"),
        AccessBlocked("blocked"),
        RateLimited("FMKorea", "30"),
    ],
)
async def test_fetch_failures_propagate_without_any_post_cache(
    cache: JsonCache,
    error: FetchError,
) -> None:
    client = FakeClient(error)
    service = fmk_service(client, cache)

    with pytest.raises(type(error)) as raised:
        await service.load_post(board_post())

    assert raised.value is error


async def test_parse_error_propagates_instead_of_using_stale_board(
    cache: JsonCache,
    clock: list[float],
) -> None:
    client = FakeClient(fixture("board.html"), "<html></html>")
    service = fmk_service(client, cache)
    await service.load_board(1)
    clock[0] = 161.0

    with pytest.raises(ParseError, match="missing board rows"):
        await service.load_board(1)


async def test_malformed_strict_board_cache_is_a_miss_and_gets_replaced(
    cache: JsonCache,
) -> None:
    cache.put(
        f"{FMK_CACHE_PREFIX}:board:1",
        {
            "items": [],
            "page": "not-an-integer",
            "has_previous": False,
            "has_next": False,
        },
    )
    client = FakeClient(fixture("board.html"))
    service = fmk_service(client, cache)

    result = await service.load_board(1)

    assert result.source is DataSource.NETWORK
    assert result.value == parse_board(fixture("board.html"), page=1)
    assert client.urls == [FMK_BOARD_URL]


def test_post_page_strict_round_trip() -> None:
    detail, comments = parse_post(
        fixture("post.html"), "https://www.fmkorea.com/100", cpage=1
    )
    page = PostPage(detail=detail, comments=comments)

    assert PostPage.from_dict(page.to_dict()) == page


@pytest.mark.parametrize(
    "malformed",
    [
        {"detail": {}, "comments": {}},
        {"detail": {}, "comments": {}, "extra": True},
    ],
)
def test_post_page_from_dict_uses_strict_nested_models(
    malformed: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PostPage.from_dict(malformed)
