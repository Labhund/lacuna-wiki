from __future__ import annotations

from pathlib import Path
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
    link_audit: "bool | str | None" = None,
    mark_swept: bool = False,
    cluster: dict | None = None,
    dim: int = 768,
) -> str:
    """Core dispatch logic, separated from MCP transport for testing."""
    # link_audit mode
    if link_audit is not None:
        from lacuna_wiki.mcp.audit import (
            vault_audit,
            page_audit,
            mark_swept as do_mark_swept,
        )
        if link_audit is True:
            if mark_swept:
                return "Error: mark_swept requires link_audit to be a page slug, not True."
            return vault_audit(conn)

        # link_audit is a slug string
        slug = str(link_audit)
        if mark_swept:
            return do_mark_swept(conn, slug, cluster=cluster, dim=dim)
        return page_audit(conn, slug, embed_fn, dim=dim)

    # Normal wiki modes
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


def make_wiki_tool(
    conn_or_path: "duckdb.DuckDBPyConnection | Path",
    embed_fn: EmbedFn,
    dim: int = 768,
) -> None:
    """Register the wiki tool on mcp_app.

    Pass a pre-opened DuckDBPyConnection (daemon mode — shared within one
    process) or a Path to the database file (stdio mode — ephemeral per-call
    connections so the write lock is never held between requests).
    """
    from lacuna_wiki.db.connection import get_connection

    @mcp_app.tool()
    def wiki(
        q: str | None = None,
        scope: str = "wiki",
        page: str | None = None,
        section: str | None = None,
        pages: list[str] | None = None,
        link_audit: "bool | str | None" = None,
        mark_swept: bool = False,
        cluster: dict | None = None,
    ) -> str:
        """Search the wiki or navigate to a page.

        Search: provide `q` (query text). Optional `scope`: "wiki" (default),
        "sources" (raw source chunks), or "all".

        Navigate: provide `page` (slug). Optional `section` (section name).

        Multi-read: provide `pages` (list of slugs).

        Audit: provide `link_audit=True` for full vault audit (research gaps, ghost
        pages, sweep queue). Provide `link_audit="slug"` for single-page audit
        (unlinked candidates + synthesis candidates).

        Sweep commit: provide `link_audit="slug"` and `mark_swept=True` to mark the
        page swept. Optionally include `cluster={"members": [...], "label": "...",
        "rationale": "..."}` to create or extend a synthesis cluster.
        """
        if isinstance(conn_or_path, Path):
            # Read-write connection — mark_swept writes to DB
            conn = get_connection(conn_or_path, readonly=False)
            try:
                return dispatch_wiki(conn, embed_fn, q=q, scope=scope,
                                     page=page, section=section, pages=pages,
                                     link_audit=link_audit, mark_swept=mark_swept,
                                     cluster=cluster, dim=dim)
            finally:
                conn.close()
        else:
            return dispatch_wiki(conn_or_path, embed_fn, q=q, scope=scope,
                                 page=page, section=section, pages=pages,
                                 link_audit=link_audit, mark_swept=mark_swept,
                                 cluster=cluster, dim=dim)
