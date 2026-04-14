"""lacuna status — vault health report."""
from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from lacuna_wiki.config import load_config
from lacuna_wiki.db.connection import get_connection
from lacuna_wiki.vault import db_path, find_vault_root

console = Console()

_TABLES = ["pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"]


@click.command()
def status() -> None:
    """Show vault status and table row counts."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red] "
                      "(No directory with both wiki/ and raw/ found.)")
        sys.exit(1)

    db = db_path(vault_root)
    if not db.exists():
        console.print(f"[red]Vault found at {vault_root} but database missing.[/red] "
                      "Run [bold]lacuna sync[/bold] to rebuild.")
        sys.exit(1)

    conn = get_connection(db, readonly=True)

    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("Table", style="dim")
    tbl.add_column("Rows", justify="right")

    for t in _TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tbl.add_row(t, str(count))

    conn.close()

    config = load_config(vault_root)
    from lacuna_wiki.sources.embedder import check_embed_server
    embed_check = check_embed_server(config["embed_url"], config["embed_model"])
    embed_status = (
        f"[green]✓ {embed_check.url}[/green]  ({embed_check.model})"
        if embed_check.ok
        else f"[bold red]✗ unreachable — {embed_check.url}[/bold red]"
    )

    console.print(f"\n[bold]lacuna status[/bold]")
    console.print(f"  Vault:    {vault_root}")
    console.print(f"  Database: {db}")
    console.print(f"  Embed:    {embed_status}\n")
    console.print(tbl)

    if not embed_check.ok:
        from lacuna_wiki.cli._warn import warn_embed_unreachable
        console.print()
        warn_embed_unreachable(embed_check.url, embed_check.model, embed_check.error)

    console.print()
