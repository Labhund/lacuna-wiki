"""llm-wiki status — vault health report."""
from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from llm_wiki.db.connection import get_connection
from llm_wiki.vault import db_path, find_vault_root

console = Console()

_TABLES = ["pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"]


@click.command()
def status() -> None:
    """Show vault status and table row counts."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an llm-wiki vault.[/red] "
                      "(No directory with both wiki/ and raw/ found.)")
        sys.exit(1)

    db = db_path(vault_root)
    if not db.exists():
        console.print(f"[red]Vault found at {vault_root} but database missing.[/red] "
                      "Run [bold]llm-wiki sync[/bold] to rebuild.")
        sys.exit(1)

    conn = get_connection(db, readonly=True)

    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("Table", style="dim")
    tbl.add_column("Rows", justify="right")

    for t in _TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tbl.add_row(t, str(count))

    conn.close()

    console.print(f"\n[bold]llm-wiki status[/bold]")
    console.print(f"  Vault:    {vault_root}")
    console.print(f"  Database: {db}\n")
    console.print(tbl)
    console.print()
