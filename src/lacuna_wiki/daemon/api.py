"""Status HTTP API served by the daemon on mcp_port+1.

Endpoints:
  GET  /status        — vault table counts + sweep metrics (JSON)
  GET  /claims        — claim list (?mode=virgin|stale|page&page=SLUG)
  GET  /sweep/status  — current sweep job progress (JSON)
  POST /sweep         — submit a sweep pre-computation job
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                submit_sweep(batch=body.get("batch"), force=body.get("force", False))
                self._json({"status": "accepted"})
            else:
                self.send_response(404)
                self.end_headers()

        def _with_conn(self, fn):
            conn = reader_pool.acquire()
            try:
                return fn(conn)
            finally:
                reader_pool.release(conn)

        def _json(self, data: dict):
            body = json.dumps(data).encode()
            self.send_response(200)
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
) -> HTTPServer:
    """Start the status HTTP API on a daemon thread. Returns the server."""
    handler = _make_handler(reader_pool, sweep_state, submit_sweep)
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
