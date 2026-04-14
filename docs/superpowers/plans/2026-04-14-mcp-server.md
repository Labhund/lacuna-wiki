# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `wiki` MCP tool — hybrid BM25+vector search and DB-computed navigate/multi-read responses — so agents can query the wiki without any LLM involvement.

**Architecture:** A FastMCP server exposes a single `wiki` tool with two call patterns: search (`q`) and navigate (`page`/`pages`). Search uses DuckDB FTS for BM25 and `array_inner_product` for vector similarity, combined with Reciprocal Rank Fusion. Navigate assembles section content + navigation panel (links in/out, sources cited, semantically close sections) entirely from DB. The daemon rebuilds the FTS index after each page sync. The MCP server opens a read-only DuckDB connection.

**Tech Stack:** `mcp>=1.0` (FastMCP), DuckDB FTS extension (bundled), `array_inner_product` (no extension needed), `lacuna_wiki.sources.embedder.embed_texts` for query embedding. Vault path from `LACUNA_VAULT` env var.

---

## File Map

```
src/lacuna_wiki/
  mcp/
    __init__.py       — empty package marker
    server.py         — FastMCP instance, wiki tool, entry point (run via stdio)
    search.py         — bm25_search(), vec_search(), hybrid_search()
    navigate.py       — navigate_page(), multi_read()
    format.py         — format_search_results(), format_navigate_response()
  cli/
    mcp_cmd.py        — `lacuna mcp` Click command (reads LACUNA_VAULT, calls server.run)
    main.py           — add mcp command (modify)
  db/
    schema.py         — add content TEXT to sections + source_chunks (modify)
    connection.py     — load_fts_extension() helper (modify)
  daemon/
    sync.py           — store content in _sync_sections INSERT; rebuild_fts() after commit (modify)
  sources/
    register.py       — store chunk.text in source_chunks INSERT (modify)
  cli/
    init.py           — INSTALL fts extension at vault init (modify)
tests/
  mcp/
    __init__.py
    test_search.py
    test_navigate.py
    test_format.py
  test_mcp_integration.py
  fixtures/
    wiki-vault/
      wiki/
        attention-mechanism.md   — real content with wikilinks + citation
        transformer.md           — real content with wikilink back to attention
      raw/
        (empty — sources added programmatically in live tests)
```

---

## DuckDB FTS notes (discovered during TDD)

- FTS extension is bundled in DuckDB 1.5.x — `LOAD fts` works without `INSTALL`.
- `PRAGMA create_fts_index('table', 'id_col', 'content_col')` — 3-argument form only. Named `overwrite` param does NOT work in this version.
- To rebuild: `PRAGMA drop_fts_index('table')` then `PRAGMA create_fts_index(...)`. 
- Rebuild must happen **after** data is committed (FTS reads committed rows).
- FTS index is stored in the DB file and is queryable from read-only connections after `LOAD fts`.
- Common English stopwords (e.g. "new", "is", "the") are filtered — tests must use content words.
- `fts_main_<table>.match_bm25(id_col, query)` returns NULL for non-matching rows — use `WHERE score IS NOT NULL`.

---

## Task 1: Schema — add content columns

**Files:**
- Modify: `src/lacuna_wiki/db/schema.py`
- Modify: `src/lacuna_wiki/daemon/sync.py`
- Modify: `src/lacuna_wiki/sources/register.py`

Sections and source_chunks currently store only offsets and hashes — no raw text. BM25 and navigate both need text in the DB.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_schema.py — new test at the bottom

def test_sections_has_content_column(conn):
    conn.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('p', 'wiki/p.md', now())")
    page_id = conn.execute("SELECT id FROM pages WHERE slug='p'").fetchone()[0]
    conn.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count)"
        " VALUES (?, 0, 'Intro', 'Hello world text.', 'abc123', 3)",
        [page_id],
    )
    text = conn.execute("SELECT content FROM sections WHERE name='Intro'").fetchone()[0]
    assert text == "Hello world text."


def test_source_chunks_has_content_column(conn):
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('s1', 'raw/s.pdf', 'paper')"
    )
    src_id = conn.execute("SELECT id FROM sources WHERE slug='s1'").fetchone()[0]
    conn.execute(
        "INSERT INTO source_chunks (source_id, chunk_index, start_line, end_line, content)"
        " VALUES (?, 0, 1, 10, 'Chunk text here.')",
        [src_id],
    )
    text = conn.execute("SELECT content FROM source_chunks").fetchone()[0]
    assert text == "Chunk text here."
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_schema.py::test_sections_has_content_column tests/test_schema.py::test_source_chunks_has_content_column -v 2>&1 | tail -5
```

Expected: FAIL — `OperationalError: table sections has no column named content`

- [ ] **Step 3: Add content columns to schema.py**

In `src/lacuna_wiki/db/schema.py`, update the sections and source_chunks CREATE TABLE statements:

```python
    """CREATE TABLE IF NOT EXISTS sections (
    id           INTEGER DEFAULT nextval('sections_id_seq') PRIMARY KEY,
    page_id      INTEGER REFERENCES pages(id),
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    content      TEXT,
    content_hash TEXT,
    token_count  INTEGER,
    embedding    FLOAT[768]
)""",
```

```python
    """CREATE TABLE IF NOT EXISTS source_chunks (
    id          INTEGER DEFAULT nextval('source_chunks_id_seq') PRIMARY KEY,
    source_id   INTEGER REFERENCES sources(id),
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    token_count INTEGER,
    content     TEXT,
    embedding   FLOAT[768]
)""",
```

- [ ] **Step 4: Run schema tests**

```bash
.venv/bin/pytest tests/test_schema.py -v 2>&1 | tail -8
```

Expected: all PASS.

- [ ] **Step 5: Update _sync_sections in sync.py to store content**

In `src/lacuna_wiki/daemon/sync.py`, find the INSERT in `_sync_sections` and add `content`:

```python
    conn.execute("DELETE FROM sections WHERE page_id=?", [page_id])
    for s in sections:
        conn.execute(
            """INSERT INTO sections
               (page_id, position, name, content, content_hash, token_count, embedding)
               VALUES (?,?,?,?,?,?,?)""",
            [page_id, s.position, s.name, s.content, s.content_hash,
             count_tokens(s.content), existing.get(s.content_hash)],
        )
