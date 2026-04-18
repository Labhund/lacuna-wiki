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


def _daemon_api_url(vault_root) -> str | None:
    """Return the status API base URL if the daemon is running, else None."""
    from lacuna_wiki.daemon.process import is_running, read_pid
    pid = read_pid()
    if pid is None or not is_running(pid):
        return None
    mcp_port = int(load_config(vault_root).get("mcp_port", 7654))
    return f"http://127.0.0.1:{mcp_port + 1}"


def _sweep_counts(conn) -> dict[str, int]:
    """Compute counts for the four sweep rows."""
    gap_rows = conn.execute("""
        SELECT p.id,
               COALESCE((SELECT SUM(s.token_count) FROM sections s WHERE s.page_id = p.id), 0) AS tokens,
               (SELECT COUNT(*) FROM sections s WHERE s.page_id = p.id) AS sec_count
        FROM pages p
    """).fetchall()
    research_gaps = sum(
        1 for _, tokens, sec_count in gap_rows
        if int(tokens * 0.75) < 100 or sec_count < 2
    )
    stub_ids = {
        row[0] for row in gap_rows
        if int(row[1] * 0.75) < 100 or row[2] < 2
    }

    ghost_pages = conn.execute("""
        SELECT COUNT(DISTINCT l.target_slug)
        FROM links l
        LEFT JOIN pages p ON l.target_slug = p.slug
        WHERE p.slug IS NULL
    """).fetchone()[0]

    backlog_rows = conn.execute("""
        SELECT id FROM pages
        WHERE last_swept IS NULL OR last_modified > last_swept
    """).fetchall()
    sweep_backlog = sum(1 for (pid,) in backlog_rows if pid not in stub_ids)

    try:
        synthesis_queue = conn.execute(
            "SELECT COUNT(*) FROM synthesis_clusters WHERE status='pending'"
        ).fetchone()[0]
    except Exception:
        synthesis_queue = 0

    synthesised_pages = conn.execute(
        "SELECT COUNT(*) FROM pages WHERE synthesised_into IS NOT NULL"
    ).fetchone()[0]

    return {
        "research gaps": research_gaps,
        "ghost pages": ghost_pages,
        "sweep backlog": sweep_backlog,
        "synthesis queue": synthesis_queue,
        "synthesised pages": synthesised_pages,
    }


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

    api_url = _daemon_api_url(vault_root)
    if api_url:
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(f"{api_url}/status", timeout=5) as resp:
                data = json.loads(resp.read())
            counts = data["tables"]
            sweep = data["sweep"]
        except Exception as exc:
            console.print(f"[red]Daemon running but status API unreachable:[/red] {exc}")
            sys.exit(1)
    else:
        conn = get_connection(db, readonly=True)
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}
        try:
            sweep = _sweep_counts(conn)
        except Exception:
            sweep = {}
        conn.close()

    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("Table", style="dim")
    tbl.add_column("Rows", justify="right")

    tbl.add_row("pages", str(counts.get("pages", 0)))
    try:
        tbl.add_row("research gaps", str(sweep.get("research gaps", sweep.get("research_gaps", 0))))
        tbl.add_row("ghost pages", str(sweep.get("ghost pages", sweep.get("ghost_pages", 0))))
        tbl.add_row("sweep backlog", str(sweep.get("sweep backlog", sweep.get("sweep_backlog", 0))))
        tbl.add_row("synthesis queue", str(sweep.get("synthesis queue", sweep.get("synthesis_queue", 0))))
        tbl.add_row("synthesised pages", str(sweep.get("synthesised pages", sweep.get("synthesised_pages", 0))))
    except Exception:
        pass

    for t in _TABLES[1:]:
        tbl.add_row(t, str(counts.get(t, 0)))

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
