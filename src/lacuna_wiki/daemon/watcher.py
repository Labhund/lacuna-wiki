from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import duckdb
from watchdog.events import FileSystemEventHandler

from lacuna_wiki.daemon.sync import sync_page

EmbedFn = Callable[[list[str]], list[list[float]]]


class WikiEventHandler(FileSystemEventHandler):
    """Watchdog event handler that syncs wiki .md files to DuckDB on change."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        vault_root: Path,
        embed_fn: EmbedFn,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._vault_root = vault_root
        self._embed_fn = embed_fn
        self._lock = threading.Lock()

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".md":
            self._sync(path)

    def on_created(self, event) -> None:
        self.on_modified(event)

    def on_deleted(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".md":
            self._sync(path)

    def on_moved(self, event) -> None:
        """Handle file renames / moves within wiki/."""
        if event.is_directory:
            return
        old = Path(event.src_path)
        new = Path(event.dest_path)
        if old.suffix == ".md":
            self._sync(old)  # old path no longer exists — sync_page handles deletion
        if new.suffix == ".md":
            self._sync(new)

    def _sync(self, abs_path: Path) -> None:
        try:
            rel = abs_path.relative_to(self._vault_root)
        except ValueError:
            return
        # Skip wiki/.sessions/ — ingest session manifests, not wiki pages
        if ".sessions" in rel.parts:
            return
        with self._lock:
            sync_page(self._conn, self._vault_root, rel, self._embed_fn)


def initial_sync(
    conn: duckdb.DuckDBPyConnection,
    vault_root: Path,
    embed_fn: EmbedFn,
) -> None:
    """Sync all existing wiki/*.md files at daemon startup."""
    wiki_dir = vault_root / "wiki"
    for md_file in sorted(wiki_dir.rglob("*.md")):
        rel = md_file.relative_to(vault_root)
        if ".sessions" in rel.parts:
            continue
        sync_page(conn, vault_root, rel, embed_fn)
