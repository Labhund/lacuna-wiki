"""lacuna MCP — synthesise operations: cluster_queue, cluster_detail, commit_synthesis."""
from __future__ import annotations

import re
import duckdb

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _label_to_slug(label: str) -> str:
    return _SLUG_RE.sub('-', label.lower()).strip('-')


def _source_diversity(conn: duckdb.DuckDBPyConnection, slugs: list[str]) -> int:
    """Count distinct sources cited across member pages by scanning section content."""
    if not slugs:
        return 0
    placeholders = ','.join('?' * len(slugs))
    row = conn.execute(f"""
        SELECT COUNT(DISTINCT citation)
        FROM (
            SELECT UNNEST(regexp_extract_all(
                content,
                '\\[\\[([a-z0-9][a-z0-9_./ -]*\\.(pdf|md|bib|txt))\\]\\]',
                1
            )) AS citation
            FROM sections s
            JOIN pages p ON s.page_id = p.id
            WHERE p.slug IN ({placeholders})
        )
    """, slugs).fetchone()
    return row[0] if row else 0


def _diversity_note(source_count: int) -> str:
    if source_count == 0:
        return "source diversity: unknown (no source links detected)"
    if source_count == 1:
        return "source diversity: 1 distinct source  ⚠ single-source cluster"
    return f"source diversity: {source_count} distinct sources"


def cluster_queue(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute(
        "SELECT id, concept_label FROM synthesis_clusters WHERE status='pending' ORDER BY id"
    ).fetchall()
    if not rows:
        return "Synthesis queue: 0 pending clusters."

    lines = [f"Synthesis queue: {len(rows)} pending cluster(s).", ""]
    for cid, label in rows:
        members = conn.execute(
            "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cid]
        ).fetchall()
        member_slugs = [m[0] for m in members]
        source_count = _source_diversity(conn, member_slugs)
        lines.append(
            f"  cluster {cid}: \"{label}\" — {len(member_slugs)} members"
            f" — {_diversity_note(source_count)}"
        )
    return "\n".join(lines)


def cluster_detail(conn: duckdb.DuckDBPyConnection, cluster_id: int) -> str:
    row = conn.execute(
        "SELECT concept_label, agent_rationale, status, synthesis_page_slug "
        "FROM synthesis_clusters WHERE id=?",
        [cluster_id],
    ).fetchone()
    if row is None:
        return f"Cluster {cluster_id} not found."

    label, rationale, status, existing_slug = row
    members = conn.execute(
        "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?",
        [cluster_id],
    ).fetchall()
    member_slugs = [m[0] for m in members]

    lines = [
        f"cluster {cluster_id} — \"{label}\"",
        f"status: {status}",
        f"rationale: {rationale or '(none)'}",
        "",
        f"members ({len(member_slugs)}):",
    ]

    for slug in member_slugs:
        page = conn.execute(
            "SELECT title, synthesised_into FROM pages WHERE slug=?", [slug]
        ).fetchone()
        if page:
            title, synth = page
            synth_note = f"  [synthesised into [[{synth}]]]" if synth else ""
            token_count = conn.execute(
                "SELECT COALESCE(SUM(token_count), 0) FROM sections WHERE page_id="
                "(SELECT id FROM pages WHERE slug=?)", [slug]
            ).fetchone()[0]
            approx_words = int(token_count * 0.75)
            lines.append(
                f"  [[{slug}]] — \"{title or slug}\" — ~{approx_words} words{synth_note}"
            )
        else:
            lines.append(f"  [[{slug}]] — (ghost page)")

    source_count = _source_diversity(conn, member_slugs)
    lines.append("")
    lines.append(_diversity_note(source_count))
    lines.append("")
    lines.append(f"suggested slug: {_label_to_slug(label)}")

    if existing_slug:
        lines.append(f"existing synthesis page: [[{existing_slug}]] (revision run)")
    else:
        lines.append("existing synthesis page: none")

    return "\n".join(lines)


def commit_synthesis(
    conn: duckdb.DuckDBPyConnection,
    cluster_id: int,
    slug: str,
) -> str:
    """Mark cluster completed and record synthesis page slug.

    Note: member pages receive their %% synthesised-into %% notice via the agent
    (skill Step 1d), not here. The daemon sets synthesised_into asynchronously on
    next sync. There is a brief window where the cluster is completed but member
    pages still appear in the sweep queue — the skill's step order (notice before
    commit) mitigates this.
    """
    row = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE id=?", [cluster_id]
    ).fetchone()
    if row is None:
        return f"Error: cluster {cluster_id} not found."

    conn.execute(
        "UPDATE synthesis_clusters SET status='completed', synthesis_page_slug=? WHERE id=?",
        [slug, cluster_id],
    )
    return f"Committed: cluster {cluster_id} marked completed. Synthesis page: [[{slug}]]."
