from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
import inspect
from pathlib import Path
import sys
from typing import Protocol

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from commu.adapters import CommunityAdapter, adapter_for
from commu.browser import BrowserRuntime
from commu.cache import JsonCache
from commu.client import (
    DEFAULT_REQUEST_STATE_REGISTRY,
    PlaywrightCommunityClient,
)
from commu.errors import ReaderError
from commu.explorer import (
    AccessPane,
    ArticlePane,
    ExplorerNodeKind,
    ExplorerShell,
    NavigationTree,
)
from commu.models import Comment, PageResult, PostSummary
from commu.paths import cache_path
from commu.service import CommunityService, LoadResult, PostPage
from commu.targets import CommunityTarget, RECOMMENDED_URLS, Site, route_url
from commu.url_history import UrlHistory, default_url_history_path


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
    client: PlaywrightCommunityClient
    cache: JsonCache
    adapter: CommunityAdapter
    service: CommunityService


@dataclass(slots=True)
class PendingResourceCleanup:
    resources: ReaderResources
    cache_closed: bool = False


class ResourceFactory(Protocol):
    def __call__(
        self,
        target: CommunityTarget,
        runtime: BrowserRuntime,
    ) -> ReaderResources | Awaitable[ReaderResources]: ...


def default_cache_path(home: Path | None = None) -> Path:
    return cache_path(home)


async def create_reader_resources(
    target: CommunityTarget,
    runtime: BrowserRuntime,
) -> ReaderResources:
    adapter = adapter_for(target)
    cache: JsonCache | None = None
    try:
        cache = JsonCache(default_cache_path())
        client = PlaywrightCommunityClient(
            runtime,
            adapter.policy,
            state=DEFAULT_REQUEST_STATE_REGISTRY.state_for(target.site),
        )
        service = CommunityService(
            adapter,
            client,
            cache,
        )
        return ReaderResources(client, cache, adapter, service)
    except BaseException as original_error:
        cleanup_errors: list[BaseException] = []
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
        heading_children: list[Label] = []
        if post.category:
            heading_children.append(
                Label(
                    f"[{post.category}]",
                    classes="post-category",
                    markup=False,
                )
            )
        heading_children.append(
            Label(post.title, classes="post-title", markup=False)
        )
        heading = Horizontal(*heading_children, classes="post-heading")
        metadata = Label(
            f"Votes {post.votes} · Comments {post.comment_count} · "
            f"{post.created_at}",
            classes="post-meta",
            markup=False,
        )
        super().__init__(heading, metadata)


