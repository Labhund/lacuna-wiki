# Adversary Commit CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `adversary-commit` CLI command that batch-writes claim relationship verdicts to DuckDB, safely pausing the daemon while it holds the read-write connection.

**Architecture:** Three components. (1) `lacuna claims` — read-only targeting query that lists claims for adversary evaluation (by mode: virgin/stale/page). (2) Daemon SIGUSR1 handler — the running daemon catches SIGUSR1, finishes its in-flight sync, stops the observer, closes the DB connection, writes an ack file, then waits for the file to be deleted before re-opening and resuming. (3) `lacuna adversary-commit` — parses verdict arguments, detects whether the daemon is running, executes the pause/write/resume handshake if so, and writes `claim_sources.relationship + checked_at` and `claims.last_adversary_check` (and optionally `claims.superseded_by`).

**Tech Stack:** Python `signal`, `threading.Event`, DuckDB read-write connection, Click CLI, existing `vault.state_dir_for()` for the ack file path.

---

## Background: the concurrency contract

The daemon holds the single read-write DuckDB connection at all times. `claim_sources.relationship`, `claim_sources.checked_at`, and `claims.last_adversary_check` have no markdown representation — the daemon cannot derive them from file changes. They can only enter the DB through a process that temporarily takes the RW connection. That process is `adversary-commit`.

**Pause handshake:**
1. CLI sends SIGUSR1 to daemon PID.
2. Daemon finishes any in-flight sync (serialised by `handler._lock`), stops the observer, closes DB, writes `{state_dir}/daemon.paused`.
3. CLI polls for `daemon.paused` to appear (≤10s), then opens RW connection, writes all verdicts, closes.
4. CLI deletes `daemon.paused`.
5. Daemon detects the file is gone, re-opens DB, restarts observer.

If the daemon is not running, `adversary-commit` skips the handshake and opens RW directly.

---

## File Map

```
src/lacuna_wiki/
  cli/
    claims.py          — Create: list_claims() + `lacuna claims` Click command
    adversary_commit.py — Create: Verdict, Supersession, write_verdicts(), `lacuna adversary-commit`
    main.py            — Modify: register two new commands
  daemon/
    process.py         — Modify: add SIGUSR1 handler + pause/resume loop in run_daemon

tests/
  test_claims.py          — Create
  test_adversary_commit.py — Create
  test_daemon_pause.py    — Create
```

---

## DuckDB / schema notes

Relevant columns (all already exist in schema):
- `claims.last_adversary_check TIMESTAMP` — set to now() on every verdict commit
- `claims.superseded_by INTEGER REFERENCES claims(id)` — set for supersession
- `claim_sources.relationship TEXT` — "supports" | "refutes" | "gap" | NULL
- `claim_sources.checked_at TIMESTAMP` — set to now() on every verdict commit

The `claims` table PK is `id`. The `claim_sources` PK is `(claim_id, source_id)`. A verdict updates ALL `claim_sources` rows for a given `claim_id` (a claim typically cites one source; if it cites multiple, all get the same relationship verdict).

---

## Task 1: `claims` listing command

**Files:**
- Create: `src/lacuna_wiki/cli/claims.py`
- Create: `tests/test_claims.py`
- Modify: `src/lacuna_wiki/cli/main.py`

The adversary skill needs to enumerate targets. `list_claims()` is the pure function; the CLI command wraps it with vault resolution and output formatting.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_claims.py
import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.cli.claims import list_claims


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "v.db"))
    init_db(c)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attn', 'wiki/attn.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='attn'").fetchone()[0]
    c.execute(
        "INSERT INTO sources (slug, path, source_type, registered_at)"
        " VALUES ('vaswani2017', 'raw/v.pdf', 'paper', '2026-01-01')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    # Claim 1 — never evaluated
    c.execute(
        "INSERT INTO claims (page_id, text) VALUES (?, 'Attention computes QKT. [[vaswani2017.pdf]]')",
        [page_id],
    )
    claim1 = c.execute("SELECT id FROM claims ORDER BY id LIMIT 1").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 1)",
        [claim1, src_id],
    )
    # Claim 2 — already evaluated (last_adversary_check set)
    c.execute(
        "INSERT INTO claims (page_id, text, last_adversary_check)"
        " VALUES (?, 'Softmax normalises weights. [[vaswani2017.pdf]]', now())",
        [page_id],
    )
    claim2 = c.execute("SELECT id FROM claims ORDER BY id DESC LIMIT 1").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 2)",
        [claim2, src_id],
    )
    return c


