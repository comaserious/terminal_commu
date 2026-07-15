from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, ListView, OptionList, Static, Tree
from textual.widgets.option_list import Option

from commu.errors import TargetError
from commu.launcher import LauncherError
from commu.models import PostSummary
from commu.targets import CommunityTarget, RECOMMENDED_URLS, Site, route_url
from commu.url_history import UrlHistory


class ExplorerNodeKind(Enum):
    ROOT = "root"
    SITE = "site"
    RECOMMENDED = "recommended"
    HISTORY = "history"
    DIRECT = "direct"
    BOARD = "board"
    POST = "post"


@dataclass(frozen=True, slots=True)
class ExplorerNode:
    kind: ExplorerNodeKind
    site: Site | None = None
    target: CommunityTarget | None = None
    post: PostSummary | None = None
    url: str | None = None


class PathBar(Static):
    def __init__(self, *segments: str, id: str | None = None) -> None:
        super().__init__("", id=id, markup=False)
        self.set_path(*(segments or ("communities",)))

    def set_path(self, *segments: str) -> None:
        self.update(Text("~/" + "/".join(segments)))


class NavigationTree(Tree[ExplorerNode]):
    BINDINGS = [
        Binding("left", "collapse_selected", show=False),
        Binding("right", "expand_selected", show=False),
    ]

    class NodeActivated(Message):
        def __init__(self, node: ExplorerNode) -> None:
            super().__init__()
            self.node = node

    def __init__(self, history: UrlHistory, *, id: str | None = None) -> None:
        super().__init__(
            Text("communities/"),
            ExplorerNode(ExplorerNodeKind.ROOT),
            id=id,
        )
        self._site_nodes = {}
        self._board_node = None
        self._post_nodes = {}
        self.root.expand()
        for site in Site:
            site_node = self.root.add(
                Text(f"{site.display_name}/"),
                ExplorerNode(ExplorerNodeKind.SITE, site=site),
                expand=False,
            )
            site_node.add_leaf(
                Text("recommended/"),
                ExplorerNode(
                    ExplorerNodeKind.RECOMMENDED,
                    site=site,
                    target=route_url(RECOMMENDED_URLS[site]),
                ),
            )
            for entry in history.entries(site):
                site_node.add_leaf(
                    Text(f"recent/{entry.label}"),
                    ExplorerNode(
                        ExplorerNodeKind.HISTORY,
                        site=site,
                        target=route_url(entry.url),
                        url=entry.url,
                    ),
                )
            site_node.add_leaf(
                Text("enter-url"),
                ExplorerNode(ExplorerNodeKind.DIRECT, site=site),
            )
            self._site_nodes[site] = site_node

    @property
    def board_nodes(self) -> tuple:
        return () if self._board_node is None else (self._board_node,)

    @property
    def post_nodes(self) -> tuple:
        if self._board_node is None:
            return ()
        return tuple(self._board_node.children)

    def select_site(self, site: Site) -> None:
        node = self._site_nodes[site]
        node.expand()
        self.select_node(node)

    def move_to_site(self, site: Site) -> None:
        node = self._site_nodes[site]
        node.expand()
        self.move_cursor(node)

    def move_to_board(self) -> None:
        if self._board_node is not None:
            self.move_cursor(self._board_node)

    def set_board(
        self,
        target: CommunityTarget,
        posts: Sequence[PostSummary],
    ) -> None:
        if (
            self._board_node is None
            or self._board_node.data is None
            or self._board_node.data.target != target
        ):
            if self._board_node is not None:
                self._board_node.remove()
            site_node = self._site_nodes[target.site]
            site_node.expand()
            self._board_node = site_node.add(
                Text(f"{target.board_id}/"),
                ExplorerNode(
                    ExplorerNodeKind.BOARD,
                    site=target.site,
                    target=target,
                ),
                expand=True,
            )
        else:
            self._board_node.remove_children()
        self._post_nodes = {}
        for post in posts:
            category = f"[{post.category}] " if post.category else ""
            node = self._board_node.add_leaf(
                Text(f"{category}{post.title}"),
                ExplorerNode(
                    ExplorerNodeKind.POST,
                    site=target.site,
                    target=target,
                    post=post,
                ),
            )
            self._post_nodes[post.post_id] = node
        self._board_node.expand()
        self.move_cursor(self._board_node)

    def select_post(self, post: PostSummary) -> None:
        node = self._post_nodes.get(post.post_id)
        if node is not None:
            self.move_cursor(node)

    def action_collapse_selected(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.select_node(node.parent)

    def action_expand_selected(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if not node.is_expanded:
            node.expand()
        elif node.children:
            self.select_node(node.children[0])

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data is not None:
            self.post_message(self.NodeActivated(event.node.data))


class AccessPane(Vertical):
    class TargetSelected(Message):
        def __init__(self, target: CommunityTarget) -> None:
            super().__init__()
            self.target = target

    def __init__(
        self,
        history: UrlHistory,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._history = history
        self._site: Site | None = None
        self._known_urls: tuple[str, ...] = ()

    @property
    def known_urls(self) -> tuple[str, ...]:
        return self._known_urls

    def compose(self) -> ComposeResult:
        yield Static("Select a site", id="access-title", markup=False)
        yield Static(
            "ACCESS · ↑/↓ select · Enter open · Esc up",
            id="access-hint",
            markup=False,
        )
        yield OptionList(id="explorer-access", markup=False)
        target_url = Input(
            placeholder="Supported board or post URL",
            id="explorer-target-url",
        )
        target_url.display = False
        yield target_url
        yield LauncherError("", id="explorer-access-error", markup=False)

    def show_site(self, site: Site) -> None:
        self._site = site
        entries = self._history.entries(site)
        self._known_urls = tuple(entry.url for entry in entries)
        self.query_one("#access-title", Static).update(site.display_name)
        options = self.query_one("#explorer-access", OptionList)
        options.clear_options()
        options.add_option(Option("Recommended board", id="recommended"))
        for index, entry in enumerate(entries):
            options.add_option(
                Option(f"Recent URL · {entry.label}", id=f"history:{index}")
            )
        options.add_option(Option("Enter URL", id="direct"))
        options.highlighted = 0
        options.display = True
        self.query_one("#explorer-target-url", Input).display = False
        self.query_one("#explorer-access-error", Static).update("")

    def focus_options(self) -> None:
        self.query_one("#explorer-access", OptionList).focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id != "explorer-access" or self._site is None:
            return
        option_id = event.option.id
        if option_id == "recommended":
            self.post_message(
                self.TargetSelected(route_url(RECOMMENDED_URLS[self._site]))
            )
            return
        if option_id == "direct":
            self.show_url_input()
            return
        if option_id is None or not option_id.startswith("history:"):
            return
        index = int(option_id.removeprefix("history:"))
        self.post_message(
            self.TargetSelected(route_url(self._known_urls[index]))
        )

    def show_url_input(self) -> None:
        self.query_one("#explorer-access", OptionList).display = False
        target_url = self.query_one("#explorer-target-url", Input)
        target_url.display = True
        self.query_one("#explorer-access-error", Static).update("")
        target_url.focus()

    def show_options(self) -> None:
        self.query_one("#explorer-target-url", Input).display = False
        options = self.query_one("#explorer-access", OptionList)
        options.display = True
        self.query_one("#explorer-access-error", Static).update("")
        options.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "explorer-target-url":
            return
        try:
            target = route_url(event.value)
        except TargetError as error:
            self.query_one("#explorer-access-error", Static).update(str(error))
            return
        try:
            self._history.record(event.value)
        except OSError:
            pass
        self.post_message(self.TargetSelected(target))


class PostListPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(
            "POSTS · Enter read · ←/→ page · Esc tree",
            id="list-hint",
            markup=False,
        )
        yield ListView(id="post-list")


class ArticlePane(VerticalScroll):
    can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(
            "ARTICLE · Esc posts · ←/→ comment page",
            id="article-hint",
            markup=False,
        )
        yield Static("Select a post", id="article-title", markup=False)
        yield Static("", id="article-meta", markup=False)
        yield Static("", id="article-content", markup=False)


class ExplorerShell(Vertical):
    def __init__(
        self,
        history: UrlHistory,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes="root")
        self._history = history
        self._target: CommunityTarget | None = None
        self.active_pane = "tree"
        self._state = "root"
        self._narrow = False

    def compose(self) -> ComposeResult:
        yield PathBar(id="path-bar")
        with Horizontal(id="explorer-body"):
            with Vertical(id="explorer-tree-pane", classes="explorer-pane"):
                yield Static(
                    "TREE · ←/→ Collapse/expand · Enter open · Esc up",
                    id="tree-hint",
                    markup=False,
                )
                yield NavigationTree(self._history, id="navigation-tree")
            yield AccessPane(
                self._history,
                id="explorer-access-pane",
                classes="explorer-pane",
            )
            yield PostListPane(
                id="post-list-pane",
                classes="explorer-pane",
            )
            yield ArticlePane(
                id="article-pane",
                classes="explorer-pane",
            )
        yield Static(
            "GLOBAL · Tab pane · r refresh · s sites · q quit",
            id="global-hints",
            markup=False,
        )

    def on_mount(self) -> None:
        self.show_root()

    def _set_state(self, state: str) -> None:
        self._state = state
        for name in ("root", "site", "loading", "board", "reading"):
            self.remove_class(name)
        self.add_class(state)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        tree_pane = self.query_one("#explorer-tree-pane")
        access = self.query_one(AccessPane)
        post_list = self.query_one(PostListPane)
        article = self.query_one(ArticlePane)
        if self._narrow:
            tree_pane.display = self.active_pane == "tree"
            access.display = self.active_pane == "access"
            post_list.display = self.active_pane == "list"
            article.display = self.active_pane == "article"
            return
        tree_pane.display = True
        access.display = self._state in {"root", "site", "loading"}
        post_list.display = self._state in {"board", "reading"}
        article.display = self._state == "reading"

    def show_root(self) -> None:
        self._target = None
        self.active_pane = "tree"
        self._set_state("root")
        self.query_one(PathBar).set_path("communities")
        self.query_one("#access-title", Static).update("Select a site")

    def show_site(self, site: Site) -> None:
        self._target = None
        self.active_pane = "access"
        self._set_state("site")
        self.query_one(PathBar).set_path("communities", site.display_name)
        pane = self.query_one(AccessPane)
        pane.show_site(site)
        pane.focus_options()

    def show_loading(self, target: CommunityTarget) -> None:
        self._target = target
        self.active_pane = "access"
        self._set_state("loading")
        self.query_one(PathBar).set_path(
            "communities",
            target.site.display_name,
            target.board_id,
        )
        self.query_one("#access-title", Static).update("Preparing community...")

    def show_board(
        self,
        target: CommunityTarget,
        posts: tuple[PostSummary, ...] | list[PostSummary],
    ) -> None:
        self._target = target
        self.active_pane = "list"
        self._set_state("board")
        self.query_one(PathBar).set_path(
            "communities",
            target.site.display_name,
            target.board_id,
        )
        self.query_one(NavigationTree).set_board(target, posts)

    def show_article(self, post: PostSummary) -> None:
        if self._target is None:
            return
        self.active_pane = "article"
        self._set_state("reading")
        self.query_one(PathBar).set_path(
            "communities",
            self._target.site.display_name,
            self._target.board_id,
            post.post_id,
        )
        self.query_one(NavigationTree).select_post(post)

    def show_list(self) -> None:
        if self._target is None:
            return
        self.active_pane = "list"
        self._set_state("board")
        self.query_one(PathBar).set_path(
            "communities",
            self._target.site.display_name,
            self._target.board_id,
        )

    def set_narrow(self, narrow: bool) -> None:
        self._narrow = narrow
        self.set_class(narrow, "narrow")
        self._apply_visibility()

    def focus_tree_sites(self) -> None:
        self.active_pane = "tree"
        tree = self.query_one(NavigationTree)
        if self._target is not None:
            tree.move_to_site(self._target.site)
        self._apply_visibility()
        tree.focus()

    def focus_tree_board(self) -> None:
        self.active_pane = "tree"
        tree = self.query_one(NavigationTree)
        tree.move_to_board()
        self._apply_visibility()
        tree.focus()