class CommunityReaderApp(App[None]):
    TITLE = "Commu"
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    BINDINGS = [
        ("left", "previous_page", "Previous page"),
        ("right", "next_page", "Next page"),
        ("r", "refresh", "Refresh"),
        ("escape", "back", "Back"),
        ("s", "switch_site", "Select site"),
        ("q", "quit", "Quit"),
    ]

    def _get_dom_base(self):
        """Make app-level queries follow the active launcher or reader screen."""
        return self.screen

    def __init__(
        self,
        target: CommunityTarget | None = None,
        service: ReaderService | None = None,
        browser_runtime: BrowserRuntime | None = None,
        resource_factory: ResourceFactory | None = None,
        url_history: UrlHistory | None = None,
    ) -> None:
        super().__init__()
        if service is not None and target is None:
            target = route_url(RECOMMENDED_URLS[Site.FMKOREA])
        self.target: CommunityTarget | None = None
        self._initial_target = target
        self._injected_service = service
        self.browser_runtime = (
            browser_runtime if browser_runtime is not None else BrowserRuntime()
        )
        self.client = None
        self.cache = None
        self.adapter: CommunityAdapter | None = None
        self._resource_factory = resource_factory or create_reader_resources
        self._owns_resources = False
        self._cache_closed = False
        self.service: ReaderService | None = None
        self.url_history = url_history or UrlHistory(default_url_history_path())

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
        yield ExplorerShell(self.url_history, id="explorer-shell")
        yield Footer()

    async def on_mount(self) -> None:
        self._sync_layout(self.size.width)
        await self.browser_runtime.start()
        if self._initial_target is None:
            self.query_one(ExplorerShell).show_root()
            self.query_one(NavigationTree).focus()
            return
        self.query_one("#post-list", ListView).focus()
        self._begin_activation(self._initial_target, self._injected_service)

    async def on_unmount(self) -> None:
        self._activation_generation += 1
        self._activation_in_progress = False
        runtime_error: BaseException | None = None
        try:
            await self.browser_runtime.aclose()
        except BaseException as error:
            runtime_error = error
        active_error: BaseException | None = None
        try:
            await self._release_owned_resources()
        except BaseException as error:
            active_error = error
        cleanup_errors = await self._retry_pending_resource_cleanups()
        if runtime_error is not None:
            if active_error is not None:
                runtime_error.add_note(f"Additional cleanup error: {active_error}")
            for cleanup_error in cleanup_errors:
                runtime_error.add_note(
                    f"Additional retained cleanup error: {cleanup_error}"
                )
            raise runtime_error
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

    def on_access_pane_target_selected(
        self, event: AccessPane.TargetSelected
    ) -> None:
        if self._activation_in_progress:
            return
        self._begin_activation(event.target)

    async def on_navigation_tree_node_activated(
        self, event: NavigationTree.NodeActivated
    ) -> None:
        node = event.node
        shell = self.query_one(ExplorerShell)
        if node.kind is ExplorerNodeKind.ROOT:
            if self.target is not None:
                await self._switch_site()
            else:
                shell.show_root()
            return
        if node.kind is ExplorerNodeKind.SITE and node.site is not None:
            if self.target is not None:
                await self._switch_site(node.site)
            else:
                shell.show_site(node.site)
            return
        if node.kind is ExplorerNodeKind.DIRECT and node.site is not None:
            shell.show_site(node.site)
            shell.query_one(AccessPane).show_url_input()
            return
        if node.kind is ExplorerNodeKind.BOARD:
            shell.show_list()
            self.query_one("#post-list", ListView).focus()
            return
        if node.kind is ExplorerNodeKind.POST and node.post is not None:
            post_list = self.query_one("#post-list", ListView)
            for index, item in enumerate(post_list.children):
                if isinstance(item, PostItem) and item.post == node.post:
                    post_list.index = index
                    break
            self._open_post(node.post)
            return
        if node.target is not None and not self._activation_in_progress:
            self._begin_activation(node.target)

    def _begin_activation(
        self,
        target: CommunityTarget,
        injected_service: ReaderService | None = None,
    ) -> None:
        self._activation_generation += 1
        generation = self._activation_generation
        self._activation_in_progress = True
        self._show_activation_loading(target)
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
                pending_resources = self._resource_factory(
                    target,
                    self.browser_runtime,
                )
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
                    f"Could not prepare community: {error}",
                    severity="error",
                    markup=False,
                )
                self.query_one(ExplorerShell).show_site(target.site)
            return

        if generation != self._activation_generation:
            if resources is not None:
                await self._discard_resources(resources)
            return

        self.target = target
        self.adapter = adapter
        self.service = service
        if resources is not None:
            self.client = resources.client
            self.cache = resources.cache
            self._owns_resources = True
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
        shell = self.query_one(ExplorerShell)
        shell.show_board(target, (direct_post,))
        shell.show_article(direct_post)
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
                "Unused resource cleanup failed: "
                f"{cleanup_errors[0]}",
                severity="error",
                markup=False,
            )

    async def _close_pending_resources(
        self,
        pending: PendingResourceCleanup,
    ) -> list[BaseException]:
        cleanup_errors: list[BaseException] = []
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
        self._reader_context = f"{site.display_name} · {board_id}"
        self.title = f"{self.TITLE} · {self._reader_context}"
        self.sub_title = self._reader_context

    def _status_with_context(self, status: str) -> str:
        if not self._reader_context:
            return status
        return f"{self._reader_context} · {status}"

    def _show_activation_loading(self, target: CommunityTarget) -> None:
        self.default_screen.query_one(ExplorerShell).show_loading(target)
        self.default_screen.query_one("#article-title", Static).update(
            "Preparing community"
        )
        self.default_screen.query_one("#article-meta", Static).update("Preparing...")
        self.default_screen.query_one("#article-content", Static).update("")
        self.sub_title = "Preparing community"

    def _clear_uncommitted_activation(self) -> None:
        self.target = None
        self.adapter = None
        self.service = None
        self.client = None
        self.cache = None
        self._owns_resources = False

    def _open_launcher(self) -> None:
        self.query_one(ExplorerShell).show_root()

    async def _release_owned_resources(self) -> None:
        if not self._owns_resources:
            return
        errors: list[BaseException] = []
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
        self.client = None
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
            if self.target is not None:
                self.query_one(ExplorerShell).show_board(
                    self.target,
                    result.value.items,
                )
                post_list.focus()
            self.sub_title = self._status_with_context(
                f"Page {result.value.page} · {result.source.value}"
            )
            if result.warning:
                self.notify(result.warning, severity="warning", markup=False)
        finally:
            if request_id == self._board_request_id:
                self._pending_board_page = None

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self._reader_is_usable() or not isinstance(event.item, PostItem):
            return
        self._open_post(event.item.post)

    def _open_post(self, post: PostSummary) -> None:
        if not self._reader_is_usable():
            return
        self.current_post = post
        self.comment_page = 1
        self.comments_have_previous = False
        self.comments_have_next = False
        self._displayed_post_id = None
        self._show_loading(post)
        shell = self.query_one(ExplorerShell)
        shell.show_article(post)
        if shell.has_class("narrow"):
            self.query_one("#article-pane", ArticlePane).focus()
        self.load_post(post=post, target_page=1)

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
                f"{summary.author} · {summary.created_at} · Views {summary.views} "
                f"· Votes {summary.votes} · Comments {summary.comment_count}"
            )
            self.query_one("#article-content", Static).update(
                self._format_article(page)
            )
            self.sub_title = self._status_with_context(
                f"Post {summary.post_id} · Comments page {page.comments.page} "
                f"· {result.source.value}"
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
        self.query_one("#article-meta", Static).update("Loading...")
        self.query_one("#article-content", Static).update("Loading...")
        self.sub_title = self._status_with_context(
            f"Post {post.post_id} · Loading..."
        )

    def _show_load_failure(
        self, post: PostSummary, error: ReaderError
    ) -> None:
        self.query_one("#article-title", Static).update(post.title)
        self.query_one("#article-meta", Static).update("Load failed")
        self.query_one("#article-content", Static).update(
            f"Load failed: {error}"
        )
        self.sub_title = self._status_with_context(
            f"Post {post.post_id} · Load failed"
        )

    @staticmethod
    def _format_article(page: PostPage) -> str:
        sections = [page.detail.body]
        if page.detail.links:
            sections.append("Links\n" + "\n".join(page.detail.links))
        comments = "\n\n".join(
            CommunityReaderApp._format_comment(comment)
            for comment in page.comments.items
        )
        sections.append(f"Comments · Page {page.comments.page}\n{comments}")
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

    async def action_back(self) -> None:
        shell = self.query_one(ExplorerShell)
        access = shell.query_one(AccessPane)
        target_url = access.query_one("#explorer-target-url")
        if target_url.display:
            access.show_options()
            return
        if not self._reader_is_usable() and shell.has_class("site"):
            shell.show_root()
            self.query_one(NavigationTree).focus()
            return
        if not self._reader_is_usable():
            return
        article = self.query_one("#article-pane", ArticlePane)
        post_list = self.query_one("#post-list", ListView)
        tree = self.query_one(NavigationTree)
        if article.has_focus or shell.active_pane == "article":
            shell.show_list()
            post_list.focus()
            if self._direct_start:
                self._direct_start = False
                self.current_post = None
                self.load_board()
            return
        if post_list.has_focus or shell.active_pane == "list":
            shell.focus_tree_board()
            return
        if tree.has_focus or shell.active_pane == "tree":
            await self._switch_site(self.target.site)

    def action_switch_site(self) -> None:
        if not self._reader_is_active() or self._activation_in_progress:
            return
        self.query_one(ExplorerShell).focus_tree_sites()

    async def _switch_site(self, destination: Site | None = None) -> None:
        if self._switch_in_progress:
            return
        self._switch_in_progress = True
        try:
            self.workers.cancel_all()
            await self.workers.wait_for_complete()
            try:
                await self._release_owned_resources()
            except Exception as error:
                self._reader_unusable = True
                self.notify(
                    f"Resource cleanup failed: {error}",
                    severity="error",
                    markup=False,
                )
                return

            self.target = None
            self.adapter = None
            self.service = None
            self._reset_reader_state()
            await self.query_one("#post-list", ListView).clear()
            self.query_one("#article-title", Static).update("Select a post")
            self.query_one("#article-meta", Static).update("")
            self.query_one("#article-content", Static).update("")
            shell = self.query_one(ExplorerShell)
            if destination is None:
                shell.show_root()
            else:
                shell.show_site(destination)
            self._reader_context = ""
            self.title = self.TITLE
            self.sub_title = ""
        finally:
            self._switch_in_progress = False

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
        shell = self.default_screen.query_one(ExplorerShell)
        narrow = width < 100
        shell.set_narrow(narrow)
        if not narrow:
            return
        if shell.active_pane == "article":
            self.default_screen.query_one("#article-pane", ArticlePane).focus()
        elif shell.active_pane == "list":
            self.default_screen.query_one("#post-list", ListView).focus()
        elif shell.active_pane == "tree":
            self.default_screen.query_one(NavigationTree).focus()
        else:
            access = self.default_screen.query_one(AccessPane)
            if access.query_one("#explorer-target-url").display:
                access.query_one("#explorer-target-url").focus()
            else:
                access.focus_options()


def parse_cli(argv: Sequence[str]) -> CommunityTarget | None:
    parser = argparse.ArgumentParser(prog="commu")
    parser.add_argument("url", nargs="?")
    args = parser.parse_args(list(argv))
    return None if args.url is None else route_url(args.url)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    CommunityReaderApp(target=parse_cli(arguments)).run()
