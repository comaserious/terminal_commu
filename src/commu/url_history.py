from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commu.targets import CommunityTarget, Site, route_url
from commu import work_disguise


@dataclass(frozen=True, slots=True)
class UrlHistoryEntry:
    url: str
    site: Site
    board_id: str
    label: str


def default_url_history_path(home: Path | None = None) -> Path:
    base = Path.home() if home is None else home
    return base / ".cache" / "commu" / "url-history.json"


class UrlHistory:
    def __init__(self, path: Path, *, limit: int = 20) -> None:
        self._path = path
        self._limit = limit

    def record(self, raw_url: str) -> CommunityTarget:
        target = route_url(raw_url)
        url = _canonical_url(target)
        items = [item for item in self._read_raw_items() if item.get("url") != url]
        items.insert(0, {"url": url})
        self._write_raw_items(items[: self._limit])
        return target

    def entries(self, site: Site | None = None) -> tuple[UrlHistoryEntry, ...]:
        entries: list[UrlHistoryEntry] = []
        seen: set[str] = set()
        for item in self._read_raw_items():
            raw_url = item.get("url")
            if not isinstance(raw_url, str) or raw_url in seen:
                continue
            try:
                target = route_url(raw_url)
            except Exception:
                continue
            if site is not None and target.site is not site:
                continue
            seen.add(raw_url)
            entries.append(
                UrlHistoryEntry(
                    url=_canonical_url(target),
                    site=target.site,
                    board_id=target.board_id,
                    label=_entry_label(target),
                )
            )
        return tuple(entries)

    def _read_raw_items(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write_raw_items(self, items: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _canonical_url(target: CommunityTarget) -> str:
    return target.article_url or target.board_url


def _entry_label(target: CommunityTarget) -> str:
    source = work_disguise.source_label(target.site, target.board_id)
    if target.article_id is None:
        return f"{source} · 목록"
    return f"{source} · 항목 {target.article_id}"
