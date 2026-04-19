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
    sweep: "str | None" = None,
    mark_swept: bool = False,
    cluster: dict | None = None,
    synthesise: "bool | int | str | None" = None,
    commit: dict | None = None,
    limit: "int | None" = None,
    dim: int = 768,
    vault_root: "Path | None" = None,
) -> str:
    """Core dispatch logic, separated from MCP transport for testing."""
    # Normalise string "true"/"false" sent by agents that don't coerce JSON booleans
    if isinstance(link_audit, str) and link_audit.lower() == "true":
        link_audit = True
    elif isinstance(link_audit, str) and link_audit.lower() == "false":
        link_audit = None

    if isinstance(synthesise, str) and synthesise.lower() == "true":
        synthesise = True
    elif isinstance(synthesise, str) and synthesise.lower() == "false":
        synthesise = None
    elif isinstance(synthesise, str) and synthesise.isdigit():
        synthesise = int(synthesise)

    # `sweep="slug"` is the preferred per-page alias; fold into link_audit for dispatch
    if sweep is not None:
        if link_audit is not None:
            return "Error: sweep and link_audit are mutually exclusive."
        link_audit = sweep

    # Mutual exclusion guard
    if synthesise is not None and link_audit is not None:
        return "Error: synthesise and link_audit are mutually exclusive."

    # synthesise mode
    if synthesise is not None:
        from lacuna_wiki.mcp.synthesise import (
            cluster_queue,
            cluster_detail,
            commit_synthesis,
        )
        if synthesise is True:
            return cluster_queue(conn)
        cluster_id = int(synthesise)
        if commit:
            return commit_synthesis(conn, cluster_id, commit["slug"], vault_root=vault_root)
        return cluster_detail(conn, cluster_id)

    # link_audit / sweep mode
    if link_audit is not None:
        from lacuna_wiki.mcp.audit import (
            vault_audit,
            page_audit,
            mark_swept as do_mark_swept,
        )
        if link_audit is True:
            if mark_swept:
                return "Error: mark_swept requires a page slug. Use sweep='slug' or link_audit='slug', not link_audit=True."
            return vault_audit(conn, limit=limit)

        # link_audit is a slug string
        slug = str(link_audit)
        if mark_swept:
            return do_mark_swept(conn, slug, cluster=cluster, dim=dim)
        return page_audit(conn, slug, embed_fn, dim=dim, vault_root=vault_root)

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
    vault_root: "Path | None" = None,
) -> None:
    """Register the wiki tool on mcp_app.

    Pass a ConnectionPool (daemon mode — per-call acquire/release so pool
    close/reopen during initial_sync or SIGUSR1 pause never breaks in-flight
    requests), a Path (stdio mode — ephemeral per-call connections), or a
    pre-opened DuckDBPyConnection (legacy/test — shared, not pool-managed).
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
        sweep: "str | None" = None,
        mark_swept: bool = False,
        cluster: dict | None = None,
        synthesise: "bool | int | str | None" = None,
        commit: dict | None = None,
        limit: "int | None" = None,
    ) -> str:
        """Search the wiki or navigate to a page.

        Search: provide `q` (query text). Optional `scope`: "wiki" (default),
        "sources" (raw source chunks), or "all".

        Navigate: provide `page` (slug). Optional `section` (section name).

        Multi-read: provide `pages` (list of slugs).

        Vault audit: provide `link_audit=True`. Use `limit=N` to get only the top N
        sweep queue entries with summary counts for gaps/ghosts (recommended for large
        vaults — call again after each batch).

        Per-page sweep: provide `sweep="page-slug"` to audit a single page (unlinked
        candidates + synthesis candidates). Add `mark_swept=True` to mark it swept.
        Optionally include `cluster={"members": [...], "label": "...", "rationale":
        "..."}` to create or extend a synthesis cluster.

        Synthesise: provide `synthesise=True` for cluster queue. `synthesise=N` for
        cluster detail. `synthesise=N` with `commit={"slug": "..."}` to mark complete.
        """
        # Detect ConnectionPool by duck-typing (avoids circular import)
        if hasattr(conn_or_path, "acquire") and hasattr(conn_or_path, "release"):
            try:
                conn = conn_or_path.acquire(timeout=30)
            except TimeoutError:
                return "Daemon is still initializing (initial sync in progress). Please retry in a moment."
            try:
                return dispatch_wiki(conn, embed_fn, q=q, scope=scope,
                                     page=page, section=section, pages=pages,
                                     link_audit=link_audit, sweep=sweep,
                                     mark_swept=mark_swept, cluster=cluster,
                                     synthesise=synthesise, commit=commit,
                                     limit=limit, dim=dim, vault_root=vault_root)
            finally:
                conn_or_path.release(conn)
        elif isinstance(conn_or_path, Path):
            conn = get_connection(conn_or_path, readonly=False)
            try:
                return dispatch_wiki(conn, embed_fn, q=q, scope=scope,
                                     page=page, section=section, pages=pages,
                                     link_audit=link_audit, sweep=sweep,
                                     mark_swept=mark_swept, cluster=cluster,
                                     synthesise=synthesise, commit=commit,
                                     limit=limit, dim=dim, vault_root=vault_root)
            finally:
                conn.close()
        else:
            return dispatch_wiki(conn_or_path, embed_fn, q=q, scope=scope,
                                 page=page, section=section, pages=pages,
                                 link_audit=link_audit, sweep=sweep,
                                 mark_swept=mark_swept, cluster=cluster,
                                 synthesise=synthesise, commit=commit,
                                 limit=limit, dim=dim, vault_root=vault_root)
