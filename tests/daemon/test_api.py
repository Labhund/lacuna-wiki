"""Tests for the daemon status HTTP API."""
from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import duckdb
import pytest

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.connections import ConnectionPool
from lacuna_wiki.daemon.api import start_api_server


@pytest.fixture
def api_server(tmp_path):
    db = tmp_path / "vault.db"
    conn = duckdb.connect(str(db))
    init_db(conn)
    conn.close()

    pool = ConnectionPool(db, size=2)
    pool.open()

    sweep_state = {"done": 0, "total": 0, "running": False}
    server = start_api_server(
        port=17655, reader_pool=pool, sweep_state=sweep_state,
        submit_sweep=lambda: None,
    )
    time.sleep(0.05)
    yield server, sweep_state
    server.shutdown()
    pool.close()


def _get(path: str) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", 17655, timeout=3)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def _post(path: str) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", 17655, timeout=3)
    conn.request("POST", path)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_get_status_returns_200(api_server):
    status, data = _get("/status")
    assert status == 200
    assert "tables" in data
    assert "sweep" in data


def test_get_status_table_counts(api_server):
    _, data = _get("/status")
    assert set(data["tables"].keys()) >= {"pages", "sections", "sources", "claims"}
    assert all(isinstance(v, int) for v in data["tables"].values())


def test_get_status_sweep_keys(api_server):
    _, data = _get("/status")
    assert "sweep backlog" in data["sweep"] or "sweep_backlog" in data["sweep"]
    assert "ghost pages" in data["sweep"] or "ghost_pages" in data["sweep"]


def test_get_claims_returns_200(api_server):
    status, data = _get("/claims?mode=virgin")
    assert status == 200
    assert "claims" in data
    assert isinstance(data["claims"], list)


def test_get_sweep_status(api_server):
    server, sweep_state = api_server
    sweep_state["done"] = 5
    sweep_state["total"] = 10
    _, data = _get("/sweep/status")
    assert data["done"] == 5
    assert data["total"] == 10


def test_post_sweep_returns_200(api_server):
    status, _ = _post("/sweep")
    assert status == 200


def test_unknown_path_returns_404(api_server):
    conn = HTTPConnection("127.0.0.1", 17655, timeout=3)
    conn.request("GET", "/nonexistent")
    resp = conn.getresponse()
    assert resp.status == 404


def test_port_conflict_raises_runtimeerror(tmp_path):
    """Starting a server on an already-bound port raises RuntimeError."""
    import socket
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 17656))
    blocker.listen(1)

    db = tmp_path / "vault2.db"
    conn = duckdb.connect(str(db))
    init_db(conn)
    conn.close()
    pool = ConnectionPool(db, size=1)
    pool.open()

    try:
        with pytest.raises(RuntimeError, match="Address already in use"):
            start_api_server(
                port=17656, reader_pool=pool, sweep_state={},
                submit_sweep=lambda: None,
            )
    finally:
        blocker.close()
        pool.close()
