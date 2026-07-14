from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from commu.adapters.base import RequestPolicy
from commu.paths import browser_state_path
from commu.targets import Site


@dataclass(slots=True)
class BrowserSession:
    context: BrowserContext
    page: Page


class BrowserRuntime:
    def __init__(
        self,
        playwright_factory: Callable[[], Any] = async_playwright,
        state_path: Callable[[Site], Path] = browser_state_path,
    ) -> None:
        self._factory = playwright_factory
        self._state_path = state_path
        self._playwright: Any | None = None
        self._browser: Browser | None = None
        self._sessions: dict[Site, BrowserSession] = {}
        self._start_lock = asyncio.Lock()
        self._session_locks = {site: asyncio.Lock() for site in Site}

    async def start(self) -> None:
        if self._browser is not None:
            return

        async with self._start_lock:
            if self._browser is not None:
                return

            manager = self._factory()
            try:
                playwright = await manager.start()
            except BaseException as error:
                try:
                    await manager.__aexit__(type(error), error, error.__traceback__)
                except BaseException as cleanup_error:
                    error.add_note(f"Playwright cleanup failed: {cleanup_error!r}")
                raise
            try:
                browser = await playwright.chromium.launch(headless=True)
            except BaseException as error:
                try:
                    await playwright.stop()
                except BaseException as cleanup_error:
                    error.add_note(f"Playwright cleanup failed: {cleanup_error!r}")
                raise

            self._playwright = playwright
            self._browser = browser

    async def session_for(
        self,
        site: Site,
        policy: RequestPolicy,
    ) -> BrowserSession:
        async with self._session_locks[site]:
            return await self._session_for_locked(site, policy)

    async def _session_for_locked(
        self,
        site: Site,
        policy: RequestPolicy,
    ) -> BrowserSession:
        await self.start()
        existing = self._sessions.get(site)
        if existing is not None:
            return existing

        options: dict[str, object] = {"locale": "ko-KR"}
        if policy.user_agent is not None:
            options["user_agent"] = policy.user_agent
        state = self._load_state(site)
        if state is not None:
            options["storage_state"] = state

        if self._browser is None:
            raise RuntimeError("browser runtime failed to start")
        try:
            context = await self._browser.new_context(**options)
        except Exception:
            if state is None:
                raise
            options.pop("storage_state")
            context = await self._browser.new_context(**options)
        try:
            page = await context.new_page()
        except BaseException as error:
            try:
                await context.close()
            except BaseException as cleanup_error:
                error.add_note(f"Browser context cleanup failed: {cleanup_error!r}")
            raise

        session = BrowserSession(context, page)
        self._sessions[site] = session
        return session

    async def reset(
        self,
        site: Site,
        policy: RequestPolicy,
    ) -> BrowserSession:
        async with self._session_locks[site]:
            session = self._sessions.pop(site, None)
            if session is not None:
                errors: list[BaseException] = []
                await self._close_session(session, errors)
                self._raise_cleanup_errors(errors)
            return await self._session_for_locked(site, policy)

    async def aclose(self) -> None:
        sessions = list(self._sessions.items())
        browser = self._browser
        playwright = self._playwright
        self._sessions.clear()
        self._browser = None
        self._playwright = None

        errors: list[BaseException] = []
        for site, session in sessions:
            try:
                await self._save_state(site, session.context)
            except BaseException as error:
                errors.append(error)

        for _, session in sessions:
            await self._close_session(session, errors)

        if browser is not None:
            try:
                await browser.close()
            except BaseException as error:
                errors.append(error)
        if playwright is not None:
            try:
                await playwright.stop()
            except BaseException as error:
                errors.append(error)

        self._raise_cleanup_errors(errors)

    def _load_state(self, site: Site) -> dict[str, object] | None:
        try:
            with self._state_path(site).open(encoding="utf-8") as state_file:
                state = json.load(state_file)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return state if isinstance(state, dict) else None

    async def _save_state(self, site: Site, context: BrowserContext) -> None:
        destination = self._state_path(site)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            await context.storage_state(path=str(temporary))
            os.replace(temporary, destination)
        except BaseException as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                error.add_note(
                    f"Temporary storage state cleanup failed: {cleanup_error!r}"
                )
            raise

    @staticmethod
    async def _close_session(
        session: BrowserSession,
        errors: list[BaseException],
    ) -> None:
        try:
            await session.page.close()
        except BaseException as error:
            errors.append(error)
        try:
            await session.context.close()
        except BaseException as error:
            errors.append(error)

    @staticmethod
    def _raise_cleanup_errors(errors: list[BaseException]) -> None:
        if not errors:
            return
        first, *remaining = errors
        for error in remaining:
            first.add_note(f"Additional cleanup error: {error!r}")
        raise first
