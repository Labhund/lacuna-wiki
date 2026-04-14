# URL Source Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `lacuna add-source` to accept URLs, fetching content via the Jina reader API, so all source types from the spec can be ingested — not just local files.

**Architecture:** Detect URL input at the top of `add_source()`, fetch markdown from Jina (`https://r.jina.ai/{url}`), parse Jina's title/date headers, attempt DOI extraction for bibtex key derivation (reusing existing PDF machinery), fall through to the shared chunk → embed → register path that already exists. Zero duplication.

**Tech Stack:** `httpx` (already a dependency), `respx` (already in dev deps for mocking), Jina reader API (no auth required for public URLs).

---

## File Map

- **Create:** `src/lacuna_wiki/sources/fetcher.py` — `fetch_url_as_markdown`, `key_from_url`, `parse_jina_headers`
- **Create:** `tests/sources/test_fetcher.py` — unit tests for all three functions
- **Modify:** `src/lacuna_wiki/cli/add_source.py` — URL detection + URL branch before shared code
- **Modify:** `tests/test_add_source.py` — URL add-source integration tests

---

### Task 1: Failing tests for `key_from_url` and `parse_jina_headers`

**Files:**
- Create: `tests/sources/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/sources/test_fetcher.py
from __future__ import annotations

import duckdb
import pytest
import respx
import httpx

from lacuna_wiki.sources.fetcher import key_from_url, parse_jina_headers, fetch_url_as_markdown
from lacuna_wiki.db.schema import init_db


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    init_db(c)
    yield c
    c.close()


# --- key_from_url ---

def test_key_from_url_blog_post(conn):
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    key = key_from_url(url, conn)
    assert key == "thetransformerfamilyv2"


def test_key_from_url_arxiv(conn):
    url = "https://arxiv.org/abs/1706.03762"
    key = key_from_url(url, conn)
    assert key == "170603762"


def test_key_from_url_root_falls_back(conn):
    url = "https://example.com/"
    key = key_from_url(url, conn)
    assert key == "examplecom"


def test_key_from_url_disambiguates(conn):
    # Pre-insert a slug that would collide
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('mypost', 'raw/x.md', 'url')"
    )
    url = "https://example.com/my-post"
    key = key_from_url(url, conn)
    assert key == "mypostb"


def test_key_from_url_strips_query_and_fragment(conn):
    url = "https://example.com/articles/deep-learning?ref=newsletter#section"
    key = key_from_url(url, conn)
    assert key == "deeplearning"


# --- parse_jina_headers ---

_JINA_RESPONSE = """\
Title: Attention Is All You Need
URL Source: https://arxiv.org/abs/1706.03762
Published Time: 2017-06-12

## Abstract

The dominant sequence transduction models are based on complex recurrent...
"""

_JINA_ISO_TIME = """\
Title: My Blog Post
URL Source: https://example.com/my-post
Published Time: 2023-01-27T00:00:00.000Z

Content here.
"""

_JINA_NO_DATE = """\
Title: Some Page
URL Source: https://example.com/page

Content without a date.
"""


def test_parse_jina_headers_title(conn):
    meta = parse_jina_headers(_JINA_RESPONSE)
    assert meta["title"] == "Attention Is All You Need"


def test_parse_jina_headers_date(conn):
    meta = parse_jina_headers(_JINA_RESPONSE)
    assert meta["published_time"] == "2017-06-12"


def test_parse_jina_headers_iso_date_truncated(conn):
    meta = parse_jina_headers(_JINA_ISO_TIME)
    assert meta["published_time"] == "2023-01-27"


def test_parse_jina_headers_no_date(conn):
    meta = parse_jina_headers(_JINA_NO_DATE)
    assert "published_time" not in meta


def test_parse_jina_headers_no_title(conn):
    meta = parse_jina_headers("Just some content without headers.\n")
    assert "title" not in meta
```

- [ ] **Step 2: Run to confirm FAIL**

```
source .venv/bin/activate && python -m pytest tests/sources/test_fetcher.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'key_from_url' from 'lacuna_wiki.sources.fetcher'`

---

### Task 2: Implement `key_from_url` and `parse_jina_headers`

**Files:**
- Create: `src/lacuna_wiki/sources/fetcher.py`

- [ ] **Step 1: Write implementation**

