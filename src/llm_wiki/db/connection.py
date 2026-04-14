"""DuckDB connection factory."""
from __future__ import annotations

import duckdb
from pathlib import Path


def get_connection(db_path: Path, readonly: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection to the vault database."""
    conn = duckdb.connect(str(db_path), read_only=readonly)
    _load_extensions(conn)
    return conn


def _load_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """Load required DuckDB extensions into this connection."""
    try:
        conn.execute("LOAD fts")
    except Exception:
        pass  # FTS not available — search degrades gracefully
