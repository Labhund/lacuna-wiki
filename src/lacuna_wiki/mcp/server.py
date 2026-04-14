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
    dim: int = 768,
) -> str:
    """Core dispatch logic, separated from MCP transport for testing."""
    provided = sum([q is not None, page is not None, pages is not None])
    if provided != 1:
        raise ValueError("exactly one of q, page, or pages must be provided")

    if q is not None:
        embedding = embed_fn([q])[0]
        hits = hybrid_search(conn, q, embedding, scope=scope, n=10, dim=dim)  # type: ignore[arg-type]
        return format_search_results(hits, q)

    if page is not None:
        try:
            return navigate_page(conn, page, section_name=section, dim=dim)
        except PageNotFoundError:
            return f"Page '{page}' not found in wiki."

    # pages
    return multi_read(conn, pages)  # type: ignore[arg-type]


def make_wiki_tool(conn: duckdb.DuckDBPyConnection, embed_fn: EmbedFn, dim: int = 768) -> None:
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
                             page=page, section=section, pages=pages, dim=dim)