def test_list_claims_virgin_returns_unevaluated(conn):
    results = list_claims(conn, "virgin")
    assert len(results) == 1
    assert results[0]["claim_id"] is not None
    assert "Attention computes" in results[0]["text"]


def test_list_claims_virgin_excludes_evaluated(conn):
    results = list_claims(conn, "virgin")
    texts = [r["text"] for r in results]
    assert not any("Softmax" in t for t in texts)


def test_list_claims_stale_includes_virgin(conn):
    results = list_claims(conn, "stale")
    assert len(results) >= 1


def test_list_claims_page_mode(conn):
    results = list_claims(conn, "page", page_slug="attn")
    assert len(results) == 2  # both claims on this page (superseded_by IS NULL for both)


def test_list_claims_page_mode_wrong_slug(conn):
    results = list_claims(conn, "page", page_slug="nonexistent")
    assert results == []


def test_list_claims_result_has_expected_keys(conn):
    results = list_claims(conn, "virgin")
    r = results[0]
    assert "claim_id" in r
    assert "page_slug" in r
    assert "section_name" in r
    assert "text" in r
    assert "source_slug" in r
    assert "published_date" in r
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_claims.py -v 2>&1 | tail -8
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.cli.claims'`

- [ ] **Step 3: Write `src/lacuna_wiki/cli/claims.py`**

```python
"""lacuna claims — list claims for adversary evaluation."""
from __future__ import annotations

import os
import sys

import click
import duckdb

from lacuna_wiki.vault import db_path, find_vault_root


def list_claims(
    conn: duckdb.DuckDBPyConnection,
    mode: str,
    page_slug: str | None = None,
) -> list[dict]:
    """Return claims matching the targeting mode.

    mode: "virgin" | "stale" | "page"
    page_slug: required when mode == "page"

    Each dict has keys: claim_id, page_slug, section_name, text,
    source_slug, published_date.
    """
    base = """
        SELECT DISTINCT
            c.id          AS claim_id,
            p.slug        AS page_slug,
            s.name        AS section_name,
            c.text        AS text,
            src.slug      AS source_slug,
            src.published_date
        FROM claims c
        JOIN pages p ON c.page_id = p.id
        LEFT JOIN sections s ON c.section_id = s.id
        LEFT JOIN claim_sources cs ON cs.claim_id = c.id
        LEFT JOIN sources src ON cs.source_id = src.id
        WHERE c.superseded_by IS NULL
    """

    if mode == "virgin":
        sql = base + " AND c.last_adversary_check IS NULL ORDER BY p.slug, c.id"
        rows = conn.execute(sql).fetchall()

    elif mode == "stale":
        sql = base + """
          AND (
            c.last_adversary_check IS NULL
            OR c.last_adversary_check < (
                SELECT MAX(registered_at) FROM sources WHERE registered_at IS NOT NULL
            )
          )
          ORDER BY p.slug, c.id
        """
        rows = conn.execute(sql).fetchall()

    elif mode == "page":
        if page_slug is None:
            raise ValueError("page_slug required for mode='page'")
        sql = base + " AND p.slug = ? ORDER BY c.id"
        rows = conn.execute(sql, [page_slug]).fetchall()

    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use: virgin, stale, page")

    return [
        {
            "claim_id": r[0],
            "page_slug": r[1],
            "section_name": r[2],
            "text": r[3],
            "source_slug": r[4],
            "published_date": r[5],
        }
        for r in rows
    ]


@click.command("claims")
@click.option(
    "--mode",
    type=click.Choice(["virgin", "stale", "page"]),
    default="virgin",
    show_default=True,
    help="Targeting mode.",
)
@click.option("--page", "page_slug", default=None, help="Slug for mode=page.")
def claims_command(mode: str, page_slug: str | None) -> None:
    """List claims for adversary evaluation."""
    vault_root = find_vault_root()
    if vault_root is None:
        click.echo("Not inside an lacuna vault.", err=True)
        sys.exit(1)

    db = db_path(vault_root)
    from lacuna_wiki.db.connection import get_connection
    conn = get_connection(db, readonly=True)

    try:
        results = list_claims(conn, mode, page_slug=page_slug)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    finally:
        conn.close()

    if not results:
        click.echo(f"No claims found (mode={mode}).")
        return

    pages_seen: set[str] = set()
    for r in results:
        if r["page_slug"] not in pages_seen:
            if pages_seen:
                click.echo("")
            click.echo(f"  {r['page_slug']}")
            pages_seen.add(r["page_slug"])
        section = r["section_name"] or "—"
        source = r["source_slug"] or "—"
        date = str(r["published_date"]) if r["published_date"] else "—"
        text_preview = r["text"][:80].replace("\n", " ")
        click.echo(f"  [{r['claim_id']}] {section} | {source} ({date})")
        click.echo(f"        {text_preview!r}")

    click.echo(f"\n{len(results)} claim(s) (mode={mode}).")
```