```python
# src/lacuna_wiki/sources/fetcher.py
"""URL source fetching via the Jina reader API."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import duckdb
import httpx

from lacuna_wiki.sources.key import _disambiguate

_JINA_BASE = "https://r.jina.ai/"


def key_from_url(url: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Derive a stable slug from a URL, disambiguated against existing sources.

    Strategy: take the last non-empty path segment (or domain if path is /),
    strip non-alphanumeric chars, lowercase, truncate to 40 chars.
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        raw = segments[-1]
    else:
        # Root URL — use domain without TLD noise
        raw = parsed.netloc.split(":")[0]  # strip port if any
    base = re.sub(r"[^a-z0-9]", "", raw.lower())[:40] or "url"
    return _disambiguate(base, conn)


def parse_jina_headers(markdown: str) -> dict:
    """Extract metadata from Jina reader response headers.

    Jina prepends a header block before the first blank line:
        Title: Some Title
        URL Source: https://...
        Published Time: 2023-01-27  (or ISO 8601 with time component)

    Returns a dict with keys 'title' and/or 'published_time' (YYYY-MM-DD string).
    Only includes keys that were present in the response.
    """
    result: dict = {}
    for line in markdown.splitlines():
        if not line.strip():
            break  # end of header block
        if line.startswith("Title:"):
            result["title"] = line[len("Title:"):].strip()
        elif line.startswith("Published Time:"):
            raw = line[len("Published Time:"):].strip()
            # Normalise ISO 8601 with time component to YYYY-MM-DD
            result["published_time"] = raw[:10]
    return result


def fetch_url_as_markdown(url: str) -> str:
    """Fetch a URL via the Jina reader API and return clean markdown.

    Raises httpx.HTTPStatusError on non-2xx responses.
    Raises httpx.RequestError on network failures.
    """
    jina_url = _JINA_BASE + url
    resp = httpx.get(
        jina_url,
        timeout=30.0,
        headers={"User-Agent": "lacuna/2.0 (research tool)"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text
```

- [ ] **Step 2: Run tests**

```
source .venv/bin/activate && python -m pytest tests/sources/test_fetcher.py -k "not fetch_url" -v
```

Expected: all `key_from_url` and `parse_jina_headers` tests pass.

---

### Task 3: Failing test for `fetch_url_as_markdown`

**Files:**
- Modify: `tests/sources/test_fetcher.py`

- [ ] **Step 1: Add respx-mocked HTTP tests**

Append to `tests/sources/test_fetcher.py`:

```python
# --- fetch_url_as_markdown ---

@respx.mock
def test_fetch_url_returns_markdown():
    url = "https://example.com/my-article"
    respx.get("https://r.jina.ai/https://example.com/my-article").mock(
        return_value=httpx.Response(200, text="Title: My Article\n\nContent here.")
    )
    result = fetch_url_as_markdown(url)
    assert "Title: My Article" in result
    assert "Content here" in result


@respx.mock
def test_fetch_url_raises_on_404():
    url = "https://example.com/not-found"
    respx.get("https://r.jina.ai/https://example.com/not-found").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_url_as_markdown(url)
```

- [ ] **Step 2: Run to confirm tests pass**

```
source .venv/bin/activate && python -m pytest tests/sources/test_fetcher.py -v
```

Expected: all tests pass (implementation was already written in Task 2).

---

### Task 4: Failing tests for URL `add-source` CLI

**Files:**
- Modify: `tests/test_add_source.py`

- [ ] **Step 1: Add URL add-source tests**

Append to `tests/test_add_source.py`:

