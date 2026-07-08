import pytest

from commu.errors import TargetError
from commu.targets import Site, route_url


@pytest.mark.parametrize(
    ("url", "site", "board_id", "article_id"),
    [
        (
            "https://www.fmkorea.com/football_world",
            Site.FMKOREA,
            "football_world",
            None,
        ),
        (
            "https://www.fmkorea.com/123456",
            Site.FMKOREA,
            "football_world",
            "123456",
        ),
        (
            "https://gall.dcinside.com/board/lists/?id=football_new9",
            Site.DCINSIDE,
            "football_new9",
            None,
        ),
        (
            "https://gall.dcinside.com/mgallery/board/view/?id=test&no=42",
            Site.DCINSIDE,
            "test",
            "42",
        ),
        (
            "https://gall.dcinside.com/mini/board/lists/?id=test",
            Site.DCINSIDE,
            "test",
            None,
        ),
        (
            "https://m.dcinside.com/board/football_new9/42",
            Site.DCINSIDE,
            "football_new9",
            "42",
        ),
        ("https://arca.live/b/rogersfu", Site.ARCA, "rogersfu", None),
        (
            "https://arca.live/b/rogersfu/176096992?p=1#comment",
            Site.ARCA,
            "rogersfu",
            "176096992",
        ),
    ],
)
def test_route_url_recognizes_supported_targets(url, site, board_id, article_id):
    target = route_url(url)
    assert (target.site, target.board_id, target.article_id) == (
        site,
        board_id,
        article_id,
    )
    assert target.board_url.startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://arca.live/b/rogersfu",
        "https://user:pass@arca.live/b/rogersfu",
        "https://example.com/board",
        "https://arca.live/u/login",
        "https://gall.dcinside.com/board/write/?id=football_new9",
        "https://gall.dcinside.com/board/lists/?id=../bad",
    ],
)
def test_route_url_rejects_unsafe_or_unsupported_urls(url):
    with pytest.raises(TargetError):
        route_url(url)


@pytest.mark.parametrize(
    ("url", "board_url", "article_url"),
    [
        (
            "https://www.fmkorea.com/123456?listStyle=webzine#comments",
            "https://www.fmkorea.com/football_world",
            "https://www.fmkorea.com/123456",
        ),
        (
            "https://gall.dcinside.com/mini/board/view/?id=test&no=42&page=3#reply",
            "https://m.dcinside.com/board/test",
            "https://m.dcinside.com/board/test/42",
        ),
        (
            "https://arca.live/b/rogersfu/176096992?p=1#comment",
            "https://arca.live/b/rogersfu",
            "https://arca.live/b/rogersfu/176096992",
        ),
    ],
)
def test_route_url_builds_fragment_free_canonical_urls(url, board_url, article_url):
    target = route_url(url)
    assert target.board_url == board_url
    assert target.article_url == article_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.fmkorea.com/football_korean",
        "https://www.fmkorea.com/football_world/write",
        "https://fmkorea.com/football_world",
        "https://gall.dcinside.com/board/lists/?id=test&id=other",
        "https://gall.dcinside.com/board/view/?id=test",
        "https://m.dcinside.com/board/test/not-an-article",
        "https://m.dcinside.com/board/test/42/extra",
        "https://arca.live/b/test/not-an-article",
        "https://arca.live/b/test/42/extra",
        "https://arca.live:444/b/test",
    ],
)
def test_route_url_rejects_urls_outside_exact_read_only_families(url):
    with pytest.raises(TargetError):
        route_url(url)


def test_target_models_are_immutable():
    target = route_url("https://arca.live/b/rogersfu")

    with pytest.raises((AttributeError, TypeError)):
        target.board_id = "other"
