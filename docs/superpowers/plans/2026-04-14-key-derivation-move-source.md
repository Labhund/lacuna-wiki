# Key Derivation + move-source CLI + BibTeX Sidecars Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix key derivation for YouTube and URL sources (author+year+5char format), add `lacuna move-source` CLI command, and generate BibTeX sidecars for all source types.

**Architecture:** `key_from_author_year` added to `sources/key.py`. YouTube and URL paths in `add_source.py` updated to use it. A new `move_source.py` CLI command atomically moves source files and updates the DB path (pausing the daemon). BibTeX sidecar generation centralised in a `_write_bib_sidecar` helper in `add_source.py`.

**Tech Stack:** Python, Click, DuckDB, `shutil`, existing `daemon.process` pause mechanism.

---

### Background

Current YouTube key derivation uses the title-derived slug (`we-dont-need-kv-cache-anymore`) which is long, not machine-parseable, and requires an LLM to decode. The target format is `{author}{year}{first_5_of_title_slug}` — e.g. `hay2026wedon` for "We Don't Need KV Cache Anymore?" by Chris Hay (2026). Academic PDF keys (vaswani2017 via BibTeX) are unchanged.

The `--concept` flag on `add-source` forces the agent to guess the concept directory before reading the source. `move-source SLUG --concept domain/subdomain` allows concept assignment after reading, atomically moving all associated files.

BibTeX sidecars already exist for PDFs. Extending to all source types gives consistent citation metadata.

---

### File Map

```
src/lacuna_wiki/sources/key.py          add key_from_author_year()
src/lacuna_wiki/cli/add_source.py       update YouTube + URL key derivation; add _write_bib_sidecar()
src/lacuna_wiki/cli/move_source.py      NEW — move-source command
src/lacuna_wiki/cli/main.py             register move_source
tests/test_add_source.py             update YouTube/URL key assertions
tests/test_move_source.py            NEW — move-source tests
```

---

### Task 1: `key_from_author_year` in sources/key.py

**Files:**
- Modify: `src/lacuna_wiki/sources/key.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_add_source.py` (find the existing key derivation tests section, or add at end):

```python
from lacuna_wiki.sources.key import key_from_author_year

def test_key_from_author_year_basic():
    # Last name "Hay" → "hay", 2026, "We Don't Need..." → "wedon" → "hay2026wedon"
    import duckdb
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Chris Hay", 2026, "We Don't Need KV Cache Anymore?", conn)
    assert key == "hay2026wedon"

def test_key_from_author_year_title_truncated():
    # Single-name author: "Vaswani" → "vaswani"; title first 5 alphanumeric → "atten"
    import duckdb
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Vaswani", 2017, "Attention Is All You Need", conn)
    assert key == "vaswani2017atten"

def test_key_from_author_year_disambiguates():
    import duckdb
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    conn.execute("INSERT INTO sources VALUES ('hay2026wedon')")
    key = key_from_author_year("Chris Hay", 2026, "We Don't Need KV Cache Anymore?", conn)
    assert key == "hay2026wedonb"

def test_key_from_author_year_no_title():
    import duckdb
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Chris Hay", 2026, None, conn)
    assert key == "hay2026"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_add_source.py::test_key_from_author_year_basic -v
```

Expected: FAIL with `ImportError` or `AttributeError: module has no attribute 'key_from_author_year'`

- [ ] **Step 3: Implement `key_from_author_year`**

Add to `src/lacuna_wiki/sources/key.py` after `derive_key_from_bibtex`:

```python
def key_from_author_year(
    author: str,
    year: int | str,
    title: str | None,
    conn: duckdb.DuckDBPyConnection,
) -> str:
    """Derive key as {lastname}{year}{title_prefix_5}.

    Author: last space-separated token, lowercase alpha only (matches bibtex convention).
    Year: 4-digit integer or string.
    Title: optional; first 5 alphanumeric chars of slugified title appended.
    Disambiguates with b, c, ... suffix if needed.

    Example: "Chris Hay", 2026, "We Don't Need KV Cache Anymore?" → "hay2026wedon"
    """
    last_name = author.split()[-1] if author.strip() else author
    author_slug = re.sub(r"[^a-z]", "", last_name.lower()) or "source"
    year_str = str(year)[:4]
    base = author_slug + year_str
    if title:
        title_slug = re.sub(r"[^a-z0-9]", "", title.lower())
        base += title_slug[:5]
    return _disambiguate(base, conn)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_add_source.py::test_key_from_author_year_basic tests/test_add_source.py::test_key_from_author_year_title_truncated tests/test_add_source.py::test_key_from_author_year_disambiguates tests/test_add_source.py::test_key_from_author_year_no_title -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/key.py tests/test_add_source.py
git commit -m "feat: key_from_author_year for non-academic source key derivation"
```