```python
import respx
import httpx

_JINA_BLOG = """\
Title: The Transformer Family
URL Source: https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/
Published Time: 2023-01-27

## Overview

Transformers are a type of neural network architecture.

## Key Properties

The attention mechanism is central. [[vaswani2017.md]]
"""

_JINA_ARXIV = """\
Title: Attention Is All You Need
URL Source: https://arxiv.org/abs/1706.03762
Published Time: 2017-06-12

10.48550/arXiv.1706.03762

## Abstract

The dominant sequence transduction models...
"""

_BIBTEX = """@article{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and others},
  year={2017}
}
"""


@respx.mock
def test_add_url_source_creates_sources_row(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    result = CliRunner().invoke(add_source, [url])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


@respx.mock
def test_add_url_source_type_is_url(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "url"


@respx.mock
def test_add_url_source_title_from_jina_headers(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url])
    conn = duckdb.connect(str(db_path(vault)))
    title = conn.execute("SELECT title FROM sources").fetchone()[0]
    conn.close()
    assert title == "The Transformer Family"


@respx.mock
def test_add_url_source_date_from_jina_headers(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url])
    conn = duckdb.connect(str(db_path(vault)))
    pub_date = conn.execute("SELECT published_date FROM sources").fetchone()[0]
    conn.close()
    assert str(pub_date) == "2023-01-27"


@respx.mock
def test_add_url_source_writes_md_file(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url])
    md_files = list((vault / "raw").rglob("*.md"))
    assert len(md_files) == 1
    assert "Transformers" in md_files[0].read_text()


@respx.mock
def test_add_url_source_with_concept(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url, "--concept", "machine-learning"])
    assert (vault / "raw" / "machine-learning").is_dir()


@respx.mock
def test_add_url_source_output_contains_cite_as(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    result = CliRunner().invoke(add_source, [url])
    assert "Cite as:" in result.output
    assert "[[" in result.output


@respx.mock
def test_add_url_source_doi_uses_bibtex_key(vault, monkeypatch):
    """When Jina content contains a DOI, the key is derived from bibtex author+year."""
    monkeypatch.chdir(vault)
    # Mock Jina fetch
    url = "https://arxiv.org/abs/1706.03762"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_ARXIV)
    )
    # Mock CrossRef bibtex fetch
    respx.get(
        "https://api.crossref.org/works/10.48550/arXiv.1706.03762/transform/application/x-bibtex"
    ).mock(return_value=httpx.Response(200, text=_BIBTEX))

    result = CliRunner().invoke(add_source, [url])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    slug = conn.execute("SELECT slug FROM sources").fetchone()[0]
    conn.close()
    assert slug == "vaswani2017"


@respx.mock
def test_add_url_source_type_override(vault, monkeypatch):
    monkeypatch.chdir(vault)
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    respx.get(f"https://r.jina.ai/{url}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [url, "--type", "blog"])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "blog"
```

- [ ] **Step 2: Run to confirm FAIL**

```
source .venv/bin/activate && python -m pytest tests/test_add_source.py -k "url" -v 2>&1 | head -40
```

Expected: FAIL — `add_source` does not handle URL input yet.

---

### Task 5: Implement URL branch in `add_source.py`

**Files:**
- Modify: `src/lacuna_wiki/cli/add_source.py`

The current file starts with a `Path(input_path).resolve()` which will fail for URLs. The fix: detect URL at the very top, run URL-specific setup (fetch, key, metadata), then fall through to the shared chunk → embed → register path.

- [ ] **Step 1: Add import and URL branch**

After the existing imports in `add_source.py`, add `fetch_url_as_markdown`, `key_from_url`, and `parse_jina_headers` to the imports:

```python
# add to existing imports in add_source.py
from lacuna_wiki.sources.fetcher import fetch_url_as_markdown, key_from_url, parse_jina_headers
```

- [ ] **Step 2: Refactor `add_source()` to support URL input**

Replace the current body of `add_source()` with this version that forks early for URLs:

