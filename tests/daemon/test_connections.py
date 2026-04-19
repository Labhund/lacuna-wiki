"""Tests for ConnectionPool."""
from __future__ import annotations

import threading
from pathlib import Path

import duckdb
import pytest

from lacuna_wiki.daemon.connections import ConnectionPool


@pytest.fixture
def pool(tmp_path):
    db = tmp_path / "test.db"
    conn = duckdb.connect(str(db))
    conn.close()
    p = ConnectionPool(db, size=2)
    p.open()
    yield p
    p.close()


def test_pool_acquire_and_release(pool):
    conn = pool.acquire()
    assert conn is not None
    result = conn.execute("SELECT 42").fetchone()[0]
    assert result == 42
    pool.release(conn)


def test_pool_blocks_when_exhausted(pool):
    """Pool of size 2 blocks on 3rd acquire until one is released."""
    c1 = pool.acquire()
    c2 = pool.acquire()

    got_third = threading.Event()

    def try_acquire():
        pool.acquire()
        got_third.set()

    t = threading.Thread(target=try_acquire, daemon=True)
    t.start()

    assert not got_third.wait(timeout=0.1), "should still be blocked"
    pool.release(c1)
    assert got_third.wait(timeout=1.0), "should unblock after release"
    pool.release(c2)


def test_pool_close_and_reopen(tmp_path):
    db = tmp_path / "reopen.db"
    conn = duckdb.connect(str(db))
    conn.close()

    p = ConnectionPool(db, size=2)
    p.open()
    c = p.acquire()
    p.release(c)
    p.close()

    p.reopen()
    c2 = p.acquire()
    assert c2.execute("SELECT 1").fetchone()[0] == 1
    p.release(c2)
    p.close()


def test_pool_concurrent_use(tmp_path):
    """Multiple threads each acquire, use, and release without corruption."""
    from lacuna_wiki.db.schema import init_db

    db = tmp_path / "concurrent.db"
    setup_conn = duckdb.connect(str(db))
    init_db(setup_conn)
    setup_conn.close()

    p = ConnectionPool(db, size=4)
    p.open()

    errors = []

    def worker(i):
        try:
            conn = p.acquire()
            conn.execute("SELECT COUNT(*) FROM pages").fetchone()
            p.release(conn)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Worker errors: {errors}"
    p.close()
