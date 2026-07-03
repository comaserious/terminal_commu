import sqlite3

import pytest

from fmk_reader.cache import CacheHit, JsonCache


def test_get_respects_ttl_and_can_return_stale_values(tmp_path) -> None:
    now = [100.0]
    cache = JsonCache(tmp_path / "cache.db", clock=lambda: now[0])
    cache.put("board:1", {"page": 1, "posts": []})

    assert cache.get("board:1", ttl=60) == CacheHit(
        value={"page": 1, "posts": []},
        fetched_at=100.0,
        is_stale=False,
    )

    now[0] = 161.0
    assert cache.get("board:1", ttl=60) is None
    assert cache.get("board:1", ttl=60, allow_stale=True) == CacheHit(
        value={"page": 1, "posts": []},
        fetched_at=100.0,
        is_stale=True,
    )
    cache.close()


def test_get_removes_corrupt_json_rows(tmp_path) -> None:
    path = tmp_path / "cache.db"
    cache = JsonCache(path, clock=lambda: 100.0)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
            ("board:1", 1.0, "{"),
        )

    assert cache.get("board:1", ttl=60, allow_stale=True) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
        ).fetchone() is None
    cache.close()


def test_get_removes_valid_json_that_is_not_an_object(tmp_path) -> None:
    path = tmp_path / "cache.db"
    cache = JsonCache(path, clock=lambda: 100.0)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
            ("board:1", 1.0, "[]"),
        )

    assert cache.get("board:1", ttl=60, allow_stale=True) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
        ).fetchone() is None
    cache.close()


def test_put_upserts_value_and_timestamp(tmp_path) -> None:
    now = [100.0]
    cache = JsonCache(tmp_path / "nested" / "cache.db", clock=lambda: now[0])
    cache.put("board:1", {"page": 1})
    now[0] = 125.0

    cache.put("board:1", {"page": 2})

    assert cache.get("board:1", ttl=60) == CacheHit(
        value={"page": 2}, fetched_at=125.0, is_stale=False
    )
    cache.close()


def test_close_closes_connection(tmp_path) -> None:
    cache = JsonCache(tmp_path / "cache.db")
    connection = cache._connection

    cache.close()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
