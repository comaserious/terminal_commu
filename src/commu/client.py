from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from commu.adapters.base import PagePolicy, RequestPolicy
from commu.adapters.fmk import FmkAdapter
from commu.errors import AccessBlocked, FetchError, RateLimited
from commu.targets import Site


FMK_POLICY = FmkAdapter.policy


class _Session(Protocol):
    page: object


class _BrowserRuntime(Protocol):
    async def session_for(self, site: Site, policy: RequestPolicy) -> _Session: ...

    async def reset(self, site: Site, policy: RequestPolicy) -> _Session: ...


@dataclass(slots=True)
class CommunityRequestState:
    """Request timing and cooldown state shared by clients for one site."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_started: float | None = None
    retry_not_before: float | None = None


class RequestStateRegistry:
    """Own one request state per site for the registry's lifetime."""

    def __init__(self) -> None:
        self._states: dict[Site, CommunityRequestState] = {}

    def state_for(self, site: Site) -> CommunityRequestState:
        state = self._states.get(site)
        if state is None:
            state = CommunityRequestState()
            self._states[site] = state
        return state


DEFAULT_REQUEST_STATE_REGISTRY = RequestStateRegistry()


class _BrokenSession(Exception):
    pass


class _ChallengePage(Exception):
    def __init__(self, message: str = "", *, effective_url: str) -> None:
        super().__init__(message)
        self.effective_url = effective_url


