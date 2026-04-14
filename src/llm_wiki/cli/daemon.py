"""llm-wiki start / stop — daemon lifecycle commands.

Stubs only. Full implementation in Plan 3 (Daemon).
"""
from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.command()
def start() -> None:
    """Start the file-watcher daemon."""
    console.print("[yellow]Daemon not yet implemented (Plan 3).[/yellow]")


@click.command()
def stop() -> None:
    """Stop the file-watcher daemon."""
    console.print("[yellow]Daemon not yet implemented (Plan 3).[/yellow]")
