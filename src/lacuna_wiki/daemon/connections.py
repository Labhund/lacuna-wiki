"""Thread-safe DuckDB connection pool for daemon worker and reader threads."""
from __future__ import annotations

import threading
from pathlib import Path

import duckdb

from lacuna_wiki.db.connection import get_connection


class ConnectionPool:
    """Thread-safe pool of DuckDB connections.

    All connections are opened in read-write mode — DuckDB 1.5.x does not
    allow mixing RW and read-only connections within the same process.
    Reader pools use these connections for SELECT-only queries; worker pools
    use them for full sync_page transactions on disjoint page rows.
    """

    def __init__(self, db_path: Path, size: int) -> None:
        self._db_path = db_path
        self._size = size
        self._available: list[duckdb.DuckDBPyConnection] = []
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(0)

    def open(self) -> None:
        """Open all pool connections. Call once at startup."""
        for _ in range(self._size):
            conn = get_connection(self._db_path)
            with self._lock:
                self._available.append(conn)
            self._sem.release()

    def acquire(self, timeout: float | None = None) -> duckdb.DuckDBPyConnection:
        """Acquire a connection. Blocks until one is available or timeout expires.

        Raises TimeoutError if timeout seconds pass with no available connection.
        """
        if not self._sem.acquire(timeout=timeout):
            raise TimeoutError("No pool connection available — daemon may be initializing")
        with self._lock:
            return self._available.pop()

    def release(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Return a connection to the pool."""
        with self._lock:
            self._available.append(conn)
        self._sem.release()

    def close(self) -> None:
        """Close all connections. Only call when no connections are acquired."""
        with self._lock:
            for conn in self._available:
                try:
                    conn.close()
                except Exception:
                    pass
            self._available.clear()
        for _ in range(self._size):
            self._sem.acquire(blocking=False)

    def reopen(self) -> None:
        """Reopen connections after close (e.g. after SIGUSR1 pause/resume)."""
        self.open()
