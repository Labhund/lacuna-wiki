"""lacuna move-source — relocate a registered source to a concept directory."""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.db.connection import get_connection
from lacuna_wiki.vault import db_path, find_vault_root

console = Console()


@click.command("move-source")
@click.argument("slug")
@click.option("--concept", required=True,
              help="Target concept path within raw/ (e.g. machine-learning/attention)")
@click.option("--vault", "vault_path", default=None,
              help="Vault root (default: auto-detect from cwd)")
def move_source(slug: str, concept: str, vault_path: str | None) -> None:
    """Move all files for SLUG to raw/CONCEPT/ and update the DB path."""
    if vault_path:
        vault_root = Path(vault_path)
    else:
        vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    conn = get_connection(db_path(vault_root))

    row = conn.execute("SELECT path FROM sources WHERE slug=?", [slug]).fetchone()
    if row is None:
        console.print(f"[red]Source '{slug}' not found in DB.[/red]")
        conn.close()
        sys.exit(1)

    current_rel = Path(row[0])          # e.g. raw/hay2026wedon.md
    current_dir = vault_root / current_rel.parent
    target_dir = vault_root / "raw" / concept
    target_dir.mkdir(parents=True, exist_ok=True)

    # Find all files sharing the slug stem in current directory
    files_to_move = list(current_dir.glob(f"{slug}.*"))
    if not files_to_move:
        console.print(f"[red]No files found for slug '{slug}' in {current_dir}.[/red]")
        conn.close()
        sys.exit(1)

    # Pre-check: abort if any target already exists
    for f in files_to_move:
        dest = target_dir / f.name
        if dest.exists():
            console.print(f"[red]Target already exists: {dest.relative_to(vault_root)}[/red]")
            conn.close()
            sys.exit(1)

    # Move all files
    for f in files_to_move:
        f.rename(target_dir / f.name)

    # Update DB: path uses the primary file's extension
    new_rel = (Path("raw") / concept / f"{slug}{current_rel.suffix}").as_posix()
    conn.execute("UPDATE sources SET path=? WHERE slug=?", [new_rel, slug])
    conn.close()

    console.print(f"  [green]✓[/green] {slug} → raw/{concept}/")
    console.print(f"  Path: {new_rel}")
