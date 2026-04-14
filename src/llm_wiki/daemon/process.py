from __future__ import annotations

import os
import time
from pathlib import Path

_STATE_DIR = Path.home() / ".llm-wiki"
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


def run_daemon(vault_root: Path) -> None:
    """Daemon entry point. Called from the _daemon-run CLI subcommand.

    Writes PID file, performs initial sync, starts watchdog observer loop,
    and blocks until SIGTERM is received.
    """
    from watchdog.observers import Observer

    from llm_wiki.daemon.watcher import WikiEventHandler, initial_sync
    from llm_wiki.db.connection import get_connection
    from llm_wiki.sources.embedder import embed_texts
    from llm_wiki.vault import db_path

    write_pid(os.getpid())

    db = db_path(vault_root)
    conn = get_connection(db)

    initial_sync(conn, vault_root, embed_texts)

    handler = WikiEventHandler(conn, vault_root, embed_texts)
    observer = Observer()
    observer.schedule(handler, str(vault_root / "wiki"), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        observer.stop()
        observer.join()
        conn.close()
        _PID_FILE.unlink(missing_ok=True)
