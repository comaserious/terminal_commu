import sqlite3
from contextlib import closing

import pytest

import fmk_reader.cache as cache_module
from fmk_reader.cache import CacheHit, JsonCache


def test_get_respects_ttl_and_can_return_stale_values(tmp_path) -> None:
    now = [100.0]
    with closing(JsonCache(tmp_path / "cache.db", clock=lambda: now[0])) as cache:
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


def test_get_removes_corrupt_json_rows(tmp_path) -> None:
    path = tmp_path / "cache.db"
    with closing(JsonCache(path, clock=lambda: 100.0)) as cache:
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
                    ("board:1", 1.0, "{"),
                )

        assert cache.get("board:1", ttl=60, allow_stale=True) is None
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
            ).fetchone() is None


def test_get_removes_valid_json_that_is_not_an_object(tmp_path) -> None:
    path = tmp_path / "cache.db"
    with closing(JsonCache(path, clock=lambda: 100.0)) as cache:
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
                    ("board:1", 1.0, "[]"),
                )

        assert cache.get("board:1", ttl=60, allow_stale=True) is None
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
            ).fetchone() is None


def test_put_upserts_value_and_timestamp(tmp_path) -> None:
    now = [100.0]
    with closing(
        JsonCache(tmp_path / "nested" / "cache.db", clock=lambda: now[0])
    ) as cache:
        cache.put("board:1", {"page": 1})
        now[0] = 125.0

        cache.put("board:1", {"page": 2})

        assert cache.get("board:1", ttl=60) == CacheHit(
            value={"page": 2}, fetched_at=125.0, is_stale=False
        )


def test_close_closes_connection(tmp_path) -> None:
    with closing(JsonCache(tmp_path / "cache.db")) as cache:
        connection = cache.connection

        cache.close()

        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_put_rolls_back_when_a_trigger_aborts_the_write(tmp_path) -> None:
    with closing(JsonCache(tmp_path / "cache.db")) as cache:
        connection = cache.connection
        connection.execute(
            """
            CREATE TRIGGER reject_cache_insert
            BEFORE INSERT ON cache_entries
            BEGIN
                SELECT RAISE(ABORT, 'write rejected');
            END
            """
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="write rejected"):
            cache.put("board:1", {"page": 1})

        assert connection.in_transaction is False
        connection.execute("DROP TRIGGER reject_cache_insert")
        connection.commit()
        assert connection.execute(
            "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
        ).fetchone() is None


def test_get_removes_non_text_payloads(tmp_path) -> None:
    path = tmp_path / "cache.db"
    with closing(JsonCache(path, clock=lambda: 100.0)) as cache:
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
                    ("board:1", 1.0, sqlite3.Binary(b"\xff")),
                )

        assert cache.get("board:1", ttl=60, allow_stale=True) is None
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                "SELECT key FROM cache_entries WHERE key = ?", ("board:1",)
            ).fetchone() is None


def test_get_treats_a_backward_clock_as_stale(tmp_path) -> None:
    now = [100.0]
    with closing(JsonCache(tmp_path / "cache.db", clock=lambda: now[0])) as cache:
        cache.put("board:1", {"page": 1})
        now[0] = 99.0

        assert cache.get("board:1", ttl=60) is None
        assert cache.get("board:1", ttl=60, allow_stale=True) == CacheHit(
            value={"page": 1}, fetched_at=100.0, is_stale=True
        )


def test_get_treats_exact_ttl_boundary_as_fresh(tmp_path) -> None:
    now = [100.0]
    with closing(JsonCache(tmp_path / "cache.db", clock=lambda: now[0])) as cache:
        cache.put("board:1", {"page": 1})
        now[0] = 160.0

        assert cache.get("board:1", ttl=60) == CacheHit(
            value={"page": 1}, fetched_at=100.0, is_stale=False
        )


def test_constructor_quarantines_corrupt_database_and_recreates_cache(
    tmp_path,
) -> None:
    path = tmp_path / "cache.db"
    corrupt_bytes = b"not a sqlite database"
    path.write_bytes(corrupt_bytes)

    with closing(JsonCache(path, clock=lambda: 100.0)) as cache:
        cache.put("board:1", {"page": 1})

        assert cache.get("board:1", ttl=60) == CacheHit(
            value={"page": 1}, fetched_at=100.0, is_stale=False
        )

    assert (tmp_path / "cache.db.corrupt").read_bytes() == corrupt_bytes


def test_constructor_preserves_existing_quarantine_and_moves_sidecars(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cache.db"
    path.write_bytes(b"broken database")
    (tmp_path / "cache.db-wal").write_bytes(b"broken wal")
    (tmp_path / "cache.db-shm").write_bytes(b"broken shm")
    (tmp_path / "cache.db.corrupt").write_bytes(b"older quarantine")
    unrelated = tmp_path / "cache.db-wal.backup"
    unrelated.write_bytes(b"unrelated")

    class BrokenConnection:
        closed = False

        def execute(self, statement: str) -> None:
            error = sqlite3.DatabaseError("schema initialization failed")
            error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
            raise error

        def close(self) -> None:
            self.closed = True

    broken_connection = BrokenConnection()
    connect = sqlite3.connect
    connections = iter((broken_connection, None))

    def fail_once(database):
        connection = next(connections)
        return connect(database) if connection is None else connection

    monkeypatch.setattr(cache_module.sqlite3, "connect", fail_once)

    with closing(JsonCache(path)):
        pass

    assert broken_connection.closed is True
    assert (tmp_path / "cache.db.corrupt").read_bytes() == b"older quarantine"
    assert (tmp_path / "cache.db.corrupt.1").read_bytes() == b"broken database"
    assert (tmp_path / "cache.db.corrupt.1-wal").read_bytes() == b"broken wal"
    assert (tmp_path / "cache.db.corrupt.1-shm").read_bytes() == b"broken shm"
    assert unrelated.read_bytes() == b"unrelated"


def test_constructor_does_not_quarantine_non_corruption_database_failure(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cache.db"
    original = b"database in use"
    path.write_bytes(original)
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY

    def fail_to_connect(database):
        raise error

    monkeypatch.setattr(cache_module.sqlite3, "connect", fail_to_connect)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        JsonCache(path)

    assert path.read_bytes() == original
    assert not (tmp_path / "cache.db.corrupt").exists()