---

### Task 2: Update YouTube key derivation in add_source.py

**Files:**
- Modify: `src/lacuna_wiki/cli/add_source.py`

- [ ] **Step 1: Check existing YouTube key import**

At the top of `src/lacuna_wiki/cli/add_source.py`, the imports include:
```python
from lacuna_wiki.sources.fetcher import fetch_url_as_markdown, key_from_url, parse_jina_headers
from lacuna_wiki.sources.youtube import fetch_youtube_transcript, is_youtube_url, key_from_title
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex
```

Add `key_from_author_year` to the key import:
```python
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex, key_from_author_year
```

- [ ] **Step 2: Update the YouTube key derivation block**

Find the YouTube path in `add_source.py` (around line 84):
```python
key = (key_from_title(yt_meta["title"], conn) if yt_meta.get("title")
       else key_from_url(url, conn))
```

Replace with:
```python
if yt_meta.get("channel") and final_date:
    key = key_from_author_year(
        yt_meta["channel"], final_date.year, yt_meta.get("title"), conn
    )
elif yt_meta.get("title"):
    key = key_from_author_year("", 0, yt_meta["title"], conn) if False else key_from_title(yt_meta["title"], conn)
else:
    key = key_from_url(url, conn)
```

Wait — `final_date` is set later in the YouTube block (lines 95–102). Move the key derivation after the date extraction. The correct structure is:

```python
# Metadata: CLI flags > yt-dlp info
final_title = title or yt_meta.get("title")
final_authors = authors or yt_meta.get("channel")
final_date: date | None = None
if pub_date:
    final_date = date.fromisoformat(pub_date)
elif "upload_date" in yt_meta:
    try:
        final_date = date.fromisoformat(yt_meta["upload_date"])
    except ValueError:
        pass

# Key: author+year+title_prefix if we have author and date; fallback to title slug
if final_authors and final_date:
    key = key_from_author_year(final_authors, final_date.year, final_title, conn)
elif final_title:
    key = key_from_title(final_title, conn)
else:
    key = key_from_url(url, conn)
```

Replace the entire YouTube block (lines ~77–102 in current file) with the above, putting key derivation after metadata extraction.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all tests pass (count ≥ 289)

- [ ] **Step 4: Commit**

```bash
git add src/lacuna_wiki/cli/add_source.py
git commit -m "feat: YouTube key derivation uses author+year+5char format"
```

---

### Task 3: BibTeX sidecar for all source types

**Files:**
- Modify: `src/lacuna_wiki/cli/add_source.py`

- [ ] **Step 1: Write failing test for bibtex sidecar on YouTube source**

Add to `tests/test_add_source.py`:

```python
def test_youtube_source_generates_bib_sidecar(tmp_path, monkeypatch, mock_embed):
    """YouTube registration should write a .bib sidecar alongside the .md."""
    # This test patches fetch_youtube_transcript and checks the .bib file exists
    import duckdb
    from lacuna_wiki.db.schema import init_db
    from lacuna_wiki.vault import db_path, state_dir_for

    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "raw").mkdir()
    state_dir_for(vault).mkdir(parents=True)
    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)
    conn.close()

    # Mock fetch_youtube_transcript
    monkeypatch.chdir(vault)
    monkeypatch.setenv("LACUNA_VAULT", str(vault))
    # ... use CliRunner pattern from existing test_add_source.py tests
    # Check: vault / "raw" / "{key}.bib" exists after add-source on a YouTube URL
```

Actually — look at how `test_add_source.py` currently tests YouTube. Read the existing test patterns first:

```bash
grep -n "youtube\|YouTube\|bib" tests/test_add_source.py | head -30
```

Model the bibtex test on the existing YouTube test structure.

- [ ] **Step 2: Add `_write_bib_sidecar` helper to add_source.py**

Add after the `_SOURCE_TYPES` and `_CHUNK_STRATEGY` constants:

