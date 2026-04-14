"""llm-wiki init — vault setup wizard."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
from rich.console import Console

from llm_wiki.db.connection import get_connection
from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for

console = Console()


@click.command()
@click.argument("path", default=".", type=click.Path())
def init(path: str) -> None:
    """Initialise a new llm-wiki vault at PATH (default: current directory)."""
    vault_root = Path(path).resolve()

    console.print("\n[bold]llm-wiki v2 — vault setup[/bold]\n")
    console.print(f"  Initialising vault at [bold]{vault_root}[/bold]\n")

    if not vault_root.exists():
        vault_root.mkdir(parents=True)

    # Directory structure
    (vault_root / "wiki").mkdir(exist_ok=True)
    (vault_root / "raw").mkdir(exist_ok=True)
    console.print("  [green]✓[/green] wiki/ and raw/ ready")

    # git init
    if not (vault_root / ".git").exists():
        subprocess.run(
            ["git", "init", str(vault_root)],
            check=True,
            capture_output=True,
        )
        console.print("  [green]✓[/green] git repository initialised")
    else:
        console.print("  [dim]→ git already initialised[/dim]")

    # .gitignore
    gitignore = vault_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# llm-wiki database lives in ~/.llm-wiki/vaults/ — not in the vault itself\n"
        )

    # Database
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    db = db_path(vault_root)
    conn = get_connection(db)
    init_db(conn)
    conn.close()
    console.print(f"  [green]✓[/green] database ready at {db}")

    # MCP configuration
    _offer_mcp_config(vault_root)

    # Initial commit (best-effort; skip if nothing to commit)
    subprocess.run(
        ["git", "-C", str(vault_root), "add", ".gitignore"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(vault_root), "commit", "-m", "chore: initialise llm-wiki vault"],
        capture_output=True,
    )

    console.print(
        f"\n[bold green]Vault ready.[/bold green]  "
        f"Run [bold]llm-wiki status[/bold] to confirm.\n"
    )


def _offer_mcp_config(vault_root: Path) -> None:
    """Offer to wire the MCP server into the user's harness configs."""
    console.print("\n[bold]MCP configuration[/bold]")

    if click.confirm("  Wire into Claude Code (~/.claude/mcp.json)?", default=True):
        _merge_claude_code_mcp(Path.home() / ".claude" / "mcp.json", vault_root)
        console.print("  [green]✓[/green] Claude Code MCP config updated")

    hermes_config = Path.home() / ".hermes" / "config.yaml"
    if hermes_config.exists():
        if click.confirm("  Wire into Hermes (~/.hermes/config.yaml)?", default=True):
            _merge_hermes_mcp(hermes_config, vault_root)
            console.print("  [green]✓[/green] Hermes MCP config updated")


def _merge_claude_code_mcp(mcp_path: Path, vault_root: Path) -> None:
    """Add llm-wiki MCP server entry to Claude Code's mcp.json."""
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if mcp_path.exists():
        data = json.loads(mcp_path.read_text())
    data.setdefault("mcpServers", {})
    data["mcpServers"]["llm-wiki"] = {
        "command": "llm-wiki",
        "args": ["mcp"],
        "env": {"LLM_WIKI_VAULT": str(vault_root)},
        "timeout": 120,
        "connect_timeout": 30,
    }
    mcp_path.write_text(json.dumps(data, indent=2) + "\n")


def _merge_hermes_mcp(config_path: Path, vault_root: Path) -> None:
    """Add llm-wiki MCP server block to Hermes config.yaml."""
    import yaml
    data: dict = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text()) or {}
    data.setdefault("mcp_servers", {})
    data["mcp_servers"]["llm-wiki"] = {
        "command": "llm-wiki",
        "args": ["mcp"],
        "env": {"LLM_WIKI_VAULT": str(vault_root)},
        "timeout": 120,
        "connect_timeout": 30,
    }
    config_path.write_text(yaml.dump(data, default_flow_style=False))