```

- [ ] **Step 6: Update register_chunks in register.py to store chunk text**

In `src/lacuna_wiki/sources/register.py`, update `register_chunks`:

```python
def register_chunks(
    conn: duckdb.DuckDBPyConnection,
    source_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    """Insert source_chunks rows. Text stored for BM25 search."""
    for chunk, embedding in zip(chunks, embeddings):
        conn.execute(
            """INSERT INTO source_chunks
               (source_id, chunk_index, heading, start_line, end_line, token_count, content, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [source_id, chunk.chunk_index, chunk.heading,
             chunk.start_line, chunk.end_line, chunk.token_count, chunk.text, embedding],
        )
```

- [ ] **Step 7: Run full test suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS (existing tests pass because content is an optional column — existing inserts without it will store NULL).

- [ ] **Step 8: Commit**

```bash
git add src/lacuna_wiki/db/schema.py src/lacuna_wiki/daemon/sync.py src/lacuna_wiki/sources/register.py tests/test_schema.py
git commit -m "feat: add content TEXT to sections and source_chunks for BM25 search"
```

---

## Task 2: FTS index management + MCP package skeleton

**Files:**
- Modify: `src/lacuna_wiki/db/connection.py`
- Modify: `src/lacuna_wiki/cli/init.py`
- Modify: `src/lacuna_wiki/daemon/sync.py`
- Modify: `pyproject.toml`
- Create: `src/lacuna_wiki/mcp/__init__.py`
- Create: `tests/mcp/__init__.py`

The daemon rebuilds the FTS index after each sync. The MCP server queries it read-only.

- [ ] **Step 1: Add mcp to pyproject.toml and install**

In `pyproject.toml`, add to dependencies:

```toml
dependencies = [
    "click>=8.0",
    "duckdb>=0.10.0",
    "rich>=13.0",
    "tomli-w>=1.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "watchdog>=3.0",
    "psutil>=5.9",
    "mcp>=1.0",
]
```

Then install:

```bash
.venv/bin/pip install -e ".[dev]"
```

Expected: `mcp` installs successfully.

- [ ] **Step 2: Add load_fts_extension() to connection.py**

Replace `src/lacuna_wiki/db/connection.py` with:

```python
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
```

- [ ] **Step 3: Add FTS install to init.py**

Read `src/lacuna_wiki/cli/init.py` first, then add FTS installation. Find where `init_db(conn)` is called and add extension install before it:

```python
    # Install extensions (idempotent — safe to re-run)
    try:
        conn.execute("INSTALL fts")
        conn.execute("LOAD fts")
    except Exception:
        pass  # non-fatal if offline
    init_db(conn)
```

- [ ] **Step 4: Add FTS rebuild to sync.py**

In `src/lacuna_wiki/daemon/sync.py`, add a `_rebuild_fts` helper and call it from `sync_page` after commit:

```python
def sync_page(
    conn: duckdb.DuckDBPyConnection,
    vault_root: Path,
    rel_path: Path,
    embed_fn: EmbedFn,
) -> None:
    """Full sync of one wiki page to DB."""
    full_path = vault_root / rel_path
    slug = rel_path.stem

    if not full_path.exists():
        _delete_page(conn, slug)
        return

    text = full_path.read_text(encoding="utf-8")
    conn.begin()
    try:
        page_id = _upsert_page(conn, slug, str(rel_path), text)
        _sync_sections(conn, page_id, text, embed_fn)
        _sync_links(conn, page_id, text)
        _sync_claims(conn, page_id, text, embed_fn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    _rebuild_fts(conn)


def _rebuild_fts(conn: duckdb.DuckDBPyConnection) -> None:
    """Rebuild FTS index on sections after a sync commit. Non-fatal on failure."""
    try:
        conn.execute("PRAGMA drop_fts_index('sections')")
    except Exception:
        pass  # index may not exist yet
    try:
        conn.execute("PRAGMA create_fts_index('sections', 'id', 'content')")
    except Exception:
        pass  # non-fatal
```

- [ ] **Step 5: Create package markers**

```bash
touch src/lacuna_wiki/mcp/__init__.py tests/mcp/__init__.py
```

- [ ] **Step 6: Verify FTS rebuild in sync test**

Add this test to `tests/daemon/test_sync.py`:

```python
def test_sync_page_builds_fts_index(vault, fake_embed):
    vault_root, conn = vault
    conn.execute("LOAD fts")
    write_page(vault_root, "page.md", "# P\n\n## Methods\n\nAttention computes queries keys values.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    rows = conn.execute(
        "SELECT id, fts_main_sections.match_bm25(id, 'queries') as s"
        " FROM sections WHERE s IS NOT NULL"
    ).fetchall()
    assert len(rows) >= 1
```

- [ ] **Step 7: Run new test**

```bash
.venv/bin/pytest tests/daemon/test_sync.py::test_sync_page_builds_fts_index -v 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 8: Run full test suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/lacuna_wiki/db/connection.py src/lacuna_wiki/cli/init.py src/lacuna_wiki/daemon/sync.py src/lacuna_wiki/mcp/__init__.py tests/mcp/__init__.py tests/daemon/test_sync.py
git commit -m "feat: FTS index management — daemon rebuilds after sync, mcp package skeleton"
```

---

## Task 3: BM25 + vector search

**Files:**
- Create: `src/lacuna_wiki/mcp/search.py`
- Create: `tests/mcp/test_search.py`

`hybrid_search` runs BM25 and vector queries separately, ranks each, and combines with RRF (k=60).

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_search.py
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.search import bm25_search, vec_search, hybrid_search, SearchHit


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)
    c.execute("LOAD fts")
    # Insert a page with two sections
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attn', 'wiki/attn.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='attn'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'Overview', 'Attention computes queries keys values scaled dot product.', 'h1', 8, ?)",
        [page_id, [0.9] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 1, 'Background', 'Transformer encoder decoder architecture residual connections.', 'h2', 6, ?)",
        [page_id, [0.0] * 767 + [0.9]],
    )
    c.execute("PRAGMA create_fts_index('sections', 'id', 'content')")
    # source chunk for scope=sources testing
    c.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    c.execute(
        "INSERT INTO source_chunks (source_id, chunk_index, start_line, end_line, token_count, content, embedding)"
        " VALUES (?, 0, 1, 20, 10, 'Scaled dot-product attention mechanism query key value softmax.', ?)",
        [src_id, [0.8] + [0.0] * 767],
    )
    c.execute("PRAGMA create_fts_index('source_chunks', 'id', 'content')")
    return c


def test_bm25_search_finds_matching_section(conn):
    hits = bm25_search(conn, "queries", scope="wiki", n=5)
    assert len(hits) >= 1
    assert any(h.section_name == "Overview" for h in hits)


def test_bm25_search_scope_sources(conn):
    hits = bm25_search(conn, "softmax", scope="sources", n=5)
    assert len(hits) >= 1
    assert all(h.source_type == "source" for h in hits)


def test_bm25_search_scope_all(conn):
    hits = bm25_search(conn, "attention", scope="all", n=10)
    types = {h.source_type for h in hits}
    assert "wiki" in types
    assert "source" in types


def test_bm25_search_no_results(conn):
    hits = bm25_search(conn, "zzznomatchzzz", scope="wiki", n=5)
    assert hits == []


def test_vec_search_finds_similar_section(conn):
    # Query vector close to Overview section ([0.9, 0.0, ...])
    query_vec = [0.9] + [0.0] * 767
    hits = vec_search(conn, query_vec, scope="wiki", n=5)
    assert len(hits) >= 1
    assert hits[0].section_name == "Overview"


def test_vec_search_scope_sources(conn):
    query_vec = [0.8] + [0.0] * 767
    hits = vec_search(conn, query_vec, scope="sources", n=5)
    assert len(hits) >= 1
    assert all(h.source_type == "source" for h in hits)


def test_hybrid_search_combines_results(conn):
    query_vec = [0.9] + [0.0] * 767
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    assert len(hits) >= 1
    # Overview should rank highly (matches both BM25 and vec)
    assert hits[0].section_name == "Overview"


def test_hybrid_search_mechanism_label(conn):
    query_vec = [0.9] + [0.0] * 767
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    overview = next(h for h in hits if h.section_name == "Overview")
    # Should match both BM25 and vector
    assert overview.mechanism == "bm25+vec"


def test_hybrid_search_vec_only_mechanism(conn):
    # Vector close to Background section ([0.0, ..., 0.9])
    query_vec = [0.0] * 767 + [0.9]
    # BM25 query that won't match Background
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    background = next((h for h in hits if h.section_name == "Background"), None)
    if background:
        assert background.mechanism in ("vec", "bm25+vec")
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/mcp/test_search.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.mcp.search'`

- [ ] **Step 3: Write src/lacuna_wiki/mcp/search.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import duckdb

Scope = Literal["wiki", "sources", "all"]


@dataclass
class SearchHit:
    id: int
    slug: str
    section_name: str
    content: str
    token_count: int
    score: float
    mechanism: str   # "bm25", "vec", "bm25+vec"
    source_type: Literal["wiki", "source"]


def bm25_search(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    scope: Scope = "wiki",
    n: int = 10,
) -> list[SearchHit]:
    """BM25 text search against sections and/or source_chunks."""
    hits: list[SearchHit] = []

    if scope in ("wiki", "all"):
        try:
            rows = conn.execute(
                """
                SELECT s.id, p.slug, s.name, s.content, s.token_count,
                       fts_main_sections.match_bm25(s.id, ?) AS bm25_score
                FROM sections s
                JOIN pages p ON s.page_id = p.id
                WHERE bm25_score IS NOT NULL
                ORDER BY bm25_score DESC
                LIMIT ?
                """,
                [query, n],
            ).fetchall()
            for row in rows:
                hits.append(SearchHit(
                    id=row[0], slug=row[1], section_name=row[2],
                    content=row[3] or "", token_count=row[4] or 0,
                    score=row[5], mechanism="bm25", source_type="wiki",
                ))
        except Exception:
            pass  # FTS index not built yet

    if scope in ("sources", "all"):
        try:
            rows = conn.execute(
                """
                SELECT sc.id, s.slug, sc.heading, sc.content, sc.token_count,
                       fts_main_source_chunks.match_bm25(sc.id, ?) AS bm25_score
                FROM source_chunks sc
                JOIN sources s ON sc.source_id = s.id
                WHERE bm25_score IS NOT NULL
                ORDER BY bm25_score DESC
                LIMIT ?
                """,
                [query, n],
            ).fetchall()
            for row in rows:
                hits.append(SearchHit(
                    id=row[0], slug=row[1],
                    section_name=row[2] or f"chunk-{row[0]}",
                    content=row[3] or "", token_count=row[4] or 0,
                    score=row[5], mechanism="bm25", source_type="source",
                ))
        except Exception:
            pass

    return hits


def vec_search(
    conn: duckdb.DuckDBPyConnection,
    query_embedding: list[float],
    scope: Scope = "wiki",
    n: int = 10,
) -> list[SearchHit]:
    """Cosine similarity search using array_inner_product (normalized embeddings)."""
    hits: list[SearchHit] = []

    if scope in ("wiki", "all"):
        rows = conn.execute(
            """
            SELECT s.id, p.slug, s.name, s.content, s.token_count,
                   array_inner_product(s.embedding, ?::FLOAT[768]) AS vec_score
            FROM sections s
            JOIN pages p ON s.page_id = p.id
            WHERE s.embedding IS NOT NULL
            ORDER BY vec_score DESC
            LIMIT ?
            """,
            [query_embedding, n],
        ).fetchall()
        for row in rows:
            hits.append(SearchHit(
                id=row[0], slug=row[1], section_name=row[2],
                content=row[3] or "", token_count=row[4] or 0,
                score=row[5], mechanism="vec", source_type="wiki",
            ))

    if scope in ("sources", "all"):
        rows = conn.execute(
            """
            SELECT sc.id, s.slug, sc.heading, sc.content, sc.token_count,
                   array_inner_product(sc.embedding, ?::FLOAT[768]) AS vec_score
            FROM source_chunks sc
            JOIN sources s ON sc.source_id = s.id
            WHERE sc.embedding IS NOT NULL
            ORDER BY vec_score DESC
            LIMIT ?
            """,
            [query_embedding, n],
        ).fetchall()
        for row in rows:
            hits.append(SearchHit(
                id=row[0], slug=row[1],
                section_name=row[2] or f"chunk-{row[0]}",
                content=row[3] or "", token_count=row[4] or 0,
                score=row[5], mechanism="vec", source_type="source",
            ))

    return hits


def hybrid_search(
    conn: duckdb.DuckDBPyConnection,
    query_text: str,
    query_embedding: list[float],
    scope: Scope = "wiki",
    n: int = 10,
) -> list[SearchHit]:
    """Hybrid BM25 + vector search combined with Reciprocal Rank Fusion (k=60)."""
    bm25_hits = bm25_search(conn, query_text, scope, n * 2)
    vec_hits = vec_search(conn, query_embedding, scope, n * 2)

    # Build rank maps: key = (source_type, id)
    def _key(h: SearchHit) -> tuple[str, int]:
        return (h.source_type, h.id)

    bm25_ranks = {_key(h): i for i, h in enumerate(bm25_hits)}
    vec_ranks = {_key(h): i for i, h in enumerate(vec_hits)}
    hit_map: dict[tuple[str, int], SearchHit] = {_key(h): h for h in bm25_hits + vec_hits}

    K = 60
    rrf_scores: dict[tuple[str, int], float] = {}
    for key in hit_map:
        score = 0.0
        if key in bm25_ranks:
            score += 1.0 / (K + bm25_ranks[key])
        if key in vec_ranks:
            score += 1.0 / (K + vec_ranks[key])
        rrf_scores[key] = score

    ranked = sorted(rrf_scores.items(), key=lambda x: -x[1])[:n]

    results: list[SearchHit] = []
    for key, rrf_score in ranked:
        hit = hit_map[key]
        in_bm25 = key in bm25_ranks
        in_vec = key in vec_ranks
        mechanism = "bm25+vec" if in_bm25 and in_vec else "bm25" if in_bm25 else "vec"
        results.append(SearchHit(
            id=hit.id, slug=hit.slug, section_name=hit.section_name,
            content=hit.content, token_count=hit.token_count,
            score=rrf_score, mechanism=mechanism, source_type=hit.source_type,
        ))
    return results
```

- [ ] **Step 4: Run search tests**

```bash
.venv/bin/pytest tests/mcp/test_search.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/mcp/search.py tests/mcp/test_search.py
git commit -m "feat: hybrid BM25+vector search with RRF combination"
```

---

## Task 4: Navigate response

**Files:**
- Create: `src/lacuna_wiki/mcp/navigate.py`
- Create: `tests/mcp/test_navigate.py`

`navigate_page` assembles section content + full navigation panel from DB. `multi_read` calls it per page and concatenates.

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_navigate.py
import duckdb
import pytest

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.navigate import navigate_page, multi_read, PageNotFoundError


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)

    # Page 1: attention-mechanism
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attention-mechanism', 'wiki/attention-mechanism.md', now())")
    attn_id = c.execute("SELECT id FROM pages WHERE slug='attention-mechanism'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'attention-mechanism', 'Intro text.', 'h0', 2, ?)",
        [attn_id, [0.9] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 1, 'Scaled Dot-Product', 'Attention computes QKT over sqrt dk.', 'h1', 7, ?)",
        [attn_id, [0.8, 0.1] + [0.0] * 766],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 2, 'Multi-Head', 'Multiple heads in parallel.', 'h2', 4, ?)",
        [attn_id, [0.0] * 767 + [0.9]],
    )

    # Page 2: transformer (links to attention-mechanism)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('transformer', 'wiki/transformer.md', now())")
    trans_id = c.execute("SELECT id FROM pages WHERE slug='transformer'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'transformer', 'Transformer uses attention.', 'h3', 4, ?)",
        [trans_id, [0.7] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO links (source_page_id, target_slug) VALUES (?, 'attention-mechanism')",
        [trans_id],
    )

    # Source + claim on attention-mechanism
    c.execute("INSERT INTO sources (slug, path, title, published_date, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'Attention Is All You Need', '2017-06-12', 'paper')")
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    sec_id = c.execute("SELECT id FROM sections WHERE name='Scaled Dot-Product'").fetchone()[0]
    c.execute(
        "INSERT INTO claims (page_id, section_id, text, embedding) VALUES (?, ?, 'Attention claim.', NULL)",
        [attn_id, sec_id],
    )
    claim_id = c.execute("SELECT id FROM claims WHERE text='Attention claim.'").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 1)",
        [claim_id, src_id],
    )
    return c


def test_navigate_page_returns_section_content(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "Intro text." in result


def test_navigate_page_specific_section(conn):
    result = navigate_page(conn, "attention-mechanism", section_name="Scaled Dot-Product")
    assert "Attention computes QKT" in result


def test_navigate_page_lists_all_sections(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "Scaled Dot-Product" in result
    assert "Multi-Head" in result


def test_navigate_page_links_in(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "transformer" in result


def test_navigate_page_sources_cited(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "vaswani2017" in result
    assert "Attention Is All You Need" in result
    assert "[1]" in result


def test_navigate_page_not_found_raises(conn):
    with pytest.raises(PageNotFoundError):
        navigate_page(conn, "nonexistent-page")


def test_navigate_page_semantically_close(conn):
    # Overview embedding [0.9, 0.0, ...] — Scaled Dot-Product [0.8, 0.1, ...] is closest
    result = navigate_page(conn, "attention-mechanism")
    assert "semantically close" in result.lower()


def test_multi_read_concatenates_pages(conn):
    result = multi_read(conn, ["attention-mechanism", "transformer"])
    assert "attention-mechanism" in result
    assert "transformer" in result
    assert "---" in result  # separator between pages
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/mcp/test_navigate.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.mcp.navigate'`

- [ ] **Step 3: Write src/lacuna_wiki/mcp/navigate.py**

```python
from __future__ import annotations

import duckdb


class PageNotFoundError(Exception):
    pass


def navigate_page(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    section_name: str | None = None,
    n_close: int = 3,
) -> str:
    """Assemble a navigate response for a page or specific section.

    Raises PageNotFoundError if the slug is not in the DB.
    """
    row = conn.execute("SELECT id FROM pages WHERE slug=?", [slug]).fetchone()
    if row is None:
        raise PageNotFoundError(slug)
    page_id = row[0]

    # All sections on this page
    sections = conn.execute(
        "SELECT id, position, name, content, token_count, embedding"
        " FROM sections WHERE page_id=? ORDER BY position",
        [page_id],
    ).fetchall()

    if not sections:
        return f"## {slug}\n\n(no sections)\n"

    # Target: specific section or first section (preamble)
    if section_name:
        target = next((s for s in sections if s[2] == section_name), None)
        if target is None:
            target = sections[0]
    else:
        target = sections[0]

    target_id, target_pos, target_name, target_content, target_tokens, target_emb = target

    # Links out (pages this page links to)
    links_out = [
        r[0] for r in conn.execute(
            "SELECT target_slug FROM links WHERE source_page_id=? ORDER BY target_slug",
            [page_id],
        ).fetchall()
    ]

    # Links in (pages that link to this page)
    links_in = [
        r[0] for r in conn.execute(
            "SELECT p.slug FROM links l JOIN pages p ON l.source_page_id = p.id"
            " WHERE l.target_slug=? ORDER BY p.slug",
            [slug],
        ).fetchall()
    ]

    # Semantically close sections (cosine via dot product on normalised vectors)
    close_sections: list[tuple[str, str, float, int]] = []  # (slug, section_name, score, tokens)
    if target_emb is not None:
        rows = conn.execute(
            """
            SELECT p.slug, s.name, s.token_count,
                   array_inner_product(s.embedding, ?::FLOAT[768]) AS score
            FROM sections s
            JOIN pages p ON s.page_id = p.id
            WHERE s.embedding IS NOT NULL AND s.id != ?
            ORDER BY score DESC
            LIMIT ?
            """,
            [target_emb, target_id, n_close],
        ).fetchall()
        close_sections = [(r[0], r[1], r[3], r[2]) for r in rows]

    # Sources cited on this page (via claims → claim_sources → sources)
    cited = conn.execute(
        """
        SELECT DISTINCT cs.citation_number, s.slug, s.title, s.published_date
        FROM claim_sources cs
        JOIN sources s ON cs.source_id = s.id
        JOIN claims c ON cs.claim_id = c.id
        WHERE c.page_id = ?
        ORDER BY cs.citation_number
        """,
        [page_id],
    ).fetchall()

    return _render_navigate(
        slug=slug,
        section_name=target_name,
        content=target_content or "",
        sections=[(s[2], s[4]) for s in sections],  # (name, token_count)
        links_out=links_out,
        links_in=links_in,
        close_sections=close_sections,
        cited=cited,
    )


def _render_navigate(
    slug: str,
    section_name: str,
    content: str,
    sections: list[tuple[str, int]],
    links_out: list[str],
    links_in: list[str],
    close_sections: list[tuple[str, str, float, int]],
    cited: list[tuple],
) -> str:
    lines: list[str] = []
    lines.append(f"## {slug} › {section_name}")
    lines.append("")
    lines.append(content)
    lines.append("")
    lines.append("--- navigation ---")

    # Other sections
    section_parts = [f"{name} ({tok} tok)" for name, tok in sections]
    lines.append("sections on this page:")
    lines.append("  " + " | ".join(section_parts))

    # Links
    if links_out:
        lines.append(f"links out:  {' | '.join(links_out)}")
    if links_in:
        lines.append(f"links in:   {' | '.join(links_in)}")

    # Semantically close
    if close_sections:
        lines.append("semantically close sections:")
        for s_slug, s_name, s_score, s_tok in close_sections:
            lines.append(f"  {s_slug} › {s_name}  ({s_score:.2f}, {s_tok} tok)")

    # Sources
    if cited:
        lines.append("sources cited on this page:")
        for cite_num, src_slug, src_title, src_date in cited:
            title_str = (src_title or src_slug)[:50]
            date_str = str(src_date) if src_date else "unknown"
            lines.append(f"  [{cite_num}] {src_slug:<16} {title_str:<52} {date_str}")

    return "\n".join(lines)


def multi_read(
    conn: duckdb.DuckDBPyConnection,
    slugs: list[str],
) -> str:
    """Navigate view for each slug, concatenated with --- separators."""
    parts: list[str] = []
    for slug in slugs:
        try:
            parts.append(navigate_page(conn, slug))
        except PageNotFoundError:
            parts.append(f"## {slug}\n\n(page not found)\n")
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run navigate tests**

```bash
.venv/bin/pytest tests/mcp/test_navigate.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/mcp/navigate.py tests/mcp/test_navigate.py
git commit -m "feat: navigate response — section content, navigation panel, semantically close sections"
```

---

## Task 5: Response formatting

**Files:**
- Create: `src/lacuna_wiki/mcp/format.py`
- Create: `tests/mcp/test_format.py`

`format_search_results` renders `SearchHit` objects as the text the agent reads. It extracts a relevant passage from the section content (up to 300 chars around the first query term match, or first 300 chars).

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_format.py
from lacuna_wiki.mcp.format import format_search_results, extract_passage
from lacuna_wiki.mcp.search import SearchHit


def _hit(slug, section, content, score=0.9, mechanism="bm25+vec", tok=300):
    return SearchHit(
        id=1, slug=slug, section_name=section,
        content=content, token_count=tok,
        score=score, mechanism=mechanism, source_type="wiki",
    )


def test_format_search_results_header():
    hits = [_hit("attention-mechanism", "Overview", "Attention computes queries.")]
    result = format_search_results(hits, "attention")
    assert "attention-mechanism › Overview" in result
    assert "bm25+vec" in result


def test_format_search_results_score():
    hits = [_hit("attn", "Sec", "Content.", score=0.94)]
    result = format_search_results(hits, "content")
    assert "0.94" in result


def test_format_search_results_passage_shown():
    hits = [_hit("attn", "Sec", "Background text. Attention mechanism here. More text.")]
    result = format_search_results(hits, "attention")
    assert "Attention mechanism" in result


def test_format_search_results_empty():
    result = format_search_results([], "query")
    assert "no results" in result.lower()


def test_format_search_results_multiple_hits():
    hits = [
        _hit("page1", "Sec1", "First result content.", score=0.9),
        _hit("page2", "Sec2", "Second result content.", score=0.7),
    ]
    result = format_search_results(hits, "content")
    assert "page1 › Sec1" in result
    assert "page2 › Sec2" in result


def test_extract_passage_finds_term():
    content = "A" * 100 + " attention mechanism " + "B" * 100
    passage = extract_passage(content, "attention", max_chars=60)
    assert "attention" in passage.lower()


def test_extract_passage_fallback_to_start():
    content = "Start of the text. More words here."
    passage = extract_passage(content, "notfound", max_chars=20)
    assert passage.startswith("Start")


def test_format_search_results_source_type_shown():
    hit = SearchHit(
        id=2, slug="vaswani2017", section_name="chunk-2",
        content="Source chunk content.", token_count=50,
        score=0.8, mechanism="vec", source_type="source",
    )
    result = format_search_results([hit], "content")
    assert "source" in result.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/mcp/test_format.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.mcp.format'`

- [ ] **Step 3: Write src/lacuna_wiki/mcp/format.py**

```python
from __future__ import annotations

from lacuna_wiki.mcp.search import SearchHit

_PASSAGE_MAX = 300


def extract_passage(content: str, query: str, max_chars: int = _PASSAGE_MAX) -> str:
    """Extract a relevant passage from content. Centers on first query term match."""
    lower = content.lower()
    idx = lower.find(query.lower().split()[0]) if query.strip() else -1
    if idx == -1:
        return content[:max_chars].rstrip() + ("..." if len(content) > max_chars else "")
    start = max(0, idx - max_chars // 3)
    end = min(len(content), start + max_chars)
    passage = content[start:end].strip()
    if start > 0:
        passage = "..." + passage
    if end < len(content):
        passage = passage + "..."
    return passage


def format_search_results(hits: list[SearchHit], query: str) -> str:
    """Render search hits as text for the agent."""
    if not hits:
        return f"No results for '{query}'."

    lines: list[str] = []
    for hit in hits:
        type_tag = f" [{hit.source_type}]" if hit.source_type == "source" else ""
        lines.append(
            f"{hit.slug} › {hit.section_name}{type_tag}"
            f"  (score {hit.score:.2f}, {hit.mechanism}, {hit.token_count} tok)"
        )
        passage = extract_passage(hit.content, query)
        lines.append(f'  "{passage}"')
        lines.append("")

    return "\n".join(lines).rstrip()
```

- [ ] **Step 4: Run format tests**

```bash
.venv/bin/pytest tests/mcp/test_format.py -v 2>&1 | tail -12
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/mcp/format.py tests/mcp/test_format.py
git commit -m "feat: search result formatting with passage extraction"
```

---

## Task 6: MCP server + CLI command

**Files:**
- Create: `src/lacuna_wiki/mcp/server.py`
- Create: `src/lacuna_wiki/cli/mcp_cmd.py`
- Modify: `src/lacuna_wiki/cli/main.py`

The `wiki` tool dispatches to search or navigate based on which parameters are set. Exactly one of `q`, `page`, or `pages` must be provided.

- [ ] **Step 1: Write failing tests**

```python
# tests/mcp/test_server.py  (tool routing logic only — no live MCP transport)
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.server import dispatch_wiki


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)
    c.execute("LOAD fts")
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('mypage', 'wiki/mypage.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='mypage'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'Intro', 'Hello wiki content here.', 'h1', 4, ?)",
        [page_id, [0.5] + [0.0] * 767],
    )
    c.execute("PRAGMA create_fts_index('sections', 'id', 'content')")
    return c


def fake_embed(texts):
    return [[0.5] + [0.0] * 767 for _ in texts]


def test_dispatch_search_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, q="wiki content", scope="wiki")
    assert isinstance(result, str)
    assert len(result) > 0


def test_dispatch_navigate_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, page="mypage")
    assert isinstance(result, str)
    assert "mypage" in result


def test_dispatch_multi_read_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, pages=["mypage"])
    assert isinstance(result, str)
    assert "mypage" in result


def test_dispatch_no_params_raises(conn):
    with pytest.raises(ValueError, match="exactly one"):
        dispatch_wiki(conn, fake_embed)


def test_dispatch_conflicting_params_raises(conn):
    with pytest.raises(ValueError, match="exactly one"):
        dispatch_wiki(conn, fake_embed, q="query", page="mypage")


def test_dispatch_page_not_found(conn):
    result = dispatch_wiki(conn, fake_embed, page="nosuchpage")
    assert "not found" in result.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/mcp/test_server.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.mcp.server'`

- [ ] **Step 3: Write src/lacuna_wiki/mcp/server.py**

```python
from __future__ import annotations

from typing import Callable

import duckdb
from mcp.server.fastmcp import FastMCP

from lacuna_wiki.mcp.format import format_search_results
from lacuna_wiki.mcp.navigate import PageNotFoundError, multi_read, navigate_page
from lacuna_wiki.mcp.search import hybrid_search

EmbedFn = Callable[[list[str]], list[list[float]]]

mcp_app = FastMCP("lacuna")


def dispatch_wiki(
    conn: duckdb.DuckDBPyConnection,
    embed_fn: EmbedFn,
    q: str | None = None,
    scope: str = "wiki",
    page: str | None = None,
    section: str | None = None,
    pages: list[str] | None = None,
) -> str:
    """Core dispatch logic, separated from MCP transport for testing."""
    provided = sum([q is not None, page is not None, pages is not None])
    if provided != 1:
        raise ValueError("exactly one of q, page, or pages must be provided")

    if q is not None:
        embedding = embed_fn([q])[0]
        hits = hybrid_search(conn, q, embedding, scope=scope, n=10)  # type: ignore[arg-type]
        return format_search_results(hits, q)

    if page is not None:
        try:
            return navigate_page(conn, page, section_name=section)
        except PageNotFoundError:
            return f"Page '{page}' not found in wiki."

    # pages
    return multi_read(conn, pages)  # type: ignore[arg-type]


def make_wiki_tool(conn: duckdb.DuckDBPyConnection, embed_fn: EmbedFn):
    """Register the wiki tool on mcp_app with the given DB connection and embedder."""

    @mcp_app.tool()
    def wiki(
        q: str | None = None,
        scope: str = "wiki",
        page: str | None = None,
        section: str | None = None,
        pages: list[str] | None = None,
    ) -> str:
        """Search the wiki or navigate to a page.

        Search: provide `q` (query text). Optional `scope`: "wiki" (default),
        "sources" (raw source chunks), or "all".

        Navigate: provide `page` (slug). Optional `section` (section name).

        Multi-read: provide `pages` (list of slugs).
        """
        return dispatch_wiki(conn, embed_fn, q=q, scope=scope,
                             page=page, section=section, pages=pages)
```

- [ ] **Step 4: Write src/lacuna_wiki/cli/mcp_cmd.py**

```python
"""lacuna mcp — start the MCP server (stdio transport)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from lacuna_wiki.vault import db_path, find_vault_root


@click.command("mcp")
def mcp_command() -> None:
    """Start the MCP server (stdio transport). Vault from LACUNA_VAULT env var."""
    vault_env = os.environ.get("LACUNA_VAULT")
    if vault_env:
        vault_root = Path(vault_env)
    else:
        vault_root = find_vault_root()

    if vault_root is None:
        click.echo("LACUNA_VAULT not set and not inside an lacuna vault.", err=True)
        sys.exit(1)

    db = db_path(vault_root)
    if not db.exists():
        click.echo(f"Database not found at {db}. Run lacuna init first.", err=True)
        sys.exit(1)

    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.mcp.server import make_wiki_tool, mcp_app
    from lacuna_wiki.sources.embedder import embed_texts

    conn = get_connection(db, readonly=True)
    make_wiki_tool(conn, embed_texts)
    mcp_app.run(transport="stdio")
```

- [ ] **Step 5: Register mcp command in main.py**

In `src/lacuna_wiki/cli/main.py`, add:

```python
from lacuna_wiki.cli.mcp_cmd import mcp_command  # noqa: E402

cli.add_command(mcp_command)
```

- [ ] **Step 6: Run server tests**

```bash
.venv/bin/pytest tests/mcp/test_server.py -v 2>&1 | tail -12
```

Expected: all PASS.

- [ ] **Step 7: Verify CLI help**

```bash
.venv/bin/lacuna --help
.venv/bin/lacuna mcp --help
```

Expected: `mcp` appears in the command list.

- [ ] **Step 8: Run full test suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add src/lacuna_wiki/mcp/server.py src/lacuna_wiki/cli/mcp_cmd.py src/lacuna_wiki/cli/main.py tests/mcp/test_server.py
git commit -m "feat: MCP server — wiki tool with search and navigate dispatch"
```

---

## Task 7: Integration test + fixture vault

**Files:**
- Create: `tests/test_mcp_integration.py`
- Create: `tests/fixtures/wiki-vault/wiki/attention-mechanism.md`
- Create: `tests/fixtures/wiki-vault/wiki/transformer.md`

The pytest integration test wires everything together: sync pages → build FTS → call `dispatch_wiki` → verify results. The fixture vault files serve the separate-window MCP live test (see design doc §MCP Integration Testing Protocol).

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_mcp_integration.py
"""End-to-end MCP integration tests.

Wires sync → FTS build → search → navigate through dispatch_wiki.
No subprocess, no live embedding server — fake embedder.
"""
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import db_path, state_dir_for
from lacuna_wiki.mcp.server import dispatch_wiki


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    (vault_root / "raw").mkdir()
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    conn.execute("LOAD fts")
    return vault_root, conn


def fake_embed(texts):
    # Deterministic: [1.0, 0.0, ...] for all
    return [[1.0] + [0.0] * 767 for _ in texts]


def write_and_sync(vault_root, conn, name, content):
    path = vault_root / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki") / name, fake_embed)


def test_search_finds_synced_page(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "attention.md",
                   "# attention\n\n## Overview\n\nAttention computes queries keys values.\n")
    result = dispatch_wiki(conn, fake_embed, q="queries", scope="wiki")
    assert "attention" in result
    assert "Overview" in result


def test_search_no_results_message(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page.md", "# page\n\nSome content here.\n")
    result = dispatch_wiki(conn, fake_embed, q="zzznomatchzzz", scope="wiki")
    assert "no results" in result.lower()


def test_navigate_returns_page_content(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "transformer.md",
                   "# transformer\n\n## Architecture\n\nEncoder decoder structure.\n")
    result = dispatch_wiki(conn, fake_embed, page="transformer")
    assert "transformer" in result
    assert "Architecture" in result


def test_navigate_unknown_page(vault):
    vault_root, conn = vault
    result = dispatch_wiki(conn, fake_embed, page="unknown-slug")
    assert "not found" in result.lower()


def test_multi_read_both_pages(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md", "# page-a\n\nContent A.\n")
    write_and_sync(vault_root, conn, "page-b.md", "# page-b\n\nContent B.\n")
    result = dispatch_wiki(conn, fake_embed, pages=["page-a", "page-b"])
    assert "page-a" in result
    assert "page-b" in result


def test_navigate_shows_links_in(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "target.md", "# target\n\nTarget content.\n")
    write_and_sync(vault_root, conn, "source.md",
                   "# source\n\nLinks to [[target]] here.\n")
    result = dispatch_wiki(conn, fake_embed, page="target")
    assert "source" in result  # links in


def test_navigate_shows_citation(vault):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, title, source_type)"
        " VALUES ('vaswani2017', 'raw/v.pdf', 'Attention Is All You Need', 'paper')"
    )
    write_and_sync(vault_root, conn, "attn.md",
                   "# attn\n\n## S\n\nThe mechanism. [[vaswani2017.pdf]]\n")
    result = dispatch_wiki(conn, fake_embed, page="attn")
    assert "vaswani2017" in result
    assert "Attention Is All You Need" in result
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_mcp_integration.py -v 2>&1 | tail -8
```

Expected: some tests fail (dispatch_wiki or navigate not wired correctly end-to-end).

- [ ] **Step 3: Run until all pass, then run full suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 4: Create fixture vault files for live MCP testing**

These files are for the separate-window live MCP test described in the design doc. They are committed as-is; the live test session syncs them via `lacuna start`.

```bash
mkdir -p tests/fixtures/wiki-vault/wiki tests/fixtures/wiki-vault/raw
```

`tests/fixtures/wiki-vault/wiki/attention-mechanism.md`:

```markdown
# attention-mechanism

The attention mechanism computes a weighted sum of values, where weights are determined by compatibility between a query and a set of keys.

## Scaled Dot-Product

Attention scores are computed as dot products between query and key vectors, scaled by √d_k to prevent gradient saturation. [[vaswani2017.pdf]]

The formula is: Attention(Q, K, V) = softmax(QK^T / √d_k) V

## Multi-Head Attention

Multiple attention heads run in parallel, each attending to different subspaces. Outputs are concatenated and projected. [[vaswani2017.pdf]]

See also: [[transformer]]
```

`tests/fixtures/wiki-vault/wiki/transformer.md`:

```markdown
# transformer

The Transformer is a sequence-to-sequence architecture that relies entirely on attention mechanisms, dispensing with recurrence. [[vaswani2017.pdf]]

## Architecture

The encoder maps input tokens to continuous representations. The decoder generates output tokens autoregressively.

See also: [[attention-mechanism]]
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_mcp_integration.py tests/fixtures/
git commit -m "test: MCP integration tests + fixture vault for live testing"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| `{ "q": "..." }` search | Task 3 + 6 |
| `scope` param (wiki/sources/all) | Task 3 |
| BM25 text search | Task 3 |
| Vector similarity search | Task 3 |
| RRF hybrid combination | Task 3 |
| `{ "page": "..." }` navigate | Task 4 + 6 |
| `{ "page": "...", "section": "..." }` | Task 4 + 6 |
| `{ "pages": [...] }` multi-read | Task 4 + 6 |
| Navigate: sections list | Task 4 |
| Navigate: links in/out | Task 4 |
| Navigate: semantically close sections | Task 4 |
| Navigate: sources cited with citation numbers | Task 4 |
| `LACUNA_VAULT` env var | Task 6 |
| `lacuna mcp` CLI command | Task 6 |
| Fixture vault for live testing | Task 7 |
| Read-only DB connection | Task 6 (`get_connection(db, readonly=True)`) |
| FTS rebuilt by daemon | Task 2 |

**No gaps found.**
