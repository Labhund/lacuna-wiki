"""DuckDB connection factory."""
from __future__ import annotations

import duckdb
from pathlib import Path


def get_connection(db_path: Path, readonly: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection to the vault database.

    readonly=True for skills scripts and status reads.
    readonly=False (default) for the daemon and CLI write commands.
    vss extension is loaded in Plan 4 when vector search is wired up.
    """
    return duckdb.connect(str(db_path), read_only=readonly)
