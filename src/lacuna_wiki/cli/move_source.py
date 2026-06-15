"""lacuna move-source — relocate a registered source to a concept directory.

Moves files on disk only. The daemon's watchdog picks up the move event
and updates sources.path in the DB — no DuckDB connection needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.vault import find_vault_root

console = Console()


@click.command("move-source")
@click.argument("slug")
@click.option("--concept", required=True,
              help="Target concept path within raw/ (e.g. machine-learning/attention)")
@click.option("--vault", "vault_path", default=None,
              help="Vault root (default: auto-detect from cwd)")
def move_source(slug: str, concept: str, vault_path: str | None) -> None:
    """Move all files for SLUG to raw/CONCEPT/. Daemon updates DB on next sync."""
    if vault_path:
        vault_root = Path(vault_path)
    else:
        vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    raw_dir = vault_root / "raw"

    # Find all files matching the slug anywhere under raw/
    matches: list[Path] = []
    for f in raw_dir.rglob(f"{slug}.*"):
        # Skip files in the target directory (already there)
        try:
            rel = f.relative_to(raw_dir)
        except ValueError:
            continue
        if str(rel.parent) == concept:
            continue
        matches.append(f)

    if not matches:
        # Try case-insensitive match as fallback
        for f in raw_dir.rglob("*"):
            if f.is_file() and f.stem.lower() == slug.lower():
                try:
                    rel = f.relative_to(raw_dir)
                except ValueError:
                    continue
                if str(rel.parent) == concept:
                    continue
                matches.append(f)

    if not matches:
        console.print(f"[red]No files found for slug '{slug}' under raw/.[/red]")
        sys.exit(1)

    target_dir = raw_dir / concept
    target_dir.mkdir(parents=True, exist_ok=True)

    # Pre-check: abort if any target already exists
    for f in matches:
        dest = target_dir / f.name
        if dest.exists():
            console.print(f"[red]Target already exists: {dest.relative_to(vault_root)}[/red]")
            sys.exit(1)

    # Move all files
    for f in matches:
        dest = target_dir / f.name
        f.rename(dest)

    console.print(f"  [green]✓[/green] {slug} → raw/{concept}/")
    console.print(f"  {len(matches)} file(s) moved. Daemon will update DB path on next sync.")
