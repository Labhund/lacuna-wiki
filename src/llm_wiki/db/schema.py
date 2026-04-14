"""DuckDB schema — all seven tables."""
from __future__ import annotations

import duckdb

_SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS pages_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS sections_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS sources_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS claims_id_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS source_chunks_id_seq START 1",
]

_TABLES = [
    """CREATE TABLE IF NOT EXISTS pages (
    id            INTEGER DEFAULT nextval('pages_id_seq') PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    path          TEXT NOT NULL,
    title         TEXT,
    cluster       TEXT,
    last_modified TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS sections (
    id           INTEGER DEFAULT nextval('sections_id_seq') PRIMARY KEY,
    page_id      INTEGER REFERENCES pages(id),
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    content_hash TEXT,
    token_count  INTEGER,
    embedding    FLOAT[768]
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
    """CREATE TABLE IF NOT EXISTS claims (
    id                   INTEGER DEFAULT nextval('claims_id_seq') PRIMARY KEY,
    page_id              INTEGER REFERENCES pages(id),
    section_id           INTEGER,
    text                 TEXT NOT NULL,
    embedding            FLOAT[768],
    superseded_by        INTEGER REFERENCES claims(id),
    last_adversary_check TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS claim_sources (
    claim_id        INTEGER REFERENCES claims(id),
    source_id       INTEGER REFERENCES sources(id),
    citation_number INTEGER,
    relationship    TEXT,
    checked_at      TIMESTAMP,
    PRIMARY KEY (claim_id, source_id)
)""",
    """CREATE TABLE IF NOT EXISTS source_chunks (
    id          INTEGER DEFAULT nextval('source_chunks_id_seq') PRIMARY KEY,
    source_id   INTEGER REFERENCES sources(id),
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    token_count INTEGER,
    embedding   FLOAT[768]
)""",
]


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Create sequences and tables. Safe to call on an existing DB."""
    for stmt in _SEQUENCES:
        conn.execute(stmt)
    for stmt in _TABLES:
        conn.execute(stmt)
