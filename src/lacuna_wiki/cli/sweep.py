"""lacuna sweep — pre-compute unlinked/synthesis candidates for the sweep skill."""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.vault import db_path, find_vault_root

console = Console()


def _run_sweep_locally(vault_root: Path, batch: int | None, force: bool) -> None:
    """Run sweep pre-computation directly (no daemon running)."""
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.db.schema import init_db
    from lacuna_wiki.mcp.audit import precompute_unlinked_candidates

    db = db_path(vault_root)
    conn = get_connection(db)
    init_db(conn)

    if force:
        rows = conn.execute("SELECT id FROM pages").fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM pages WHERE last_swept IS NULL OR last_modified > last_swept"
        ).fetchall()

    if batch is not None:
        rows = rows[:batch]

    if not rows:
        console.print("[green]Sweep queue is empty — nothing to pre-compute.[/green]")
        conn.close()
        return

    page_ids = [r[0] for r in rows]
    console.print(f"Pre-computing candidates for [bold]{len(page_ids)}[/bold] pages...")

    precompute_unlinked_candidates(conn, vault_root, page_ids=page_ids)

    console.print(f"[green]✓[/green] Done. {len(page_ids)} pages pre-computed.")
    conn.close()


def _run_sweep_via_daemon(vault_root: Path) -> None:
    """Submit sweep job to daemon and poll until complete."""
    import json
    import time
    import urllib.request
    from lacuna_wiki.config import load_config

    config = load_config(vault_root)
    mcp_port = int(config.get("mcp_port", 7654))
    api_base = f"http://127.0.0.1:{mcp_port + 1}"

    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{api_base}/sweep", method="POST"),
            timeout=5,
        )
    except Exception as exc:
        console.print(f"[red]Failed to submit sweep job to daemon:[/red] {exc}")
        sys.exit(1)

    console.print("Sweep job submitted. Polling for completion...")
    while True:
        try:
            with urllib.request.urlopen(f"{api_base}/sweep/status", timeout=5) as resp:
                state = json.loads(resp.read())
        except Exception:
            time.sleep(1)
            continue

        done = state.get("done", 0)
        total = state.get("total", 0)
        running = state.get("running", True)

        if total > 0:
            console.print(f"\r[{done}/{total}] pages pre-computed", end="")

        if not running and total > 0 and done >= total:
            console.print(f"\n[green]✓[/green] Sweep complete. {done} pages pre-computed.")
            break

        time.sleep(0.5)


@click.command()
@click.option("--batch", default=None, type=int,
              help="Process next N pages from queue. Default: all.")
@click.option("--force", is_flag=True, default=False,
              help="Recompute all pages regardless of last_swept.")
def sweep(batch: int | None, force: bool) -> None:
    """Pre-compute unlinked/synthesis candidates for the sweep skill.

    Run this after a large ingest to pre-warm the candidate cache so
    the sweep skill does not time out.
    """
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    from lacuna_wiki.daemon.process import is_running, read_pid
    pid = read_pid()
    if pid and is_running(pid):
        _run_sweep_via_daemon(vault_root)
    else:
        _run_sweep_locally(vault_root, batch=batch, force=force)
