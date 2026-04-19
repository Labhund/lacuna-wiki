"""Audit functions for the sweep skill.

Three entry points:
- vault_audit(conn) → str — full vault picture: research gaps, ghost pages, sweep queue
- page_audit(conn, slug, embed_fn, dim) → str — single-page unlinked candidates + synthesis candidates
- mark_swept(conn, slug, cluster) → str — set last_swept; optionally create synthesis cluster
"""
from __future__ import annotations

import re
from typing import Callable

import duckdb

EmbedFn = Callable[[list[str]], list[list[float]]]

# A page is a stub (research gap) if < 100 words OR < 2 sections
_STUB_MIN_WORDS = 100
_STUB_MIN_SECTIONS = 2


# ---------------------------------------------------------------------------
# vault_audit
# ---------------------------------------------------------------------------

def vault_audit(conn: duckdb.DuckDBPyConnection, limit: int | None = None, claim: bool = False) -> str:
    """Return formatted vault audit: research gaps, ghost pages, sweep queue.

    When limit is set, ghost pages are shown as a count only and the sweep
    queue is truncated to the top `limit` entries — suitable for incremental
    tick-off workflows on large vaults.

    When claim=True and limit is not None, atomically sets sweep_lease_expires
    on the returned pages so a second parallel agent gets a different batch.
    """
    gaps = _research_gaps(conn)
    ghosts = _ghost_pages(conn)
    queue = _sweep_queue(conn)

    lines: list[str] = []

    if limit is not None:
        # Compact header — counts only, no enumeration of gaps/ghosts
        lines.append(f"research gaps: {len(gaps)}")
        lines.append(f"ghost pages: {len(ghosts)}")
        lines.append("")
        shown = queue[:limit]
        lines.append(
            f"sweep queue ({len(shown)} of {len(queue)} shown, ranked by link gap):"
        )
    else:
        lines.append(f"research gaps ({len(gaps)}):")
        for slug, title, links, words in gaps:
            lines.append(f"  {slug} — \"{title or slug}\" — {links} links, {words} words")

        lines.append("")
        lines.append(f"ghost pages ({len(ghosts)}):")
        for ghost_slug, referrers in ghosts:
            ref_str = ", ".join(
                f"{r_slug} (×{count})" for r_slug, count in referrers[:3]
            )
            lines.append(f"  {ghost_slug} — linked from: {ref_str}")

        lines.append("")
        shown = queue
        lines.append(f"sweep queue ({len(queue)} pages, ranked by link gap):")

    if claim and limit is not None and shown:
        from datetime import datetime, timezone, timedelta
        lease_until = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
        for slug, *_ in shown:
            conn.execute(
                "UPDATE pages SET sweep_lease_expires=? WHERE slug=?",
                [lease_until, slug],
            )

    for i, (slug, title, link_count, word_count, unlinked) in enumerate(shown, 1):
        unlinked_str = ", ".join(f"{s} (×{n})" for s, n in unlinked[:3])
        lines.append(
            f"  {i}. {slug} — \"{title or slug}\" — "
            f"{link_count} links / {word_count} words"
            + (f" — unlinked: {unlinked_str}" if unlinked else "")
        )

    try:
        synth_count = conn.execute(
            "SELECT COUNT(*) FROM synthesis_clusters WHERE status='pending'"
        ).fetchone()[0]
    except Exception:
        synth_count = 0
    lines.append("")
    lines.append(f"synthesis queue: {synth_count} pending clusters")

    return "\n".join(lines)


