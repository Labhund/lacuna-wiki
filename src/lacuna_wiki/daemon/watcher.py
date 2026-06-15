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


class RawSourceHandler(FileSystemEventHandler):
    """Watchdog event handler that registers new raw/ sources in DuckDB.

    When add-source writes .md + .pdf + .bib files into raw/, this handler
    picks them up and does chunking → embedding → DB registration.
    File moves (from move-source) trigger a DB path update.
    """

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
        # Track files we've already registered to avoid double-processing
        # watchdog fires on_created + on_modified for the same write
        self._seen: set[str] = set()

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".md":
            self._register(path)

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".md" and str(path) not in self._seen:
            self._register(path)

    def on_moved(self, event) -> None:
        """Handle source moves between clusters — update sources.path in DB."""
        if event.is_directory:
            return
        old = Path(event.src_path)
        new = Path(event.dest_path)
        # Only care about moves of the primary file (.pdf for papers, .md for URLs)
        if old.suffix in (".pdf", ".md"):
            try:
                old_rel = old.relative_to(self._vault_root)
                new_rel = new.relative_to(self._vault_root)
            except ValueError:
                return
            key = old.stem
            with self._lock:
                row = self._conn.execute(
                    "SELECT id FROM sources WHERE slug=?", [key]
                ).fetchone()
                if row is not None:
                    self._conn.execute(
                        "UPDATE sources SET path=? WHERE slug=?",
                        [new_rel.as_posix(), key],
                    )

    def _register(self, abs_path: Path) -> None:
        """Register a new raw/ source: chunk → embed → insert into DB."""
        try:
            rel = abs_path.relative_to(self._vault_root)
        except ValueError:
            return

        key = abs_path.stem
        # Prevent duplicate registration from rapid-fire watchdog events
        if key in self._seen:
            return
        self._seen.add(key)

        # Only process files inside raw/ subdirectories (not raw/ root)
        if len(rel.parts) < 2:
            return

        # Check if already registered
        row = self._conn.execute(
            "SELECT id FROM sources WHERE slug=?", [key]
        ).fetchone()
        if row is not None:
            return

        from lacuna_wiki.sources.chunker import chunk_md
        from lacuna_wiki.sources.register import register_source, register_chunks

        # Chunk and embed the extracted text
        chunks = chunk_md(abs_path, strategy="heading")
        if not chunks:
            return

        embeddings = self._embed_fn([c.text for c in chunks])

        # Determine source type and cite extension from what files exist
        source_dir = abs_path.parent
        has_pdf = (source_dir / f"{key}.pdf").exists()
        has_bib = (source_dir / f"{key}.bib").exists()

        source_type = "paper" if has_pdf else "url"
        cite_ext = ".pdf" if has_pdf else ".md"

        # Read metadata from .bib sidecar if available
        title = None
        authors = None
        published_date = None
        if has_bib:
            bib_path = source_dir / f"{key}.bib"
            try:
                from lacuna_wiki.sources.metadata import parse_bibtex_fields
                bib_text = bib_path.read_text(encoding="utf-8")
                meta = parse_bibtex_fields(bib_text)
                title = meta.get("title")
                authors = meta.get("authors")
                year = meta.get("year")
                if year:
                    from datetime import date
                    published_date = date(int(year), 1, 1)
            except Exception:
                pass

        # The primary file is the PDF if it exists, otherwise the .md
        primary_path = (source_dir / f"{key}.pdf") if has_pdf else abs_path
        rel_path = str(primary_path.relative_to(self._vault_root))

        with self._lock:
            source_id = register_source(
                self._conn, key, rel_path, title, authors,
                published_date, source_type,
            )
            register_chunks(self._conn, source_id, chunks, embeddings)


def initial_sync(
    conn: duckdb.DuckDBPyConnection,
    vault_root: Path,
    embed_fn: EmbedFn,
    n_workers: int = 1,
    embed_concurrency: int = 1,
    rebuild_fts: bool = True,
) -> None:
    """Sync all existing wiki/*.md files.

    When n_workers > 1, pages are processed in parallel using a temporary
    ConnectionPool. Each worker gets its own DB connection and writes to
    disjoint page rows — no conflicts.

    rebuild_fts: if True, rebuild the full-text index at the end. Set False
    when calling from the daemon watchdog (startup) to skip the expensive
    checkpoint — the FTS index is already in a good state from the previous
    run. Only rebuild on explicit sync or when pages actually changed.
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
        pages_changed = 0
        for rel in md_files:
            if sync_page(conn, vault_root, rel, throttled_embed, rebuild_fts=False):
                pages_changed += 1
        if rebuild_fts or pages_changed > 0:
            _sync_mod._rebuild_fts(conn)
        return

    from lacuna_wiki.daemon.connections import ConnectionPool
    from lacuna_wiki.vault import db_path as get_db_path

    db = get_db_path(vault_root)
    worker_pool = ConnectionPool(db, size=n_workers)
    worker_pool.open()

    pages_changed = 0

    def sync_one(rel_path):
        nonlocal pages_changed
        wconn = worker_pool.acquire()
        try:
            if sync_page(wconn, vault_root, rel_path, throttled_embed, rebuild_fts=False):
                pages_changed += 1
        finally:
            worker_pool.release(wconn)

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = [executor.submit(sync_one, rel) for rel in md_files]
            for fut in as_completed(futures):
                fut.result()
    finally:
        worker_pool.close()

    if rebuild_fts or pages_changed > 0:
        _sync_mod._rebuild_fts(conn)