class PlaywrightCommunityClient:
    """Fetch rendered HTML through a caller-owned persistent browser runtime."""

    _NAVIGATION_OPTIONS = {"wait_until": "domcontentloaded", "timeout": 10_000}

    def __init__(
        self,
        runtime: _BrowserRuntime,
        policy: RequestPolicy,
        state: CommunityRequestState | None = None,
        min_interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if min_interval is None:
            min_interval = policy.min_interval
        if min_interval < 0 or not math.isfinite(min_interval):
            raise ValueError("min_interval must be finite and non-negative")

        self._runtime = runtime
        self._policy = policy
        self._site_name = policy.site.display_name
        self._state = state or CommunityRequestState()
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._jitter = jitter

    async def get_text(self, url: str) -> str:
        self._validate_initial_origin(url)
        async with self._state.lock:
            self._raise_if_cooling_down()
            return await self._get_text_bounded(url)

    async def _get_text_bounded(self, url: str) -> str:
        challenge_reload_available = True
        session_reset_available = True
        fallback_available = self._policy.fallback_origin is not None
        current_url = url
        session = await self._session_for()

        while True:
            page = session.page
            try:
                if self._page_is_closed(page):
                    raise _BrokenSession
                html = await self._navigate(page, current_url)
            except _ChallengePage as challenge:
                challenge_message = str(challenge)
                challenge_effective_url = challenge.effective_url
                if challenge_reload_available:
                    challenge_reload_available = False
                    try:
                        html = await self._reload(page, current_url)
                    except _ChallengePage as reload_challenge:
                        challenge_message = str(reload_challenge)
                        challenge_effective_url = reload_challenge.effective_url
                    except (AccessBlocked, RateLimited, FetchError):
                        raise
                    except Exception as error:
                        if not session_reset_available:
                            raise FetchError(
                                f"{self._site_name} browser session failed"
                            ) from error
                        session_reset_available = False
                        session = await self._reset_session()
                        continue
                    else:
                        return html

                fallback_url = (
                    self._fallback_url(current_url, challenge_effective_url)
                    if fallback_available
                    else None
                )
                if fallback_url is None:
                    raise AccessBlocked(
                        challenge_message
                        or f"{self._site_name} returned a challenge page"
                    ) from None
                fallback_available = False
                current_url = fallback_url
                continue
            except (AccessBlocked, RateLimited, FetchError):
                raise
            except Exception as error:
                if not session_reset_available:
                    raise FetchError(
                        f"{self._site_name} browser session failed"
                    ) from error
                session_reset_available = False
                session = await self._reset_session()
                continue
            return html

    async def _navigate(self, page: object, url: str) -> str:
        await self._begin_navigation()
        try:
            response = await page.goto(url, **self._NAVIGATION_OPTIONS)
        except Exception as error:
            raise _BrokenSession from error
        return await self._read_response(page, response, url)

    async def _reload(self, page: object, url: str) -> str:
        await self._begin_navigation()
        response = await page.reload(**self._NAVIGATION_OPTIONS)
        return await self._read_response(page, response, url)

    async def _read_response(self, page: object, response: object, url: str) -> str:
        if response is None:
            raise FetchError(f"{self._site_name} navigation returned no response")
        self._validate_response(response)
        # Challenge documents often never attach the requested content root.
        # Detect their stable browser-visible markers before waiting for it.
        if await self._is_challenge(page):
            raise _ChallengePage(
                effective_url=self._validate_current_page(page)
            )
        selector = self._selector_for(url)
        try:
            await page.wait_for_selector(
                selector,
                state="attached",
                timeout=10_000,
            )
        except Exception:
            self._validate_current_page(page)
            try:
                html = await page.content()
            except Exception:
                html = None
            if await self._is_challenge(page, html):
                raise _ChallengePage(
                    effective_url=self._validate_current_page(page)
                ) from None
            self._validate_current_page(page)
            raise
        self._validate_current_page(page)
        html = await page.content()
        if await self._is_challenge(page, html):
            raise _ChallengePage(
                effective_url=self._validate_current_page(page)
            )
        self._validate_current_page(page)
        return html

    def _validate_response(self, response: object) -> None:
        response_url = str(getattr(response, "url", ""))
        if self._origin(response_url) not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected cross-origin response")

        status = int(getattr(response, "status", 0))
        headers = getattr(response, "headers", {})
        if status in self._policy.rate_limit_statuses:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            self._set_retry_deadline(retry_after)
            raise RateLimited(self._site_name, retry_after)
        if status in self._policy.blocked_statuses:
            raise _ChallengePage(
                f"{self._site_name} denied access",
                effective_url=response_url,
            )
        if not 200 <= status < 300:
            raise FetchError(f"{self._site_name} returned HTTP {status}")

    async def _is_challenge(self, page: object, html: str | None = None) -> bool:
        if html is not None and self._html_is_challenge(html):
            return True
        try:
            raw_title = await page.title()
        except Exception:
            raw_title = ""
        title = " ".join(raw_title.casefold().split()).rstrip(" .…")
        if title in {"access denied", "captcha", "complete captcha", "just a moment"}:
            return True
        for selector in self._policy.page_policy.challenge_selectors:
            try:
                if await page.query_selector(selector) is not None:
                    return True
            except Exception:
                continue
        return False

    def _html_is_challenge(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
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
        return any(
            soup.select_one(selector) is not None
            for selector in self._policy.page_policy.challenge_selectors
        )

    def _selector_for(self, url: str) -> str:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        segments = parsed.path.strip("/").split("/")
        if self._policy.site is Site.ARCA:
            is_post = (
                len(segments) == 3
                and segments[0] == "b"
                and segments[2].isdecimal()
            )
        elif self._policy.site is Site.DCINSIDE:
            is_post = (
                len(segments) == 3
                and segments[0] == "board"
                and segments[2].isdecimal()
            )
        else:
            document_ids = query.get("document_srl", [])
            is_post = (
                len(segments) == 1 and segments[0].isdecimal()
            ) or (
                len(document_ids) == 1 and document_ids[0].isdecimal()
            )
        page_policy: PagePolicy = self._policy.page_policy
        return page_policy.post_selector if is_post else page_policy.board_selector

    async def _begin_navigation(self) -> None:
        await self._wait_for_turn()
        self._state.last_started = self._clock()

    async def _session_for(self) -> _Session:
        try:
            return await self._runtime.session_for(self._policy.site, self._policy)
        except Exception as error:
            raise FetchError(f"{self._site_name} browser session failed") from error

    async def _reset_session(self) -> _Session:
        try:
            return await self._runtime.reset(self._policy.site, self._policy)
        except Exception as error:
            raise FetchError(f"{self._site_name} browser session reset failed") from error

    @staticmethod
    def _page_is_closed(page: object) -> bool:
        is_closed = getattr(page, "is_closed", None)
        return bool(callable(is_closed) and is_closed())

    async def _wait_for_turn(self) -> None:
        if self._state.last_started is None:
            return
        jitter = 0.0 if self._min_interval == 0 else self._jitter()
        if jitter < 0 or not math.isfinite(jitter):
            raise FetchError(f"{self._site_name} request jitter is invalid")
        not_before = self._state.last_started + self._min_interval + jitter
        delay = not_before - self._clock()
        if delay <= 0:
            return
        await self._sleep(delay)
        if self._clock() < not_before:
            raise FetchError(f"{self._site_name} request spacing could not be enforced")

    def _raise_if_cooling_down(self) -> None:
        if self._state.retry_not_before is None:
            return
        remaining = math.ceil(self._state.retry_not_before - self._clock())
        if remaining > 0:
            raise RateLimited(self._site_name, str(remaining))

    def _set_retry_deadline(self, retry_after: str | None) -> None:
        if retry_after is None:
            return
        try:
            delay = float(int(retry_after))
        except (ValueError, OverflowError):
            try:
                delay = parsedate_to_datetime(retry_after).timestamp() - self._wall_clock()
            except (TypeError, ValueError, OverflowError):
                return
        if delay <= 0:
            return
        deadline = self._clock() + delay
        current = self._state.retry_not_before
        self._state.retry_not_before = deadline if current is None else max(current, deadline)

    def _validate_initial_origin(self, url: str) -> None:
        if self._origin(url) not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected request origin")

    def _fallback_url(self, url: str, effective_url: str) -> str | None:
        fallback = self._policy.fallback_origin
        if fallback is None:
            return None

        requested_origin = self._origin(url)
        effective_origin = self._origin(effective_url)
        if effective_origin not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected challenge origin")
        if requested_origin == fallback or effective_origin != requested_origin:
            return None

        scheme, host, port = fallback
        if fallback not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected fallback origin")

        parsed = urlsplit(url)
        default_port = {"http": 80, "https": 443}.get(scheme)
        netloc = host if port == default_port else f"{host}:{port}"
        candidate = urlunsplit(
            (scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )
        if self._origin(candidate) not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected fallback origin")
        return candidate

    def _validate_current_page(self, page: object) -> str:
        current_url = str(getattr(page, "url", ""))
        if self._origin(current_url) not in self._policy.allowed_origins:
            raise FetchError(f"{self._site_name} rejected cross-origin current page")
        return current_url

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return "", "", -1
        scheme = parsed.scheme.casefold()
        if port is None:
            port = {"http": 80, "https": 443}.get(scheme, -1)
        return scheme, (parsed.hostname or "").casefold(), port
