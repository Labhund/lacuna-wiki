from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import duckdb

from llm_wiki.daemon.parser import (
    CitationEntry, parse_citation_claims, parse_sections, parse_wikilinks,
)
from llm_wiki.tokens import count_tokens

EmbedFn = Callable[[list[str]], list[list[float]]]


def sync_page(
    conn: duckdb.DuckDBPyConnection,
    vault_root: Path,
    rel_path: Path,
    embed_fn: EmbedFn,
) -> None:
    """Full sync of one wiki page to DB. Wraps everything in a transaction.

    rel_path: path relative to vault_root, e.g. Path("wiki/attention.md")
    embed_fn: callable(texts) -> list[list[float]] — 768-dim vectors
    """
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upsert_page(conn: duckdb.DuckDBPyConnection, slug: str, path: str, text: str) -> int:
    title = _extract_title(text)
    cluster = _path_to_cluster(path)
    row = conn.execute("SELECT id FROM pages WHERE slug = ?", [slug]).fetchone()
    if row:
        conn.execute(
            "UPDATE pages SET path=?, title=?, cluster=?, last_modified=now() WHERE id=?",
            [path, title, cluster, row[0]],
        )
        return row[0]
    conn.execute(
        "INSERT INTO pages (slug, path, title, cluster, last_modified) VALUES (?,?,?,?,now())",
        [slug, path, title, cluster],
    )
    return conn.execute("SELECT id FROM pages WHERE slug=?", [slug]).fetchone()[0]


def _extract_title(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _path_to_cluster(path: str) -> str:
    """wiki/machine-learning/attention/sdpa.md  →  'machine-learning/attention'"""
    parts = Path(path).parts
    return "/".join(parts[1:-1])


def _sync_sections(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    text: str,
    embed_fn: EmbedFn,
) -> None:
    sections = parse_sections(text)

    # Collect existing {content_hash: embedding} to reuse unchanged embeddings
    existing: dict[str, list[float]] = {}
    for row in conn.execute(
        "SELECT content_hash, embedding FROM sections WHERE page_id=?", [page_id]
    ).fetchall():
        if row[0] and row[1] is not None:
            existing[row[0]] = row[1]

    # Embed only sections whose hash isn't cached
    to_embed = [s for s in sections if s.content_hash not in existing]
    if to_embed:
        new_vecs = embed_fn([s.content for s in to_embed])
        for s, vec in zip(to_embed, new_vecs):
            existing[s.content_hash] = vec

    conn.execute("DELETE FROM sections WHERE page_id=?", [page_id])
    for s in sections:
        conn.execute(
            """INSERT INTO sections (page_id, position, name, content_hash, token_count, embedding)
               VALUES (?,?,?,?,?,?)""",
            [page_id, s.position, s.name, s.content_hash,
             count_tokens(s.content), existing.get(s.content_hash)],
        )


def _sync_links(conn: duckdb.DuckDBPyConnection, page_id: int, text: str) -> None:
    conn.execute("DELETE FROM links WHERE source_page_id=?", [page_id])
    for target in parse_wikilinks(text):
        conn.execute(
            "INSERT INTO links (source_page_id, target_slug) VALUES (?,?)",
            [page_id, target],
        )


def _sync_claims(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    text: str,
    embed_fn: EmbedFn,
) -> None:
    """Merge citation claims for this page.

    Preserves existing relationship values for unchanged claim texts.
    Assigns citation numbers sequentially by first-appearance of each source.
    Unknown source keys: claim row is created, claim_sources row is skipped.
    """
    sections = parse_sections(text)
    all_citations: list[CitationEntry] = []
    for s in sections:
        all_citations.extend(parse_citation_claims(s.content, s.name, s.position))

    # Existing claims keyed by text → claim_id
    existing: dict[str, int] = {
        row[1]: row[0]
        for row in conn.execute(
            "SELECT id, text FROM claims WHERE page_id=?", [page_id]
        ).fetchall()
    }

    new_texts = {c.text for c in all_citations}

    # Delete removed claims and their claim_sources
    for old_text, old_id in existing.items():
        if old_text not in new_texts:
            conn.execute("DELETE FROM claim_sources WHERE claim_id=?", [old_id])
            conn.execute("DELETE FROM claims WHERE id=?", [old_id])

    # Embed new claim texts
    to_embed_claims = [c for c in all_citations if c.text not in existing]
    if to_embed_claims:
        new_vecs = embed_fn([c.text for c in to_embed_claims])
        vec_map: dict[str, list[float]] = {c.text: v for c, v in zip(to_embed_claims, new_vecs)}
    else:
        vec_map = {}

    # Citation numbers: first-appearance order of source keys across all citations
    citation_numbers: dict[str, int] = {}
    num = 1
    for c in all_citations:
        if c.source_key not in citation_numbers:
            citation_numbers[c.source_key] = num
            num += 1

    # Section position → section row id
    section_ids: dict[int, int] = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT position, id FROM sections WHERE page_id=?", [page_id]
        ).fetchall()
    }

    for citation in all_citations:
        if citation.text in existing:
            claim_id = existing[citation.text]
            section_id = section_ids.get(citation.section_position)
            conn.execute(
                "UPDATE claims SET section_id=? WHERE id=?",
                [section_id, claim_id],
            )
        else:
            section_id = section_ids.get(citation.section_position)
            embedding = vec_map.get(citation.text)
            conn.execute(
                "INSERT INTO claims (page_id, section_id, text, embedding) VALUES (?,?,?,?)",
                [page_id, section_id, citation.text, embedding],
            )
            claim_id = conn.execute(
                "SELECT id FROM claims WHERE page_id=? AND text=?",
                [page_id, citation.text],
            ).fetchone()[0]

        src_row = conn.execute(
            "SELECT id FROM sources WHERE slug=?", [citation.source_key]
        ).fetchone()
        if src_row is None:
            continue  # unknown source key — skip claim_sources row

        source_id = src_row[0]
        cite_num = citation_numbers[citation.source_key]

        existing_cs = conn.execute(
            "SELECT relationship FROM claim_sources WHERE claim_id=? AND source_id=?",
            [claim_id, source_id],
        ).fetchone()
        if existing_cs:
            conn.execute(
                "UPDATE claim_sources SET citation_number=? WHERE claim_id=? AND source_id=?",
                [cite_num, claim_id, source_id],
            )
        else:
            conn.execute(
                "INSERT INTO claim_sources (claim_id, source_id, citation_number, relationship)"
                " VALUES (?,?,?,NULL)",
                [claim_id, source_id, cite_num],
            )


def _delete_page(conn: duckdb.DuckDBPyConnection, slug: str) -> None:
    row = conn.execute("SELECT id FROM pages WHERE slug=?", [slug]).fetchone()
    if not row:
        return
    page_id = row[0]
    conn.execute(
        "DELETE FROM claim_sources WHERE claim_id IN (SELECT id FROM claims WHERE page_id=?)",
        [page_id],
    )
    conn.execute("DELETE FROM claims WHERE page_id=?", [page_id])
    conn.execute("DELETE FROM links WHERE source_page_id=?", [page_id])
    conn.execute("DELETE FROM sections WHERE page_id=?", [page_id])
    conn.execute("DELETE FROM pages WHERE id=?", [page_id])
