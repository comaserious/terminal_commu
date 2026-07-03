import asyncio

import httpx
import pytest

from fmk_reader.client import FmkHttpClient, make_httpx_client
from fmk_reader.errors import AccessBlocked, FetchError, RateLimited


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


@pytest.mark.asyncio
async def test_sequential_requests_are_spaced_from_their_start_times() -> None:
    clock = FakeClock(10.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, clock=clock, sleep=clock.sleep)

        first = await client.get_text("https://www.fmkorea.com/first")
        second = await client.get_text("https://www.fmkorea.com/second")

    assert first == "/first"
    assert second == "/second"
    assert clock.sleeps == [2.0]


@pytest.mark.asyncio
async def test_rate_limit_and_access_denial_map_to_typed_errors() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(403),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    clock = FakeClock(10.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, clock=clock, sleep=clock.sleep)

        with pytest.raises(RateLimited) as rate_limited:
            await client.get_text("https://www.fmkorea.com/rate-limited")
        with pytest.raises(AccessBlocked, match="FMKorea denied access"):
            await client.get_text("https://www.fmkorea.com/forbidden")

    assert rate_limited.value.retry_after == "30"
    assert clock.sleeps == [2.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (httpx.ReadTimeout, "FMKorea request timed out"),
        (httpx.ConnectError, "FMKorea request failed"),
    ],
)
async def test_transport_errors_map_to_fetch_error(
    error_type: type[httpx.RequestError], message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("network failure", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        with pytest.raises(FetchError, match=message):
            await client.get_text("https://www.fmkorea.com/post")


@pytest.mark.asyncio
async def test_other_http_error_maps_to_fetch_error_with_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        with pytest.raises(FetchError, match="FMKorea returned HTTP 500"):
            await client.get_text("https://www.fmkorea.com/post")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["Please complete CAPTCHA", "ACCESS DENIED"])
async def test_challenge_page_maps_to_access_blocked(body: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        with pytest.raises(AccessBlocked, match="FMKorea returned a challenge page"):
            await client.get_text("https://www.fmkorea.com/post")


@pytest.mark.asyncio
async def test_response_cookies_are_neither_stored_nor_sent() -> None:
    cookie_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cookie_headers.append(request.headers.get("Cookie"))
        headers = {"Set-Cookie": "session=secret"} if len(cookie_headers) == 1 else {}
        return httpx.Response(200, headers=headers, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        await client.get_text("https://www.fmkorea.com/first")
        await client.get_text("https://www.fmkorea.com/second")

        assert cookie_headers == [None, None]
        assert len(raw_client.cookies.jar) == 0


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized_through_response_completion() -> None:
    in_flight = 0
    max_in_flight = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await asyncio.sleep(0.01)
            return httpx.Response(200, text=request.url.path)
        finally:
            in_flight -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        results = await asyncio.gather(
            client.get_text("https://www.fmkorea.com/one"),
            client.get_text("https://www.fmkorea.com/two"),
        )

    assert results == ["/one", "/two"]
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_default_httpx_client_configuration() -> None:
    raw_client = make_httpx_client()
    try:
        assert raw_client.follow_redirects is True
        assert raw_client.timeout.read == 10.0
        assert raw_client.timeout.write == 10.0
        assert raw_client.timeout.pool == 10.0
        assert raw_client.timeout.connect == 5.0
        assert raw_client.headers["User-Agent"] == (
            "fmk-reader/0.1 personal read-only client"
        )
        assert raw_client.headers["Accept-Language"] == "ko-KR,ko;q=0.9"
    finally:
        await raw_client.aclose()

    assert raw_client.is_closed