- [ ] **Step 4: Register in main.py**

In `src/lacuna_wiki/cli/main.py`, add:

```python
from lacuna_wiki.cli.claims import claims_command  # noqa: E402

cli.add_command(claims_command)
```

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/pytest tests/test_claims.py -v 2>&1 | tail -10
```

Expected: 6 tests PASS.

- [ ] **Step 6: Smoke test the CLI**

```bash
.venv/bin/lacuna claims --help
```

Expected: shows `--mode` and `--page` options.

- [ ] **Step 7: Commit**

```bash
git add src/lacuna_wiki/cli/claims.py src/lacuna_wiki/cli/main.py tests/test_claims.py
git commit -m "feat: add lacuna claims command for adversary targeting"
```

---

## Task 2: Daemon SIGUSR1 pause/resume

**Files:**
- Modify: `src/lacuna_wiki/daemon/process.py`
- Create: `tests/test_daemon_pause.py`

The daemon's main loop checks a `threading.Event` between sleeps. When the event is set (by SIGUSR1 handler), it acquires `handler._lock` (serialising with any in-flight sync), stops the observer, closes the DB connection, writes the ack file, polls until the ack file is deleted, then re-opens the connection and restarts the observer.

The ack file lives in the vault-specific state dir: `state_dir_for(vault_root) / "daemon.paused"`. The `adversary-commit` command knows this path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_daemon_pause.py
"""Tests for daemon SIGUSR1 pause mechanism.

We test the pause logic (event → ack file → resume) directly by calling
_handle_sigusr1 and simulating the ack-file deletion, without spawning a
full subprocess. Signal handlers in Python only fire in the main thread,
so these tests exercise the handler and the event directly.
"""
import os
import signal
import time
import threading
from pathlib import Path

import pytest

from lacuna_wiki.daemon.process import _pause_event, _handle_sigusr1


def test_handle_sigusr1_sets_pause_event():
    _pause_event.clear()
    _handle_sigusr1(signal.SIGUSR1, None)
    assert _pause_event.is_set()
    _pause_event.clear()  # cleanup


def test_pause_event_starts_clear():
    _pause_event.clear()
    assert not _pause_event.is_set()


def test_ack_file_written_and_cleared(tmp_path):
    """Simulate the pause loop: write ack, delete it, verify cleared."""
    ack = tmp_path / "daemon.paused"

    # Simulate what run_daemon does when _pause_event is set:
    # write ack file, then wait for it to disappear
    results = {}

    def simulate_pause():
        ack.write_text("paused")
        # poll until deleted (simulates daemon waiting)
        deadline = time.monotonic() + 2.0
        while ack.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        results["ack_gone"] = not ack.exists()

    t = threading.Thread(target=simulate_pause)
    t.start()

    # simulate adversary-commit: wait for ack, then delete it
    deadline = time.monotonic() + 2.0
    while not ack.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ack.exists(), "ack file never appeared"
    ack.unlink()

    t.join(timeout=2.0)
    assert results.get("ack_gone"), "daemon did not detect ack file deletion"
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_daemon_pause.py -v 2>&1 | tail -8
```

Expected: `ImportError: cannot import name '_pause_event' from 'lacuna_wiki.daemon.process'`

- [ ] **Step 3: Update `src/lacuna_wiki/daemon/process.py`**

Replace the full file:

