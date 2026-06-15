"""lacuna adversary-commit — batch-write adversary verdicts to DuckDB.

When the daemon is running, delegates via the status API.
Otherwise opens the DB directly.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from lacuna_wiki.vault import db_path, find_vault_root

_VALID_RELS = {"supports", "refutes", "gap"}


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
    """Batch-commit adversary verdicts to DuckDB, delegating to daemon if running."""
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

    from lacuna_wiki.daemon.process import is_running, read_pid
    pid = read_pid()
    if pid and is_running(pid):
        # Daemon running — delegate via API
        from lacuna_wiki.config import load_config
        config = load_config(vault_root)
        mcp_port = int(config.get("mcp_port", 7654))
        api_url = f"http://127.0.0.1:{mcp_port + 1}/adversary-commit"

        body = {
            "verdicts": [{"claim_id": v.claim_id, "rel": v.rel} for v in verdicts],
            "supersessions": [{"old_id": s.old_id, "new_id": s.new_id} for s in supersessions],
        }

        try:
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                api_url, data=data, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            if result.get("status") == "ok":
                n_v = result.get("verdicts", len(verdicts))
                n_s = result.get("supersessions", len(supersessions))
                click.echo(f"Committed {n_v} verdict(s), {n_s} supersession(s).")
            else:
                click.echo(f"Error: {result.get('error', 'unknown')}", err=True)
                sys.exit(1)
        except Exception as exc:
            click.echo(f"Failed to reach daemon API: {exc}", err=True)
            sys.exit(1)
    else:
        # No daemon — direct DB access
        from lacuna_wiki.db.connection import get_connection
        conn = get_connection(db_path(vault_root), readonly=False)
        try:
            write_verdicts(conn, verdicts, supersessions)
        finally:
            conn.close()

        n_v = len(verdicts)
        n_s = len(supersessions)
        click.echo(f"Committed {n_v} verdict(s), {n_s} supersession(s).")
