from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Protocol

import pytest
from textual.app import App
from textual.containers import Horizontal, VerticalScroll
from textual.pilot import Pilot
from textual.widgets import ListView, OptionList, Static

import fmk_reader.app as app_module
from fmk_reader.adapters import adapter_for
from fmk_reader.app import CommunityReaderApp, FmkReaderApp, ReaderResources
from fmk_reader.errors import ReaderError
from fmk_reader.models import Comment, PageResult, PostDetail, PostSummary
from fmk_reader.service import DataSource, LoadResult, PostPage
from fmk_reader.targets import CommunityTarget, route_url


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


class DelayedService(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.board_gate = asyncio.Event()
        self.post_gate = asyncio.Event()

    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        if page == 1:
            return await super().load_board(page, refresh)
        self.board_calls.append((page, refresh))
        await self.board_gate.wait()
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
        if cpage == 1:
            return await super().load_post(post, cpage, refresh)
        self.post_calls.append((post.post_id, cpage, refresh))
        await self.post_gate.wait()
        detail = PostDetail(post, self.body, ())
        comments = PageResult(
            (Comment("2", "댓글러", f"댓글 내용 {cpage}", "방금", 0),),
            cpage,
            cpage > 1,
            cpage < 2,
        )
        return LoadResult(PostPage(detail, comments), DataSource.CACHE)


class FailingPageService(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.fail_board_page_2 = True
        self.fail_comment_page_2 = True
        self.fail_post_ids: set[str] = set()
        self.failed_post_gate = asyncio.Event()

    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        self.board_calls.append((page, refresh))
        if page == 2 and self.fail_board_page_2:
            raise ReaderError("board page 2 failed")
        posts = tuple(
            replace(post, title=f"{post.title} p{page}") for post in POSTS
        )
        return LoadResult(
            PageResult(posts, page, page > 1, page < 2),
            DataSource.CACHE,
        )

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]:
        self.post_calls.append((post.post_id, cpage, refresh))
        if post.post_id in self.fail_post_ids:
            await self.failed_post_gate.wait()
            raise ReaderError("new post failed")
        if cpage == 2 and self.fail_comment_page_2:
            raise ReaderError("comment page 2 failed")
        detail = PostDetail(post, f"본문 {post.post_id}", ())
        comments = PageResult(
            (Comment("1", "댓글러", f"댓글 내용 {cpage}", "방금", 0),),
            cpage,
            cpage > 1,
            cpage < 2,
        )
        return LoadResult(PostPage(detail, comments), DataSource.CACHE)


class LiteralTextService(FakeService):
    async def load_board(
        self, page: int, refresh: bool = False
    ) -> LoadResult[PageResult[PostSummary]]:
        self.board_calls.append((page, refresh))
        post = replace(
            POSTS[0],
            title="[bold]제목[/bold] a[b]c [/]",
            author="[bold]작성자[/bold] a[b]c [/]",
        )
        return LoadResult(
            PageResult((post,), page, False, False),
            DataSource.CACHE,
        )

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]:
        self.post_calls.append((post.post_id, cpage, refresh))
        detail = PostDetail(post, "[bold]본문[/bold] a[b]c [/]", ())
        comments = PageResult(
            (
                Comment(
                    "1",
                    "[bold]댓글러[/bold] a[b]c [/],",
                    "[bold]댓글[/bold] a[b]c [/],",
                    "방금",
                    0,
                ),
            ),
            1,
            False,
            False,
        )
        return LoadResult(PostPage(detail, comments), DataSource.CACHE)


class NoticeApp(CommunityReaderApp):
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
    app = CommunityReaderApp(service=FakeService())
    assert app.TITLE == "Commu"
    assert FmkReaderApp is CommunityReaderApp