```python
def _write_bib_sidecar(
    dest_dir: Path,
    key: str,
    title: str | None,
    authors: str | None,
    pub_date,   # date | None
    source_type: str,
    url: str | None = None,
) -> None:
    """Write a minimal BibTeX .bib sidecar for non-PDF sources."""
    lines = [f"@misc{{{key},"]
    if authors:
        lines.append(f"  author       = {{{authors}}},")
    if title:
        lines.append(f"  title        = {{{title}}},")
    if pub_date:
        lines.append(f"  year         = {{{pub_date.year}}},")
        lines.append(f"  month        = {{{pub_date.month}}},")
    if url:
        lines.append(f"  howpublished = {{\\url{{{url}}}}},")
    _TYPE_NOTES = {
        "transcript": "YouTube video transcript",
        "blog": "Blog post",
        "url": "Web page",
        "podcast": "Podcast transcript",
        "note": "Personal note",
        "session": "Research session",
        "experiment": "Experiment log",
    }
    note = _TYPE_NOTES.get(source_type, "")
    if note:
        lines.append(f"  note         = {{{note}}}")
    lines.append("}")
    bib_content = "\n".join(lines) + "\n"
    (dest_dir / f"{key}.bib").write_text(bib_content, encoding="utf-8")
```

- [ ] **Step 3: Call `_write_bib_sidecar` in the YouTube path**

After `md_dest.write_text(text, encoding="utf-8")` in the YouTube block, add:

```python
_write_bib_sidecar(
    target_dir, key, final_title, final_authors, final_date,
    inferred_type, url=url,
)
```

- [ ] **Step 4: Call `_write_bib_sidecar` in the URL path (non-YouTube, no existing bibtex)**

In the general URL block, after `md_dest.write_text(text, encoding="utf-8")`, find where `.bib` is written for DOI sources:
```python
if bibtex_str:
    (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
```

Add an `else` branch for sources without DOI/bibtex:
```python
if bibtex_str:
    (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
else:
    _write_bib_sidecar(
        target_dir, key, final_title, final_authors, final_date,
        inferred_type, url=url,
    )
```

- [ ] **Step 5: Call `_write_bib_sidecar` for non-PDF file sources**

In the file path block, after the `.md` file is written and bibtex check:
```python
if suffix == ".pdf":
    ...
    if bibtex_str:
        (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
    # PDF without DOI: no bibtex sidecar (can't generate metadata without the source)
else:
    md_dest = target_dir / f"{key}{suffix}"
    shutil.copy2(src, md_dest)
    primary_dest = md_dest
    cite_ext = suffix
    # Non-PDF file: generate minimal bibtex sidecar
    _write_bib_sidecar(
        target_dir, key, final_title, final_authors, final_date, inferred_type,
    )
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/lacuna_wiki/cli/add_source.py
git commit -m "feat: bibtex sidecar for all source types (YouTube, URL, non-PDF files)"
```

---

### Task 4: `lacuna move-source` CLI command

**Files:**
- Create: `src/lacuna_wiki/cli/move_source.py`
- Modify: `src/lacuna_wiki/cli/main.py`
- Create: `tests/test_move_source.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_move_source.py`:

```python
"""Tests for lacuna move-source command."""
import duckdb
import pytest
import shutil
from pathlib import Path
from click.testing import CliRunner

from lacuna_wiki.cli.main import cli
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    (vault_root / "raw").mkdir()
    state_dir_for(vault_root).mkdir(parents=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    # Register a source in raw/
    (vault_root / "raw" / "hay2026wedon.md").write_text("# transcript\ncontent")
    conn.execute(
        "INSERT INTO sources (slug, path, title, authors, source_type, registered_at)"
        " VALUES (?, ?, ?, ?, ?, now())",
        ["hay2026wedon", "raw/hay2026wedon.md", "We Don't Need KV Cache",
         "Chris Hay", "transcript"],
    )
    conn.close()
    return vault_root


def test_move_source_moves_md_file(vault):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0, result.output
    assert not (vault / "raw" / "hay2026wedon.md").exists()
    assert (vault / "raw" / "machine-learning" / "kv-cache" / "hay2026wedon.md").exists()


def test_move_source_updates_db_path(vault):
    runner = CliRunner()
    runner.invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    conn = duckdb.connect(str(db_path(vault)), read_only=True)
    row = conn.execute("SELECT path FROM sources WHERE slug='hay2026wedon'").fetchone()
    conn.close()
    assert row[0] == "raw/machine-learning/kv-cache/hay2026wedon.md"


def test_move_source_moves_all_associated_files(vault):
    """All files sharing the slug (.md, .pdf, .bib) must move atomically."""
    # Add companion files
    (vault / "raw" / "hay2026wedon.bib").write_text("@misc{hay2026wedon}")
    (vault / "raw" / "hay2026wedon.pdf").write_bytes(b"fake pdf")
    runner = CliRunner()
    runner.invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    dest = vault / "raw" / "machine-learning" / "kv-cache"
    assert (dest / "hay2026wedon.md").exists()
    assert (dest / "hay2026wedon.bib").exists()
    assert (dest / "hay2026wedon.pdf").exists()


def test_move_source_missing_slug_errors(vault):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "move-source", "nonexistent", "--concept", "somewhere",
        "--vault", str(vault),
    ])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_move_source_target_already_occupied_errors(vault):
    """If a file with the same name already exists at destination, abort."""
    dest_dir = vault / "raw" / "machine-learning" / "kv-cache"
    dest_dir.mkdir(parents=True)
    (dest_dir / "hay2026wedon.md").write_text("already here")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    assert result.exit_code != 0
    assert "already exists" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_move_source.py -v
```

