from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
import inspect
from pathlib import Path
import sys
from typing import Protocol

import httpx
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from commu.adapters import CommunityAdapter, adapter_for
from commu.cache import JsonCache
from commu.client import (
    DEFAULT_REQUEST_STATE_REGISTRY,
    CommunityHttpClient,
    make_httpx_client,
)
from commu.errors import ReaderError
from commu.launcher import LauncherScreen
from commu.models import Comment, PageResult, PostSummary
from commu.service import CommunityService, LoadResult, PostPage
from commu.targets import CommunityTarget, RECOMMENDED_URLS, Site, route_url
from commu import work_disguise


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


@dataclass(slots=True)
class ReaderResources:
    raw_client: httpx.AsyncClient
    cache: JsonCache
    adapter: CommunityAdapter
    service: CommunityService


@dataclass(slots=True)
class PendingResourceCleanup:
    resources: ReaderResources
    raw_client_closed: bool = False
    cache_closed: bool = False


class ResourceFactory(Protocol):
    def __call__(
        self, target: CommunityTarget
    ) -> ReaderResources | Awaitable[ReaderResources]: ...


def default_cache_path(home: Path | None = None) -> Path:
    base = Path.home() if home is None else home
    return base / ".cache" / "commu" / "cache.db"


async def create_reader_resources(target: CommunityTarget) -> ReaderResources:
    adapter = adapter_for(target)
    cache: JsonCache | None = None
    raw_client: httpx.AsyncClient | None = None
    try:
        cache = JsonCache(default_cache_path())
        raw_client = make_httpx_client(adapter.policy)
        service = CommunityService(
            adapter,
            CommunityHttpClient(
                raw_client,
                adapter.policy,
                state=DEFAULT_REQUEST_STATE_REGISTRY.state_for(target.site),
            ),
            cache,
        )
        return ReaderResources(raw_client, cache, adapter, service)
    except BaseException as original_error:
        cleanup_errors: list[BaseException] = []
        if raw_client is not None:
            try:
                await raw_client.aclose()
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cache is not None:
            try:
                cache.close()
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        for cleanup_error in cleanup_errors:
            original_error.add_note(f"Cleanup error: {cleanup_error}")
        raise


class PostItem(ListItem):
    """A variable-height board row which retains its source model."""

    def __init__(self, post: PostSummary) -> None:
        self.post = post
        text = work_disguise.post_row(
            category=post.category,
            title=post.title,
            votes=post.votes,
            comment_count=post.comment_count,
            created_at=post.created_at,
        )
        super().__init__(Label(text, markup=False))


class ArticlePane(VerticalScroll):
    can_focus = True


