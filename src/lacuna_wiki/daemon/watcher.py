from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import duckdb
from watchdog.events import FileSystemEventHandler

import lacuna_wiki.daemon.sync as _sync_mod
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
    n_workers: int = 1,
    embed_concurrency: int = 1,
) -> None:
    """Sync all existing wiki/*.md files at daemon startup.

    When n_workers > 1, pages are processed in parallel using a temporary
    ConnectionPool. Each worker gets its own DB connection and writes to
    disjoint page rows — no conflicts. FTS index is rebuilt once at the end.
    The embed semaphore caps simultaneous HTTP requests to the embedding server.
    """
    wiki_dir = vault_root / "wiki"
    md_files = [
        md_file.relative_to(vault_root)
        for md_file in sorted(wiki_dir.rglob("*.md"))
        if ".sessions" not in md_file.relative_to(vault_root).parts
    ]
    if not md_files:
        return

    embed_sem = threading.Semaphore(embed_concurrency)

    def throttled_embed(texts):
        with embed_sem:
            return embed_fn(texts)

    if n_workers <= 1:
        for rel in md_files:
            sync_page(conn, vault_root, rel, throttled_embed, rebuild_fts=False)
        _sync_mod._rebuild_fts(conn)
        return

    from lacuna_wiki.daemon.connections import ConnectionPool
    from lacuna_wiki.vault import db_path as get_db_path

    db = get_db_path(vault_root)
    worker_pool = ConnectionPool(db, size=n_workers)
    worker_pool.open()

    def sync_one(rel_path):
        wconn = worker_pool.acquire()
        try:
            sync_page(wconn, vault_root, rel_path, throttled_embed, rebuild_fts=False)
        finally:
            worker_pool.release(wconn)

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = [executor.submit(sync_one, rel) for rel in md_files]
            for fut in as_completed(futures):
                fut.result()
    finally:
        worker_pool.close()

    _sync_mod._rebuild_fts(conn)
