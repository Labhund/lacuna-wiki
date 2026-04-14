"""lacuna mcp — start the MCP server (stdio transport)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from lacuna_wiki.vault import db_path, find_vault_root


@click.command("mcp")
def mcp_command() -> None:
    """Start the MCP server (stdio transport, standalone/testing use).

    For normal use, start the daemon instead — it runs the MCP server on SSE
    alongside the watchdog in one process, avoiding DuckDB lock contention.
    """
    vault_env = os.environ.get("LACUNA_VAULT")
    if vault_env:
        vault_root = Path(vault_env)
    else:
        vault_root = find_vault_root()

    if vault_root is None:
        click.echo("LACUNA_VAULT not set and not inside an lacuna vault.", err=True)
        sys.exit(1)

    db = db_path(vault_root)
    if not db.exists():
        click.echo(f"Database not found at {db}. Run lacuna init first.", err=True)
        sys.exit(1)

    from functools import partial

    from lacuna_wiki.config import load_config
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.mcp.server import make_wiki_tool, mcp_app
    from lacuna_wiki.sources.embedder import embed_texts

    config = load_config(vault_root)

    from lacuna_wiki.cli._warn import warn_embed_unreachable
    from lacuna_wiki.sources.embedder import check_embed_server
    check = check_embed_server(config["embed_url"], config["embed_model"])
    if not check.ok:
        warn_embed_unreachable(check.url, check.model, check.error)
        click.echo("Semantic search will be unavailable. BM25 only.", err=True)

    embed_fn = partial(embed_texts, url=config["embed_url"], model=config["embed_model"])
    conn = get_connection(db, readonly=True)
    make_wiki_tool(conn, embed_fn, dim=config["embed_dim"])
    mcp_app.run(transport="stdio")
