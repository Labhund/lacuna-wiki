# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the CLI scaffold, vault detection, DuckDB schema, `llm-wiki init` wizard (dirs + git + MCP wiring), `llm-wiki status`, and `llm-wiki start`/`stop` stubs.

**Architecture:** DB lives at `~/.llm-wiki/vaults/{slug}-{hash}/vault.db` — completely outside the vault, which stays clean (just `wiki/`, `raw/`, `.gitignore`, git history). Vault root is detected by walking up the directory tree looking for both `wiki/` and `raw/` directories. `llm-wiki init` creates the vault, inits git, creates the DB, and wires MCP config for the user's harness (Hermes, Claude Code).

**Tech Stack:** Python 3.11+, Click 8+, DuckDB 0.10+, Rich 13+, tomli-w, pytest

**Note on daemon commands:** `llm-wiki start` and `llm-wiki stop` are scaffolded as stubs in this plan. The daemon itself is Plan 3. The CLI entry points are defined now so the command surface is complete from day one.

**Note on v1 migration:** Not in scope. Re-extract from sources via `add-source` + ingest skill (Plans 2 + 5). Onboarding story = normal first-use workflow.

---

## File Map

```
src/llm_wiki/
  __init__.py              — package marker
  vault.py                 — Vault class: root detection, state dir, db path
  cli/
    __init__.py            — package marker
    main.py                — Click group, entry point registered in pyproject.toml
    init.py                — `llm-wiki init` wizard
    status.py              — `llm-wiki status`
    daemon.py              — `llm-wiki start` / `llm-wiki stop` stubs
  db/
    __init__.py            — package marker
    schema.py              — CREATE TABLE statements, init_db()
    connection.py          — DuckDB connection factory
tests/
  __init__.py
  conftest.py              — shared fixtures (tmp vault, db connection)
  test_vault.py            — vault root detection, state dir derivation
  test_schema.py           — schema creates all 7 tables with correct columns
  test_init.py             — init creates dirs, git repo, DB, gitignore
  test_status.py           — status reads from DB, reports counts
pyproject.toml
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/llm_wiki/__init__.py`
- Create: `src/llm_wiki/cli/__init__.py`
- Create: `src/llm_wiki/db/__init__.py`
- Create: `src/llm_wiki/cli/main.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "llm-wiki"
version = "2.0.0"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "duckdb>=0.10.0",
    "rich>=13.0",
    "tomli-w>=1.0",
]

[project.scripts]
llm-wiki = "llm_wiki.cli.main:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/llm_wiki"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create package markers**

`src/llm_wiki/__init__.py` — empty file.
`src/llm_wiki/cli/__init__.py` — empty file.
`src/llm_wiki/db/__init__.py` — empty file.
`tests/__init__.py` — empty file.

- [ ] **Step 3: Write `src/llm_wiki/cli/main.py`**

```python
import click


@click.group()
def cli():
    """llm-wiki v2 — personal research knowledge substrate."""
    pass


from llm_wiki.cli.init import init       # noqa: E402
from llm_wiki.cli.status import status   # noqa: E402
from llm_wiki.cli.daemon import start, stop  # noqa: E402

cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
```

- [ ] **Step 4: Install in editable mode**

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -e .
```

- [ ] **Step 5: Verify entry point**

```bash
llm-wiki --help
```

Expected output contains: `init`, `status`, `start`, `stop`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/__init__.py
git commit -m "chore: scaffold CLI package with Click entry point"
```

---

## Task 2: Vault root detection and state directory

**Files:**
- Create: `src/llm_wiki/vault.py`
- Create: `tests/test_vault.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vault.py
import hashlib
from pathlib import Path
import pytest
from llm_wiki.vault import find_vault_root, state_dir_for, db_path