Expected: FAIL with `No such command 'move-source'`

- [ ] **Step 3: Implement move_source.py**

Create `src/lacuna_wiki/cli/move_source.py`:

```python
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
@click.option("--concept", required=True, help="Target concept path (e.g. machine-learning/attention)")
@click.option("--vault", default=None, help="Vault root (default: auto-detect)")
def move_source(slug: str, concept: str, vault: str | None) -> None:
    """Move all files for SLUG to raw/CONCEPT/ and update the DB path."""
    if vault:
        vault_root = Path(vault)
    else:
        vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    conn = get_connection(db_path(vault_root))

    # Look up the source
    row = conn.execute(
        "SELECT path FROM sources WHERE slug=?", [slug]
    ).fetchone()
    if row is None:
        console.print(f"[red]Source '{slug}' not found in DB.[/red]")
        conn.close()
        sys.exit(1)

    current_rel = Path(row[0])          # e.g. raw/hay2026wedon.md
    current_dir = vault_root / current_rel.parent
    target_dir = vault_root / "raw" / concept
    target_dir.mkdir(parents=True, exist_ok=True)

    # Find all files sharing the slug stem in the current directory
    files_to_move = list(current_dir.glob(f"{slug}.*"))
    if not files_to_move:
        console.print(f"[red]No files found for slug '{slug}' in {current_dir}[/red]")
        conn.close()
        sys.exit(1)

    # Pre-check: abort if any target file already exists
    for f in files_to_move:
        dest = target_dir / f.name
        if dest.exists():
            console.print(f"[red]Target already exists: {dest}[/red]")
            conn.close()
            sys.exit(1)

    # Move all files
    for f in files_to_move:
        dest = target_dir / f.name
        f.rename(dest)

    # Update DB: path and cluster
    primary_ext = current_rel.suffix
    new_rel = f"raw/{concept}/{slug}{primary_ext}"
    new_cluster = concept

    conn.execute(
        "UPDATE sources SET path=?, cluster=? WHERE slug=?",
        [new_rel, new_cluster, slug],
    )
    conn.close()

    console.print(f"  [green]✓[/green] {slug} → raw/{concept}/")
    console.print(f"  Path:    {new_rel}")
    console.print(f"  Cluster: {new_cluster}")
```

- [ ] **Step 4: Register in main.py**

Add to `src/lacuna_wiki/cli/main.py`:

```python
from lacuna_wiki.cli.move_source import move_source  # noqa: E402
```

And:

```python
cli.add_command(move_source)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_move_source.py -v
```

Expected: all 5 PASSED

- [ ] **Step 6: Run full suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/lacuna_wiki/cli/move_source.py src/lacuna_wiki/cli/main.py tests/test_move_source.py
git commit -m "feat: lacuna move-source — atomic file move + DB path update"
```

---

### Task 5: Update spec and install skills

- [ ] **Step 1: Update the spec settled decisions**

In `docs/design/2026-04-14-v2-design-draft.md`, add to the Settled Decisions table:

```markdown
| Key derivation (non-academic) | `{author_slug}{year}{title_prefix_5}` — e.g. `hay2026wedon`. Academic PDFs keep BibTeX convention (vaswani2017). Author = channel name for YouTube, domain for anonymous URLs. Title prefix = first 5 alphanumeric chars of slugified title. Fallback: `b`, `c`, ... suffix. |
| move-source CLI | `lacuna move-source SLUG --concept domain/subdomain` — atomically moves all slug-associated files in `raw/`, updates `sources.path` and cluster in DB. Daemon not involved (no raw/ watcher). Enables concept assignment after reading. |
```

- [ ] **Step 2: Reinstall skills**

```bash
lacuna install-skills
```

- [ ] **Step 3: Commit**

```bash
git add docs/design/2026-04-14-v2-design-draft.md
git commit -m "docs: key derivation and move-source in settled decisions"
```
