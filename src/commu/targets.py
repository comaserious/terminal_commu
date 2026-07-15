import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import SplitResult, parse_qs, urlsplit, urlunsplit

from commu.errors import TargetError

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")
_DC_DESKTOP_PATHS = {
    "/board/lists": False,
    "/board/view": True,
    "/mgallery/board/lists": False,
    "/mgallery/board/view": True,
    "/mini/board/lists": False,
    "/mini/board/view": True,
}


class Site(str, Enum):
    FMKOREA = "fmkorea"
    DCINSIDE = "dcinside"
    ARCA = "arca"

    @property
    def display_name(self) -> str:
        return {
            Site.FMKOREA: "FMKorea",
            Site.DCINSIDE: "DCInside",
            Site.ARCA: "Arca Live",
        }[self]


@dataclass(frozen=True, slots=True)
class CommunityTarget:
    site: Site
    board_id: str
    board_url: str
    article_id: str | None = None
    article_url: str | None = None


RECOMMENDED_URLS = {
    Site.FMKOREA: "https://www.fmkorea.com/football_world",
    Site.DCINSIDE: "https://gall.dcinside.com/board/lists/?id=football_new9",
    Site.ARCA: "https://arca.live/b/rogersfu",
}


def route_url(raw: str) -> CommunityTarget:
    """Validate and canonicalize one supported read-only community URL."""
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise TargetError("Community URL must be a non-empty string")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise TargetError("Community URL contains control characters")

    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise TargetError("Community URL is malformed") from exc

    if parsed.scheme != "https":
        raise TargetError("Community URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise TargetError("Community URL must not contain credentials")
    if port not in (None, 443):
        raise TargetError("Community URL must use the default HTTPS port")

    routers = {
        "www.fmkorea.com": _route_fmk,
        "m.fmkorea.com": _route_fmk,
        "gall.dcinside.com": _route_dcinside,
        "m.dcinside.com": _route_dcinside,
        "arca.live": _route_arca,
    }
    router = routers.get(hostname)
    if router is None:
        raise TargetError(f"Unsupported community host: {hostname or '(missing)'}")
    return router(parsed)


def _route_fmk(parsed: SplitResult) -> CommunityTarget:
    path = _without_optional_trailing_slash(parsed.path)
    board_url = _canonical_url("www.fmkorea.com", "/football_world")
    if path == "/football_world":
        return CommunityTarget(Site.FMKOREA, "football_world", board_url)

    article_id = path.removeprefix("/")
    if path.count("/") != 1 or not _valid_article_id(article_id):
        raise TargetError("Unsupported FMKorea path")
    return CommunityTarget(
        Site.FMKOREA,
        "football_world",
        board_url,
        article_id,
        _canonical_url("www.fmkorea.com", f"/{article_id}"),
    )


def _route_dcinside(parsed: SplitResult) -> CommunityTarget:
    if parsed.hostname == "gall.dcinside.com":
        board_id, article_id = _route_dcinside_desktop(parsed)
    else:
        board_id, article_id = _route_dcinside_mobile(parsed)

    board_url = _canonical_url("m.dcinside.com", f"/board/{board_id}")
    article_url = (
        _canonical_url("m.dcinside.com", f"/board/{board_id}/{article_id}")
        if article_id is not None
        else None
    )
    return CommunityTarget(
        Site.DCINSIDE,
        board_id,
        board_url,
        article_id,
        article_url,
    )


def _route_dcinside_desktop(parsed: SplitResult) -> tuple[str, str | None]:
    path = _without_optional_trailing_slash(parsed.path)
    is_article = _DC_DESKTOP_PATHS.get(path)
    if is_article is None:
        raise TargetError("Unsupported DCInside desktop path")

    query = parse_qs(parsed.query, keep_blank_values=True)
    board_id = _single_query_value(query, "id")
    if not _valid_board_id(board_id):
        raise TargetError("Invalid DCInside gallery identifier")

    if not is_article:
        return board_id, None
    article_id = _single_query_value(query, "no")
    if not _valid_article_id(article_id):
        raise TargetError("Invalid DCInside article identifier")
    return board_id, article_id


def _route_dcinside_mobile(parsed: SplitResult) -> tuple[str, str | None]:
    segments = _path_segments(parsed.path)
    if len(segments) not in (2, 3) or segments[0] != "board":
        raise TargetError("Unsupported DCInside mobile path")

    board_id = segments[1]
    if not _valid_board_id(board_id):
        raise TargetError("Invalid DCInside gallery identifier")
    if len(segments) == 2:
        return board_id, None

    article_id = segments[2]
    if not _valid_article_id(article_id):
        raise TargetError("Invalid DCInside article identifier")
    return board_id, article_id


def _route_arca(parsed: SplitResult) -> CommunityTarget:
    segments = _path_segments(parsed.path)
    if len(segments) not in (2, 3) or segments[0] != "b":
        raise TargetError("Unsupported Arca Live path")

    board_id = segments[1]
    if not _valid_board_id(board_id):
        raise TargetError("Invalid Arca Live channel identifier")

    article_id = None if len(segments) == 2 else segments[2]
    if article_id is not None and not _valid_article_id(article_id):
        raise TargetError("Invalid Arca Live article identifier")

    board_url = _canonical_url("arca.live", f"/b/{board_id}")
    article_url = (
        _canonical_url("arca.live", f"/b/{board_id}/{article_id}")
        if article_id is not None
        else None
    )
    return CommunityTarget(Site.ARCA, board_id, board_url, article_id, article_url)


def _valid_board_id(value: str | None) -> bool:
    return value is not None and _IDENTIFIER_PATTERN.fullmatch(value) is not None


def _valid_article_id(value: str | None) -> bool:
    return value is not None and value.isdecimal()


def _single_query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    return values[0] if len(values) == 1 else None


def _without_optional_trailing_slash(path: str) -> str:
    return path[:-1] if path.endswith("/") and path != "/" else path


def _path_segments(path: str) -> list[str]:
    normalized = _without_optional_trailing_slash(path)
    if not normalized.startswith("/"):
        return []
    return normalized.removeprefix("/").split("/")


def _canonical_url(host: str, path: str) -> str:
    return urlunsplit(("https", host, path, "", ""))
