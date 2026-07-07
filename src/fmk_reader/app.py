from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Protocol

import httpx
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from fmk_reader.adapters import CommunityAdapter, adapter_for
from fmk_reader.cache import JsonCache
from fmk_reader.client import CommunityHttpClient, make_httpx_client
from fmk_reader.errors import ReaderError
from fmk_reader.launcher import LauncherScreen
from fmk_reader.models import Comment, PageResult, PostSummary
from fmk_reader.service import CommunityService, LoadResult, PostPage
from fmk_reader.targets import CommunityTarget, RECOMMENDED_URLS, Site, route_url


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


class ResourceFactory(Protocol):
    def __call__(self, target: CommunityTarget) -> ReaderResources: ...


def create_reader_resources(target: CommunityTarget) -> ReaderResources:
    adapter = adapter_for(target)
    cache: JsonCache | None = None
    raw_client: httpx.AsyncClient | None = None
    try:
        cache = JsonCache(Path.home() / ".cache" / "fmk-reader" / "cache.db")
        raw_client = make_httpx_client(adapter.policy)
        service = CommunityService(
            adapter,
            CommunityHttpClient(raw_client, adapter.policy),
            cache,
        )
        return ReaderResources(raw_client, cache, adapter, service)
    except BaseException:
        if cache is not None:
            cache.close()
        if raw_client is not None:
            _close_failed_client(raw_client)
        raise


async def _quietly_close_client(raw_client: httpx.AsyncClient) -> None:
    try:
        await raw_client.aclose()
    except Exception:
        pass


def _close_failed_client(raw_client: httpx.AsyncClient) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_quietly_close_client(raw_client))
    else:
        loop.create_task(_quietly_close_client(raw_client))


class PostItem(ListItem):
    """A variable-height board row which retains its source model."""

    def __init__(self, post: PostSummary) -> None:
        self.post = post
        text = (
            f"[{post.category}] {post.title}\n"
            f"추천 {post.votes} · 댓글 {post.comment_count} · {post.created_at}"
        )
        super().__init__(Label(text, markup=False))


class ArticlePane(VerticalScroll):
    can_focus = True


class CommunityReaderApp(App[None]):
    TITLE = "Commu"
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
        self.target = target
        self.raw_client = None
        self.cache = None
        self.adapter: CommunityAdapter | None = None
        self._resource_factory = resource_factory or create_reader_resources
        self._owns_resources = False
        self.service = service

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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(id="post-list")
            with ArticlePane(id="article-pane"):
                yield Static(
                    "글을 선택하세요",
                    id="article-title",
                    markup=False,
                )
                yield Static("", id="article-meta", markup=False)
                yield Static("", id="article-content", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._sync_layout(self.size.width)
        self.query_one("#post-list", ListView).focus()
        if self.target is None:
            self.push_screen(LauncherScreen(), self._accept_target)
            return
        self._activate_target(self.target)

    async def on_unmount(self) -> None:
        await self._release_owned_resources()

    def _accept_target(self, target: CommunityTarget | None) -> None:
        if target is None:
            return
        self.target = target
        self._activate_target(target)

    def _activate_target(self, target: CommunityTarget) -> None:
        if self.service is None:
            resources = self._resource_factory(target)
            self.raw_client = resources.raw_client
            self.cache = resources.cache
            self.adapter = resources.adapter
            self.service = resources.service
            self._owns_resources = True
        elif self.adapter is None:
            self.adapter = adapter_for(target)
        direct_post = self.adapter.direct_post()
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

    async def _release_owned_resources(self) -> None:
        if not self._owns_resources:
            return
        raw_client = self.raw_client
        cache = self.cache
        self.raw_client = None
        self.cache = None
        self._owns_resources = False
        try:
            if raw_client is not None:
                await raw_client.aclose()
        finally:
            if cache is not None:
                cache.close()

    def load_board(
        self,
        refresh: bool = False,
        *,
        target_page: int | None = None,
    ) -> None:
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
            self.sub_title = (
                f"{result.value.page}페이지 · {result.source.value}"
            )
            if result.warning:
                self.notify(result.warning, severity="warning", markup=False)
        finally:
            if request_id == self._board_request_id:
                self._pending_board_page = None

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not isinstance(event.item, PostItem):
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
                f"{summary.author} · {summary.created_at} · 조회 {summary.views} "
                f"· 추천 {summary.votes} · 댓글 {summary.comment_count}"
            )
            self.query_one("#article-content", Static).update(
                self._format_article(page)
            )
            self.sub_title = (
                f"글 {summary.post_id} · 댓글 {page.comments.page}페이지 "
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
        self.query_one("#article-meta", Static).update("불러오는 중...")
        self.query_one("#article-content", Static).update("불러오는 중...")

    def _show_load_failure(
        self, post: PostSummary, error: ReaderError
    ) -> None:
        self.query_one("#article-title", Static).update(post.title)
        self.query_one("#article-meta", Static).update("불러오기 실패")
        self.query_one("#article-content", Static).update(
            f"불러오기 실패: {error}"
        )

    @staticmethod
    def _format_article(page: PostPage) -> str:
        sections = [page.detail.body]
        if page.detail.links:
            sections.append("링크\n" + "\n".join(page.detail.links))
        comments = "\n\n".join(
            CommunityReaderApp._format_comment(comment)
            for comment in page.comments.items
        )
        sections.append(f"댓글 {page.comments.page}페이지\n{comments}")
        return "\n\n".join(sections)

    @staticmethod
    def _format_comment(comment: Comment) -> str:
        indent = "  " * comment.depth
        return (
            f"{indent}└ {comment.author} · {comment.created_at}\n"
            f"{indent}  {comment.content}"
        )

    def action_previous_page(self) -> None:
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
        if (
            self.current_post is not None
            and self.query_one("#article-pane", ArticlePane).has_focus
        ):
            self.load_post(refresh=True)
        else:
            self.load_board(refresh=True)

    def action_back(self) -> None:
        self.query_one("#main", Horizontal).remove_class("reading")
        self.query_one("#post-list", ListView).focus()
        if self._direct_start:
            self._direct_start = False
            self.current_post = None
            self.load_board()

    async def action_switch_site(self) -> None:
        self.workers.cancel_all()
        await self.workers.wait_for_complete()
        try:
            await self._release_owned_resources()
        except Exception as error:
            self.notify(
                f"리소스를 닫는 중 오류가 발생했습니다: {error}",
                severity="error",
                markup=False,
            )

        self.target = None
        self.adapter = None
        self.service = None
        self._reset_reader_state()
        await self.query_one("#post-list", ListView).clear()
        self.query_one("#article-title", Static).update("글을 선택하세요")
        self.query_one("#article-meta", Static).update("")
        self.query_one("#article-content", Static).update("")
        self.query_one("#main", Horizontal).remove_class("reading")
        self.sub_title = ""
        self.push_screen(LauncherScreen(), self._accept_target)

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


FmkReaderApp = CommunityReaderApp
