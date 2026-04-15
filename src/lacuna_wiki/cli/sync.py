"""lacuna sync — one-shot full sync of wiki/ to the DB."""
from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.config import load_config
from lacuna_wiki.db.connection import get_connection
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, find_vault_root

console = Console()


@click.command("sync")
def sync() -> None:
    """Re-sync all wiki pages to the DB (no daemon required).

    Useful after bulk file operations (moving pages between clusters,
    renaming files) when the daemon is not running.
    """
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    from lacuna_wiki.cli._warn import warn_embed_unreachable
    from lacuna_wiki.sources.embedder import check_embed_server, embed_texts
    from lacuna_wiki.daemon.watcher import initial_sync

    config = load_config(vault_root)
    check = check_embed_server(config["embed_url"], config["embed_model"])
    if not check.ok:
        warn_embed_unreachable(check.url, check.model, check.error)
        console.print("[bold red]Aborting sync — embeddings cannot be generated.[/bold red]")
        sys.exit(1)

    embed_fn = partial(embed_texts, url=config["embed_url"], model=config["embed_model"])

    conn = get_connection(db_path(vault_root))
    init_db(conn, dim=config["embed_dim"])

    wiki_dir = vault_root / "wiki"
    pages = sorted(wiki_dir.rglob("*.md"))
    console.print(f"  Syncing {len(pages)} pages...")
    initial_sync(conn, vault_root, embed_fn)
    conn.close()
    console.print(f"  [green]✓[/green] Sync complete")
