from __future__ import annotations

from lacuna_wiki.mcp.search import SearchHit

_PASSAGE_MAX = 300


def extract_passage(content: str, query: str, max_chars: int = _PASSAGE_MAX) -> str:
    """Extract a relevant passage from content centered around the first query term."""
    first_term = query.strip().split()[0] if query.strip() else ""
    idx = content.lower().find(first_term.lower()) if first_term else -1

    if idx == -1:
        snippet = content[:max_chars]
        return snippet + ("..." if len(content) > max_chars else "")

    start = max(0, idx - max_chars // 3)
    end = min(len(content), start + max_chars)
    passage = content[start:end].strip()
    if start > 0:
        passage = "..." + passage
    if end < len(content):
        passage = passage + "..."
    return passage


def format_search_results(hits: list[SearchHit], query: str) -> str:
    """Format search hits into a readable string for MCP tool output."""
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
