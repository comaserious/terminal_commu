from dataclasses import dataclass
import re
from typing import ClassVar
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from commu.adapters.base import RequestPolicy
from commu.errors import ParseError
from commu.models import Comment, PageResult, PostDetail, PostSummary
from commu.parser import parse_board, parse_post
from commu.targets import CommunityTarget, Site


_BASE_URL = "https://m.fmkorea.com"
_BOARD_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)


def _board_from_url(href: str) -> str | None:
    try:
        parsed = urlsplit(urljoin(_BASE_URL, href.strip()))
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ("m.fmkorea.com", "www.fmkorea.com")
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None

    query_mid = parse_qs(parsed.query).get("mid", [])
    if len(query_mid) == 1 and _BOARD_ID.fullmatch(query_mid[0]):
        return query_mid[0]

    segments = parsed.path.strip("/").split("/")
    if (
        len(segments) == 1
        and _BOARD_ID.fullmatch(segments[0])
        and not segments[0].isdecimal()
    ):
        return segments[0]
    return None


def _returned_board_identities(html: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    identities: set[str] = set()
    selectors = (
        "link[rel~='canonical'][href]",
        ".bd_tl a[href]",
        ".tl_srch a.category[href]",
    )
    for selector in selectors:
        for marker in soup.select(selector):
            identity = _board_from_url(str(marker.get("href", "")))
            if identity is not None:
                identities.add(identity)

    for marker in soup.select("form.bd_pg input[name='mid'][value]"):
        value = str(marker.get("value", ""))
        if _BOARD_ID.fullmatch(value):
            identities.add(value)
    return identities


@dataclass(frozen=True, slots=True)
class FmkAdapter:
    target: CommunityTarget

    site_name: ClassVar[str] = "FMKorea"
    policy: ClassVar[RequestPolicy] = RequestPolicy(
        site=Site.FMKOREA,
        user_agent=_MOBILE_USER_AGENT,
        allowed_origins=frozenset({("https", "m.fmkorea.com", 443), ("https", "www.fmkorea.com", 443)}),
        rate_limit_statuses=frozenset({429, 430}),
    )

    def board_url(self, page: int) -> str:
        if page == 1:
            return self.target.board_url
        return (
            f"{_BASE_URL}/index.php"
            f"?mid={self.target.board_id}&page={page}"
        )

    def post_url(self, post: PostSummary, cpage: int) -> str:
        if cpage == 1:
            return post.url
        return (
            f"{_BASE_URL}/index.php"
            f"?mid={self.target.board_id}"
            f"&document_srl={post.post_id}&cpage={cpage}"
        )

    def direct_post(self) -> PostSummary | None:
        if self.target.article_id is None or self.target.article_url is None:
            return None
        return PostSummary(
            post_id=self.target.article_id,
            title=f"글 {self.target.article_id}",
            category="",
            author="",
            created_at="",
            views="",
            votes=0,
            comment_count=0,
            url=self.target.article_url,
            is_notice=False,
        )

    def parse_board(self, html: str, page: int) -> PageResult[PostSummary]:
        try:
            self._validate_board_identity(html)
            return parse_board(html, page=page)
        except ParseError as error:
            raise self._site_parse_error(error) from error

    def parse_post(
        self, html: str, post: PostSummary, cpage: int
    ) -> tuple[PostDetail, PageResult[Comment]]:
        try:
            self._validate_board_identity(html)
            detail, comments = parse_post(html, post.url, cpage=cpage)
            if detail.summary.post_id != post.post_id:
                raise ParseError("post id mismatch")
            return detail, comments
        except ParseError as error:
            raise self._site_parse_error(error) from error

    def _validate_board_identity(self, html: str) -> None:
        identities = _returned_board_identities(html)
        if not identities:
            raise ParseError("returned page has no trustworthy board identity")
        if identities != {self.target.board_id}:
            returned = ", ".join(repr(value) for value in sorted(identities))
            raise ParseError(
                f"returned board {returned} does not match "
                f"'{self.target.board_id}'"
            )

    @staticmethod
    def _site_parse_error(error: ParseError) -> ParseError:
        message = str(error)
        if message.startswith("FMKorea: "):
            return error
        return ParseError(f"FMKorea: {message}")
