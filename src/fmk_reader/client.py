import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup

from fmk_reader.adapters.base import RequestPolicy
from fmk_reader.adapters.fmk import FmkAdapter
from fmk_reader.errors import AccessBlocked, FetchError, RateLimited

FMK_POLICY = FmkAdapter.policy


class CommunityHttpClient:
    """Stateless community requests over a caller-owned async client.

    This wrapper exclusively controls the injected client's request session state,
    while the caller remains responsible for closing the client.
    """

    _REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
    _MAX_REDIRECTS = 5

    def __init__(
        self,
        raw: httpx.AsyncClient,
        policy: RequestPolicy,
        min_interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if min_interval is None:
            min_interval = policy.min_interval
        if min_interval < 0 or not math.isfinite(min_interval):
            raise ValueError("min_interval must be finite and non-negative")

        self._client = raw
        self._policy = policy
        self._site_name = policy.site.display_name
        self._site_headers = _headers_for_policy(policy)
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._last_started: float | None = None
        self._retry_not_before: float | None = None
        self._lock = asyncio.Lock()

    async def get_text(self, url: str) -> str:
        async with self._lock:
            self._raise_if_cooling_down()
            try:
                response = await self._request(url)
            except httpx.TimeoutException as exc:
                raise FetchError(f"{self._site_name} request timed out") from exc
            except httpx.HTTPStatusError as exc:
                raise FetchError(
                    f"{self._site_name} returned HTTP {exc.response.status_code}"
                ) from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"{self._site_name} request failed") from exc

            if response.status_code in self._policy.rate_limit_statuses:
                retry_after = response.headers.get("Retry-After")
                self._set_retry_deadline(retry_after)
                raise RateLimited(self._site_name, retry_after)

        if response.status_code in self._policy.blocked_statuses:
            raise AccessBlocked(f"{self._site_name} denied access")
        if not response.is_success:
            raise FetchError(f"{self._site_name} returned HTTP {response.status_code}")

        text = response.text
        if self._is_challenge_page(text):
            raise AccessBlocked(f"{self._site_name} returned a challenge page")
        return text

    @staticmethod
    def _is_challenge_page(text: str) -> bool:
        soup = BeautifulSoup(text, "html.parser")
        if soup.title is not None:
            title = " ".join(
                soup.title.get_text(" ", strip=True).casefold().split()
            ).rstrip(" .…")
            if title in {
                "access denied",
                "captcha",
                "complete captcha",
                "just a moment",
            }:
                return True

        for element in soup.find_all(True):
            attributes = [element.get("id"), element.get("class")]
            if element.name in {"form", "input"}:
                attributes.extend(
                    [
                        element.get("name"),
                        element.get("action"),
                        element.get("type"),
                    ]
                )
            markers = " ".join(
                str(value)
                for value in attributes
                if value is not None
            ).casefold()
            if "captcha" in markers:
                return True
        return False

    async def _wait_for_turn(self) -> None:
        now = self._clock()
        not_before = now
        if self._last_started is not None:
            not_before = max(not_before, self._last_started + self._min_interval)

        delay = not_before - now
        if delay <= 0:
            return
        await self._sleep(delay)
        if self._clock() < not_before:
            raise FetchError(
                f"{self._site_name} request spacing could not be enforced"
            )

    def _raise_if_cooling_down(self) -> None:
        if self._retry_not_before is None:
            return
        remaining = math.ceil(self._retry_not_before - self._clock())
        if remaining > 0:
            raise RateLimited(self._site_name, str(remaining))

    async def _request(self, url: str) -> httpx.Response:
        current_url = url
        for redirect_count in range(self._MAX_REDIRECTS + 1):
            if self._origin(httpx.URL(current_url)) not in self._policy.allowed_origins:
                raise FetchError(f"{self._site_name} rejected request origin")
            await self._wait_for_turn()
            self._last_started = self._clock()
            response = await self._send_without_state(current_url)
            if response.status_code not in self._REDIRECT_STATUSES:
                return response

            location = response.headers.get("Location")
            if not location:
                raise FetchError(
                    f"{self._site_name} returned HTTP {response.status_code} "
                    "without a redirect location"
                )
            if redirect_count == self._MAX_REDIRECTS:
                raise FetchError(
                    f"{self._site_name} redirect limit exceeded at HTTP "
                    f"{response.status_code}"
                )
            redirect_url = response.url.join(location)
            if self._origin(redirect_url) not in self._policy.allowed_origins:
                raise FetchError(
                    f"{self._site_name} rejected cross-origin redirect"
                )
            current_url = str(redirect_url)

        raise FetchError(f"{self._site_name} redirect limit exceeded")

    async def _send_without_state(self, url: str) -> httpx.Response:
        self._clear_cookies()
        try:
            build_request = getattr(self._client, "build_request", None)
            send = getattr(self._client, "send", None)
            if callable(build_request) and callable(send):
                request = build_request("GET", url, headers=self._site_headers)
                request.headers.pop("cookie", None)
                return await send(request, follow_redirects=False)
            return await self._client.get(url, headers=self._site_headers)
        finally:
            self._clear_cookies()

    def _clear_cookies(self) -> None:
        cookies = getattr(self._client, "cookies", None)
        clear = getattr(cookies, "clear", None)
        if callable(clear):
            clear()

    @staticmethod
    def _origin(url: httpx.URL) -> tuple[str, str, int]:
        scheme = url.scheme.casefold()
        port = url.port
        if port is None:
            port = {"http": 80, "https": 443}.get(scheme)
        return scheme, url.host.casefold(), port or -1

    def _set_retry_deadline(self, retry_after: str | None) -> None:
        if retry_after is None:
            return

        try:
            delta_seconds = int(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                delay = retry_at.timestamp() - self._wall_clock()
            except (TypeError, ValueError, OverflowError):
                return
        else:
            try:
                delay = float(delta_seconds)
            except OverflowError:
                return

        if delay > 0:
            self._retry_not_before = self._clock() + delay


def _headers_for_policy(policy: RequestPolicy) -> dict[str, str]:
    return {
        "User-Agent": policy.user_agent,
        "Accept-Language": "ko-KR,ko;q=0.9",
    }


def make_httpx_client(policy: RequestPolicy = FMK_POLICY) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers=_headers_for_policy(policy),
    )
