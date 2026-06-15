from __future__ import annotations

import os
import threading
import time
from pathlib import Path

_STATE_DIR = Path.home() / ".lacuna"
_PID_FILE = _STATE_DIR / "daemon.pid"
_LOG_FILE = _STATE_DIR / "daemon.log"


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


def _run_watchdog_loop(
    conn,
    vault_root: Path,
    embed_fn,
    reader_pool=None,
    n_workers: int = 1,
    embed_concurrency: int = 1,
    submit_sweep=None,
) -> None:
    """Watchdog loop — runs on a background thread inside the daemon process.

    Watches wiki/ and raw/ for changes and syncs them to the DB.
    """
    from lacuna_wiki.daemon.watcher import WikiEventHandler, RawSourceHandler, initial_sync
    from lacuna_wiki.vault import db_path

    # Close reader pool during initial_sync: FTS catalog rebuild needs exclusive
    # DuckDB access and will deadlock against idle reader connections.
    if reader_pool is not None:
        reader_pool.close()
    initial_sync(conn, vault_root, embed_fn, n_workers=n_workers, embed_concurrency=embed_concurrency)
    if reader_pool is not None:
        reader_pool.reopen()
    if submit_sweep is not None:
        submit_sweep()

    from watchdog.observers import Observer
    wiki_handler = WikiEventHandler(conn, vault_root, embed_fn)
    raw_handler = RawSourceHandler(conn, vault_root, embed_fn)
    observer = Observer()
    observer.schedule(wiki_handler, str(vault_root / "wiki"), recursive=True)
    observer.schedule(raw_handler, str(vault_root / "raw"), recursive=True)
    observer.start()

    try:
        while True:
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

    write_pid(os.getpid())

    config = load_config(vault_root)
    embed_fn = partial(embed_texts, url=config["embed_url"], model=config["embed_model"])
    mcp_port = int(config["mcp_port"])
    n_workers = int(config["sync_workers"])
    embed_concurrency = int(config["embed_concurrency"])
    reader_pool_size = int(config["reader_pool_size"])

    db = db_path(vault_root)

    # Write connection: owned by the watchdog thread.
    # Auto-recover from corrupt WAL left by a mid-FTS-rebuild kill.
    import logging as _logging
    _log = _logging.getLogger(__name__)
    wal = Path(str(db) + ".wal")
    try:
        write_conn = get_connection(db)
    except Exception as _exc:
        if "Failure while replaying WAL" in str(_exc) and wal.exists():
            _log.warning("Corrupt WAL detected — deleting and retrying: %s", wal)
            wal.unlink()
            write_conn = get_connection(db)
        else:
            raise

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
        db_path=db,
        vault_root=vault_root,
        embed_fn=embed_fn,
    )

    watchdog_thread = threading.Thread(
        target=_run_watchdog_loop,
        args=(write_conn, vault_root, embed_fn),
        kwargs={
            "reader_pool": reader_pool,
            "n_workers": n_workers,
            "embed_concurrency": embed_concurrency,
            "submit_sweep": _submit_sweep,
        },
        daemon=True,
        name="lacuna-watchdog",
    )
    watchdog_thread.start()

    # MCP server acquires/releases from reader pool per-call, so pool
    # close/reopen during initial_sync never strands it.
    make_wiki_tool(reader_pool, embed_fn, vault_root=vault_root)

    try:
        mcp_app.settings.port = mcp_port
        mcp_app.run(transport="streamable-http")
    finally:
        api_server.shutdown()
        _PID_FILE.unlink(missing_ok=True)