class GatedDirectService(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def load_post(
        self,
        post: PostSummary,
        cpage: int = 1,
        refresh: bool = False,
    ) -> LoadResult[PostPage]:
        self.started.set()
        await self.gate.wait()
        return await super().load_post(post, cpage, refresh)


async def test_direct_article_starts_in_loading_reader_then_back_loads_board() -> None:
    service = GatedDirectService()
    target = route_url("https://arca.live/b/rogersfu/176096992")
    app = CommunityReaderApp(target=target, service=service)

    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        assert service.started.is_set()
        assert service.board_calls == []
        assert "불러오는 중..." in widget_text(
            app.query_one("#article-content", Static)
        )
        assert app.query_one("#main", Horizontal).has_class("reading")

        service.gate.set()
        await settle(app, pilot)
        assert service.post_calls == [("176096992", 1, False)]

        await pilot.press("escape")
        await settle(app, pilot)
        assert service.board_calls == [(1, False)]
        assert not app.query_one("#main", Horizontal).has_class("reading")


class SwitchRawClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


class SwitchCache:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class SwitchFactory:
    def __init__(self) -> None:
        self.created: list[CommunityTarget] = []
        self.raw_clients: list[SwitchRawClient] = []
        self.caches: list[SwitchCache] = []

    def __call__(self, target: CommunityTarget) -> ReaderResources:
        raw = SwitchRawClient()
        cache = SwitchCache()
        self.created.append(target)
        self.raw_clients.append(raw)
        self.caches.append(cache)
        return ReaderResources(raw, cache, adapter_for(target), FakeService())


async def test_switch_site_closes_resources_clears_reader_and_reopens_launcher() -> None:
    factory = SwitchFactory()
    first = route_url("https://www.fmkorea.com/football_world")
    app = CommunityReaderApp(target=first, resource_factory=factory)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.current_post is not None

        await pilot.press("s")
        await pilot.pause()

        assert app.target is None
        assert factory.raw_clients[0].close_calls == 1
        assert factory.caches[0].close_calls == 1
        assert app.current_post is None
        assert widget_text(app.default_screen.query_one("#article-content", Static)) == ""
        assert app.query_one("#launcher-sites", OptionList).display


async def test_mount_loads_board_focuses_list_and_shows_source() -> None:
    service = FakeService()
    app = CommunityReaderApp(service=service)

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
    app = CommunityReaderApp(service=service)

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
    narrow = CommunityReaderApp(service=FakeService())
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

    wide = CommunityReaderApp(service=FakeService())
    async with wide.run_test(size=(120, 30)) as pilot:
        await settle(wide, pilot)
        assert wide.query_one("#post-list", ListView).display
        assert wide.query_one("#article-pane", VerticalScroll).display


async def test_arrow_pages_board_and_comments_only_within_boundaries() -> None:
    service = FakeService()
    app = CommunityReaderApp(service=service)

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
    app = CommunityReaderApp(service=service)

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
    app = CommunityReaderApp(service=FakeService(body=body))

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
) -> None:
    factory = SwitchFactory()
    target = route_url("https://www.fmkorea.com/football_world")
    production = CommunityReaderApp(target=target, resource_factory=factory)
    async with production.run_test(size=(120, 30)) as pilot:
        await settle(production, pilot)
    assert factory.raw_clients[0].close_calls == 1
    assert factory.caches[0].close_calls == 1

    injected = FakeService()
    injected_app = CommunityReaderApp(service=injected)
    async with injected_app.run_test(size=(120, 30)) as pilot:
        await settle(injected_app, pilot)
    assert not hasattr(injected, "closed")


async def test_remote_rich_like_text_is_rendered_literally() -> None:
    app = CommunityReaderApp(service=LiteralTextService())

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        label = app.query_one("#post-list", ListView).query_one("Label")
        assert "[bold]제목[/bold] a[b]c [/]" in str(label.render())

        await pilot.press("enter")
        await settle(app, pilot)
        assert widget_text(app.query_one("#article-title", Static)) == (
            "[bold]제목[/bold] a[b]c [/]"
        )
        assert "[bold]작성자[/bold] a[b]c [/]" in widget_text(
            app.query_one("#article-meta", Static)
        )
        content = widget_text(app.query_one("#article-content", Static))
        assert "[bold]본문[/bold] a[b]c [/]" in content
        assert "[bold]댓글러[/bold] a[b]c [/]" in content
        assert "[bold]댓글[/bold] a[b]c [/]" in content


async def test_rapid_arrows_coalesce_to_next_confirmed_pages() -> None:
    service = DelayedService()
    app = CommunityReaderApp(service=service)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        await pilot.press("right")
        await pilot.pause()
        await pilot.press("right", "right")
        await pilot.pause()
        assert service.board_calls == [(1, False), (2, False)]
        assert app.board_page == 1
        service.board_gate.set()
        await settle(app, pilot)
        assert app.board_page == 2

        await pilot.press("left")
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("tab", "right")
        await pilot.pause()
        await pilot.press("right", "right")
        await pilot.pause()
        assert service.post_calls == [("100", 1, False), ("100", 2, False)]
        assert app.comment_page == 1
        service.post_gate.set()
        await settle(app, pilot)
        assert app.comment_page == 2


