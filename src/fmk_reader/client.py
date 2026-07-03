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
        self._client = client
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_started: float | None = None
        self._lock = asyncio.Lock()

    async def get_text(self, url: str) -> str:
        async with self._lock:
            if self._last_started is not None:
                delay = self._min_interval - (self._clock() - self._last_started)
                if delay > 0:
                    await self._sleep(delay)

            self._last_started = self._clock()
            self._clear_cookies()
            try:
                response = await self._client.get(url)
            except httpx.TimeoutException as exc:
                raise FetchError("FMKorea request timed out") from exc
            except httpx.HTTPError as exc:
                raise FetchError("FMKorea request failed") from exc
            finally:
                self._clear_cookies()

        if response.status_code == 429:
            raise RateLimited(response.headers.get("Retry-After"))
        if response.status_code == 403:
            raise AccessBlocked("FMKorea denied access")
        if response.is_error:
            raise FetchError(f"FMKorea returned HTTP {response.status_code}")

        text = response.text
        normalized_text = text.casefold()
        if "captcha" in normalized_text or "access denied" in normalized_text:
            raise AccessBlocked("FMKorea returned a challenge page")
        return text

    def _clear_cookies(self) -> None:
        cookies = getattr(self._client, "cookies", None)
        clear = getattr(cookies, "clear", None)
        if callable(clear):
            clear()


def make_httpx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={
            "User-Agent": "fmk-reader/0.1 personal read-only client",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
