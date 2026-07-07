from pathlib import Path
import tomllib

import pytest

import fmk_reader.app as app_module
from fmk_reader.app import main, parse_cli
from fmk_reader.errors import TargetError
from fmk_reader.targets import Site


def test_parse_cli_without_url_opens_launcher() -> None:
    assert parse_cli([]) is None


def test_parse_cli_routes_direct_url() -> None:
    target = parse_cli(["https://arca.live/b/rogersfu"])

    assert target is not None
    assert target.site is Site.ARCA


def test_project_exposes_primary_and_compatibility_commands() -> None:
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]

    assert scripts == {
        "commu": "fmk_reader.app:main",
        "fmk": "fmk_reader.app:main",
    }


def test_main_direct_url_bypasses_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    created = []

    class FakeApp:
        def __init__(self, *, target) -> None:
            created.append(target)

        def run(self) -> None:
            created.append("run")

    monkeypatch.setattr(app_module, "CommunityReaderApp", FakeApp)

    main(["https://arca.live/b/rogersfu/176096992"])

    assert created[0].article_id == "176096992"
    assert created[1] == "run"


def test_unsupported_direct_url_creates_no_app_or_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = []
    monkeypatch.setattr(
        app_module,
        "CommunityReaderApp",
        lambda **kwargs: created.append(kwargs),
    )

    with pytest.raises(TargetError):
        main(["https://example.com/community"])

    assert created == []
