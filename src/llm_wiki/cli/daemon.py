"""llm-wiki start / stop — daemon lifecycle commands."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console

from llm_wiki.daemon.process import (
    _LOG_FILE, _PID_FILE, is_running, read_pid,
)
from llm_wiki.vault import find_vault_root

console = Console()

_STARTUP_TIMEOUT = 5.0
_POLL_INTERVAL = 0.2


@click.command()
def start() -> None:
    """Start the file-watcher daemon."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an llm-wiki vault.[/red]")
        sys.exit(1)

    pid = read_pid()
    if pid and is_running(pid):
        console.print(f"[yellow]Daemon already running (PID {pid}).[/yellow]")
        return

    if _PID_FILE.exists():
        _PID_FILE.unlink()

    llm_wiki_bin = Path(sys.executable).parent / "llm-wiki"
    if not llm_wiki_bin.exists():
        import shutil
        found = shutil.which("llm-wiki")
        if not found:
            console.print("[red]Cannot find llm-wiki executable.[/red]")
            sys.exit(1)
        llm_wiki_bin = Path(found)

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_FILE, "w") as log:
        subprocess.Popen(
            [str(llm_wiki_bin), "_daemon-run", str(vault_root)],
            start_new_session=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
        pid = read_pid()
        if pid and is_running(pid):
            console.print(f"[green]✓[/green] Daemon started (PID {pid})")
            console.print(f"  Watching: {vault_root / 'wiki'}")
            console.print(f"  Log:      {_LOG_FILE}")
            return

    console.print(f"[red]Daemon failed to start.[/red] Check {_LOG_FILE}")
    sys.exit(1)


@click.command()
def stop() -> None:
    """Stop the file-watcher daemon."""
    pid = read_pid()
    if pid is None:
        console.print("[yellow]No daemon PID file found — daemon may not be running.[/yellow]")
        return

    if not is_running(pid):
        console.print(f"[yellow]Daemon (PID {pid}) is not running. Cleaning up stale PID file.[/yellow]")
        _PID_FILE.unlink(missing_ok=True)
        return

    os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if not is_running(pid):
            console.print(f"[green]✓[/green] Daemon (PID {pid}) stopped.")
            return

    console.print(f"[red]Daemon (PID {pid}) did not exit within 5 seconds.[/red]")
    sys.exit(1)


@click.command("_daemon-run", hidden=True)
@click.argument("vault_path")
def daemon_run(vault_path: str) -> None:
    """Internal: run daemon process. Called by `llm-wiki start`."""
    from llm_wiki.daemon.process import run_daemon
    run_daemon(Path(vault_path))