```python
from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

_STATE_DIR = Path.home() / ".lacuna"
_PID_FILE = _STATE_DIR / "daemon.pid"
_LOG_FILE = _STATE_DIR / "daemon.log"

_pause_event = threading.Event()


def _handle_sigusr1(signum, frame) -> None:
    """Signal handler: request a daemon pause."""
    _pause_event.set()


def write_pid(pid: int) -> None:
    """Write daemon PID to file."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def read_pid() -> int | None:
    """Read daemon PID from file. Returns None if missing or corrupt."""
    if not _PID_FILE.exists():
        return None
    try:
        return int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(pid: int) -> bool:
    """Return True if a process with this PID currently exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it


def run_daemon(vault_root: Path) -> None:
    """Daemon entry point. Writes PID, syncs, starts observer, handles SIGUSR1 pause."""
    from watchdog.observers import Observer

    from lacuna_wiki.daemon.watcher import WikiEventHandler, initial_sync
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.sources.embedder import embed_texts
    from lacuna_wiki.vault import db_path, state_dir_for

    signal.signal(signal.SIGUSR1, _handle_sigusr1)

    write_pid(os.getpid())

    db = db_path(vault_root)
    pause_ack = state_dir_for(vault_root) / "daemon.paused"

    conn = get_connection(db)
    initial_sync(conn, vault_root, embed_texts)

    handler = WikiEventHandler(conn, vault_root, embed_texts)
    observer = Observer()
    observer.schedule(handler, str(vault_root / "wiki"), recursive=True)
    observer.start()

    try:
        while True:
            if _pause_event.is_set():
                # Acquire handler lock to wait for any in-flight sync to finish,
                # then stop the observer before closing the connection.
                with handler._lock:
                    observer.stop()
                observer.join()
                conn.close()

                # Signal readiness and wait for adversary-commit to finish.
                pause_ack.write_text("paused")
                while pause_ack.exists():
                    time.sleep(0.05)

                # Re-open and restart.
                conn = get_connection(db)
                handler._conn = conn
                observer = Observer()
                observer.schedule(handler, str(vault_root / "wiki"), recursive=True)
                observer.start()
                _pause_event.clear()

            time.sleep(1)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        observer.stop()
        observer.join()
        conn.close()
        _PID_FILE.unlink(missing_ok=True)
        pause_ack.unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/pytest tests/test_daemon_pause.py -v 2>&1 | tail -8
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lacuna_wiki/daemon/process.py tests/test_daemon_pause.py
git commit -m "feat: daemon SIGUSR1 pause/resume for adversary-commit handshake"
```

---

## Task 3: `adversary-commit` command

**Files:**
- Create: `src/lacuna_wiki/cli/adversary_commit.py`
- Create: `tests/test_adversary_commit.py`
- Modify: `src/lacuna_wiki/cli/main.py`

Parses `--verdict "claim_id=N,rel=VALUE"` and `--supersede "old=N,new=M"` arguments, executes the pause handshake if daemon is running, then writes verdicts to DB.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_adversary_commit.py
import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.cli.adversary_commit import (
    Verdict, Supersession, parse_verdict, parse_supersession, write_verdicts,
)


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "v.db"))
    init_db(c)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('p', 'wiki/p.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='p'").fetchone()[0]
    c.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    # claim 1
    c.execute("INSERT INTO claims (page_id, text) VALUES (?, 'Claim A. [[vaswani2017.pdf]]')", [page_id])
    claim1 = c.execute("SELECT id FROM claims ORDER BY id LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?,?,1)", [claim1, src_id])
    # claim 2
    c.execute("INSERT INTO claims (page_id, text) VALUES (?, 'Claim B. [[vaswani2017.pdf]]')", [page_id])
    claim2 = c.execute("SELECT id FROM claims ORDER BY id DESC LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?,?,2)", [claim2, src_id])
    return c, claim1, claim2


def test_parse_verdict_supports():
    v = parse_verdict("claim_id=42,rel=supports")
    assert v == Verdict(claim_id=42, rel="supports")


def test_parse_verdict_gap():
    v = parse_verdict("claim_id=7,rel=gap")
    assert v == Verdict(claim_id=7, rel="gap")


def test_parse_verdict_refutes():
    v = parse_verdict("claim_id=1,rel=refutes")
    assert v == Verdict(claim_id=1, rel="refutes")


def test_parse_verdict_bad_rel_raises():
    with pytest.raises(ValueError, match="rel must be"):
        parse_verdict("claim_id=1,rel=maybe")


def test_parse_supersession():
    s = parse_supersession("old=3,new=9")
    assert s == Supersession(old_id=3, new_id=9)


def test_write_verdicts_sets_relationship(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="supports")], [])
    rel = c.execute(
        "SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]
    ).fetchone()[0]
    assert rel == "supports"


def test_write_verdicts_sets_checked_at(conn):
    c, claim1, _ = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="gap")], [])
    checked = c.execute(
        "SELECT checked_at FROM claim_sources WHERE claim_id=?", [claim1]
    ).fetchone()[0]
    assert checked is not None


