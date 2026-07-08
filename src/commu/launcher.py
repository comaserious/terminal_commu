from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from commu.errors import TargetError
from commu.targets import CommunityTarget, RECOMMENDED_URLS, Site, route_url


class LauncherError(Static):
    @property
    def markup(self) -> bool:
        return self._render_markup

    @property
    def renderable(self):
        """Expose the literal content for stable interaction assertions."""
        return self.render()


class LauncherOptionList(OptionList):
    """Keep rapid keyboard sequences on the launcher's current step."""

    BINDINGS = []

    def action_select(self) -> None:
        screen = self.screen
        if isinstance(screen, LauncherScreen):
            screen.action_select()

    def action_cursor_up(self) -> None:
        screen = self.screen
        if isinstance(screen, LauncherScreen):
            screen.move_option(-1)

    def action_cursor_down(self) -> None:
        screen = self.screen
        if isinstance(screen, LauncherScreen):
            screen.move_option(1)


class LauncherScreen(Screen[CommunityTarget]):
    """Select and validate a community target without creating resources."""

    BINDINGS = [
        Binding("up", "move_up", "위", priority=True),
        Binding("down", "move_down", "아래", priority=True),
        Binding("enter", "select", "선택", priority=True),
        Binding("escape", "back", "뒤로", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._site: Site | None = None
        self._step = "site"

    def compose(self) -> ComposeResult:
        with Vertical(id="launcher"):
            yield Static("커뮤니티 선택", id="launcher-title", markup=False)
            yield LauncherOptionList(
                *(
                    Option(site.display_name, id=site.value)
                    for site in Site
                ),
                id="launcher-sites",
                markup=False,
            )
            access = LauncherOptionList(
                Option("추천 게시판", id="recommended"),
                Option("URL 직접 입력", id="direct"),
                id="launcher-access",
                markup=False,
            )
            access.display = False
            yield access
            target_url = Input(
                placeholder="지원하는 게시판 또는 게시글 URL",
                id="target-url",
            )
            target_url.display = False
            yield target_url
            yield LauncherError("", id="launcher-error", markup=False)

    def on_mount(self) -> None:
        self.query_one("#launcher-sites", OptionList).focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "launcher-sites":
            self._site = Site(event.option.id)
            self._show_access()
            return
        if event.option_list.id != "launcher-access":
            return
        if event.option.id == "recommended":
            assert self._site is not None
            self.dismiss(route_url(RECOMMENDED_URLS[self._site]))
        else:
            self._show_url_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "target-url":
            return
        self._submit_url(event.value)

    def action_select(self) -> None:
        if self._step == "site":
            sites = self.query_one("#launcher-sites", OptionList)
            if sites.highlighted is None:
                return
            option = sites.get_option_at_index(sites.highlighted)
            assert option.id is not None
            self._site = Site(option.id)
            self._show_access()
        elif self._step == "access":
            access = self.query_one("#launcher-access", OptionList)
            if access.highlighted is None:
                return
            option = access.get_option_at_index(access.highlighted)
            if option.id == "recommended":
                assert self._site is not None
                self.dismiss(route_url(RECOMMENDED_URLS[self._site]))
            else:
                self._show_url_input()
        else:
            self._submit_url(self.query_one("#target-url", Input).value)

    def move_option(self, direction: int) -> None:
        option_list = self._active_option_list()
        if option_list is None:
            return
        if direction < 0:
            OptionList.action_cursor_up(option_list)
        else:
            OptionList.action_cursor_down(option_list)

    def action_move_up(self) -> None:
        self.move_option(-1)

    def action_move_down(self) -> None:
        self.move_option(1)

    def _active_option_list(self) -> OptionList | None:
        if self._step == "site":
            return self.query_one("#launcher-sites", OptionList)
        if self._step == "access":
            return self.query_one("#launcher-access", OptionList)
        return None

    def _submit_url(self, value: str) -> None:
        try:
            target = route_url(value)
        except TargetError as error:
            self.query_one("#launcher-error", Static).update(str(error))
            return
        self.dismiss(target)

    def action_back(self) -> None:
        if self._step == "url":
            self._show_access()
        elif self._step == "access":
            self._show_sites()

    def _show_sites(self) -> None:
        self._step = "site"
        self.query_one("#launcher-sites", OptionList).display = True
        self.query_one("#launcher-access", OptionList).display = False
        self.query_one("#target-url", Input).display = False
        self.query_one("#launcher-error", Static).update("")
        self.query_one("#launcher-sites", OptionList).focus()

    def _show_access(self) -> None:
        self._step = "access"
        self.query_one("#launcher-sites", OptionList).display = False
        access = self.query_one("#launcher-access", OptionList)
        access.display = True
        access.highlighted = 0
        self.query_one("#target-url", Input).display = False
        self.query_one("#launcher-error", Static).update("")
        access.focus()

    def _show_url_input(self) -> None:
        self._step = "url"
        self.query_one("#launcher-access", OptionList).display = False
        target_url = self.query_one("#target-url", Input)
        target_url.display = True
        self.query_one("#launcher-error", Static).update("")
        target_url.focus()