def test_find_vault_root_from_wiki_dir(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    assert find_vault_root(tmp_path) == tmp_path


def test_find_vault_root_from_subdir(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    subdir = tmp_path / "wiki" / "ml" / "attention"
    subdir.mkdir(parents=True)
    assert find_vault_root(subdir) == tmp_path


def test_find_vault_root_returns_none_outside_vault(tmp_path):
    assert find_vault_root(tmp_path) is None


def test_find_vault_root_requires_both_dirs(tmp_path):
    (tmp_path / "wiki").mkdir()
    # raw/ is missing
    assert find_vault_root(tmp_path) is None


def test_state_dir_for_is_deterministic(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    d1 = state_dir_for(tmp_path)
    d2 = state_dir_for(tmp_path)
    assert d1 == d2


def test_state_dir_for_different_vaults_differ(tmp_path):
    vault_a = tmp_path / "vault_a"
    vault_b = tmp_path / "vault_b"
    for v in [vault_a, vault_b]:
        (v / "wiki").mkdir(parents=True)
        (v / "raw").mkdir(parents=True)
    assert state_dir_for(vault_a) != state_dir_for(vault_b)


def test_db_path_is_inside_state_dir(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    assert db_path(tmp_path).parent == state_dir_for(tmp_path)
    assert db_path(tmp_path).name == "vault.db"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vault.py -v
```

Expected: all FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write `src/llm_wiki/vault.py`**

```python
from __future__ import annotations

import hashlib
from pathlib import Path

_STATE_ROOT = Path.home() / ".llm-wiki" / "vaults"


def state_dir_for(vault_root: Path) -> Path:
    """Derive a stable state directory path for a given vault root."""
    resolved = str(vault_root.resolve())
    slug = resolved.strip("/").replace("/", "-")[:60]
    short_hash = hashlib.sha256(resolved.encode()).hexdigest()[:8]
    return _STATE_ROOT / f"{slug}-{short_hash}"


def db_path(vault_root: Path) -> Path:
    """Path to the DuckDB file for this vault."""
    return state_dir_for(vault_root) / "vault.db"


def find_vault_root(start: Path | None = None) -> Path | None:
    """Walk up the directory tree from `start` to find a vault root.

    A vault root is a directory containing both wiki/ and raw/ subdirectories.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "wiki").is_dir() and (candidate / "raw").is_dir():
            return candidate
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_vault.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm_wiki/vault.py tests/test_vault.py
git commit -m "feat: vault root detection and state directory derivation"
```

---

## Task 3: DuckDB schema

**Files:**
- Create: `src/llm_wiki/db/schema.py`
- Create: `src/llm_wiki/db/connection.py`
- Create: `tests/conftest.py`
- Create: `tests/test_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_schema.py
import duckdb
import pytest


def test_init_db_creates_all_tables(db_conn):
    tables = {
        row[0]
        for row in db_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    expected = {"pages", "sections", "links", "sources", "claims", "claim_sources", "source_chunks"}
    assert expected == tables


def test_pages_has_required_columns(db_conn):
    cols = _column_names(db_conn, "pages")
    assert {"id", "slug", "path", "title", "cluster", "last_modified"} <= cols


def test_sections_has_position_and_embedding(db_conn):
    cols = _column_names(db_conn, "sections")
    assert {"id", "page_id", "position", "name", "content_hash", "token_count", "embedding"} <= cols


def test_links_has_composite_pk(db_conn):
    cols = _column_names(db_conn, "links")
    assert {"source_page_id", "target_slug"} <= cols


def test_sources_has_registered_at(db_conn):
    cols = _column_names(db_conn, "sources")
    assert {"id", "slug", "path", "published_date", "registered_at", "source_type"} <= cols


def test_claims_has_adversary_fields(db_conn):
    cols = _column_names(db_conn, "claims")
    assert {"id", "page_id", "section_id", "text", "embedding", "superseded_by",
            "last_adversary_check"} <= cols


def test_claim_sources_has_relationship(db_conn):
    cols = _column_names(db_conn, "claim_sources")
    assert {"claim_id", "source_id", "citation_number", "relationship", "checked_at"} <= cols


def test_source_chunks_has_no_preview_column(db_conn):
    cols = _column_names(db_conn, "source_chunks")
    assert "preview" not in cols
    assert {"id", "source_id", "chunk_index", "heading", "start_line", "end_line",
            "token_count", "embedding"} <= cols


def test_init_db_is_idempotent(db_conn):
    from llm_wiki.db.schema import init_db
    init_db(db_conn)  # second call — must not raise
    tables = db_conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchone()[0]
    assert tables == 7


def _column_names(conn, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND table_schema = 'main'"
        ).fetchall()
    }
```

```python
# tests/conftest.py
import duckdb
import pytest
from llm_wiki.db.schema import init_db


@pytest.fixture
def db_conn():
    """In-memory DuckDB connection with schema initialised."""
    conn = duckdb.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schema.py -v
```

Expected: all FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/llm_wiki/db/schema.py`**

```python
"""DuckDB schema — all seven tables."""
from __future__ import annotations

import duckdb

_TABLES = """
CREATE TABLE IF NOT EXISTS pages (
    id            INTEGER PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    path          TEXT NOT NULL,
    title         TEXT,
    cluster       TEXT,
    last_modified TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sections (
    id           INTEGER PRIMARY KEY,
    page_id      INTEGER REFERENCES pages(id),
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    content_hash TEXT,
    token_count  INTEGER,
    embedding    FLOAT[1024]
);

CREATE TABLE IF NOT EXISTS links (
    source_page_id INTEGER REFERENCES pages(id),
    target_slug    TEXT NOT NULL,
    PRIMARY KEY (source_page_id, target_slug)
);

CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY,
    slug           TEXT UNIQUE NOT NULL,
    path           TEXT NOT NULL,
    title          TEXT,
    authors        TEXT,
    published_date DATE,
    registered_at  TIMESTAMP,
    source_type    TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id                   INTEGER PRIMARY KEY,
    page_id              INTEGER REFERENCES pages(id),
    section_id           INTEGER REFERENCES sections(id),
    text                 TEXT NOT NULL,
    embedding            FLOAT[1024],
    superseded_by        INTEGER REFERENCES claims(id),
    last_adversary_check TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claim_sources (
    claim_id        INTEGER REFERENCES claims(id),
    source_id       INTEGER REFERENCES sources(id),
    citation_number INTEGER,
    relationship    TEXT,
    checked_at      TIMESTAMP,
    PRIMARY KEY (claim_id, source_id)
);

CREATE TABLE IF NOT EXISTS source_chunks (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER REFERENCES sources(id),
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    token_count INTEGER,
    embedding   FLOAT[1024]
);
"""


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables. Safe to call on an existing DB (CREATE IF NOT EXISTS)."""
    for statement in _TABLES.strip().split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)
```

- [ ] **Step 4: Write `src/llm_wiki/db/connection.py`**

```python
"""DuckDB connection factory."""
from __future__ import annotations

import duckdb
from pathlib import Path


def get_connection(db_path: Path, readonly: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection to the vault database.

    readonly=True for skills scripts and status reads.
    readonly=False (default) for the daemon and CLI write commands.
    vss extension is loaded in Plan 4 when vector search is wired up.
    """
    return duckdb.connect(str(db_path), read_only=readonly)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_schema.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/llm_wiki/db/ tests/conftest.py tests/test_schema.py
git commit -m "feat: DuckDB schema — seven tables, CREATE IF NOT EXISTS"
```

---

## Task 4: `llm-wiki init` wizard

**Files:**
- Create: `src/llm_wiki/cli/init.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_init.py
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from llm_wiki.cli.init import init
from llm_wiki.vault import db_path, find_vault_root


@pytest.fixture
def runner():
    return CliRunner()


def test_init_creates_wiki_and_raw_dirs(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(init, input="test-vault\n")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "wiki").is_dir()
    assert (tmp_path / "raw").is_dir()


def test_init_creates_git_repo(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init, input="test-vault\n")
    assert (tmp_path / ".git").is_dir()


def test_init_creates_database(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init, input="test-vault\n")
    db = db_path(tmp_path)
    assert db.exists()


def test_init_database_has_tables(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init, input="test-vault\n")
    import duckdb
    conn = duckdb.connect(str(db_path(tmp_path)))
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}
    conn.close()
    assert {"pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"} == tables


def test_init_creates_gitignore(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init, input="test-vault\n")
    assert (tmp_path / ".gitignore").exists()


def test_init_is_idempotent(tmp_path, runner, monkeypatch):
    """Running init twice on the same directory must not raise."""
    monkeypatch.chdir(tmp_path)
    r1 = runner.invoke(init, input="test-vault\n")
    r2 = runner.invoke(init, input="test-vault\n")
    assert r1.exit_code == 0
    assert r2.exit_code == 0


def test_init_vault_root_detectable_after_init(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init, input="test-vault\n")
    assert find_vault_root(tmp_path) == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_init.py -v
```

Expected: all FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write `src/llm_wiki/cli/init.py`**

```python
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

    # Vault name (cosmetic only — used in welcome message)
    default_name = vault_root.name
    name = click.prompt("Vault name", default=default_name)

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

    # .gitignore — DB lives outside the vault, nothing to ignore
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
        import json
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
```

- [ ] **Step 4: Add `pyyaml` to dependencies in pyproject.toml**

```toml
dependencies = [
    "click>=8.0",
    "duckdb>=0.10.0",
    "rich>=13.0",
    "tomli-w>=1.0",
    "pyyaml>=6.0",
]
```

```bash
pip install pyyaml
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_init.py -v
```

Expected: all PASS.

- [ ] **Step 6: Smoke test the wizard manually**

```bash
cd /tmp && mkdir test-vault && cd test-vault && llm-wiki init .
```

Expected: wizard runs, prompts for name, creates wiki/ raw/ .git .gitignore, prints "Vault ready."

```bash
llm-wiki status
```

Expected: prints vault path, DB path, table counts (all 0).

- [ ] **Step 7: Commit**

```bash
git add src/llm_wiki/cli/init.py tests/test_init.py pyproject.toml
git commit -m "feat: llm-wiki init wizard — dirs, git, DB, MCP config wiring"
```

---

## Task 5: `llm-wiki status`

**Files:**
- Create: `src/llm_wiki/cli/status.py`
- Create: `tests/test_status.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_status.py
import duckdb
import pytest
from click.testing import CliRunner
from pathlib import Path

from llm_wiki.cli.status import status
from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for


@pytest.fixture
def vault(tmp_path):
    """A minimal vault: wiki/ raw/ and an initialised DB."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    state = state_dir_for(tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(tmp_path)))
    init_db(conn)
    conn.close()
    return tmp_path


def test_status_shows_vault_path(vault, monkeypatch):
    monkeypatch.chdir(vault)
    runner = CliRunner()
    result = runner.invoke(status)
    assert result.exit_code == 0, result.output
    assert str(vault) in result.output


def test_status_shows_all_table_names(vault, monkeypatch):
    monkeypatch.chdir(vault)
    runner = CliRunner()
    result = runner.invoke(status)
    for table in ["pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"]:
        assert table in result.output


def test_status_shows_zero_counts_on_empty_db(vault, monkeypatch):
    monkeypatch.chdir(vault)
    runner = CliRunner()
    result = runner.invoke(status)
    assert "0" in result.output


def test_status_fails_outside_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(status)
    assert result.exit_code != 0


def test_status_shows_row_counts(vault, monkeypatch):
    monkeypatch.chdir(vault)
    # Insert one page
    conn = duckdb.connect(str(db_path(vault)))
    conn.execute(
        "INSERT INTO pages (id, slug, path) VALUES (1, 'test-page', 'wiki/test-page.md')"
    )
    conn.close()
    runner = CliRunner()
    result = runner.invoke(status)
    assert "1" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_status.py -v
```

Expected: all FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write `src/llm_wiki/cli/status.py`**

```python
"""llm-wiki status — vault health report."""
from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from llm_wiki.db.connection import get_connection
from llm_wiki.vault import db_path, find_vault_root

console = Console()

_TABLES = ["pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"]


@click.command()
def status() -> None:
    """Show vault status and table row counts."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an llm-wiki vault.[/red] "
                      "(No directory with both wiki/ and raw/ found.)")
        sys.exit(1)

    db = db_path(vault_root)
    if not db.exists():
        console.print(f"[red]Vault found at {vault_root} but database missing.[/red] "
                      "Run [bold]llm-wiki sync[/bold] to rebuild.")
        sys.exit(1)

    conn = get_connection(db, readonly=True)

    table = Table(title=None, show_header=True, header_style="bold")
    table.add_column("Table", style="dim")
    table.add_column("Rows", justify="right")

    for t in _TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        table.add_row(t, str(count))

    conn.close()

    console.print(f"\n[bold]llm-wiki status[/bold]")
    console.print(f"  Vault:    {vault_root}")
    console.print(f"  Database: {db}\n")
    console.print(table)
    console.print()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_status.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm_wiki/cli/status.py tests/test_status.py
git commit -m "feat: llm-wiki status — vault health report with table row counts"
```

---

## Task 6: `llm-wiki start` / `llm-wiki stop` stubs

**Files:**
- Create: `src/llm_wiki/cli/daemon.py`

No tests for stubs — these are wired in Plan 3 where the daemon is implemented and tested.

- [ ] **Step 1: Write `src/llm_wiki/cli/daemon.py`**

```python
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
```

- [ ] **Step 2: Verify commands appear in help**

```bash
llm-wiki --help
```

Expected output includes: `start`, `stop`, `init`, `status`.

```bash
llm-wiki start
```

Expected: prints "Daemon not yet implemented (Plan 3)."

- [ ] **Step 3: Commit**

```bash
git add src/llm_wiki/cli/daemon.py
git commit -m "chore: start/stop daemon stubs — full impl in Plan 3"
```

---

## Task 7: Full test run and smoke test

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: all PASS. If any fail, fix before proceeding.

- [ ] **Step 2: End-to-end smoke test**

```bash
cd /tmp && rm -rf smoke-vault && mkdir smoke-vault && cd smoke-vault
llm-wiki init .
# Enter "smoke-vault" when prompted for name
# Answer Y/n for MCP config prompts as preferred
llm-wiki status
```

Expected status output:
```
llm-wiki status
  Vault:    /tmp/smoke-vault
  Database: /home/<user>/.llm-wiki/vaults/...vault.db

  Table               Rows
  pages                  0
  sections               0
  sources                0
  claims                 0
  claim_sources          0
  source_chunks          0
  links                  0
```

- [ ] **Step 3: Verify git history in vault**

```bash
git -C /tmp/smoke-vault log --oneline
```

Expected: one commit — `chore: initialise llm-wiki vault`

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A && git commit -m "chore: plan 1 complete — foundation verified"
```

---

## Self-review notes

- `relationship` column in `claim_sources`: the spec allows `supports | refutes | gap | NULL`. No CHECK constraint is added — the adversary skill enforces this at write time, not the DB. Deliberately omitted to avoid friction during development.
- HNSW indexes (vss extension) are **not** in this plan. They are added in Plan 4 when search is wired up. The `embedding FLOAT[1024]` columns exist but are unindexed until then.
- `llm-wiki sync` (rebuild DB from markdown) is scaffolded in Plan 3 alongside the daemon, since the logic is the same.
- `llm-wiki adversary-commit` is Plan 5.
- v1 migration: not in scope. The onboarding path is the normal first-use workflow — `add-source` (Plan 2) + ingest skill (Plan 5).