def test_write_verdicts_sets_last_adversary_check(conn):
    c, claim1, _ = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="supports")], [])
    ts = c.execute(
        "SELECT last_adversary_check FROM claims WHERE id=?", [claim1]
    ).fetchone()[0]
    assert ts is not None


def test_write_verdicts_multiple(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [
        Verdict(claim_id=claim1, rel="supports"),
        Verdict(claim_id=claim2, rel="gap"),
    ], [])
    r1 = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]).fetchone()[0]
    r2 = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim2]).fetchone()[0]
    assert r1 == "supports"
    assert r2 == "gap"


def test_write_supersession_sets_superseded_by(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [], [Supersession(old_id=claim1, new_id=claim2)])
    sup = c.execute(
        "SELECT superseded_by FROM claims WHERE id=?", [claim1]
    ).fetchone()[0]
    assert sup == claim2


def test_write_verdicts_and_supersession_together(conn):
    c, claim1, claim2 = conn
    write_verdicts(
        c,
        [Verdict(claim_id=claim1, rel="refutes")],
        [Supersession(old_id=claim1, new_id=claim2)],
    )
    rel = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]).fetchone()[0]
    sup = c.execute("SELECT superseded_by FROM claims WHERE id=?", [claim1]).fetchone()[0]
    assert rel == "refutes"
    assert sup == claim2
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_adversary_commit.py -v 2>&1 | tail -8
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.cli.adversary_commit'`

- [ ] **Step 3: Write `src/lacuna_wiki/cli/adversary_commit.py`**

```python
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
    now = conn.execute("SELECT now()").fetchone()[0]
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
```

- [ ] **Step 4: Register in main.py**

In `src/lacuna_wiki/cli/main.py`, add:

```python
from lacuna_wiki.cli.adversary_commit import adversary_commit  # noqa: E402

cli.add_command(adversary_commit)
```

The full `main.py` after both additions:

```python
import click


@click.group()
def cli():
    """lacuna v2 — personal research knowledge substrate."""
    pass


from lacuna_wiki.cli.add_source import add_source        # noqa: E402
from lacuna_wiki.cli.init import init                    # noqa: E402
from lacuna_wiki.cli.status import status                # noqa: E402
from lacuna_wiki.cli.daemon import start, stop, daemon_run  # noqa: E402
from lacuna_wiki.cli.mcp_cmd import mcp_command          # noqa: E402
from lacuna_wiki.cli.claims import claims_command        # noqa: E402
from lacuna_wiki.cli.adversary_commit import adversary_commit  # noqa: E402

cli.add_command(add_source)
cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(daemon_run)
cli.add_command(mcp_command)
cli.add_command(claims_command)
cli.add_command(adversary_commit)
```

- [ ] **Step 5: Run adversary-commit tests**

```bash
.venv/bin/pytest tests/test_adversary_commit.py -v 2>&1 | tail -15
```

Expected: 11 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 7: Smoke test the CLI**

```bash
.venv/bin/lacuna adversary-commit --help
.venv/bin/lacuna claims --help
```

Both should print usage without error.

- [ ] **Step 8: Commit**

```bash
git add src/lacuna_wiki/cli/adversary_commit.py src/lacuna_wiki/cli/main.py tests/test_adversary_commit.py
git commit -m "feat: adversary-commit CLI with daemon pause/resume handshake"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| SIGUSR1 pauses daemon | Task 2 |
| Daemon finishes in-flight sync before pausing | Task 2 — acquires `handler._lock` |
| Ack file signals CLI that daemon is paused | Task 2 + Task 3 |
| CLI deletes ack file to resume daemon | Task 3 — `pause_ack.unlink()` in finally |
| `claim_sources.relationship` written | Task 3 — `write_verdicts` |
| `claim_sources.checked_at` written | Task 3 — `write_verdicts` |
| `claims.last_adversary_check` written | Task 3 — `write_verdicts` |
| `claims.superseded_by` written | Task 3 — `write_verdicts` |
| No daemon running → direct RW open | Task 3 — `daemon_running` guard |
| Adversary targeting queries (virgin/stale/page) | Task 1 — `list_claims` |
| Adversary targeting via `lacuna claims` | Task 1 |

**Placeholder scan:** None found.

**Type consistency:** `Verdict.claim_id: int`, `Verdict.rel: str` — consistent across `parse_verdict`, `write_verdicts`, and tests. `Supersession.old_id/new_id: int` — consistent throughout.
