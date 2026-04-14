from __future__ import annotations

from datetime import date, datetime

import duckdb

from lacuna_wiki.sources.chunker import Chunk


def register_source(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    path: str,
    title: str | None,
    authors: str | None,
    published_date: date | None,
    source_type: str,
) -> int:
    """Insert a row into the sources table. Returns the new source id."""
    conn.execute(
        """INSERT INTO sources (slug, path, title, authors, published_date, registered_at, source_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [slug, path, title, authors, published_date, datetime.utcnow(), source_type],
    )
    return conn.execute("SELECT id FROM sources WHERE slug = ?", [slug]).fetchone()[0]


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
