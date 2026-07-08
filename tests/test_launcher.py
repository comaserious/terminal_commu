from __future__ import annotations

import asyncio
from dataclasses import dataclass

from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static

from commu.app import CommunityReaderApp, ReaderResources
from commu.adapters import adapter_for
from commu.launcher import LauncherScreen
from commu.models import PageResult, PostSummary
from commu.service import DataSource, LoadResult
from commu.targets import CommunityTarget, route_url


class FakeRawClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


class FakeCache:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeAdapter:
    def __init__(self, target: CommunityTarget) -> None:
        self.target = target
        self.site_name = target.site.display_name

    def direct_post(self) -> PostSummary | None:
        return None


class FakeService:
    def __init__(self) -> None:
        self.board_calls: list[tuple[int, bool]] = []

    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        self.board_calls.append((page, refresh))
        return LoadResult(PageResult((), page, False, False), DataSource.CACHE)


@dataclass
class FakeResourceFactory:
    def __post_init__(self) -> None:
        self.created: list[CommunityTarget] = []
        self.services: list[FakeService] = []

    def __call__(self, target: CommunityTarget) -> ReaderResources:
        service = FakeService()
        self.created.append(target)
        self.services.append(service)
        return ReaderResources(
            raw_client=FakeRawClient(),
            cache=FakeCache(),
            adapter=FakeAdapter(target),
            service=service,
        )


class SuspendedFactory:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[CommunityTarget] = []
        self.raw_client = FakeRawClient()
        self.cache = FakeCache()
        self.service = FakeService()

    async def __call__(self, target: CommunityTarget) -> ReaderResources:
        self.calls.append(target)
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return ReaderResources(
            self.raw_client,
            self.cache,
            adapter_for(target),
            self.service,
        )


class ActivationNoticeApp(CommunityReaderApp):
    def __init__(self, factory: SuspendedFactory) -> None:
        self.notices: list[str] = []
        super().__init__(resource_factory=factory)

    def notify(self, message: str, **_: object) -> None:
        self.notices.append(message)


async def test_launcher_recommended_arca_flow_returns_target() -> None:
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test() as pilot:
        await pilot.press("down", "down", "enter")
        await pilot.press("enter")
        await pilot.pause()

        expected = route_url("https://arca.live/b/rogersfu")
        assert app.target == expected
        assert factory.created == [expected]


async def test_launcher_separated_arrow_and_enter_keys_use_current_step() -> None:
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.press("enter")
        assert app.query_one("#launcher-access", OptionList).display

        await pilot.press("enter")
        await pilot.pause()

        expected = route_url(
            "https://gall.dcinside.com/board/lists/?id=football_new9"
        )
        assert app.target == expected
        assert factory.created == [expected]


async def test_launcher_mouse_clicks_select_site_and_recommended_board() -> None:
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#launcher-sites", offset=(2, 3))
        await pilot.pause()
        assert app.query_one("#launcher-access", OptionList).display

        await pilot.click("#launcher-access", offset=(2, 1))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        expected = route_url("https://arca.live/b/rogersfu")
        assert app.target == expected
        assert factory.created == [expected]


async def test_launcher_direct_url_validation_stays_local() -> None:
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test() as pilot:
        await pilot.press("enter", "down", "enter")
        app.query_one("#target-url", Input).value = "https://example.com"
        await pilot.press("enter")

        assert factory.created == []
        error = app.query_one("#launcher-error", Static)
        assert error.renderable
        assert error.markup is False


async def test_launcher_escape_steps_back_through_direct_url_flow() -> None:
    app = CommunityReaderApp(resource_factory=FakeResourceFactory())

    async with app.run_test() as pilot:
        await pilot.press("enter", "down", "enter")
        assert app.query_one("#target-url", Input).display

        await pilot.press("escape")
        assert app.query_one("#launcher-access", OptionList).display

        await pilot.press("escape")
        assert app.query_one("#launcher-sites", OptionList).display


async def test_reader_actions_are_inert_on_launcher_and_switch_is_idempotent() -> None:
    factory = FakeResourceFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test() as pilot:
        launcher = app.screen
        assert isinstance(launcher, LauncherScreen)

        await pilot.press("r", "left", "right", "s", "s")
        await pilot.pause()

        assert app.is_running
        assert app.screen is launcher
        assert sum(
            isinstance(screen, LauncherScreen) for screen in app.screen_stack
        ) == 1
        assert factory.created == []

        await pilot.press("enter", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.screen is app.default_screen
        assert len(factory.created) == 1
        service = factory.services[0]
        assert service.board_calls == [(1, False)]

        await pilot.press("r", "left", "right")
        await app.workers.wait_for_complete()
        assert app.is_running
        assert service.board_calls == [(1, False), (1, True)]


async def test_launcher_fits_inside_narrow_terminal() -> None:
    app = CommunityReaderApp(resource_factory=FakeResourceFactory())

    async with app.run_test(size=(32, 20)) as pilot:
        await pilot.pause()
        launcher = app.query_one("#launcher", Vertical)

        assert launcher.region.x >= 0
        assert launcher.region.right <= app.size.width
        assert launcher.region.width <= app.size.width


async def test_suspended_activation_is_atomic_and_reader_keys_are_inert() -> None:
    factory = SuspendedFactory()
    app = CommunityReaderApp(resource_factory=factory)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        selection_task = asyncio.create_task(pilot.press("enter"))
        key_task: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(factory.started.wait(), timeout=1)
            await asyncio.wait_for(asyncio.shield(selection_task), timeout=0.5)

            assert app.target is None
            assert app.adapter is None
            assert app.service is None
            assert app.raw_client is None
            assert app.cache is None
            assert "준비 중" in str(
                app.default_screen.query_one("#article-meta", Static).render()
            )

            key_task = asyncio.create_task(
                pilot.press("r", "left", "right", "enter", "s")
            )
            await asyncio.wait_for(asyncio.shield(key_task), timeout=0.5)
            assert app.screen is app.default_screen
            assert factory.calls == [
                route_url("https://www.fmkorea.com/football_world")
            ]
            assert factory.service.board_calls == []
        finally:
            factory.release.set()
            await selection_task
            if key_task is not None:
                await key_task

        await app.workers.wait_for_complete()
        await pilot.pause()
        expected = route_url("https://www.fmkorea.com/football_world")
        assert app.target == expected
        assert app.adapter is not None
        assert app.service is factory.service
        assert app.raw_client is factory.raw_client
        assert app.cache is factory.cache
        assert factory.service.board_calls == [(1, False)]


async def test_suspended_factory_error_reopens_one_launcher_without_resources() -> None:
    factory = SuspendedFactory(error=RuntimeError("factory failed"))
    app = ActivationNoticeApp(factory)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        selection_task = asyncio.create_task(pilot.press("enter"))
        await asyncio.wait_for(factory.started.wait(), timeout=1)
        factory.release.set()
        await selection_task
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.target is None
        assert app.adapter is None
        assert app.service is None
        assert app.raw_client is None
        assert app.cache is None
        assert not app._owns_resources
        assert app.notices == ["커뮤니티를 준비하지 못했습니다: factory failed"]
        assert sum(
            isinstance(screen, LauncherScreen) for screen in app.screen_stack
        ) == 1
