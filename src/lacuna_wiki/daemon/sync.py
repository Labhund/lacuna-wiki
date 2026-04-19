from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import duckdb

from lacuna_wiki.daemon.parser import (
    CitationEntry, extract_extra_frontmatter, format_frontmatter, parse_citation_claims, parse_frontmatter,
    parse_sections, parse_wikilinks, tags_to_db,
)
from lacuna_wiki.tokens import count_tokens

EmbedFn = Callable[[list[str]], list[list[float]]]


_OBSIDIAN_COMMENT_RE = re.compile(r'%%.*?%%', re.DOTALL)
_SYNTHESISED_INTO_RE = re.compile(
    r'%%\s*synthesised-into:\s*\[\[([^\]]+)\]\]\s*%%', re.IGNORECASE
)


def _strip_obsidian_comments(text: str) -> str:
    text = _OBSIDIAN_COMMENT_RE.sub('', text)
    # Collapse multiple consecutive blank lines introduced by comment removal
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _body_hash(body: str) -> str:
    return hashlib.sha256(_strip_obsidian_comments(body).encode("utf-8")).hexdigest()[:24]


def sync_page(
    conn: duckdb.DuckDBPyConnection,
    vault_root: Path,
    rel_path: Path,
    embed_fn: EmbedFn,
    rebuild_fts: bool = False,
) -> None:
    """Full sync of one wiki page to DB. Wraps everything in a transaction.

    rel_path: path relative to vault_root, e.g. Path("wiki/attention.md")
    embed_fn: callable(texts) -> list[list[float]] — 768-dim vectors

    Skips section/link/claim sync when body is unchanged (frontmatter-only
    write). Writes created/updated dates back into the frontmatter after sync;
    idempotent — second pass detects unchanged body and exits early.
    """
    full_path = vault_root / rel_path
    slug = rel_path.stem

    if not full_path.exists():
        _delete_page(conn, slug)
        return

    text = full_path.read_text(encoding="utf-8")
    tags, body = parse_frontmatter(text)
    bh = _body_hash(body)
    tags_json = tags_to_db(tags)

    existing = conn.execute(
        "SELECT id, body_hash, tags FROM pages WHERE slug=?", [slug]
    ).fetchone()

    if existing:
        existing_id, existing_bh, existing_tags = existing
        if existing_bh == bh and existing_tags == tags_json:
            # Nothing changed at all — redundant watchdog event (e.g. after
            # the daemon wrote dates back into the frontmatter). Still update
            # synthesised_into in case the notice was added without body change.
            m = _SYNTHESISED_INTO_RE.search(body)
            conn.execute(
                "UPDATE pages SET synthesised_into=? WHERE slug=?",
                [m.group(1) if m else None, slug],
            )
            return
        if existing_bh == bh:
            # Only tags changed — update metadata and write frontmatter back;
            # skip the expensive section/link/claim re-sync.
            m = _SYNTHESISED_INTO_RE.search(body)
            conn.execute(
                "UPDATE pages SET tags=?, synthesised_into=? WHERE id=?",
                [tags_json, m.group(1) if m else None, existing_id],
            )
            _write_frontmatter_back(conn, full_path, slug, tags, body)
            return

    conn.begin()
    try:
        page_id = _upsert_page(conn, slug, str(rel_path), body, tags, bh)
        _sync_sections(conn, page_id, body, embed_fn)
        _sync_links(conn, page_id, body)
        _sync_claims(conn, page_id, body, embed_fn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    m = _SYNTHESISED_INTO_RE.search(body)
    synthesised_into = m.group(1) if m else None
    conn.execute(
        "UPDATE pages SET synthesised_into=? WHERE slug=?",
        [synthesised_into, slug],
    )

    # mean_embedding is updated after the transaction commits — DuckDB's FK
    # constraint checker sees uncommitted section rows as still referencing pages,
    # which causes a spurious violation if we UPDATE pages inside the transaction.
    _update_mean_embedding(conn, page_id)
    if rebuild_fts:
        _rebuild_fts(conn)
    _write_frontmatter_back(conn, full_path, slug, tags, body)


def _rebuild_fts(conn: duckdb.DuckDBPyConnection) -> None:
    """Rebuild FTS index on sections after a sync commit. Non-fatal on failure."""
    import logging
    log = logging.getLogger(__name__)
    log.info("Rebuilding FTS index on sections...")
    try:
        conn.execute("PRAGMA create_fts_index('sections', 'id', 'content', overwrite=1)")
        conn.commit()
        log.info("FTS index rebuild complete.")
    except Exception as exc:
        log.warning("FTS index rebuild failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upsert_page(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    path: str,
    body: str,
    tags: list[str],
    bh: str,
) -> int:
    title = _extract_title(body)
    cluster = _path_to_cluster(path)
    tags_json = tags_to_db(tags)
    row = conn.execute("SELECT id FROM pages WHERE slug = ?", [slug]).fetchone()
    if row:
        conn.execute(
            "UPDATE pages SET path=?, title=?, cluster=?, tags=?, body_hash=?,"
            " last_modified=now() WHERE id=?",
            [path, title, cluster, tags_json, bh, row[0]],
        )
        return row[0]
    conn.execute(
        "INSERT INTO pages (slug, path, title, cluster, tags, body_hash,"
        " created_at, last_modified) VALUES (?,?,?,?,?,?,now(),now())",
        [slug, path, title, cluster, tags_json, bh],
    )
    return conn.execute("SELECT id FROM pages WHERE slug=?", [slug]).fetchone()[0]


def _write_frontmatter_back(
    conn: duckdb.DuckDBPyConnection,
    full_path: Path,
    slug: str,
    tags: list[str],
    body: str,
) -> None:
    """Write canonical frontmatter (dates + tags) back into the file.

    Only writes if the result differs from what is already on disk — prevents
    infinite watchdog loops. The next watchdog event will find an unchanged
    body hash and exit early.
    """
    row = conn.execute(
        "SELECT created_at, last_modified FROM pages WHERE slug=?", [slug]
    ).fetchone()
    if row is None:
        return

    def _to_date(v) -> str:
        if isinstance(v, datetime):
            return v.date().isoformat()
        return str(v)[:10]

    created_str = _to_date(row[0])
    updated_str = _to_date(row[1])
    current_text = full_path.read_text(encoding="utf-8")
    extras = extract_extra_frontmatter(current_text)
    canonical_fm = format_frontmatter(tags, created_str, updated_str, extras=extras)

    # Reconstruct what the file should look like
    # body may or may not start with a blank line — preserve it
    canonical_text = canonical_fm + body
    if canonical_text != current_text:
        full_path.write_text(canonical_text, encoding="utf-8")


def _extract_title(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _path_to_cluster(path: str) -> str:
    """wiki/machine-learning/attention/sdpa.md  →  'machine-learning/attention'"""
    parts = Path(path).parts
    return "/".join(parts[1:-1])  # wiki cluster paths always use forward slashes


def _update_mean_embedding(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    dim: int = 768,
) -> None:
    """Compute element-wise mean of section embeddings and upsert into page_embeddings.

    Stored in a side table rather than as a column on pages because DuckDB 1.5.x has
    a bug where UPDATE with FLOAT array on a table referenced by FK children raises a
    spurious constraint error. See schema.py _synthesis_tables for the full note.
    """
    slug_row = conn.execute("SELECT slug FROM pages WHERE id=?", [page_id]).fetchone()
    if slug_row is None:
        return
    slug = slug_row[0]

    rows = conn.execute(
        "SELECT embedding FROM sections WHERE page_id=? AND embedding IS NOT NULL",
        [page_id],
    ).fetchall()
    if not rows:
        return
    vecs = [row[0] for row in rows]
    n = len(vecs)
    mean_vec = [sum(vecs[i][j] for i in range(n)) / n for j in range(dim)]

    # Upsert: DELETE then INSERT (no ON CONFLICT support in DuckDB for FLOAT arrays)
    conn.execute("DELETE FROM page_embeddings WHERE slug=?", [slug])
    conn.execute(
        "INSERT INTO page_embeddings (slug, mean_embedding) VALUES (?, ?)",
        [slug, mean_vec],
    )


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
            """INSERT INTO sections
               (page_id, position, name, content, content_hash, token_count, embedding)
               VALUES (?,?,?,?,?,?,?)""",
            [page_id, s.position, s.name, s.content, s.content_hash,
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

    # Delete removed claims and their claim_sources.
    # claim_sources.claim_id has no FK (DuckDB checks FKs against committed
    # state, making within-transaction cross-table deletes unreliable), so
    # order is enforced here: claim_sources first, then claims.
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
