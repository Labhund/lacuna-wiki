"""Shared CLI warning helpers."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

console = Console(stderr=True)


def warn_embed_unreachable(url: str, model: str, error: str) -> None:
    """Print a loud, unmissable warning when the embedding server is unreachable."""
    console.print(Panel(
        f"[bold red]Embedding server unreachable[/bold red]\n\n"
        f"  [yellow]URL:[/yellow]   {url}\n"
        f"  [yellow]Model:[/yellow] {model}\n\n"
        f"  [dim]{error}[/dim]\n\n"
        f"[bold]To fix:[/bold] start Ollama and pull the model:\n"
        f"  [green]ollama serve[/green]\n"
        f"  [green]ollama pull {model}[/green]\n\n"
        f"Or update [bold]embed.url[/bold] in your vault's [bold].lacuna.toml[/bold].",
        title="[bold red]⚠  WARNING[/bold red]",
        border_style="red",
    ))
