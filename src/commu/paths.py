from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from commu.targets import Site


def data_root(
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    configured = values.get("COMMU_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    base = Path.home() if home is None else home
    return base / ".cache" / "commu"


def cache_path(
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    return data_root(home, environ) / "cache.db"


def url_history_path(
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    return data_root(home, environ) / "url-history.json"


def browser_state_path(
    site: Site,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    filename = {
        Site.FMKOREA: "fmk.json",
        Site.DCINSIDE: "dcinside.json",
        Site.ARCA: "arca.json",
    }[site]
    return data_root(home, environ) / "browser-state" / filename
