from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from fmk_reader.cache import JsonCache
from fmk_reader.errors import AccessBlocked, FetchError, ParseError, RateLimited
from fmk_reader.models import Comment, PageResult, PostSummary
from fmk_reader.parser import parse_board, parse_post
from fmk_reader.service import BOARD_URL, BoardService, DataSource, PostPage


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


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
    service = BoardService(client, cache)
    expected = parse_board(fixture("board.html"), page=1)

    first = await service.load_board(1)
    second = await service.load_board(1)

    assert first.value == expected
    assert first.source is DataSource.NETWORK
    assert first.warning == ""
    assert second.value == expected
    assert second.source is DataSource.CACHE
    assert second.warning == ""
    assert client.urls == [BOARD_URL]


async def test_expired_board_uses_stale_cache_after_rate_limit(
    cache: JsonCache,
    clock: list[float],
) -> None:
    client = FakeClient(fixture("board.html"), RateLimited("30"))
    service = BoardService(client, cache)
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
    service = BoardService(client, cache)

    await service.load_board(1)
    refreshed = await service.load_board(1, refresh=True)
    cached = await service.load_board(1)

    assert refreshed.source is DataSource.NETWORK
    assert refreshed.value.items[0].title == "새로운 글"
    assert cached.source is DataSource.CACHE
    assert cached.value == refreshed.value
    assert client.urls == [BOARD_URL, BOARD_URL]


async def test_load_board_uses_exact_page_urls(cache: JsonCache) -> None:
    client = FakeClient(fixture("board.html"), fixture("board.html"))
    service = BoardService(client, cache)

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
    service = BoardService(client, cache)
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
        f"post:{post.post_id}:comments:{cpage}", ttl=120.0
    )
    body = cache.get(f"post:{post.post_id}:body", ttl=1800.0)
    assert combined is not None
    assert combined.value == result.value.to_dict()
    assert body is not None
    assert body.value == result.value.detail.to_dict()


async def test_fresh_post_page_cache_avoids_network(cache: JsonCache) -> None:
    post = board_post()
    client = FakeClient(fixture("post.html"))
    service = BoardService(client, cache)
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
    mismatched_html = valid_html.replace(
        'data-docSrl="100"', 'data-docSrl="999"', 1
    )
    client = FakeClient(valid_html, mismatched_html)
    service = BoardService(client, cache)
    original = await service.load_post(post)

    with pytest.raises(ParseError, match="post id mismatch"):
        await service.load_post(post, refresh=True)

    combined = cache.get(f"post:{post.post_id}:comments:1", ttl=120.0)
    body = cache.get(f"post:{post.post_id}:body", ttl=1800.0)
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
    service = BoardService(client, cache)
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
    service = BoardService(client, cache)
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
        RateLimited("30"),
    ],
)
async def test_fetch_failures_propagate_without_any_post_cache(
    cache: JsonCache,
    error: FetchError,
) -> None:
    client = FakeClient(error)
    service = BoardService(client, cache)

    with pytest.raises(type(error)) as raised:
        await service.load_post(board_post())

    assert raised.value is error


async def test_parse_error_propagates_instead_of_using_stale_board(
    cache: JsonCache,
    clock: list[float],
) -> None:
    client = FakeClient(fixture("board.html"), "<html></html>")
    service = BoardService(client, cache)
    await service.load_board(1)
    clock[0] = 161.0

    with pytest.raises(ParseError, match="missing board rows"):
        await service.load_board(1)


async def test_malformed_strict_board_cache_is_a_miss_and_gets_replaced(
    cache: JsonCache,
) -> None:
    cache.put(
        "board:1",
        {
            "items": [],
            "page": "not-an-integer",
            "has_previous": False,
            "has_next": False,
        },
    )
    client = FakeClient(fixture("board.html"))
    service = BoardService(client, cache)

    result = await service.load_board(1)

    assert result.source is DataSource.NETWORK
    assert result.value == parse_board(fixture("board.html"), page=1)
    assert client.urls == [BOARD_URL]


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
