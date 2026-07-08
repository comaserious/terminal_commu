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
        self._clock = clock
        try:
            self.connection = self._open(path)
        except sqlite3.DatabaseError as error:
            if not self._is_corrupt(error):
                raise
            self._quarantine(path)
            self.connection = self._open(path)

    @staticmethod
    def _is_corrupt(error: sqlite3.DatabaseError) -> bool:
        code = getattr(error, "sqlite_errorcode", None)
        return code is not None and code & 0xFF in {
            sqlite3.SQLITE_CORRUPT,
            sqlite3.SQLITE_NOTADB,
        }

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    fetched_at REAL NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.commit()
        except sqlite3.DatabaseError:
            if connection is not None:
                connection.close()
            raise
        return connection

    @staticmethod
    def _quarantine(path: Path) -> None:
        if not (path.is_file() or path.is_symlink()):
            return

        index = 0
        while True:
            suffix = ".corrupt" if index == 0 else f".corrupt.{index}"
            destination = path.with_name(f"{path.name}{suffix}")
            destinations = (
                destination,
                destination.with_name(f"{destination.name}-wal"),
                destination.with_name(f"{destination.name}-shm"),
            )
            if not any(candidate.exists() for candidate in destinations):
                break
            index += 1

        sources = (
            path,
            path.with_name(f"{path.name}-wal"),
            path.with_name(f"{path.name}-shm"),
        )
        for source, target in zip(sources, destinations, strict=True):
            if source.is_file() or source.is_symlink():
                source.replace(target)

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
