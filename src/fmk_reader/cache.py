from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class CacheHit:
    value: dict[str, Any]
    fetched_at: float
    is_stale: bool


class JsonCache:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self._clock = clock
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                fetched_at REAL NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def put(self, key: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO cache_entries (key, fetched_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload = excluded.payload
                """,
                (key, self._clock(), payload),
            )

    def get(
        self, key: str, ttl: float, allow_stale: bool = False
    ) -> CacheHit | None:
        row = self.connection.execute(
            "SELECT fetched_at, payload FROM cache_entries WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None

        fetched_at, payload = row
        elapsed = self._clock() - fetched_at
        is_stale = elapsed < 0 or elapsed > ttl
        if is_stale and not allow_stale:
            return None

        if not isinstance(payload, str):
            self._delete(key)
            return None
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            self._delete(key)
            return None
        if not isinstance(value, dict):
            self._delete(key)
            return None

        return CacheHit(value=value, fetched_at=fetched_at, is_stale=is_stale)

    def close(self) -> None:
        self.connection.close()

    def _delete(self, key: str) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM cache_entries WHERE key = ?", (key,)
            )