class CommunityReaderApp(App[None]):
    TITLE = work_disguise.APP_TITLE
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    BINDINGS = [
        ("left", "previous_page", "이전 페이지"),
        ("right", "next_page", "다음 페이지"),
        ("r", "refresh", "새로고침"),
        ("escape", "back", "목록"),
        ("s", "switch_site", "사이트 선택"),
        ("q", "quit", "종료"),
    ]

    def _get_dom_base(self):
        """Make app-level queries follow the active launcher or reader screen."""
        return self.screen

    def __init__(
        self,
        target: CommunityTarget | None = None,
        service: ReaderService | None = None,
        resource_factory: ResourceFactory | None = None,
    ) -> None:
        super().__init__()
        if service is not None and target is None:
            target = route_url(RECOMMENDED_URLS[Site.FMKOREA])
        self.target: CommunityTarget | None = None
        self._initial_target = target
        self._injected_service = service
        self.raw_client = None
        self.cache = None
        self.adapter: CommunityAdapter | None = None
        self._resource_factory = resource_factory or create_reader_resources
        self._owns_resources = False
        self._raw_client_closed = False
        self._cache_closed = False
        self.service: ReaderService | None = None

        self.board_page = 1
        self.comment_page = 1
        self.board_has_previous = False
        self.board_has_next = False
        self.comments_have_previous = False
        self.comments_have_next = False
        self.current_post: PostSummary | None = None
        self._displayed_post_id: str | None = None
        self._board_request_id = 0
        self._post_request_id = 0
        self._pending_board_page: int | None = None
        self._pending_post_key: tuple[str, int] | None = None
        self._direct_start = False
        self._switch_in_progress = False
        self._activation_generation = 0
        self._activation_in_progress = False
        self._reader_unusable = False
        self._reader_context = ""
        self._pending_resource_cleanups: list[PendingResourceCleanup] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(id="post-list")
            with ArticlePane(id="article-pane"):
                yield Static(
                    work_disguise.IDLE_TITLE,
                    id="article-title",
                    markup=False,
                )
                yield Static(
                    work_disguise.IDLE_META,
                    id="article-meta",
                    markup=False,
                )
                yield Static(
                    work_disguise.IDLE_BODY,
                    id="article-content",
                    markup=False,
                )
        yield Footer()

    def on_mount(self) -> None:
        self._sync_layout(self.size.width)
        self.query_one("#post-list", ListView).focus()
        if self._initial_target is None:
            self._open_launcher()
            return
        self._begin_activation(self._initial_target, self._injected_service)

    async def on_unmount(self) -> None:
        self._activation_generation += 1
        self._activation_in_progress = False
        active_error: BaseException | None = None
        try:
            await self._release_owned_resources()
        except BaseException as error:
            active_error = error
        cleanup_errors = await self._retry_pending_resource_cleanups()
        if active_error is not None:
            for cleanup_error in cleanup_errors:
                active_error.add_note(
                    f"Additional retained cleanup error: {cleanup_error}"
                )
            raise active_error
        if cleanup_errors:
            first_error = cleanup_errors[0]
            for cleanup_error in cleanup_errors[1:]:
                first_error.add_note(
                    f"Additional retained cleanup error: {cleanup_error}"
                )
            raise first_error

    def _accept_target(self, target: CommunityTarget | None) -> None:
        if target is None:
            return
        self._begin_activation(target)

    def _begin_activation(
        self,
        target: CommunityTarget,
        injected_service: ReaderService | None = None,
    ) -> None:
        self._activation_generation += 1
        generation = self._activation_generation
        self._activation_in_progress = True
        self._show_activation_loading()
        self._activate_target(target, injected_service, generation)

    @work(exclusive=True, group="activation")
    async def _activate_target(
        self,
        target: CommunityTarget,
        injected_service: ReaderService | None,
        generation: int,
    ) -> None:
        resources: ReaderResources | None = None
        try:
            if injected_service is None:
                pending_resources = self._resource_factory(target)
                resources = (
                    await pending_resources
                    if inspect.isawaitable(pending_resources)
                    else pending_resources
                )
                adapter = resources.adapter
                service: ReaderService = resources.service
            else:
                adapter = adapter_for(target)
                service = injected_service
            direct_post = adapter.direct_post()
        except asyncio.CancelledError:
            if generation == self._activation_generation:
                self._activation_in_progress = False
            raise
        except Exception as error:
            if resources is not None:
                await self._discard_resources(resources, error)
            if generation == self._activation_generation:
                self._activation_in_progress = False
                self._clear_uncommitted_activation()
                self.notify(
                    f"업무 데이터 소스를 준비하지 못했습니다: {error}",
                    severity="error",
                    markup=False,
                )
                self._open_launcher()
            return

        if generation != self._activation_generation:
            if resources is not None:
                await self._discard_resources(resources)
            return

        self.target = target
        self.adapter = adapter
        self.service = service
        if resources is not None:
            self.raw_client = resources.raw_client
            self.cache = resources.cache
            self._owns_resources = True
            self._raw_client_closed = False
            self._cache_closed = False
        self._initial_target = None
        self._injected_service = None
        self._reader_unusable = False
        self._activation_in_progress = False
        self._set_reader_context(target.site, target.board_id)
        if direct_post is None:
            self.load_board()
            return
        self._direct_start = True
        self.current_post = direct_post
        self.comment_page = 1
        self.comments_have_previous = False
        self.comments_have_next = False
        self._displayed_post_id = None
        self._show_loading(direct_post)
        self.query_one("#main", Horizontal).add_class("reading")
        self.query_one("#article-pane", ArticlePane).focus()
        self.load_post(post=direct_post, target_page=1)

    async def _discard_resources(
        self,
        resources: ReaderResources,
        original_error: BaseException | None = None,
    ) -> None:
        pending = PendingResourceCleanup(resources)
        cleanup_errors = await self._close_pending_resources(pending)
        if cleanup_errors:
            self._pending_resource_cleanups.append(pending)
        if original_error is not None:
            for cleanup_error in cleanup_errors:
                original_error.add_note(f"Cleanup error: {cleanup_error}")
        elif cleanup_errors:
            self.notify(
                "사용하지 않는 리소스를 닫는 중 오류가 발생했습니다: "
                f"{cleanup_errors[0]}",
                severity="error",
                markup=False,
            )

    async def _close_pending_resources(
        self,
        pending: PendingResourceCleanup,
    ) -> list[BaseException]:
        cleanup_errors: list[BaseException] = []
        if not pending.raw_client_closed:
            try:
                await pending.resources.raw_client.aclose()
            except BaseException as error:
                cleanup_errors.append(error)
            else:
                pending.raw_client_closed = True
        if not pending.cache_closed:
            try:
                pending.resources.cache.close()
            except BaseException as error:
                cleanup_errors.append(error)
            else:
                pending.cache_closed = True
        return cleanup_errors

    async def _retry_pending_resource_cleanups(self) -> list[BaseException]:
        cleanup_errors: list[BaseException] = []
        retained: list[PendingResourceCleanup] = []
        for pending in self._pending_resource_cleanups:
            errors = await self._close_pending_resources(pending)
            cleanup_errors.extend(errors)
            if errors:
                retained.append(pending)
        self._pending_resource_cleanups = retained
        return cleanup_errors

    def _set_reader_context(self, site: Site, board_id: str) -> None:
        self._reader_context = work_disguise.source_label(site, board_id)
        self.title = f"{self.TITLE} · {self._reader_context}"
        self.sub_title = self._reader_context

    def _status_with_context(self, status: str) -> str:
        if not self._reader_context:
            return status
        return f"{self._reader_context} · {status}"

    def _show_activation_loading(self) -> None:
        self.default_screen.query_one("#main", Horizontal).remove_class("reading")
        self.default_screen.query_one("#article-title", Static).update(
            work_disguise.ACTIVATION_TITLE
        )
        self.default_screen.query_one("#article-meta", Static).update(
            work_disguise.ACTIVATION_META
        )
        self.default_screen.query_one("#article-content", Static).update(
            work_disguise.activation_body()
        )
        self.sub_title = work_disguise.ACTIVATION_TITLE

    def _clear_uncommitted_activation(self) -> None:
        self.target = None
        self.adapter = None
        self.service = None
        self.raw_client = None
        self.cache = None
        self._owns_resources = False

    def _open_launcher(self) -> None:
        if isinstance(self.screen, LauncherScreen):
            return
        self.push_screen(LauncherScreen(), self._accept_target)

    async def _release_owned_resources(self) -> None:
        if not self._owns_resources:
            return
        errors: list[BaseException] = []
        if not self._raw_client_closed:
            try:
                if self.raw_client is not None:
                    await self.raw_client.aclose()
            except BaseException as error:
                errors.append(error)
            else:
                self._raw_client_closed = True
        if not self._cache_closed:
            try:
                if self.cache is not None:
                    self.cache.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._cache_closed = True
        if errors:
            first_error = errors[0]
            for secondary_error in errors[1:]:
                first_error.add_note(f"Additional cleanup error: {secondary_error}")
            raise first_error
        self.raw_client = None
        self.cache = None
        self._owns_resources = False

    def load_board(
        self,
        refresh: bool = False,
        *,
        target_page: int | None = None,
    ) -> None:
        if not self._reader_is_usable():
            return
        target = self.board_page if target_page is None else target_page
        if self._pending_board_page == target and not refresh:
            return
        self._board_request_id += 1
        request_id = self._board_request_id
        self._pending_board_page = target
        self._load_board(target, refresh, request_id)

    @work(exclusive=True, group="board")
    async def _load_board(
        self,
        target_page: int,
        refresh: bool,
        request_id: int,
    ) -> None:
        try:
            try:
                result = await self.service.load_board(
                    target_page, refresh=refresh
                )
            except ReaderError as error:
                if request_id == self._board_request_id:
                    self.notify(str(error), severity="error", markup=False)
                return

            if request_id != self._board_request_id:
                return

            post_list = self.query_one("#post-list", ListView)
            await post_list.clear()
            await post_list.extend(
                PostItem(post) for post in result.value.items
            )
            if result.value.items:
                post_list.index = 0
            self.board_page = result.value.page
            self.board_has_previous = result.value.has_previous
            self.board_has_next = result.value.has_next
            self.sub_title = self._status_with_context(
                work_disguise.board_status(
                    result.value.page,
                    result.source.value,
                )
            )
            if result.warning:
                self.notify(result.warning, severity="warning", markup=False)
        finally:
            if request_id == self._board_request_id:
                self._pending_board_page = None

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self._reader_is_usable() or not isinstance(event.item, PostItem):
            return
        self.current_post = event.item.post
        self.comment_page = 1
        self.comments_have_previous = False
        self.comments_have_next = False
        self._displayed_post_id = None
        self._show_loading(event.item.post)
        main = self.query_one("#main", Horizontal)
        main.add_class("reading")
        if main.has_class("narrow"):
            self.query_one("#article-pane", ArticlePane).focus()
        self.load_post(post=event.item.post, target_page=1)

    def load_post(
        self,
        refresh: bool = False,
        *,
        post: PostSummary | None = None,
        target_page: int | None = None,
    ) -> None:
        if not self._reader_is_usable():
            return
        selected_post = self.current_post if post is None else post
        if selected_post is None:
            return
        target = self.comment_page if target_page is None else target_page
        key = (selected_post.post_id, target)
        if self._pending_post_key == key and not refresh:
            return
        self._post_request_id += 1
        request_id = self._post_request_id
        self._pending_post_key = key
        self._load_post(selected_post, target, refresh, request_id)

    @work(exclusive=True, group="post")
    async def _load_post(
        self,
        post: PostSummary,
        target_page: int,
        refresh: bool,
        request_id: int,
    ) -> None:
        try:
            try:
                result = await self.service.load_post(
                    post,
                    target_page,
                    refresh=refresh,
                )
            except ReaderError as error:
                if self._is_current_post_request(post, request_id):
                    self.notify(str(error), severity="error", markup=False)
                    if self._displayed_post_id != post.post_id:
                        self._show_load_failure(post, error)
                return

            if not self._is_current_post_request(post, request_id):
                return

            page = result.value
            self.comment_page = page.comments.page
            self.comments_have_previous = page.comments.has_previous
            self.comments_have_next = page.comments.has_next
            self._displayed_post_id = post.post_id
            summary = page.detail.summary
            self.query_one("#article-title", Static).update(summary.title)
            self.query_one("#article-meta", Static).update(
                work_disguise.article_meta(
                    author=summary.author,
                    created_at=summary.created_at,
                    views=summary.views,
                    votes=summary.votes,
                    comment_count=summary.comment_count,
                )
            )
            self.query_one("#article-content", Static).update(
                self._format_article(page)
            )
            self.sub_title = self._status_with_context(
                work_disguise.post_status(
                    summary.post_id,
                    page.comments.page,
                    result.source.value,
                )
            )
            if result.warning:
                self.notify(
                    result.warning, severity="warning", markup=False
                )
        finally:
            if request_id == self._post_request_id:
                self._pending_post_key = None

    def _is_current_post_request(
        self, post: PostSummary, request_id: int
    ) -> bool:
        return (
            request_id == self._post_request_id
            and self.current_post is not None
            and self.current_post.post_id == post.post_id
        )

    def _show_loading(self, post: PostSummary) -> None:
        self.query_one("#article-title", Static).update(post.title)
        self.query_one("#article-meta", Static).update("업무 항목 동기화 중")
        self.query_one("#article-content", Static).update(
            work_disguise.loading_body(post.post_id)
        )
        self.sub_title = self._status_with_context(
            work_disguise.loading_status(post.post_id)
        )

    def _show_load_failure(
        self, post: PostSummary, error: ReaderError
    ) -> None:
        self.query_one("#article-title", Static).update(post.title)
        self.query_one("#article-meta", Static).update(
            work_disguise.LOAD_FAILURE_META
        )
        self.query_one("#article-content", Static).update(
            f"{work_disguise.LOAD_FAILURE_META}: {error}"
        )
        self.sub_title = self._status_with_context(
            f"업무 항목 {post.post_id} · 동기화 실패"
        )

    @staticmethod
    def _format_article(page: PostPage) -> str:
        sections = [page.detail.body]
        if page.detail.links:
            sections.append(
                work_disguise.link_heading() + "\n" + "\n".join(page.detail.links)
            )
        comments = "\n\n".join(
            CommunityReaderApp._format_comment(comment)
            for comment in page.comments.items
        )
        sections.append(
            f"{work_disguise.comments_heading(page.comments.page)}\n{comments}"
        )
        return "\n\n".join(sections)

    @staticmethod
    def _format_comment(comment: Comment) -> str:
        indent = "  " * comment.depth
        return (
            f"{indent}└ {comment.author} · {comment.created_at}\n"
            f"{indent}  {comment.content}"
        )

    def action_previous_page(self) -> None:
        if not self._reader_is_usable():
            return
        if self.query_one("#post-list", ListView).has_focus:
            if self.board_has_previous:
                self.load_board(target_page=self.board_page - 1)
            return
        if (
            self.query_one("#article-pane", ArticlePane).has_focus
            and self.comments_have_previous
        ):
            self.load_post(target_page=self.comment_page - 1)

    def action_next_page(self) -> None:
        if not self._reader_is_usable():
            return
        if self.query_one("#post-list", ListView).has_focus:
            if self.board_has_next:
                self.load_board(target_page=self.board_page + 1)
            return
        if (
            self.query_one("#article-pane", ArticlePane).has_focus
            and self.current_post is not None
            and self.comments_have_next
        ):
            self.load_post(target_page=self.comment_page + 1)

    def action_refresh(self) -> None:
        if not self._reader_is_usable():
            return
        if (
            self.current_post is not None
            and self.query_one("#article-pane", ArticlePane).has_focus
        ):
            self.load_post(refresh=True)
        else:
            self.load_board(refresh=True)

    def action_back(self) -> None:
        if not self._reader_is_usable():
            return
        self.query_one("#main", Horizontal).remove_class("reading")
        self.query_one("#post-list", ListView).focus()
        if self._direct_start:
            self._direct_start = False
            self.current_post = None
            self.load_board()

    async def action_switch_site(self) -> None:
        if (
            not self._reader_is_active()
            or self._activation_in_progress
            or self._switch_in_progress
        ):
            return
        self._switch_in_progress = True
        try:
            await self._switch_site()
        finally:
            self._switch_in_progress = False

    async def _switch_site(self) -> None:
        self.workers.cancel_all()
        await self.workers.wait_for_complete()
        try:
            await self._release_owned_resources()
        except Exception as error:
            self._reader_unusable = True
            self.notify(
                f"리소스를 닫는 중 오류가 발생했습니다: {error}",
                severity="error",
                markup=False,
            )
            return

        self.target = None
        self.adapter = None
        self.service = None
        self._reset_reader_state()
        await self.query_one("#post-list", ListView).clear()
        self.query_one("#article-title", Static).update(work_disguise.IDLE_TITLE)
        self.query_one("#article-meta", Static).update(work_disguise.IDLE_META)
        self.query_one("#article-content", Static).update(work_disguise.IDLE_BODY)
        self.query_one("#main", Horizontal).remove_class("reading")
        self._reader_context = ""
        self.title = self.TITLE
        self.sub_title = ""
        self.push_screen(LauncherScreen(), self._accept_target)

    def _reader_is_active(self) -> bool:
        return self.screen is self.default_screen

    def _reader_is_usable(self) -> bool:
        return (
            self._reader_is_active()
            and not self._activation_in_progress
            and not self._reader_unusable
            and self.target is not None
            and self.adapter is not None
            and self.service is not None
        )

    def _reset_reader_state(self) -> None:
        self.board_page = 1
        self.comment_page = 1
        self.board_has_previous = False
        self.board_has_next = False
        self.comments_have_previous = False
        self.comments_have_next = False
        self.current_post = None
        self._displayed_post_id = None
        self._board_request_id += 1
        self._post_request_id += 1
        self._pending_board_page = None
        self._pending_post_key = None
        self._direct_start = False
        self._reader_unusable = False

    def on_resize(self, event: events.Resize) -> None:
        self._sync_layout(event.size.width)

    def _sync_layout(self, width: int) -> None:
        main = self.default_screen.query_one("#main", Horizontal)
        narrow = width < 100
        main.set_class(narrow, "narrow")
        if narrow:
            if main.has_class("reading"):
                self.default_screen.query_one("#article-pane", ArticlePane).focus()
            else:
                self.default_screen.query_one("#post-list", ListView).focus()


def parse_cli(argv: Sequence[str]) -> CommunityTarget | None:
    parser = argparse.ArgumentParser(prog="commu")
    parser.add_argument("url", nargs="?")
    args = parser.parse_args(list(argv))
    return None if args.url is None else route_url(args.url)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    CommunityReaderApp(target=parse_cli(arguments)).run()
