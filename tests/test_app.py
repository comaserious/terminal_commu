from __future__ import annotations

from typing import Protocol

import pytest
from textual.app import App
from textual.containers import Horizontal, VerticalScroll
from textual.pilot import Pilot
from textual.widgets import ListView, Static

import fmk_reader.app as app_module
from fmk_reader.app import FmkReaderApp
from fmk_reader.errors import ReaderError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.service import DataSource, LoadResult, PostPage


POSTS = (
    PostSummary(
        "100",
        "첫 글",
        "토트넘",
        "작성자",
        "16:45",
        "20",
        3,
        1,
        "https://www.fmkorea.com/100",
        False,
    ),
    PostSummary(
        "101",
        "둘째 글",
        "맨유",
        "작성자2",
        "16:46",
        "10",
        1,
        4,
        "https://www.fmkorea.com/101",
        False,
    ),
)


class ReaderService(Protocol):
    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]: ...

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]: ...


class FakeService:
    def __init__(
        self,
        *,
        body: str = "본문 내용",
        board_error: ReaderError | None = None,
        post_error: ReaderError | None = None,
    ) -> None:
        self.body = body
        self.board_error = board_error
        self.post_error = post_error
        self.board_calls: list[tuple[int, bool]] = []
        self.post_calls: list[tuple[str, int, bool]] = []

    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        self.board_calls.append((page, refresh))
        if self.board_error is not None:
            raise self.board_error
        return LoadResult(
            PageResult(POSTS, page, page > 1, page < 2),
            DataSource.CACHE,
        )

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]:
        self.post_calls.append((post.post_id, cpage, refresh))
        if self.post_error is not None:
            raise self.post_error
        detail = PostDetail(
            post,
            self.body,
            ("https://example.com/source",),
        )
        comments = PageResult(
            (Comment("1", "댓글러", "댓글 내용", "방금", 1),),
            cpage,
            cpage > 1,
            cpage < 2,
        )
        return LoadResult(PostPage(detail, comments), DataSource.CACHE)


class NoticeApp(FmkReaderApp):
    def __init__(self, service: ReaderService) -> None:
        self.notices: list[str] = []
        super().__init__(service=service)

    def notify(self, message: str, **_: object) -> None:
        self.notices.append(message)


async def settle(app: App[None], pilot: Pilot[None]) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def widget_text(widget: Static) -> str:
    return str(widget.render())


def test_app_has_expected_title() -> None:
    app = FmkReaderApp(service=FakeService())
    assert app.TITLE == "FMK 해외축구"


async def test_mount_loads_board_focuses_list_and_shows_source() -> None:
    service = FakeService()
    app = FmkReaderApp(service=service)

    async with app.run_test(size=(120, 34)) as pilot:
        await settle(app, pilot)

        post_list = app.query_one("#post-list", ListView)
        assert service.board_calls == [(1, False)]
        assert len(post_list.children) == 2
        assert post_list.has_focus
        assert "1페이지" in app.sub_title
        assert "cache" in app.sub_title
        rendered = " ".join(
            str(label.render()) for label in post_list.query("Label")
        )
        assert "토트넘" in rendered
        assert "댓글 1" in rendered


async def test_down_and_enter_load_selected_post_and_render_article() -> None:
    service = FakeService()
    app = FmkReaderApp(service=service)

    async with app.run_test(size=(120, 34)) as pilot:
        await settle(app, pilot)
        await pilot.press("down", "enter")
        await settle(app, pilot)

        assert service.post_calls == [("101", 1, False)]
        assert "둘째 글" in widget_text(app.query_one("#article-title", Static))
        assert "작성자2" in widget_text(app.query_one("#article-meta", Static))
        content = widget_text(app.query_one("#article-content", Static))
        assert "본문 내용" in content
        assert "https://example.com/source" in content
        assert "  └ 댓글러 · 방금" in content
        assert "댓글 내용" in content


