"""DuckDB connection factory."""
from __future__ import annotations

import duckdb
from pathlib import Path


def get_connection(db_path: Path, readonly: bool = False,
                   memory_limit: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection to the vault database.

    memory_limit: DuckDB memory cap (e.g. '1GB', '512MB'). Limits the
    buffer pool size to prevent uncontrolled growth on large vaults.
    """
    conn = duckdb.connect(str(db_path), read_only=readonly)
    _load_extensions(conn)
    if memory_limit:
        conn.execute(f"SET memory_limit='{memory_limit}'")
    return conn


def _load_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """Load required DuckDB extensions into this connection."""
    try:
        conn.execute("LOAD fts")
    except Exception:
        pass  # FTS not available — search degrades gracefully
