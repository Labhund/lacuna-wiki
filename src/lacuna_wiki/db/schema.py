"""DuckDB schema — core tables plus synthesis cluster tables."""
from __future__ import annotations

import duckdb

_SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS pages_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS sections_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS sources_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS claims_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS source_chunks_id_seq START 1",
]

_SYNTHESIS_SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS synthesis_clusters_id_seq START 1",
]


def _tables(dim: int) -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS pages (
    id            INTEGER DEFAULT nextval('pages_id_seq') PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    path          TEXT NOT NULL,
    title         TEXT,
    cluster       TEXT,
    tags          TEXT,
    body_hash     TEXT,
    created_at    TIMESTAMP,
    last_modified TIMESTAMP
)""",
        f"""CREATE TABLE IF NOT EXISTS sections (
    id           INTEGER DEFAULT nextval('sections_id_seq') PRIMARY KEY,
    page_id      INTEGER REFERENCES pages(id),
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    content      TEXT,
    content_hash TEXT,
    token_count  INTEGER,
    embedding    FLOAT[{dim}]
)""",
        """CREATE TABLE IF NOT EXISTS links (
    source_page_id INTEGER REFERENCES pages(id),
    target_slug    TEXT NOT NULL,
    PRIMARY KEY (source_page_id, target_slug)
)""",
        """CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER DEFAULT nextval('sources_id_seq') PRIMARY KEY,
    slug           TEXT UNIQUE NOT NULL,
    path           TEXT NOT NULL,
    title          TEXT,
    authors        TEXT,
    published_date DATE,
    registered_at  TIMESTAMP,
    source_type    TEXT
)""",
        f"""CREATE TABLE IF NOT EXISTS claims (
    id                   INTEGER DEFAULT nextval('claims_id_seq') PRIMARY KEY,
    page_id              INTEGER REFERENCES pages(id),
    section_id           INTEGER,
    text                 TEXT NOT NULL,
    embedding            FLOAT[{dim}],
    superseded_by        INTEGER,                        -- plain int: DuckDB FK on self-ref triggers claim_sources FK on UPDATE
    last_adversary_check TIMESTAMP
)""",
        """CREATE TABLE IF NOT EXISTS claim_sources (
    claim_id        INTEGER,                            -- plain int: DuckDB FK checks committed state, making cross-table deletes within a transaction impossible
    source_id       INTEGER REFERENCES sources(id),
    citation_number INTEGER,
    relationship    TEXT,
    checked_at      TIMESTAMP,
    PRIMARY KEY (claim_id, source_id)
)""",
        f"""CREATE TABLE IF NOT EXISTS source_chunks (
    id          INTEGER DEFAULT nextval('source_chunks_id_seq') PRIMARY KEY,
    source_id   INTEGER REFERENCES sources(id),
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    token_count INTEGER,
    content     TEXT,
    embedding   FLOAT[{dim}]
)""",
    ]


def _synthesis_tables(dim: int = 768) -> list[str]:
    return [
        # page_embeddings is a side table (not part of the core page schema) to store
        # the mean section embedding per page. Stored separately because DuckDB 1.5.x
        # has a bug where UPDATE with a FLOAT array column on a table referenced by FK
        # children (sections.page_id → pages.id) raises a spurious constraint error.
        f"""CREATE TABLE IF NOT EXISTS page_embeddings (
    slug           TEXT PRIMARY KEY,
    mean_embedding FLOAT[{dim}] NOT NULL
)""",
        """CREATE TABLE IF NOT EXISTS synthesis_clusters (
    id               INTEGER DEFAULT nextval('synthesis_clusters_id_seq') PRIMARY KEY,
    concept_label    TEXT,
    agent_rationale  TEXT,
    status           TEXT DEFAULT 'pending',
    queued_at        TIMESTAMP DEFAULT now()
)""",
        """CREATE TABLE IF NOT EXISTS synthesis_cluster_members (
    cluster_id  INTEGER REFERENCES synthesis_clusters(id),
    slug        TEXT NOT NULL,
    PRIMARY KEY (cluster_id, slug)
)""",
        """CREATE TABLE IF NOT EXISTS synthesis_cluster_edges (
    cluster_id     INTEGER REFERENCES synthesis_clusters(id),
    slug_a         TEXT NOT NULL,
    slug_b         TEXT NOT NULL,
    coverage_ratio FLOAT NOT NULL,
    PRIMARY KEY (cluster_id, slug_a, slug_b)
)""",
    ]


# ---------------------------------------------------------------------------
# Schema versioning and migrations
# ---------------------------------------------------------------------------

_CURRENT_VERSION = 3


def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _set_schema_version(conn: duckdb.DuckDBPyConnection, version: int) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (?)", [version])


def _migrate_v2_claim_sources_no_fk(
    conn: duckdb.DuckDBPyConnection, dim: int
) -> None:
    """Recreate claim_sources with claim_id as a plain INTEGER (no FK).

    DuckDB checks FK constraints against the committed snapshot rather than
    the current transaction's own writes, making it impossible to delete
    claim_sources then claims within the same transaction. DuckDB also does
    not support ON DELETE CASCADE. Dropping the FK matches the same workaround
    already used for claims.superseded_by. Referential integrity is enforced
    by explicit deletion order in sync.py. Relationship values are lost but
    sync repopulates them.
    """
    conn.execute("DROP TABLE IF EXISTS claim_sources")
    conn.execute("""CREATE TABLE claim_sources (
    claim_id        INTEGER,
    source_id       INTEGER REFERENCES sources(id),
    citation_number INTEGER,
    relationship    TEXT,
    checked_at      TIMESTAMP,
    PRIMARY KEY (claim_id, source_id)
)""")


def _migrate_v3_sweep(conn: duckdb.DuckDBPyConnection, dim: int) -> None:
    """Add last_swept to pages; create page_embeddings side table + synthesis cluster tables.

    mean_embedding is stored in page_embeddings (slug TEXT PK, mean_embedding FLOAT[dim])
    rather than as a column on pages. DuckDB 1.5.x has a bug where UPDATE with a FLOAT
    array column on a table that has FK children (sections → pages) raises a spurious
    constraint error. The side table avoids this entirely.
    """
    conn.execute(
        "ALTER TABLE pages ADD COLUMN IF NOT EXISTS last_swept TIMESTAMP"
    )
    for stmt in _SYNTHESIS_SEQUENCES:
        conn.execute(stmt)
    for stmt in _synthesis_tables(dim):
        conn.execute(stmt)


def init_db(conn: duckdb.DuckDBPyConnection, dim: int = 768) -> None:
    """Create sequences and tables. Safe to call on an existing DB."""
    for stmt in _SEQUENCES:
        conn.execute(stmt)
    for stmt in _tables(dim):
        conn.execute(stmt)

    version = _get_schema_version(conn)
    if version < 2:
        _migrate_v2_claim_sources_no_fk(conn, dim)
    if version < 3:
        _migrate_v3_sweep(conn, dim)
        _set_schema_version(conn, 3)
