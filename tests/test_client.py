import asyncio
from email.utils import formatdate

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
@pytest.mark.parametrize("min_interval", [-1.0, float("inf"), float("nan")])
async def test_min_interval_must_be_finite_and_non_negative(
    min_interval: float,
) -> None:
    async with httpx.AsyncClient() as raw_client:
        with pytest.raises(ValueError, match="min_interval"):
            FmkHttpClient(raw_client, min_interval=min_interval)


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
async def test_early_returning_sleeper_cannot_bypass_spacing() -> None:
    request_count = 0
    clock = FakeClock(10.0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, text="ok")

    async def early_sleep(delay: float) -> None:
        clock.sleeps.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, clock=clock, sleep=early_sleep)

        assert await client.get_text("https://www.fmkorea.com/first") == "ok"
        with pytest.raises(FetchError, match="spacing"):
            await client.get_text("https://www.fmkorea.com/second")

    assert request_count == 1
    assert clock.sleeps == [2.0]


@pytest.mark.asyncio
async def test_rate_limit_and_access_denial_map_to_typed_errors() -> None:
    requested_paths: list[str] = []
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(403),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return next(responses)

    clock = FakeClock(10.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, clock=clock, sleep=clock.sleep)

        with pytest.raises(RateLimited) as rate_limited:
            await client.get_text("https://www.fmkorea.com/rate-limited")
        assert requested_paths == ["/rate-limited"]

        with pytest.raises(AccessBlocked, match="FMKorea denied access"):
            await client.get_text("https://www.fmkorea.com/forbidden")

    assert rate_limited.value.retry_after == "30"
    assert clock.sleeps == [30.0]


@pytest.mark.asyncio
async def test_http_date_retry_after_sets_monotonic_cooldown() -> None:
    wall_now = 1_700_000_000.0
    responses = iter(
        [
            httpx.Response(
                429,
                headers={"Retry-After": formatdate(wall_now + 20, usegmt=True)},
            ),
            httpx.Response(200, text="ok"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    clock = FakeClock(10.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(
            raw_client,
            clock=clock,
            sleep=clock.sleep,
            wall_clock=lambda: wall_now,
        )

        with pytest.raises(RateLimited):
            await client.get_text("https://www.fmkorea.com/rate-limited")
        assert await client.get_text("https://www.fmkorea.com/next") == "ok"

    assert clock.sleeps == [20.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_after",
    ["not-a-retry-date", "Wed, 21 Oct 2015 07:28:00 GMT"],
)
async def test_invalid_or_past_retry_after_uses_normal_spacing(
    retry_after: str,
) -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": retry_after}),
            httpx.Response(200, text="ok"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    clock = FakeClock(10.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(
            raw_client,
            clock=clock,
            sleep=clock.sleep,
            wall_clock=lambda: 1_700_000_000.0,
        )

        with pytest.raises(RateLimited):
            await client.get_text("https://www.fmkorea.com/rate-limited")
        assert await client.get_text("https://www.fmkorea.com/next") == "ok"

    assert clock.sleeps == [2.0]


@pytest.mark.asyncio
async def test_overflowing_retry_after_is_ignored_without_masking_rate_limit() -> None:
    retry_after = "9" * 400
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": retry_after}),
            httpx.Response(200, text="ok"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    clock = FakeClock(10.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, clock=clock, sleep=clock.sleep)

        with pytest.raises(RateLimited) as rate_limited:
            await client.get_text("https://www.fmkorea.com/rate-limited")
        assert rate_limited.value.retry_after == retry_after
        assert await client.get_text("https://www.fmkorea.com/next") == "ok"

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
async def test_http_status_error_preserves_status_and_clears_cookies() -> None:
    cookie_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cookie_headers.append(request.headers.get("Cookie"))
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError(
            "bad gateway",
            request=request,
            response=response,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        cookies={"session": "secret"},
    ) as raw_client:
        client = FmkHttpClient(raw_client)

        with pytest.raises(FetchError, match="FMKorea returned HTTP 502"):
            await client.get_text("https://www.fmkorea.com/post")

        assert cookie_headers == [None]
        assert len(raw_client.cookies.jar) == 0


@pytest.mark.asyncio
async def test_other_http_error_maps_to_fetch_error_with_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        with pytest.raises(FetchError, match="FMKorea returned HTTP 500"):
            await client.get_text("https://www.fmkorea.com/post")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "<article>This article explains why a captcha can appear.</article>",
        "<article>The quoted server response was ACCESS DENIED.</article>",
    ],
)
async def test_article_text_mentioning_challenges_is_returned(body: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        assert await client.get_text("https://www.fmkorea.com/post") == body


@pytest.mark.asyncio
async def test_article_title_mentioning_captcha_is_returned() -> None:
    body = (
        "<html><head><title>Why CAPTCHA appears - FMKorea</title></head>"
        "<body><article>Ordinary article content.</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client)

        assert await client.get_text("https://www.fmkorea.com/post") == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "<html><head><title>Access Denied</title></head><body></body></html>",
        "<html><head><title>CAPTCHA</title></head><body></body></html>",
        '<form id="captcha-form"><input name="captcha_token"></form>',
        '<div class="captcha-container">Verify that you are human</div>',
    ],
)
async def test_structural_challenge_page_maps_to_access_blocked(body: str) -> None:
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
async def test_redirects_neither_store_nor_forward_cookies() -> None:
    requests: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, request.headers.get("Cookie")))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={
                    "Location": "/final",
                    "Set-Cookie": "session=secret",
                },
            )
        return httpx.Response(200, text="done")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"Cookie": "default=secret"},
    ) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        assert await client.get_text("https://www.fmkorea.com/start") == "done"

        assert requests == [("/start", None), ("/final", None)]
        assert len(raw_client.cookies.jar) == 0


