from __future__ import annotations

from dataclasses import dataclass

from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static

from fmk_reader.app import CommunityReaderApp, ReaderResources
from fmk_reader.launcher import LauncherScreen
from fmk_reader.models import PageResult, PostSummary
from fmk_reader.service import DataSource, LoadResult
from fmk_reader.targets import CommunityTarget, route_url


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
