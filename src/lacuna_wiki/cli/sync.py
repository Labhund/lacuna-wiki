"""lacuna sync — one-shot full sync of wiki/ to the DB.

When the daemon is running, delegates to it via the status API.
Otherwise falls back to direct DB access.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from functools import partial
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.vault import find_vault_root

console = Console()


@click.command("sync")
def sync() -> None:
    """Re-sync all wiki pages to the DB.

    When the daemon is running, delegates via API (no lock contention).
    When not running, opens the DB directly.
    """
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    from lacuna_wiki.daemon.process import is_running, read_pid
    pid = read_pid()
    if pid and is_running(pid):
        # Daemon running — delegate via API
        from lacuna_wiki.config import load_config
        config = load_config(vault_root)
        mcp_port = int(config.get("mcp_port", 7654))
        api_url = f"http://127.0.0.1:{mcp_port + 1}/sync"

        try:
            req = urllib.request.Request(api_url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("status") == "ok":
                console.print("  [green]✓[/green] Sync triggered via daemon")
            else:
                console.print(f"[red]Sync failed:[/red] {result.get('error', 'unknown')}")
                sys.exit(1)
        except Exception as exc:
            console.print(f"[red]Failed to reach daemon API:[/red] {exc}")
            sys.exit(1)
    else:
        # No daemon — direct DB access
        from lacuna_wiki.cli._warn import warn_embed_unreachable
        from lacuna_wiki.config import load_config
        from lacuna_wiki.db.connection import get_connection
        from lacuna_wiki.db.schema import init_db
        from lacuna_wiki.daemon.watcher import initial_sync
        from lacuna_wiki.sources.embedder import check_embed_server, embed_texts
        from lacuna_wiki.vault import db_path

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