@pytest.mark.asyncio
async def test_cross_origin_redirect_is_rejected_before_sending_secrets() -> None:
    requests: list[tuple[str, str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                str(request.url),
                request.headers.get("Authorization"),
                request.headers.get("X-API-Key"),
            )
        )
        return httpx.Response(
            302,
            headers={"Location": "https://other.test/collect"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": "Bearer secret",
            "X-API-Key": "api-secret",
        },
    ) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        with pytest.raises(FetchError, match="cross-origin redirect"):
            await client.get_text("https://www.fmkorea.com/start")

    assert requests == [
        (
            "https://www.fmkorea.com/start",
            "Bearer secret",
            "api-secret",
        )
    ]


@pytest.mark.asyncio
async def test_redirect_without_location_is_a_fetch_error_and_clears_cookies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Set-Cookie": "session=secret"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        with pytest.raises(FetchError, match="HTTP 302"):
            await client.get_text("https://www.fmkorea.com/start")

        assert len(raw_client.cookies.jar) == 0


@pytest.mark.asyncio
async def test_redirect_limit_is_enforced_and_cookies_are_cleared() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            302,
            headers={
                "Location": "/loop",
                "Set-Cookie": "session=secret",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        with pytest.raises(FetchError, match="redirect limit"):
            await client.get_text("https://www.fmkorea.com/loop")

        assert request_count == 6
        assert len(raw_client.cookies.jar) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [101, 304])
async def test_terminal_informational_or_redirect_status_is_a_fetch_error(
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)

        with pytest.raises(FetchError, match=f"HTTP {status}"):
            await client.get_text("https://www.fmkorea.com/post")


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
async def test_cancellation_releases_lock_and_clears_cookies() -> None:
    request_started = asyncio.Event()
    request_count = 0
    cookie_headers: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        cookie_headers.append(request.headers.get("Cookie"))
        if request_count == 1:
            raw_client.cookies.set(
                "session",
                "secret",
                domain="www.fmkorea.com",
                path="/",
            )
            request_started.set()
            await asyncio.Event().wait()
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        client = FmkHttpClient(raw_client, min_interval=0)
        cancelled_request = asyncio.create_task(
            client.get_text("https://www.fmkorea.com/cancelled")
        )
        await request_started.wait()

        cancelled_request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_request

        assert len(raw_client.cookies.jar) == 0
        assert (
            await asyncio.wait_for(
                client.get_text("https://www.fmkorea.com/next"),
                timeout=1.0,
            )
            == "ok"
        )

    assert request_count == 2
    assert cookie_headers == [None, None]


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