def _research_gaps(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Pages with < 100 words OR < 2 sections."""
    rows = conn.execute("""
        SELECT p.slug, p.title,
               (SELECT COUNT(*) FROM links l WHERE l.source_page_id = p.id) AS link_count,
               COALESCE((SELECT SUM(s.token_count) FROM sections s WHERE s.page_id = p.id), 0) AS token_sum,
               (SELECT COUNT(*) FROM sections s WHERE s.page_id = p.id) AS section_count
        FROM pages p
    """).fetchall()

    gaps = []
    for slug, title, links, tokens, sections in rows:
        words = int(tokens * 0.75)
        if words < _STUB_MIN_WORDS or sections < _STUB_MIN_SECTIONS:
            gaps.append((slug, title, links, words))
    return gaps


def _ghost_pages(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Slugs referenced in links that have no corresponding page row."""
    rows = conn.execute("""
        SELECT l.target_slug, COUNT(*) AS total_refs
        FROM links l
        LEFT JOIN pages p ON l.target_slug = p.slug
        WHERE p.slug IS NULL
        GROUP BY l.target_slug
        ORDER BY total_refs DESC
    """).fetchall()

    result = []
    for ghost_slug, _ in rows:
        referrers = conn.execute("""
            SELECT p.slug, COUNT(*) AS cnt
            FROM links l
            JOIN pages p ON l.source_page_id = p.id
            WHERE l.target_slug = ?
            GROUP BY p.slug
            ORDER BY cnt DESC
            LIMIT 5
        """, [ghost_slug]).fetchall()
        result.append((ghost_slug, [(r[0], r[1]) for r in referrers]))
    return result


def _is_stub(conn: duckdb.DuckDBPyConnection, page_id: int) -> bool:
    row = conn.execute("""
        SELECT COALESCE(SUM(token_count), 0), COUNT(*)
        FROM sections WHERE page_id=?
    """, [page_id]).fetchone()
    tokens, sec_count = row
    words = int(tokens * 0.75)
    return words < _STUB_MIN_WORDS or sec_count < _STUB_MIN_SECTIONS


def _sweep_queue(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Non-stub pages needing a sweep, ranked by lowest link density first."""
    rows = conn.execute("""
        SELECT id, slug, title, link_count, token_sum FROM (
            SELECT p.id, p.slug, p.title,
                   (SELECT COUNT(*) FROM links l WHERE l.source_page_id = p.id) AS link_count,
                   COALESCE((SELECT SUM(s.token_count) FROM sections s WHERE s.page_id = p.id), 0) AS token_sum
            FROM pages p
            WHERE (p.swept_semantic_hash IS NULL OR p.semantic_hash != p.swept_semantic_hash)
              AND p.synthesised_into IS NULL
              AND (p.sweep_lease_expires IS NULL OR p.sweep_lease_expires < now())
        ) t
        ORDER BY
            CASE WHEN token_sum = 0 THEN 0 ELSE link_count::FLOAT / token_sum END ASC,
            token_sum DESC
    """).fetchall()

    result = []
    for page_id, slug, title, link_count, token_sum in rows:
        if _is_stub(conn, page_id):
            continue
        words = int(token_sum * 0.75)
        unlinked = _top_unlinked_candidates(conn, page_id, slug)
        result.append((slug, title, link_count, words, unlinked))
    return result


_WIKILINK_RE = re.compile(r'\[\[[^\]]*\]\]')


def precompute_unlinked_candidates(
    conn: duckdb.DuckDBPyConnection,
    vault_root,
    page_ids: list[int] | None = None,
) -> None:
    """Build unlinked_candidates table in one vault pass.

    For each target page, scan its body for mentions of other page slugs/titles
    that are not already wikilinked. Results stored in unlinked_candidates.
    If page_ids is given, only recompute those pages; otherwise recompute all.
    """
    from pathlib import Path
    vault_root = Path(vault_root)

    rows = conn.execute("SELECT id, slug, title, path FROM pages").fetchall()
    all_pages = {r[0]: (r[1], r[2], r[3]) for r in rows}

    target_ids = set(page_ids) if page_ids else set(all_pages.keys())

    # Build (pattern, candidate_id, candidate_slug) triples once
    candidate_patterns: list[tuple[re.Pattern, int, str]] = []
    for cid, (cslug, ctitle, _) in all_pages.items():
        candidate_patterns.append(
            (re.compile(rf'\b{re.escape(cslug)}\b', re.IGNORECASE), cid, cslug)
        )
        if ctitle and ctitle.lower() != cslug.lower():
            candidate_patterns.append(
                (re.compile(rf'\b{re.escape(ctitle)}\b', re.IGNORECASE), cid, cslug)
            )

    for pid in target_ids:
        if pid not in all_pages:
            continue
        slug, title, path = all_pages[pid]
        full_path = vault_root / path
        if not full_path.exists():
            continue

        text = full_path.read_text(encoding="utf-8")
        body_stripped = _WIKILINK_RE.sub('', text)

        mention_counts: dict[str, int] = {}
        for pat, cid, cslug in candidate_patterns:
            if cid == pid:
                continue
            hits = pat.findall(body_stripped)
            if hits:
                mention_counts[cslug] = mention_counts.get(cslug, 0) + len(hits)

        conn.execute("DELETE FROM unlinked_candidates WHERE page_id=?", [pid])
        for cslug, count in mention_counts.items():
            conn.execute(
                "INSERT INTO unlinked_candidates (page_id, candidate_slug, mention_count, computed_at)"
                " VALUES (?, ?, ?, now())",
                [pid, cslug, count],
            )


def _body_text(conn: duckdb.DuckDBPyConnection, page_id: int) -> str:
    """Concatenate all section content for a page."""
    rows = conn.execute(
        "SELECT content FROM sections WHERE page_id=? ORDER BY position",
        [page_id],
    ).fetchall()
    return "\n".join(r[0] or "" for r in rows)


def _top_unlinked_candidates(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    page_slug: str,
    top_n: int = 3,
) -> list[tuple[str, int]]:
    """Find other page slugs/titles that appear unlinked in the page body.

    Reads from pre-computed cache when available; falls back to live scan.
    """
    cached = conn.execute(
        "SELECT candidate_slug, mention_count FROM unlinked_candidates"
        " WHERE page_id=? ORDER BY mention_count DESC LIMIT ?",
        [page_id, top_n],
    ).fetchall()
    if cached:
        return [(row[0], row[1]) for row in cached]
    return _top_unlinked_candidates_live(conn, page_id, page_slug, top_n)


def _top_unlinked_candidates_live(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    page_slug: str,
    top_n: int = 3,
) -> list[tuple[str, int]]:
    """Live O(N×body) scan — used when cache is absent."""
    body = _body_text(conn, page_id)
    body_stripped = re.sub(r'\[\[[^\]]*\]\]', '', body)

    candidates: list[tuple[str, int]] = []
    rows = conn.execute(
        "SELECT slug, title FROM pages WHERE slug != ?", [page_slug]
    ).fetchall()

    for slug, title in rows:
        count = len(re.findall(r'\b' + re.escape(slug) + r'\b', body_stripped, re.IGNORECASE))
        if title and title != slug:
            count += len(re.findall(r'\b' + re.escape(title) + r'\b', body_stripped, re.IGNORECASE))
        if count > 0:
            candidates.append((slug, count))

    candidates.sort(key=lambda x: -x[1])
    return candidates[:top_n]


# ---------------------------------------------------------------------------
# page_audit
# ---------------------------------------------------------------------------

def page_audit(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    embed_fn: EmbedFn,
    dim: int = 768,
    vault_root: "Path | None" = None,
) -> str:
    """Return formatted single-page audit: unlinked candidates + synthesis candidates + page body."""
    from pathlib import Path

    row = conn.execute(
        "SELECT id, title, path FROM pages WHERE slug=?", [slug]
    ).fetchone()
    if row is None:
        return f"Page '{slug}' not found."

    page_id, title, rel_path = row
    body = _body_text(conn, page_id)

    # Unlinked candidates with section locations
    unlinked = _unlinked_with_sections(conn, page_id, slug, body)

    # Synthesis candidates via two-pass
    candidates = _synthesis_candidates(conn, slug, dim)

    lines = [f"page audit: {slug} — \"{title or slug}\"", ""]

    # Include file path so the agent can edit without a second wiki call
    if rel_path:
        abs_path = (Path(vault_root) / rel_path) if vault_root else Path(rel_path)
        lines.append(f"file: {abs_path}")
        lines.append("")

    lines.append(f"unlinked candidates ({len(unlinked)}):")
    if unlinked:
        for cand_slug, cand_title, occurrences in unlinked:
            occ_str = "; ".join(f"{sec} (×{n})" for sec, n in occurrences[:2])
            lines.append(f"  [[{cand_slug}]] — in: {occ_str}")
    else:
        lines.append("  (none found)")

    lines.append("")
    lines.append("synthesis candidates (top 3 by coverage):")
    if candidates:
        for cand_slug, cand_title, coverage in candidates[:3]:
            lines.append(
                f"  [[{cand_slug}]] — \"{cand_title or cand_slug}\" — coverage {coverage:.2f}"
            )
    else:
        lines.append("  (none above threshold)")

    # Include the page body so the agent can edit without a second wiki(page=) call
    file_content: str | None = None
    if vault_root and rel_path:
        full_path = Path(vault_root) / rel_path
        if full_path.exists():
            file_content = full_path.read_text(encoding="utf-8")

    lines.append("")
    lines.append("--- page body ---")
    lines.append(file_content if file_content is not None else body)

    return "\n".join(lines)


def _unlinked_with_sections(
    conn: duckdb.DuckDBPyConnection,
    page_id: int,
    page_slug: str,
    body: str,
) -> list[tuple[str, str | None, list[tuple[str, int]]]]:
    """Unlinked candidates with per-section occurrence counts."""
    other_pages = conn.execute(
        "SELECT slug, title FROM pages WHERE slug != ?", [page_slug]
    ).fetchall()

    section_rows = conn.execute(
        "SELECT name, content FROM sections WHERE page_id=? ORDER BY position",
        [page_id],
    ).fetchall()

    results = []
    for cand_slug, cand_title in other_pages:
        patterns = [r'\b' + re.escape(cand_slug) + r'\b']
        if cand_title and cand_title != cand_slug:
            patterns.append(r'\b' + re.escape(cand_title) + r'\b')

        per_section: list[tuple[str, int]] = []
        for sec_name, sec_content in section_rows:
            sec_stripped = re.sub(r'\[\[[^\]]*\]\]', '', sec_content or '')
            count = 0
            for pat in patterns:
                count += len(re.findall(pat, sec_stripped, re.IGNORECASE))
            if count > 0:
                per_section.append((sec_name, count))

        if per_section:
            results.append((cand_slug, cand_title, per_section))

    results.sort(key=lambda x: -sum(n for _, n in x[2]))
    return results


def _synthesis_candidates(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    dim: int = 768,
) -> list[tuple[str, str | None, float]]:
    """Two-pass synthesis candidate detection using stored embeddings in page_embeddings.

    Pass 1: mean_embedding cosine similarity pre-filter (sim > 0.50, top 20).
    Pass 2: section-level coverage ratio for each candidate.
    Returns list of (slug, title, coverage_ratio) sorted by coverage_ratio desc.
    """
    pass1 = conn.execute(f"""
        SELECT p2.slug, p2.title,
               array_inner_product(pe1.mean_embedding::FLOAT[{dim}], pe2.mean_embedding::FLOAT[{dim}]) AS sim
        FROM page_embeddings pe1
        JOIN pages p1 ON pe1.slug = p1.slug AND p1.synthesised_into IS NULL
        JOIN page_embeddings pe2 ON pe2.slug != pe1.slug
        JOIN pages p2 ON pe2.slug = p2.slug AND p2.synthesised_into IS NULL
        WHERE p1.slug = ?
        ORDER BY sim DESC
        LIMIT 20
    """, [slug]).fetchall()

    candidates = [(row[0], row[1]) for row in pass1 if row[2] > 0.50]
    if not candidates:
        return []

    results = []
    for cand_slug, cand_title in candidates:
        ratio = _coverage_ratio(conn, slug, cand_slug, dim)
        if ratio > 0.30 and _shared_source_count(conn, slug, cand_slug) >= 2:
            results.append((cand_slug, cand_title, ratio))

    results.sort(key=lambda x: -x[2])
    return results


def _shared_source_count(
    conn: duckdb.DuckDBPyConnection,
    slug_a: str,
    slug_b: str,
) -> int:
    """Count sources cited by both pages via claim_sources.

    Prevents single-source co-citation (e.g. two pages both summarise the same
    paper but cover entirely different topics) from flooding the synthesis queue.
    """
    row = conn.execute("""
        SELECT COUNT(DISTINCT cs1.source_id)
        FROM claims c1
        JOIN claim_sources cs1 ON c1.id = cs1.claim_id
        JOIN pages p1 ON c1.page_id = p1.id
        WHERE p1.slug = ?
          AND cs1.source_id IN (
              SELECT cs2.source_id
              FROM claims c2
              JOIN claim_sources cs2 ON c2.id = cs2.claim_id
              JOIN pages p2 ON c2.page_id = p2.id
              WHERE p2.slug = ?
          )
    """, [slug_a, slug_b]).fetchone()
    return row[0] if row else 0


def _coverage_ratio(
    conn: duckdb.DuckDBPyConnection,
    target_slug: str,
    candidate_slug: str,
    dim: int = 768,
) -> float:
    """Fraction of candidate's sections covered by any target section (sim > 0.60)."""
    row = conn.execute(f"""
        SELECT
            COUNT(DISTINCT cs.id)::FLOAT /
            NULLIF((
                SELECT COUNT(*) FROM sections s2
                JOIN pages p2 ON s2.page_id = p2.id
                WHERE p2.slug = ?
            ), 0)
        FROM sections ts
        JOIN pages tp ON ts.page_id = tp.id,
        sections cs
        JOIN pages cp ON cs.page_id = cp.id
        WHERE tp.slug = ? AND cp.slug = ?
          AND ts.embedding IS NOT NULL AND cs.embedding IS NOT NULL
          AND array_inner_product(ts.embedding::FLOAT[{dim}], cs.embedding::FLOAT[{dim}]) > 0.60
    """, [candidate_slug, target_slug, candidate_slug]).fetchone()
    return row[0] or 0.0


# ---------------------------------------------------------------------------
# mark_swept
# ---------------------------------------------------------------------------

def mark_swept(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    cluster: dict | None = None,
    dim: int = 768,
) -> str:
    """Set last_swept = now() on the page; also records swept_semantic_hash and clears
    sweep_lease_expires. If cluster is provided, create or extend a synthesis cluster.

    cluster dict: {"members": [slugs], "label": str, "rationale": str}
    """
    row = conn.execute(
        "SELECT id, last_modified, semantic_hash FROM pages WHERE slug=?", [slug]
    ).fetchone()
    if row is None:
        return f"Page '{slug}' not found — cannot mark swept."
    page_id, last_modified, semantic_hash = row

    conn.execute(
        "UPDATE pages SET last_swept=?, swept_semantic_hash=?, sweep_lease_expires=NULL WHERE id=?",
        [last_modified, semantic_hash, page_id],
    )

    if cluster:
        _upsert_cluster(conn, cluster, dim)
        return f"Swept [[{slug}]]: last_swept set. Cluster '{cluster.get('label', '')}' recorded."

    return f"Swept [[{slug}]]: last_swept set."


def _upsert_cluster(
    conn: duckdb.DuckDBPyConnection,
    cluster: dict,
    dim: int = 768,
) -> None:
    """Create or merge a synthesis cluster.

    If any member slug already belongs to a pending cluster, merge all new
    members into that existing cluster (union-find). Otherwise create a new one.
    """
    members: list[str] = cluster.get("members", [])
    label: str = cluster.get("label", "")
    rationale: str = cluster.get("rationale", "")

    if not members:
        return

    # Find any existing pending cluster that contains a member slug
    existing_cluster_id: int | None = None
    for member_slug in members:
        row = conn.execute("""
            SELECT scm.cluster_id FROM synthesis_cluster_members scm
            JOIN synthesis_clusters sc ON scm.cluster_id = sc.id
            WHERE scm.slug = ? AND sc.status = 'pending'
        """, [member_slug]).fetchone()
        if row:
            existing_cluster_id = row[0]
            break

    # Check if any proposed member is the synthesis_page_slug of a completed cluster
    for member in members:
        row = conn.execute(
            "SELECT id FROM synthesis_clusters WHERE synthesis_page_slug=? AND status='completed'",
            [member],
        ).fetchone()
        if row is not None:
            cluster_id = row[0]
            conn.execute(
                "UPDATE synthesis_clusters SET status='pending', concept_label=?, agent_rationale=?"
                " WHERE id=?",
                [label, rationale, cluster_id],
            )
            for m in members:
                conn.execute(
                    "INSERT INTO synthesis_cluster_members (cluster_id, slug) VALUES (?,?)"
                    " ON CONFLICT DO NOTHING",
                    [cluster_id, m],
                )
            return

    if existing_cluster_id is None:
        conn.execute(
            "INSERT INTO synthesis_clusters (concept_label, agent_rationale, status)"
            " VALUES (?, ?, 'pending')",
            [label, rationale],
        )
        cluster_id = conn.execute(
            "SELECT MAX(id) FROM synthesis_clusters WHERE concept_label=? AND agent_rationale=?",
            [label, rationale],
        ).fetchone()[0]
    else:
        cluster_id = existing_cluster_id
        if label:
            conn.execute(
                "UPDATE synthesis_clusters SET concept_label=?, agent_rationale=? WHERE id=?",
                [label, rationale, cluster_id],
            )

    # Add all new members
    existing_members = {
        row[0] for row in conn.execute(
            "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cluster_id]
        ).fetchall()
    }
    for member_slug in members:
        if member_slug not in existing_members:
            conn.execute(
                "INSERT INTO synthesis_cluster_members (cluster_id, slug) VALUES (?, ?)",
                [cluster_id, member_slug],
            )

    # Compute and store pairwise coverage ratios
    all_member_slugs = [
        row[0] for row in conn.execute(
            "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cluster_id]
        ).fetchall()
    ]
    for i, slug_a in enumerate(all_member_slugs):
        for slug_b in all_member_slugs[i + 1:]:
            ratio = _coverage_ratio(conn, slug_a, slug_b, dim)
            conn.execute(
                "DELETE FROM synthesis_cluster_edges WHERE cluster_id=? AND slug_a=? AND slug_b=?",
                [cluster_id, slug_a, slug_b],
            )
            conn.execute(
                "INSERT INTO synthesis_cluster_edges (cluster_id, slug_a, slug_b, coverage_ratio)"
                " VALUES (?, ?, ?, ?)",
                [cluster_id, slug_a, slug_b, ratio],
            )
