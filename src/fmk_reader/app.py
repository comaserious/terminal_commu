from __future__ import annotations

from pathlib import Path
from typing import Protocol

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from fmk_reader.cache import JsonCache
from fmk_reader.client import FmkHttpClient, make_httpx_client
from fmk_reader.errors import ReaderError
from fmk_reader.models import Comment, PageResult, PostSummary
from fmk_reader.service import BoardService, LoadResult, PostPage


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


class FmkReaderApp(App[None]):
    TITLE = "FMK 해외축구"
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    BINDINGS = [
        ("left", "previous_page", "이전 페이지"),
        ("right", "next_page", "다음 페이지"),
        ("r", "refresh", "새로고침"),
        ("escape", "back", "목록"),
        ("q", "quit", "종료"),
    ]

    def __init__(self, service: ReaderService | None = None) -> None:
        super().__init__()
        self.raw_client = None
        self.cache = None
        self._owns_resources = service is None
        if service is None:
            self.raw_client = make_httpx_client()
            self.cache = JsonCache(
                Path.home() / ".cache" / "fmk-reader" / "cache.db"
            )
            service = BoardService(FmkHttpClient(self.raw_client), self.cache)
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

    async def on_mount(self) -> None:
        self._sync_layout(self.size.width)
        self.query_one("#post-list", ListView).focus()
        self.load_board()

    async def on_unmount(self) -> None:
        if not self._owns_resources:
            return
        try:
            if self.raw_client is not None:
                await self.raw_client.aclose()
        finally:
            if self.cache is not None:
                self.cache.close()

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
            FmkReaderApp._format_comment(comment)
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

    def on_resize(self, event: events.Resize) -> None:
        self._sync_layout(event.size.width)

    def _sync_layout(self, width: int) -> None:
        main = self.query_one("#main", Horizontal)
        narrow = width < 100
        main.set_class(narrow, "narrow")
        if narrow:
            if main.has_class("reading"):
                self.query_one("#article-pane", ArticlePane).focus()
            else:
                self.query_one("#post-list", ListView).focus()


def main() -> None:
    FmkReaderApp().run()