```python
@click.command("add-source")
@click.argument("input_path", metavar="PATH_OR_URL")
@click.option("--concept", default="", help="Subdirectory within raw/ (e.g. machine-learning/attention)")
@click.option("--type", "source_type", type=click.Choice(_SOURCE_TYPES), default=None,
              help="Source type (inferred from input if omitted)")
@click.option("--date", "pub_date", default=None, metavar="YYYY-MM-DD",
              help="Published date (for sources without discoverable date)")
@click.option("--title", default=None, help="Override title")
@click.option("--authors", default=None, help="Override authors")
def add_source(
    input_path: str,
    concept: str,
    source_type: str | None,
    pub_date: str | None,
    title: str | None,
    authors: str | None,
) -> None:
    """Register a source file or URL in the wiki."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    target_dir = vault_root / "raw" / concept if concept else vault_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path(vault_root))

    is_url = input_path.startswith(("http://", "https://"))

    if is_url:
        # --- URL path ---
        url = input_path
        console.print(f"  Fetching [bold]{url}[/bold] via Jina reader...")
        try:
            text = fetch_url_as_markdown(url)
        except Exception as exc:
            console.print(f"[red]Fetch failed:[/red] {exc}")
            conn.close()
            sys.exit(1)

        jina_meta = parse_jina_headers(text)

        # Key: prefer bibtex (via DOI) for academic URLs, fall back to URL segment
        bibtex_str: str | None = None
        parsed_meta: dict = {}
        doi = extract_doi(text[:4000])
        if doi:
            console.print(f"  DOI found: {doi} — fetching bibtex from CrossRef...")
            bibtex_str = fetch_bibtex(doi)
            if bibtex_str:
                parsed_meta = parse_bibtex_fields(bibtex_str)
                console.print(f"  [green]✓[/green] Bibtex retrieved")

        key = (derive_key_from_bibtex(bibtex_str, conn) if bibtex_str
               else key_from_url(url, conn))

        md_dest = target_dir / f"{key}.md"
        md_dest.write_text(text, encoding="utf-8")
        if bibtex_str:
            (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")

        primary_dest = md_dest
        cite_ext = ".md"
        inferred_type = source_type or "url"

        # Metadata: CLI flags > bibtex > Jina headers
        final_title = title or parsed_meta.get("title") or jina_meta.get("title")
        final_authors = authors or parsed_meta.get("authors")
        final_date: date | None = None
        if pub_date:
            final_date = date.fromisoformat(pub_date)
        elif "year" in parsed_meta:
            final_date = date(int(parsed_meta["year"]), 1, 1)
        elif "published_time" in jina_meta:
            try:
                final_date = date.fromisoformat(jina_meta["published_time"])
            except ValueError:
                pass

    else:
        # --- File path ---
        src = Path(input_path).resolve()
        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
            conn.close()
            sys.exit(1)

        suffix = src.suffix.lower()
        inferred_type = source_type or ("paper" if suffix == ".pdf" else "note")

        console.print(f"  Extracting [bold]{src.name}[/bold]...")
        text = extract_text(src)

        bibtex_str = None
        parsed_meta = {}
        if suffix == ".pdf":
            doi = extract_doi(text[:4000])
            if doi:
                console.print(f"  DOI found: {doi} — fetching bibtex from CrossRef...")
                bibtex_str = fetch_bibtex(doi)
                if bibtex_str:
                    parsed_meta = parse_bibtex_fields(bibtex_str)
                    console.print(f"  [green]✓[/green] Bibtex retrieved")
                else:
                    console.print(f"  [yellow]⚠[/yellow] CrossRef returned nothing — using filename as key")

        key = (derive_key_from_bibtex(bibtex_str, conn) if bibtex_str
               else derive_key(src.stem, conn))

        if suffix == ".pdf":
            primary_dest = target_dir / f"{key}.pdf"
            md_dest = target_dir / f"{key}.md"
            shutil.copy2(src, primary_dest)
            md_dest.write_text(text, encoding="utf-8")
            if bibtex_str:
                (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
            cite_ext = ".pdf"
        else:
            md_dest = target_dir / f"{key}{suffix}"
            shutil.copy2(src, md_dest)
            primary_dest = md_dest
            cite_ext = suffix

        final_title = title or parsed_meta.get("title")
        final_authors = authors or parsed_meta.get("authors")
        final_date = None
        if pub_date:
            final_date = date.fromisoformat(pub_date)
        elif "year" in parsed_meta:
            final_date = date(int(parsed_meta["year"]), 1, 1)

    source_type = inferred_type
    console.print(f"  [green]✓[/green] {primary_dest.relative_to(vault_root)}")

    # --- Shared: chunk → embed → register ---
    strategy = _CHUNK_STRATEGY.get(source_type, "paragraph")
    chunks = chunk_md(md_dest, strategy=strategy)
    if not chunks:
        console.print("  [yellow]⚠[/yellow] No chunks produced — file may be empty")
        conn.close()
        return

    console.print(f"  {len(chunks)} chunks — embedding...")
    embeddings = embed_texts([c.text for c in chunks])

    rel_path = str(primary_dest.relative_to(vault_root))
    source_id = register_source(conn, key, rel_path, final_title, final_authors, final_date, source_type)
    register_chunks(conn, source_id, chunks, embeddings)
    conn.close()

    console.print(f"\n  Read:    {md_dest.relative_to(vault_root)}")
    console.print(f"  Cite as: [[{key}{cite_ext}]]", markup=False)
```

- [ ] **Step 3: Run all add-source tests**

```
source .venv/bin/activate && python -m pytest tests/test_add_source.py -v
```

Expected: all tests pass.

---

### Task 6: Full suite

- [ ] **Step 1: Run full test suite**

```
source .venv/bin/activate && python -m pytest -v 2>&1 | tail -20
```

Expected: all tests pass, count ≥ 218 (198 existing + ~10 fetcher + ~9 URL add-source).

- [ ] **Step 2: Commit**

```bash
git add src/lacuna_wiki/sources/fetcher.py \
        src/lacuna_wiki/cli/add_source.py \
        tests/sources/test_fetcher.py \
        tests/test_add_source.py
git commit -m "feat: add URL source ingestion via Jina reader

add-source now accepts URLs (http/https). Content is fetched via the
Jina reader API (r.jina.ai), which returns clean markdown. Title and
date are parsed from Jina's header block. If the content contains a
DOI, bibtex is fetched from CrossRef and used for key derivation
(e.g. vaswani2017 for arxiv URLs). Falls through to the shared
chunk → embed → register path, so all source types work identically
after fetch."
```