async def test_failed_board_navigation_keeps_confirmed_state_and_retries() -> None:
    service = FailingPageService()
    app = NoticeApp(service)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        post_list = app.query_one("#post-list", ListView)
        before = " ".join(
            str(label.render()) for label in post_list.query("Label")
        )

        await pilot.press("right")
        await settle(app, pilot)
        after_failure = " ".join(
            str(label.render()) for label in post_list.query("Label")
        )
        assert app.board_page == 1
        assert app.board_has_next
        assert not app.board_has_previous
        assert after_failure == before
        assert app.notices == ["board page 2 failed"]

        service.fail_board_page_2 = False
        await pilot.press("right")
        await settle(app, pilot)
        assert app.board_page == 2
        assert app.board_has_previous
        assert not app.board_has_next
        rendered = " ".join(
            str(label.render()) for label in post_list.query("Label")
        )
        assert "p2" in rendered


async def test_failed_comment_navigation_and_new_post_failure_clear_stale_ui() -> None:
    service = FailingPageService()
    app = NoticeApp(service)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("tab", "right")
        await settle(app, pilot)
        content = app.query_one("#article-content", Static)
        assert app.comment_page == 1
        assert app.comments_have_next
        assert not app.comments_have_previous
        assert "댓글 내용 1" in widget_text(content)

        service.fail_comment_page_2 = False
        await pilot.press("right")
        await settle(app, pilot)
        assert app.comment_page == 2
        assert app.comments_have_previous
        assert not app.comments_have_next
        assert "댓글 내용 2" in widget_text(content)

        await pilot.press("escape", "down")
        service.fail_post_ids.add("101")
        await pilot.press("enter")
        await pilot.pause()
        assert "불러오는 중..." in widget_text(content)
        service.failed_post_gate.set()
        await settle(app, pilot)
        assert "불러오기 실패" in widget_text(content)
        assert "본문 100" not in widget_text(content)


async def test_live_resize_moves_focus_to_visible_pane() -> None:
    app = CommunityReaderApp(service=FakeService())

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)
        main = app.query_one("#main", Horizontal)
        post_list = app.query_one("#post-list", ListView)
        article = app.query_one("#article-pane", VerticalScroll)

        await pilot.resize_terminal(90, 30)
        await pilot.pause()
        assert main.has_class("narrow")
        assert post_list.display and post_list.has_focus
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert post_list.display and article.display

        await pilot.press("enter")
        await settle(app, pilot)
        assert post_list.has_focus
        await pilot.resize_terminal(90, 30)
        await pilot.pause()
        assert article.display and article.has_focus
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert post_list.display and article.display and article.has_focus


async def test_cache_closes_when_http_client_close_raises(
) -> None:
    class BrokenRawClient:
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    class Cache:
        def __init__(self, path: object) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    raw = BrokenRawClient()
    cache = Cache(object())
    target = route_url("https://www.fmkorea.com/football_world")

    def factory(selected: CommunityTarget) -> ReaderResources:
        return ReaderResources(raw, cache, adapter_for(selected), FakeService())

    with pytest.raises(RuntimeError, match="close failed"):
        async with CommunityReaderApp(
            target=target, resource_factory=factory
        ).run_test(size=(120, 30)) as pilot:
            await pilot.pause()
    assert cache.closed


async def test_resource_factory_closes_partial_resources_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RawClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    class Cache:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    raw = RawClient()
    cache = Cache()
    target = route_url("https://www.fmkorea.com/football_world")
    adapter = adapter_for(target)
    monkeypatch.setattr(app_module, "adapter_for", lambda selected: adapter)
    monkeypatch.setattr(app_module, "make_httpx_client", lambda policy: raw)
    monkeypatch.setattr(app_module, "JsonCache", lambda path: cache)
    monkeypatch.setattr(
        app_module,
        "CommunityHttpClient",
        lambda client, policy: object(),
    )

    def fail_service(*args: object) -> None:
        raise RuntimeError("service construction failed")

    monkeypatch.setattr(app_module, "CommunityService", fail_service)

    with pytest.raises(RuntimeError, match="service construction failed"):
        app_module.create_reader_resources(target)
    await asyncio.sleep(0)

    assert raw.close_calls == 1
    assert cache.close_calls == 1