async def test_narrow_reading_mode_and_wide_split_visibility() -> None:
    narrow = FmkReaderApp(service=FakeService())
    async with narrow.run_test(size=(90, 30)) as pilot:
        await settle(narrow, pilot)
        main = narrow.query_one("#main", Horizontal)
        post_list = narrow.query_one("#post-list", ListView)
        article = narrow.query_one("#article-pane", VerticalScroll)
        assert main.has_class("narrow")
        assert post_list.display
        assert not article.display

        await pilot.press("enter")
        await settle(narrow, pilot)
        assert main.has_class("reading")
        assert article.display
        assert article.has_focus

        await pilot.press("escape")
        await pilot.pause()
        assert not main.has_class("reading")
        assert post_list.display
        assert post_list.has_focus

    wide = FmkReaderApp(service=FakeService())
    async with wide.run_test(size=(120, 30)) as pilot:
        await settle(wide, pilot)
        assert wide.query_one("#post-list", ListView).display
        assert wide.query_one("#article-pane", VerticalScroll).display


async def test_arrow_pages_board_and_comments_only_within_boundaries() -> None:
    service = FakeService()
    app = FmkReaderApp(service=service)

    async with app.run_test(size=(120, 34)) as pilot:
        await settle(app, pilot)
        await pilot.press("left")
        await settle(app, pilot)
        assert service.board_calls == [(1, False)]

        await pilot.press("right")
        await settle(app, pilot)
        await pilot.press("right")
        await settle(app, pilot)
        await pilot.press("left")
        await settle(app, pilot)
        assert service.board_calls == [(1, False), (2, False), (1, False)]

        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("tab", "left")
        await settle(app, pilot)
        assert service.post_calls == [("100", 1, False)]

        await pilot.press("right")
        await settle(app, pilot)
        await pilot.press("right")
        await settle(app, pilot)
        await pilot.press("left")
        await settle(app, pilot)
        assert service.post_calls == [
            ("100", 1, False),
            ("100", 2, False),
            ("100", 1, False),
        ]


async def test_refresh_uses_focused_context() -> None:
    service = FakeService()
    app = FmkReaderApp(service=service)

    async with app.run_test(size=(120, 34)) as pilot:
        await settle(app, pilot)
        await pilot.press("r")
        await settle(app, pilot)
        assert service.board_calls[-1] == (1, True)

        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("tab", "r")
        await settle(app, pilot)
        assert service.post_calls[-1] == ("100", 1, True)


async def test_tab_focuses_article_and_arrows_scroll_it() -> None:
    body = "\n".join(f"본문 {line}" for line in range(150))
    app = FmkReaderApp(service=FakeService(body=body))

    async with app.run_test(size=(120, 20)) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        article = app.query_one("#article-pane", VerticalScroll)

        await pilot.press("tab")
        await pilot.pause()
        assert article.has_focus
        start = article.scroll_y
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert article.scroll_y > start

        await pilot.press("tab")
        await pilot.pause()
        assert app.query_one("#post-list", ListView).has_focus


@pytest.mark.parametrize("context", ["board", "post"])
async def test_reader_error_notifies_without_stopping_app(context: str) -> None:
    error = ReaderError(f"{context} failed")
    service = FakeService(
        board_error=error if context == "board" else None,
        post_error=error if context == "post" else None,
    )
    app = NoticeApp(service)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        if context == "post":
            await pilot.press("enter")
            await settle(app, pilot)
        assert app.is_running
        assert app.notices == [f"{context} failed"]


async def test_production_resources_are_owned_but_injected_service_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RawClient:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class Cache:
        def __init__(self, path: object) -> None:
            self.path = path
            self.closed = False

        def close(self) -> None:
            self.closed = True

    raw = RawClient()
    created: dict[str, object] = {}
    production_service = FakeService()
    monkeypatch.setattr(app_module, "make_httpx_client", lambda: raw)
    monkeypatch.setattr(app_module, "FmkHttpClient", lambda client: client)

    def make_cache(path: object) -> Cache:
        cache = Cache(path)
        created["cache"] = cache
        return cache

    monkeypatch.setattr(app_module, "JsonCache", make_cache)
    monkeypatch.setattr(
        app_module,
        "BoardService",
        lambda client, cache: production_service,
    )

    production = FmkReaderApp()
    async with production.run_test(size=(120, 30)) as pilot:
        await settle(production, pilot)
    assert raw.closed
    assert isinstance(created["cache"], Cache)
    assert created["cache"].closed

    injected = FakeService()
    injected_app = FmkReaderApp(service=injected)
    async with injected_app.run_test(size=(120, 30)) as pilot:
        await settle(injected_app, pilot)
    assert not hasattr(injected, "closed")
