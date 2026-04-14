"""lacuna adversary-commit — batch-write adversary verdicts to DuckDB.

Pauses the daemon while it holds the RW connection, writes all verdicts,
then signals the daemon to resume.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from lacuna_wiki.vault import db_path, find_vault_root, state_dir_for

_VALID_RELS = {"supports", "refutes", "gap"}
_PAUSE_TIMEOUT = 10.0


@dataclass(frozen=True)
class Verdict:
    claim_id: int
    rel: str


@dataclass(frozen=True)
class Supersession:
    old_id: int
    new_id: int


def parse_verdict(s: str) -> Verdict:
    """Parse "claim_id=N,rel=VALUE" into a Verdict."""
    try:
        parts = dict(kv.split("=", 1) for kv in s.split(","))
        claim_id = int(parts["claim_id"])
        rel = parts["rel"]
    except (KeyError, ValueError) as e:
        raise ValueError(f"Bad verdict {s!r}: expected 'claim_id=N,rel=VALUE'") from e
    if rel not in _VALID_RELS:
        raise ValueError(f"rel must be one of {sorted(_VALID_RELS)!r}, got {rel!r}")
    return Verdict(claim_id=claim_id, rel=rel)


def parse_supersession(s: str) -> Supersession:
    """Parse "old=N,new=M" into a Supersession."""
    try:
        parts = dict(kv.split("=", 1) for kv in s.split(","))
        return Supersession(old_id=int(parts["old"]), new_id=int(parts["new"]))
    except (KeyError, ValueError) as e:
        raise ValueError(f"Bad supersession {s!r}: expected 'old=N,new=M'") from e


def write_verdicts(
    conn,
    verdicts: list[Verdict],
    supersessions: list[Supersession],
) -> None:
    """Write all verdicts and supersessions. Caller holds the RW connection."""
    now = datetime.now(tz=timezone.utc)
    for v in verdicts:
        conn.execute(
            "UPDATE claim_sources SET relationship=?, checked_at=? WHERE claim_id=?",
            [v.rel, now, v.claim_id],
        )
        conn.execute(
            "UPDATE claims SET last_adversary_check=? WHERE id=?",
            [now, v.claim_id],
        )
    for s in supersessions:
        conn.execute(
            "UPDATE claims SET superseded_by=? WHERE id=?",
            [s.new_id, s.old_id],
        )


@click.command("adversary-commit")
@click.option(
    "--verdict", "verdict_strs", multiple=True,
    metavar="claim_id=N,rel=VALUE",
    help="Verdict to commit. Repeat for multiple.",
)
@click.option(
    "--supersede", "supersede_strs", multiple=True,
    metavar="old=N,new=M",
    help="Supersession to record. Repeat for multiple.",
)
def adversary_commit(verdict_strs: tuple[str, ...], supersede_strs: tuple[str, ...]) -> None:
    """Batch-commit adversary verdicts to DuckDB, pausing the daemon if running."""
    if not verdict_strs and not supersede_strs:
        click.echo("Nothing to commit — provide --verdict or --supersede.", err=True)
        sys.exit(1)

    # Parse arguments
    verdicts: list[Verdict] = []
    for s in verdict_strs:
        try:
            verdicts.append(parse_verdict(s))
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)

    supersessions: list[Supersession] = []
    for s in supersede_strs:
        try:
            supersessions.append(parse_supersession(s))
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)

    # Resolve vault
    vault_root = find_vault_root()
    if vault_root is None:
        click.echo("Not inside an lacuna vault.", err=True)
        sys.exit(1)

    db = db_path(vault_root)
    pause_ack = state_dir_for(vault_root) / "daemon.paused"

    # Pause daemon if running
    from lacuna_wiki.daemon.process import is_running, read_pid
    pid = read_pid()
    daemon_running = pid is not None and is_running(pid)

    if daemon_running:
        os.kill(pid, signal.SIGUSR1)
        deadline = time.monotonic() + _PAUSE_TIMEOUT
        while not pause_ack.exists():
            if time.monotonic() > deadline:
                click.echo(
                    f"Daemon (PID {pid}) did not pause within {_PAUSE_TIMEOUT:.0f}s.",
                    err=True,
                )
                sys.exit(1)
            time.sleep(0.05)

    # Write verdicts with RW connection
    from lacuna_wiki.db.connection import get_connection
    conn = get_connection(db, readonly=False)
    try:
        write_verdicts(conn, verdicts, supersessions)
    finally:
        conn.close()
        if daemon_running:
            pause_ack.unlink(missing_ok=True)  # signal daemon to resume

    n_v = len(verdicts)
    n_s = len(supersessions)
    click.echo(f"Committed {n_v} verdict(s), {n_s} supersession(s).")
