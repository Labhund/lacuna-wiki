"""Status HTTP API served by the daemon on mcp_port+1.

Endpoints:
  GET  /status              — vault table counts + sweep metrics (JSON)
  GET  /claims              — claim list (?mode=virgin|stale|page&page=SLUG)
  GET  /sweep/status        — current sweep job progress (JSON)
  POST /sweep               — submit a sweep pre-computation job
  POST /sync                — trigger initial_sync of wiki/ to DB
  POST /adversary-commit    — batch-write adversary verdicts
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from lacuna_wiki.daemon.connections import ConnectionPool


def _collect_status(conn) -> dict:
    from lacuna_wiki.cli.status import _TABLES, _sweep_counts
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}
    sweep = _sweep_counts(conn)
    return {"tables": counts, "sweep": sweep}


def _collect_claims(conn, mode: str, page_slug: str | None) -> dict:
    from lacuna_wiki.cli.claims import list_claims
    results = list_claims(conn, mode, page_slug=page_slug)
    serialisable = []
    for r in results:
        row = dict(r)
        if row.get("published_date") is not None:
            row["published_date"] = str(row["published_date"])
        serialisable.append(row)
    return {"claims": serialisable}


def _make_handler(
    reader_pool: ConnectionPool,
    sweep_state: dict,
    submit_sweep: Callable,
    db_path: Path,
    vault_root: Path,
    embed_fn: Callable,
    memory_limit: str | None = None,
):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                self._json(self._with_conn(_collect_status))
            elif parsed.path == "/claims":
                qs = parse_qs(parsed.query)
                mode = qs.get("mode", ["virgin"])[0]
                page = qs.get("page", [None])[0]
                self._json(self._with_conn(lambda c: _collect_claims(c, mode, page)))
            elif parsed.path == "/sweep/status":
                self._json(dict(sweep_state))
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/sweep":
                body = self._read_body()
                submit_sweep(batch=body.get("batch"), force=body.get("force", False))
                self._json({"status": "accepted"})

            elif self.path == "/sync":
                self._handle_sync()

            elif self.path == "/adversary-commit":
                body = self._read_body()
                self._handle_adversary_commit(body)

            else:
                self.send_response(404)
                self.end_headers()

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length:
                return json.loads(self.rfile.read(length))
            return {}

        def _handle_sync(self) -> None:
            """Run initial_sync on a short-lived write connection."""
            from lacuna_wiki.db.connection import get_connection
            from lacuna_wiki.db.schema import init_db
            from lacuna_wiki.daemon.watcher import initial_sync

            conn = get_connection(db_path, memory_limit=memory_limit)
            try:
                init_db(conn)
                initial_sync(conn, vault_root, embed_fn)
            except Exception as exc:
                self._json({"status": "error", "error": str(exc)}, code=500)
                return
            finally:
                conn.close()
            self._json({"status": "ok"})

        def _handle_adversary_commit(self, body: dict) -> None:
            """Write adversary verdicts on a short-lived write connection."""
            from lacuna_wiki.db.connection import get_connection
            from lacuna_wiki.cli.adversary_commit import (
                write_verdicts, Verdict, Supersession,
            )

            verdicts_raw = body.get("verdicts", [])
            supersessions_raw = body.get("supersessions", [])

            verdicts = [Verdict(**v) for v in verdicts_raw]
            supersessions = [Supersession(**s) for s in supersessions_raw]

            conn = get_connection(db_path, memory_limit=memory_limit)
            try:
                write_verdicts(conn, verdicts, supersessions)
            except Exception as exc:
                self._json({"status": "error", "error": str(exc)}, code=500)
                return
            finally:
                conn.close()
            self._json({
                "status": "ok",
                "verdicts": len(verdicts),
                "supersessions": len(supersessions),
            })

        def _with_conn(self, fn):
            conn = reader_pool.acquire()
            try:
                return fn(conn)
            finally:
                reader_pool.release(conn)

        def _json(self, data: dict, code: int = 200):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return _Handler


def start_api_server(
    port: int,
    reader_pool: ConnectionPool,
    sweep_state: dict,
    submit_sweep: Callable,
    db_path: Path,
    vault_root: Path,
    embed_fn: Callable,
    memory_limit: str | None = None,
) -> HTTPServer:
    """Start the status HTTP API on a daemon thread. Returns the server."""
    handler = _make_handler(
        reader_pool, sweep_state, submit_sweep,
        db_path, vault_root, embed_fn, memory_limit,
    )
    try:
        server = HTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise RuntimeError(
            f"Address already in use on port {port} — "
            f"change mcp_port in .lacuna.toml"
        ) from exc
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="lacuna-api"
    )
    thread.start()
    return server
