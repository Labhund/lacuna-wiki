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

    # Links out
    links_out = [
        r[0] for r in conn.execute(
            "SELECT target_slug FROM links WHERE source_page_id=? ORDER BY target_slug",
            [page_id],
        ).fetchall()
    ]

    # Links in
    links_in = [
        r[0] for r in conn.execute(
            "SELECT p.slug FROM links l JOIN pages p ON l.source_page_id = p.id"
            " WHERE l.target_slug=? ORDER BY p.slug",
            [slug],
        ).fetchall()
    ]

    # Semantically close sections
    close_sections: list[tuple[str, str, float, int]] = []
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

    # Sources cited on this page
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
        sections=[(s[2], s[4]) for s in sections],
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

    section_parts = [f"{name} ({tok} tok)" for name, tok in sections]
    lines.append("sections on this page:")
    lines.append("  " + " | ".join(section_parts))

    if links_out:
        lines.append(f"links out:  {' | '.join(links_out)}")
    if links_in:
        lines.append(f"links in:   {' | '.join(links_in)}")

    if close_sections:
        lines.append("semantically close sections:")
        for s_slug, s_name, s_score, s_tok in close_sections:
            lines.append(f"  {s_slug} › {s_name}  ({s_score:.2f}, {s_tok} tok)")

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
