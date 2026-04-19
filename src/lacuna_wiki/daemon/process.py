from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

_STATE_DIR = Path.home() / ".lacuna"
_PID_FILE = _STATE_DIR / "daemon.pid"
_LOG_FILE = _STATE_DIR / "daemon.log"

_pause_event = threading.Event()


def _handle_sigusr1(signum, frame) -> None:
    """Signal handler: request a daemon pause."""
    _pause_event.set()


def write_pid(pid: int) -> None:
    """Write daemon PID to file."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def read_pid() -> int | None:
    """Read daemon PID from file. Returns None if missing or corrupt."""
    if not _PID_FILE.exists():
        return None
    try:
        return int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(pid: int) -> bool:
    """Return True if a process with this PID currently exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it


def _close_all_for_pause(write_conn, reader_pool) -> None:
    """Close all DuckDB connections so the file lock is fully released.

    DuckDB's lock is process-level: any open connection holds it.
    Closing only write_conn is insufficient — reader pool connections
    must also be closed before the CLI can open its own write connection.
    """
    reader_pool.close()
    try:
        write_conn.close()
    except Exception:
        pass


def _run_watchdog_loop(
    conn,
    vault_root: Path,
    embed_fn,
    pause_ack: Path,
    reader_pool=None,
    n_workers: int = 1,
    embed_concurrency: int = 1,
) -> None:
    """Watchdog loop — runs on a background thread inside the daemon process.

    Watches wiki/ for changes and syncs them to the DB. Handles SIGUSR1-driven
    pause/resume for the adversary-commit workflow (pause_ack path is used as
    the handshake file).
    """
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.daemon.watcher import WikiEventHandler, initial_sync
    from lacuna_wiki.vault import db_path

    # Close reader pool during initial_sync: FTS catalog rebuild needs exclusive
    # DuckDB access and will deadlock against idle reader connections.
    if reader_pool is not None:
        reader_pool.close()
    initial_sync(conn, vault_root, embed_fn, n_workers=n_workers, embed_concurrency=embed_concurrency)
    if reader_pool is not None:
        reader_pool.reopen()

    from watchdog.observers import Observer
    handler = WikiEventHandler(conn, vault_root, embed_fn)
    observer = Observer()
    observer.schedule(handler, str(vault_root / "wiki"), recursive=True)
    observer.start()

    try:
        while True:
            if _pause_event.is_set():
                with handler._lock:
                    observer.stop()
                observer.join()

                # Close ALL connections — DuckDB lock is process-level
                _close_all_for_pause(conn, reader_pool)

                pause_ack.write_text("paused")
                while pause_ack.exists():
                    time.sleep(0.05)

                # Reopen everything
                conn = get_connection(db_path(vault_root))
                if reader_pool is not None:
                    reader_pool.reopen()
                handler._conn = conn
                observer = Observer()
                observer.schedule(handler, str(vault_root / "wiki"), recursive=True)
                observer.start()
                _pause_event.clear()

            time.sleep(1)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        observer.stop()
        observer.join()
        try:
            conn.close()
        except Exception:
            pass


def run_daemon(vault_root: Path) -> None:
    """Daemon entry point — runs the watchdog and MCP server in one process."""
    from functools import partial

    from lacuna_wiki.config import load_config
    from lacuna_wiki.daemon.api import start_api_server
    from lacuna_wiki.daemon.connections import ConnectionPool
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.mcp.server import make_wiki_tool, mcp_app
    from lacuna_wiki.sources.embedder import embed_texts
    from lacuna_wiki.vault import db_path, state_dir_for

    signal.signal(signal.SIGUSR1, _handle_sigusr1)
    write_pid(os.getpid())

    config = load_config(vault_root)
    embed_fn = partial(embed_texts, url=config["embed_url"], model=config["embed_model"])
    mcp_port = int(config["mcp_port"])
    n_workers = int(config["sync_workers"])
    embed_concurrency = int(config["embed_concurrency"])
    reader_pool_size = int(config["reader_pool_size"])

    db = db_path(vault_root)
    pause_ack = state_dir_for(vault_root) / "daemon.paused"

    # Write connection: owned by the watchdog thread
    write_conn = get_connection(db)
    from lacuna_wiki.db.schema import init_db
    init_db(write_conn)

    # Reader pool shared by MCP server, status HTTP API, and sweep queries
    reader_pool = ConnectionPool(db, size=reader_pool_size)
    reader_pool.open()

    # Status HTTP API on mcp_port+1
    sweep_state: dict = {"done": 0, "total": 0, "running": False}

    def _run_sweep_job(batch: int | None = None, force: bool = False) -> None:
        from lacuna_wiki.db.connection import get_connection
        from lacuna_wiki.mcp.audit import precompute_unlinked_candidates
        import logging
        log = logging.getLogger(__name__)
        conn = get_connection(db)
        try:
            if force:
                rows = conn.execute("SELECT id FROM pages").fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM pages WHERE last_swept IS NULL OR last_modified > last_swept"
                ).fetchall()
            if batch is not None:
                rows = rows[:batch]
            page_ids = [r[0] for r in rows]
            sweep_state.update({"done": 0, "total": len(page_ids), "running": True})
            log.info("Sweep job started: %d pages to process.", len(page_ids))
            for i, pid in enumerate(page_ids):
                precompute_unlinked_candidates(conn, vault_root, page_ids=[pid])
                sweep_state["done"] = i + 1
            log.info("Sweep job complete: %d pages processed.", len(page_ids))
        except Exception as exc:
            log.error("Sweep job error: %s", exc)
        finally:
            sweep_state["running"] = False
            conn.close()

    def _submit_sweep(batch: int | None = None, force: bool = False) -> None:
        if sweep_state.get("running"):
            return
        threading.Thread(
            target=_run_sweep_job, kwargs={"batch": batch, "force": force},
            daemon=True, name="lacuna-sweep",
        ).start()

    api_server = start_api_server(
        port=mcp_port + 1,
        reader_pool=reader_pool,
        sweep_state=sweep_state,
        submit_sweep=_submit_sweep,
    )

    watchdog_thread = threading.Thread(
        target=_run_watchdog_loop,
        args=(write_conn, vault_root, embed_fn, pause_ack),
        kwargs={
            "reader_pool": reader_pool,
            "n_workers": n_workers,
            "embed_concurrency": embed_concurrency,
        },
        daemon=True,
        name="lacuna-watchdog",
    )
    watchdog_thread.start()

    # MCP server uses a reader pool connection (SELECT-only)
    read_conn = reader_pool.acquire()
    make_wiki_tool(read_conn, embed_fn)

    try:
        mcp_app.run(transport="sse")
    finally:
        api_server.shutdown()
        _PID_FILE.unlink(missing_ok=True)
        pause_ack.unlink(missing_ok=True)
