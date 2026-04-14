# Source Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `lacuna add-source` — the single entry point for registering sources, which extracts text, derives a canonical key, chunks, embeds, writes files to `raw/`, and inserts into `sources` + `source_chunks` tables.

**Architecture:** Nine focused modules under `src/lacuna_wiki/sources/` each with one responsibility; the CLI command in `cli/add_source.py` wires them together. Embedding is done via the local Ollama-compatible HTTP server at `http://localhost:8005`. PDF text extraction uses `pdftotext` (system binary). `.md` input skips extraction and registers directly. Config via env vars (`LACUNA_EMBED_URL`, `LACUNA_EMBED_MODEL`).

**Tech Stack:** Python 3.11+, httpx (HTTP client for embeddings + CrossRef), existing DuckDB schema from Plan 1, pdftotext system binary (poppler-utils)

**System requirement:** `pdftotext` must be installed (`pacman -S poppler` on Arch).

---

## File Map

```
src/lacuna_wiki/
  tokens.py                  — count_tokens(text) -> int
  sources/
    __init__.py
    key.py                   — derive_key, derive_key_from_bibtex, _disambiguate
    chunker.py               — Chunk dataclass, chunk_md(path, strategy)
    embedder.py              — embed_texts(texts, url, model) -> list[list[float]]
    extractor.py             — extract_text(path) -> str (.md passthrough, pdftotext)
    metadata.py              — extract_doi, fetch_bibtex, parse_bibtex_fields
    register.py              — register_source, register_chunks
  cli/
    add_source.py            — `lacuna add-source` Click command
    main.py                  — add add_source command (modify existing)
tests/
  sources/
    __init__.py
    test_key.py
    test_chunker.py
    test_embedder.py
    test_extractor.py
    test_metadata.py
    test_register.py
  test_add_source.py         — integration: add .md end-to-end
```

---

## Task 1: Token counter + dependencies

**Files:**
- Create: `src/lacuna_wiki/tokens.py`
- Modify: `pyproject.toml` (add httpx)
- Create: `src/lacuna_wiki/sources/__init__.py`
- Create: `tests/sources/__init__.py`

- [ ] **Step 1: Add httpx to pyproject.toml**

```toml
dependencies = [
    "click>=8.0",
    "duckdb>=0.10.0",
    "rich>=13.0",
    "tomli-w>=1.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Install**

```bash
uv pip install -e ".[dev]"
```

Expected: `+ httpx==...` in output.

- [ ] **Step 3: Create package markers**

`src/lacuna_wiki/sources/__init__.py` — empty.
`tests/sources/__init__.py` — empty.

- [ ] **Step 4: Write `src/lacuna_wiki/tokens.py`**

```python
def count_tokens(text: str) -> int:
    """Estimate token count. Good enough for budgeting."""
    return len(text) // 4
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/lacuna_wiki/tokens.py src/lacuna_wiki/sources/__init__.py tests/sources/__init__.py
git commit -m "chore: add httpx dep, token counter, sources package"
```

---

## Task 2: Key derivation

**Files:**
- Create: `src/lacuna_wiki/sources/key.py`
- Create: `tests/sources/test_key.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_key.py
import duckdb
import pytest
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex


@pytest.fixture
def empty_conn():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    return conn


@pytest.fixture
def conn_with_vaswani(empty_conn):
    empty_conn.execute("INSERT INTO sources VALUES ('vaswani2017')")
    return empty_conn


def test_derive_key_from_clean_stem(empty_conn):
    assert derive_key("vaswani2017", empty_conn) == "vaswani2017"


def test_derive_key_lowercases(empty_conn):
    assert derive_key("Vaswani2017", empty_conn) == "vaswani2017"


def test_derive_key_strips_non_alnum(empty_conn):
    assert derive_key("vaswani_2017_attention", empty_conn) == "vaswani2017attention"


def test_derive_key_disambiguates(conn_with_vaswani):
    assert derive_key("vaswani2017", conn_with_vaswani) == "vaswani2017b"


def test_derive_key_disambiguates_twice(conn_with_vaswani):
    conn_with_vaswani.execute("INSERT INTO sources VALUES ('vaswani2017b')")
    assert derive_key("vaswani2017", conn_with_vaswani) == "vaswani2017c"


def test_derive_key_from_bibtex_last_name_year(empty_conn):
    bibtex = """@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam},
  year = {2017},
  title = {Attention Is All You Need},
}"""
    assert derive_key_from_bibtex(bibtex, empty_conn) == "vaswani2017"


def test_derive_key_from_bibtex_non_comma_author(empty_conn):
    bibtex = """@article{ho2020denoising,
  author = {Jonathan Ho and Ajay Jain and Pieter Abbeel},
  year = {2020},
  title = {Denoising Diffusion Probabilistic Models},
}"""
    assert derive_key_from_bibtex(bibtex, empty_conn) == "abbeel2020"


def test_derive_key_from_bibtex_disambiguates(conn_with_vaswani):
    bibtex = """@article{vaswani2017,
  author = {Vaswani, Ashish},
  year = {2017},
  title = {Attention Is All You Need},
}"""
    assert derive_key_from_bibtex(bibtex, conn_with_vaswani) == "vaswani2017b"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_key.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.sources.key'`

- [ ] **Step 3: Write `src/lacuna_wiki/sources/key.py`**

```python
from __future__ import annotations

import re
import duckdb


def derive_key(stem: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Derive canonical key from a filename stem, disambiguating against the sources table."""
    base = re.sub(r"[^a-z0-9]", "", stem.lower())[:40] or "source"
    return _disambiguate(base, conn)


def derive_key_from_bibtex(bibtex: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Build author+year key from a BibTeX string, disambiguating against the sources table."""
    author_m = re.search(r"author\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    year_m = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex, re.IGNORECASE)

    if author_m and year_m:
        authors_raw = author_m.group(1)
        year = year_m.group(1)
        # Take first author. BibTeX lists: "Last, First and Last2, First2" or "First Last and ..."
        first_author = authors_raw.split(" and ")[0].strip()
        if "," in first_author:
            last_name = first_author.split(",")[0].strip()
        else:
            # "First Last" format — take final token as last name
            last_name = first_author.split()[-1]
        base = re.sub(r"[^a-z]", "", last_name.lower()) + year
    else:
        # Fall back to bibtex entry key
        key_m = re.search(r"@\w+\{([^,]+),", bibtex)
        base = re.sub(r"[^a-z0-9]", "", key_m.group(1).lower()) if key_m else "source"

    return _disambiguate(base, conn)


def _disambiguate(base: str, conn: duckdb.DuckDBPyConnection) -> str:
    existing = {row[0] for row in conn.execute("SELECT slug FROM sources").fetchall()}
    if base not in existing:
        return base
    for suffix in "bcdefghijklmnopqrstuvwxyz":
        candidate = base + suffix
        if candidate not in existing:
            return candidate
    raise ValueError(f"Cannot find unique key for '{base}' — too many disambiguations")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/sources/test_key.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/key.py tests/sources/test_key.py
git commit -m "feat: canonical key derivation with DB disambiguation"
```

---

## Task 3: Chunker

**Files:**
- Create: `src/lacuna_wiki/sources/chunker.py`
- Create: `tests/sources/test_chunker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_chunker.py
from pathlib import Path
import pytest
from lacuna_wiki.sources.chunker import Chunk, chunk_md


def write_md(tmp_path, content: str) -> Path:
    p = tmp_path / "test.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_heading_strategy_splits_on_headings(tmp_path):
    md = write_md(tmp_path, "## Overview\n\nSome text.\n\n## Methods\n\nMore text.\n")
    chunks = chunk_md(md, strategy="heading")
    assert len(chunks) == 2
    assert chunks[0].heading == "Overview"
    assert chunks[1].heading == "Methods"


def test_heading_strategy_returns_correct_line_offsets(tmp_path):
    md = write_md(tmp_path, "## Overview\n\nSome text.\n\n## Methods\n\nMore text.\n")
    chunks = chunk_md(md, strategy="heading")
    assert chunks[0].start_line == 1
    assert chunks[1].start_line == 5


def test_heading_strategy_falls_back_to_paragraph_when_no_headings(tmp_path):
    md = write_md(tmp_path, "Paragraph one.\n\nParagraph two.\n")
    chunks = chunk_md(md, strategy="heading")
    assert len(chunks) == 2
    assert chunks[0].heading is None


def test_paragraph_strategy_splits_on_blank_lines(tmp_path):
    md = write_md(tmp_path, "First paragraph.\n\nSecond paragraph.\n")
    chunks = chunk_md(md, strategy="paragraph")
    assert len(chunks) == 2
    assert chunks[0].text == "First paragraph."
    assert chunks[1].text == "Second paragraph."


def test_paragraph_strategy_heading_is_none(tmp_path):
    md = write_md(tmp_path, "Some text.\n\nMore text.\n")
    chunks = chunk_md(md, strategy="paragraph")
    assert all(c.heading is None for c in chunks)


def test_fallback_strategy_produces_chunks(tmp_path):
    # Generate content longer than one chunk
    content = "word " * 1000  # ~5000 chars
    md = write_md(tmp_path, content)
    chunks = chunk_md(md, strategy="fallback")
    assert len(chunks) >= 2


def test_chunk_index_is_sequential(tmp_path):
    md = write_md(tmp_path, "## A\n\ntext\n\n## B\n\ntext\n\n## C\n\ntext\n")
    chunks = chunk_md(md, strategy="heading")
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_chunk_token_count_is_nonzero(tmp_path):
    md = write_md(tmp_path, "## Section\n\nSome text here.\n")
    chunks = chunk_md(md, strategy="heading")
    assert all(c.token_count > 0 for c in chunks)


def test_chunk_text_matches_file_content(tmp_path):
    md = write_md(tmp_path, "## Intro\n\nHello world.\n")
    chunks = chunk_md(md, strategy="heading")
    assert "Hello world" in chunks[0].text


def test_single_paragraph_no_blank_lines(tmp_path):
    md = write_md(tmp_path, "Just one paragraph with no blank lines.\n")
    chunks = chunk_md(md, strategy="paragraph")
    assert len(chunks) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_chunker.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/lacuna_wiki/sources/chunker.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lacuna_wiki.tokens import count_tokens

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$")

_FALLBACK_CHARS = 2048
_FALLBACK_OVERLAP = 200


@dataclass
class Chunk:
    chunk_index: int
    heading: str | None   # section title, timestamp, or None
    start_line: int        # 1-indexed, inclusive
    end_line: int          # 1-indexed, inclusive
    token_count: int
    text: str              # used for embedding — NOT stored in DB


def chunk_md(path: Path, strategy: str = "heading") -> list[Chunk]:
    """Chunk a markdown file. strategy: 'heading' | 'paragraph' | 'fallback'."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if strategy == "heading":
        return _chunk_by_heading(lines)
    elif strategy == "paragraph":
        return _chunk_by_paragraph(lines)
    else:
        return _chunk_fallback(lines)


def _chunk_by_heading(lines: list[str]) -> list[Chunk]:
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m:
            boundaries.append((i, m.group(1).strip()))

    if not boundaries:
        return _chunk_by_paragraph(lines)

    chunks: list[Chunk] = []
    for idx, (start_0, heading) in enumerate(boundaries):
        end_0 = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines) - 1
        text = "\n".join(lines[start_0 : end_0 + 1]).strip()
        if not text:
            continue
        chunks.append(Chunk(
            chunk_index=len(chunks),
            heading=heading,
            start_line=start_0 + 1,
            end_line=end_0 + 1,
            token_count=count_tokens(text),
            text=text,
        ))
    return chunks


def _chunk_by_paragraph(lines: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_start_0 = 0
    current_lines: list[str] = []

    def _flush(end_0: int) -> None:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(Chunk(
                chunk_index=len(chunks),
                heading=None,
                start_line=current_start_0 + 1,
                end_line=end_0,   # i (0-indexed blank) == last content line (1-indexed)
                token_count=count_tokens(text),
                text=text,
            ))

    for i, line in enumerate(lines):
        if line.strip() == "" and current_lines:
            _flush(i)           # i is 0-indexed blank = 1-indexed last content line
            current_lines = []
            current_start_0 = i + 1
        else:
            if not current_lines:
                current_start_0 = i
            current_lines.append(line)

    if current_lines:
        _flush(len(lines))

    return chunks


def _chunk_fallback(lines: list[str]) -> list[Chunk]:
    text = "\n".join(lines)
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + _FALLBACK_CHARS, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            start_line = text[:start].count("\n") + 1
            end_line = text[:end].count("\n") + 1
            chunks.append(Chunk(
                chunk_index=len(chunks),
                heading=None,
                start_line=start_line,
                end_line=end_line,
                token_count=count_tokens(chunk_text),
                text=chunk_text,
            ))
        start = end - _FALLBACK_OVERLAP if end < len(text) else len(text)
    return chunks
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/sources/test_chunker.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/chunker.py src/lacuna_wiki/tokens.py tests/sources/test_chunker.py
git commit -m "feat: markdown chunker — heading, paragraph, fallback strategies with line offsets"
```

---

## Task 4: Embedder

**Files:**
- Create: `src/lacuna_wiki/sources/embedder.py`
- Create: `tests/sources/test_embedder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_embedder.py
import pytest
import httpx
from lacuna_wiki.sources.embedder import embed_texts


def test_embed_texts_returns_correct_count(respx_mock):
    """embed_texts returns one vector per input text."""
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"index": 0, "embedding": [0.1] * 768},
                {"index": 1, "embedding": [0.2] * 768},
            ]
        })
    )
    result = embed_texts(["hello", "world"])
    assert len(result) == 2


def test_embed_texts_returns_correct_dimensions(respx_mock):
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [{"index": 0, "embedding": [0.1] * 768}]
        })
    )
    result = embed_texts(["hello"])
    assert len(result[0]) == 768


def test_embed_texts_preserves_order(respx_mock):
    """Results are sorted by index even if server returns out of order."""
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"index": 1, "embedding": [0.2] * 768},
                {"index": 0, "embedding": [0.1] * 768},
            ]
        })
    )
    result = embed_texts(["first", "second"])
    assert result[0][0] == pytest.approx(0.1)
    assert result[1][0] == pytest.approx(0.2)


def test_embed_texts_raises_on_http_error(respx_mock):
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(500, json={"error": "server error"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        embed_texts(["hello"])
```

- [ ] **Step 2: Install respx (mock library for httpx)**

Add to `pyproject.toml` dev deps:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "respx>=0.20"]
```

```bash
uv pip install -e ".[dev]"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_embedder.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.sources.embedder'`

- [ ] **Step 4: Write `src/lacuna_wiki/sources/embedder.py`**

```python
from __future__ import annotations

import os

import httpx

_DEFAULT_URL = "http://localhost:8005"
_DEFAULT_MODEL = "nomic-embed-text:v1.5"


def embed_texts(
    texts: list[str],
    url: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts via the local Ollama-compatible HTTP server.

    Returns one 768-dim float vector per input text.
    Raises httpx.HTTPStatusError on non-2xx responses.

    Config (env vars override defaults):
      LACUNA_EMBED_URL   — default http://localhost:8005
      LACUNA_EMBED_MODEL — default nomic-embed-text:v1.5
    """
    url = (url or os.environ.get("LACUNA_EMBED_URL", _DEFAULT_URL)).rstrip("/")
    model = model or os.environ.get("LACUNA_EMBED_MODEL", _DEFAULT_MODEL)

    response = httpx.post(
        f"{url}/v1/embeddings",
        json={"model": model, "input": texts},
        timeout=60.0,
    )
    response.raise_for_status()
    items = sorted(response.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/sources/test_embedder.py -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lacuna_wiki/sources/embedder.py tests/sources/test_embedder.py pyproject.toml
git commit -m "feat: embedder — nomic-embed-text via Ollama HTTP API"
```

---

## Task 5: Text extractor

**Files:**
- Create: `src/lacuna_wiki/sources/extractor.py`
- Create: `tests/sources/test_extractor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_extractor.py
import subprocess
from pathlib import Path
import pytest
from lacuna_wiki.sources.extractor import extract_text


def test_extract_md_returns_content(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("# Hello\n\nWorld.\n")
    assert extract_text(md) == "# Hello\n\nWorld.\n"


def test_extract_markdown_extension(tmp_path):
    f = tmp_path / "test.markdown"
    f.write_text("content")
    assert extract_text(f) == "content"


def test_extract_unsupported_raises(tmp_path):
    f = tmp_path / "test.docx"
    f.write_text("content")
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(f)


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "missing.md")


def test_extract_pdf_calls_pdftotext(tmp_path, monkeypatch):
    """PDF extraction shells out to pdftotext."""
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")  # not a real PDF — pdftotext is mocked

    def fake_run(args, **kwargs):
        class R:
            returncode = 0
            stdout = b"Extracted text from PDF."
            stderr = b""
        return R()

    monkeypatch.setattr("lacuna_wiki.sources.extractor.subprocess.run", fake_run)
    result = extract_text(pdf)
    assert result == "Extracted text from PDF."


def test_extract_pdf_raises_on_pdftotext_failure(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def fake_run(args, **kwargs):
        class R:
            returncode = 1
            stdout = b""
            stderr = b"Error: PDF damaged"
        return R()

    monkeypatch.setattr("lacuna_wiki.sources.extractor.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="pdftotext failed"):
        extract_text(pdf)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_extractor.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/lacuna_wiki/sources/extractor.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path


def extract_text(path: Path) -> str:
    """Extract text from a source file.

    .md / .markdown — read directly (immutable raw content).
    .pdf            — shell out to pdftotext (requires poppler-utils).
    Anything else   — raises ValueError.
    """
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    suffix = path.suffix.lower()

    if suffix in (".md", ".markdown"):
        return path.read_text(encoding="utf-8")

    if suffix == ".pdf":
        return _pdftotext(path)

    raise ValueError(f"Unsupported file type: {suffix!r}. Supported: .md, .pdf")


def _pdftotext(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pdftotext failed (exit {result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='replace')[:300]}"
        )
    return result.stdout.decode("utf-8", errors="replace")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/sources/test_extractor.py -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/extractor.py tests/sources/test_extractor.py
git commit -m "feat: text extractor — .md passthrough and pdftotext for PDFs"
```

---

## Task 6: Metadata and BibTeX

**Files:**
- Create: `src/lacuna_wiki/sources/metadata.py`
- Create: `tests/sources/test_metadata.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_metadata.py
import httpx
import pytest
from lacuna_wiki.sources.metadata import extract_doi, fetch_bibtex, parse_bibtex_fields


def test_extract_doi_finds_doi_in_text():
    text = "See https://doi.org/10.48550/arXiv.1706.03762 for details."
    assert extract_doi(text) == "10.48550/arXiv.1706.03762"


def test_extract_doi_finds_bare_doi():
    text = "Published as 10.1038/nature12345 in Nature."
    assert extract_doi(text) == "10.1038/nature12345"


def test_extract_doi_returns_none_when_absent():
    assert extract_doi("No DOI here.") is None


def test_parse_bibtex_fields_extracts_title():
    bib = "@article{key,\n  title={Attention Is All You Need},\n  author={Vaswani, A},\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert fields["title"] == "Attention Is All You Need"


def test_parse_bibtex_fields_extracts_authors():
    bib = "@article{key,\n  author={Vaswani, Ashish and Shazeer, Noam},\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert "Vaswani" in fields["authors"]


def test_parse_bibtex_fields_extracts_year():
    bib = "@article{key,\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert fields["year"] == "2017"


def test_parse_bibtex_fields_missing_field_absent_from_dict():
    bib = "@article{key,\n  year={2020}\n}"
    fields = parse_bibtex_fields(bib)
    assert "title" not in fields
    assert "authors" not in fields


def test_fetch_bibtex_returns_string_on_success(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.1234/test/transform/application/x-bibtex").mock(
        return_value=httpx.Response(200, text="@article{key, title={Test}}")
    )
    result = fetch_bibtex("10.1234/test")
    assert result == "@article{key, title={Test}}"


def test_fetch_bibtex_returns_none_on_404(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.9999/notfound/transform/application/x-bibtex").mock(
        return_value=httpx.Response(404)
    )
    result = fetch_bibtex("10.9999/notfound")
    assert result is None


def test_fetch_bibtex_returns_none_on_network_error(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.1234/fail/transform/application/x-bibtex").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = fetch_bibtex("10.1234/fail")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_metadata.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/lacuna_wiki/sources/metadata.py`**

```python
from __future__ import annotations

import re

import httpx

_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s\]>\"']+)")


def extract_doi(text: str) -> str | None:
    """Find the first DOI in text. Returns the bare DOI (e.g. '10.48550/arXiv.1706.03762')."""
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".,;)") if m else None


def fetch_bibtex(doi: str) -> str | None:
    """Fetch BibTeX from CrossRef for a DOI. Returns None on any failure."""
    url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            headers={"User-Agent": "lacuna/2.0 (mailto:research@local.dev)"},
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def parse_bibtex_fields(bibtex: str) -> dict:
    """Extract title, authors, year from a BibTeX string.

    Returns a dict with only the keys that were found.
    """
    result: dict = {}

    title_m = re.search(r"title\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    if title_m:
        result["title"] = re.sub(r"[{}]", "", title_m.group(1)).strip()

    author_m = re.search(r"author\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    if author_m:
        result["authors"] = author_m.group(1).strip()

    year_m = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex, re.IGNORECASE)
    if year_m:
        result["year"] = year_m.group(1)

    return result
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/sources/test_metadata.py -v 2>&1 | tail -12
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/metadata.py tests/sources/test_metadata.py
git commit -m "feat: metadata — DOI extraction, CrossRef bibtex fetch, bibtex parsing"
```

---

## Task 7: DB registration

**Files:**
- Create: `src/lacuna_wiki/sources/register.py`
- Create: `tests/sources/test_register.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_register.py
from datetime import date, datetime
import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.sources.chunker import Chunk
from lacuna_wiki.sources.register import register_chunks, register_source


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    init_db(c)
    return c


def test_register_source_inserts_row(conn):
    source_id = register_source(conn, "vaswani2017", "raw/vaswani2017.pdf",
                                "Attention Is All You Need", "Vaswani et al.",
                                date(2017, 6, 12), "paper")
    row = conn.execute("SELECT slug, path, title, source_type FROM sources WHERE id = ?",
                       [source_id]).fetchone()
    assert row == ("vaswani2017", "raw/vaswani2017.pdf", "Attention Is All You Need", "paper")


def test_register_source_sets_registered_at(conn):
    source_id = register_source(conn, "test2024", "raw/test.md", None, None, None, "note")
    ts = conn.execute("SELECT registered_at FROM sources WHERE id = ?", [source_id]).fetchone()[0]
    assert ts is not None


def test_register_source_returns_id(conn):
    id1 = register_source(conn, "paper1", "raw/p1.pdf", None, None, None, "paper")
    id2 = register_source(conn, "paper2", "raw/p2.pdf", None, None, None, "paper")
    assert id1 != id2


def _make_chunk(idx: int, text: str = "some text") -> Chunk:
    return Chunk(
        chunk_index=idx, heading=f"Section {idx}",
        start_line=idx * 10 + 1, end_line=idx * 10 + 5,
        token_count=len(text) // 4, text=text,
    )


def test_register_chunks_inserts_rows(conn):
    source_id = register_source(conn, "src1", "raw/src1.md", None, None, None, "note")
    chunks = [_make_chunk(0, "text one"), _make_chunk(1, "text two")]
    embeddings = [[0.1] * 768, [0.2] * 768]
    register_chunks(conn, source_id, chunks, embeddings)
    count = conn.execute("SELECT COUNT(*) FROM source_chunks WHERE source_id = ?",
                         [source_id]).fetchone()[0]
    assert count == 2


def test_register_chunks_stores_offsets(conn):
    source_id = register_source(conn, "src2", "raw/src2.md", None, None, None, "note")
    chunk = _make_chunk(0, "hello")
    register_chunks(conn, source_id, [chunk], [[0.5] * 768])
    row = conn.execute(
        "SELECT chunk_index, heading, start_line, end_line FROM source_chunks WHERE source_id = ?",
        [source_id]
    ).fetchone()
    assert row == (0, "Section 0", 1, 5)


def test_register_chunks_stores_embedding(conn):
    source_id = register_source(conn, "src3", "raw/src3.md", None, None, None, "note")
    embedding = [float(i) / 768 for i in range(768)]
    register_chunks(conn, source_id, [_make_chunk(0)], [embedding])
    stored = conn.execute(
        "SELECT embedding FROM source_chunks WHERE source_id = ?", [source_id]
    ).fetchone()[0]
    assert len(stored) == 768
    assert abs(stored[0] - 0.0) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/sources/test_register.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/lacuna_wiki/sources/register.py`**

```python
from __future__ import annotations

from datetime import date, datetime

import duckdb

from lacuna_wiki.sources.chunker import Chunk


def register_source(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    path: str,
    title: str | None,
    authors: str | None,
    published_date: date | None,
    source_type: str,
) -> int:
    """Insert a row into the sources table. Returns the new source id."""
    conn.execute(
        """INSERT INTO sources (slug, path, title, authors, published_date, registered_at, source_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [slug, path, title, authors, published_date, datetime.utcnow(), source_type],
    )
    return conn.execute("SELECT id FROM sources WHERE slug = ?", [slug]).fetchone()[0]


def register_chunks(
    conn: duckdb.DuckDBPyConnection,
    source_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    """Insert source_chunks rows. Text is NOT stored — only offsets and embedding."""
    for chunk, embedding in zip(chunks, embeddings):
        conn.execute(
            """INSERT INTO source_chunks
               (source_id, chunk_index, heading, start_line, end_line, token_count, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [source_id, chunk.chunk_index, chunk.heading,
             chunk.start_line, chunk.end_line, chunk.token_count, embedding],
        )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/sources/test_register.py -v 2>&1 | tail -12
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/sources/register.py tests/sources/test_register.py
git commit -m "feat: DB registration — sources and source_chunks insertion"
```

---

## Task 8: CLI command

**Files:**
- Create: `src/lacuna_wiki/cli/add_source.py`
- Modify: `src/lacuna_wiki/cli/main.py`

- [ ] **Step 1: Write `src/lacuna_wiki/cli/add_source.py`**

```python
"""lacuna add-source — register a source in the vault."""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.db.connection import get_connection
from lacuna_wiki.sources.chunker import chunk_md
from lacuna_wiki.sources.embedder import embed_texts
from lacuna_wiki.sources.extractor import extract_text
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex
from lacuna_wiki.sources.metadata import extract_doi, fetch_bibtex, parse_bibtex_fields
from lacuna_wiki.sources.register import register_chunks, register_source
from lacuna_wiki.vault import db_path, find_vault_root

console = Console()

_SOURCE_TYPES = [
    "paper", "preprint", "book", "blog", "url", "podcast",
    "transcript", "session", "note", "experiment",
]

# Chunking strategy per source type
_CHUNK_STRATEGY = {
    "paper": "heading", "preprint": "heading", "book": "heading",
    "blog": "paragraph", "url": "paragraph",
    "podcast": "heading", "transcript": "heading",
    "session": "paragraph", "note": "paragraph", "experiment": "paragraph",
}


@click.command("add-source")
@click.argument("input_path", metavar="PATH")
@click.option("--concept", default="", help="Subdirectory within raw/ (e.g. machine-learning/attention)")
@click.option("--type", "source_type", type=click.Choice(_SOURCE_TYPES), default=None,
              help="Source type (inferred from extension if omitted)")
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
    """Register a source file in the wiki."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    src = Path(input_path).resolve()
    if not src.exists():
        console.print(f"[red]File not found:[/red] {src}")
        sys.exit(1)

    suffix = src.suffix.lower()
    if source_type is None:
        source_type = "paper" if suffix == ".pdf" else "note"

    target_dir = vault_root / "raw" / concept if concept else vault_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path(vault_root))

    # 1 — Extract text
    console.print(f"  Extracting [bold]{src.name}[/bold]...")
    text = extract_text(src)

    # 2 — Metadata + key
    bibtex_str: str | None = None
    parsed_meta: dict = {}

    if suffix == ".pdf":
        doi = extract_doi(text[:4000])  # scan first ~page for DOI
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

    # 3 — Write files
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

    console.print(f"  [green]✓[/green] {primary_dest.relative_to(vault_root)}")

    # 4 — Resolve metadata
    final_title = title or parsed_meta.get("title")
    final_authors = authors or parsed_meta.get("authors")
    final_date: date | None = None
    if pub_date:
        final_date = date.fromisoformat(pub_date)
    elif "year" in parsed_meta:
        final_date = date(int(parsed_meta["year"]), 1, 1)

    # 5 — Chunk + embed
    strategy = _CHUNK_STRATEGY.get(source_type, "paragraph")
    chunks = chunk_md(md_dest, strategy=strategy)
    if not chunks:
        console.print("  [yellow]⚠[/yellow] No chunks produced — file may be empty")
        conn.close()
        return

    console.print(f"  {len(chunks)} chunks — embedding...")
    embeddings = embed_texts([c.text for c in chunks])

    # 6 — Register
    rel_path = str(primary_dest.relative_to(vault_root))
    source_id = register_source(conn, key, rel_path, final_title, final_authors, final_date, source_type)
    register_chunks(conn, source_id, chunks, embeddings)
    conn.close()

    # 7 — Report
    console.print(f"\n  Read:    {md_dest.relative_to(vault_root)}")
    console.print(f"  Cite as: [[{key}{cite_ext}]]\n")
```

- [ ] **Step 2: Register command in `src/lacuna_wiki/cli/main.py`**

```python
import click


@click.group()
def cli():
    """lacuna v2 — personal research knowledge substrate."""
    pass


from lacuna_wiki.cli.add_source import add_source  # noqa: E402
from lacuna_wiki.cli.init import init               # noqa: E402
from lacuna_wiki.cli.status import status           # noqa: E402
from lacuna_wiki.cli.daemon import start, stop      # noqa: E402

cli.add_command(add_source)
cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
```

- [ ] **Step 3: Verify command appears in help**

```bash
.venv/bin/lacuna --help
```

Expected output includes `add-source`.

```bash
.venv/bin/lacuna add-source --help
```

Expected: shows PATH argument, --concept, --type, --date, --title, --authors.

- [ ] **Step 4: Commit**

```bash
git add src/lacuna_wiki/cli/add_source.py src/lacuna_wiki/cli/main.py
git commit -m "feat: lacuna add-source CLI command"
```

---

## Task 9: Integration test

**Files:**
- Create: `tests/test_add_source.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_add_source.py
"""Integration tests for lacuna add-source.

Embedding calls are monkeypatched — these tests do not require a running server.
PDF extraction is also monkeypatched — these tests do not require pdftotext.
"""
import duckdb
import pytest
from click.testing import CliRunner
from pathlib import Path

from lacuna_wiki.cli.add_source import add_source
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    state = state_dir_for(tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(tmp_path)))
    init_db(conn)
    conn.close()
    return tmp_path


@pytest.fixture(autouse=True)
def mock_embed(monkeypatch):
    """Replace embed_texts with a function that returns fake 768-dim vectors."""
    def fake_embed(texts, **kwargs):
        return [[0.1] * 768 for _ in texts]
    monkeypatch.setattr("lacuna_wiki.cli.add_source.embed_texts", fake_embed)


def _write_source(tmp_path, name="paper.md", content=None):
    if content is None:
        content = "## Introduction\n\nThis paper introduces attention.\n\n## Methods\n\nWe use dot products.\n"
    src = tmp_path / name
    src.write_text(content)
    return src


def test_add_md_source_creates_sources_row(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    result = CliRunner().invoke(add_source, [str(src)])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


def test_add_md_source_creates_chunks(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src)])
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0]
    conn.close()
    assert count >= 1


def test_add_md_source_with_concept(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--concept", "machine-learning/attention"])
    assert (vault / "raw" / "machine-learning" / "attention").is_dir()


def test_add_md_source_slug_from_filename(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path, name="vaswani2017.md")
    CliRunner().invoke(add_source, [str(src)])
    conn = duckdb.connect(str(db_path(vault)))
    slug = conn.execute("SELECT slug FROM sources").fetchone()[0]
    conn.close()
    assert slug == "vaswani2017"


def test_add_md_source_output_contains_cite_as(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path, name="vaswani2017.md")
    result = CliRunner().invoke(add_source, [str(src)])
    assert "[[vaswani2017.md]]" in result.output


def test_add_md_source_with_type_override(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--type", "session"])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "session"


def test_add_md_source_with_date(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--date", "2024-03-15"])
    conn = duckdb.connect(str(db_path(vault)))
    pub_date = conn.execute("SELECT published_date FROM sources").fetchone()[0]
    conn.close()
    assert str(pub_date) == "2024-03-15"


def test_add_md_source_disambiguates_key(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src1 = _write_source(tmp_path, "paper.md", "## A\n\nFirst source.\n")
    src2 = _write_source(tmp_path, "paper2.md", "## B\n\nSecond source.\n")
    # Both resolve to key "paper" from stem
    CliRunner().invoke(add_source, [str(src1)])
    # Force same stem by renaming
    src2_same = tmp_path / "paper.md"
    src2_same.write_text("## B\n\nSecond source.\n")
    CliRunner().invoke(add_source, [str(src2_same)])
    conn = duckdb.connect(str(db_path(vault)))
    slugs = {r[0] for r in conn.execute("SELECT slug FROM sources").fetchall()}
    conn.close()
    assert "paper" in slugs
    assert "paperb" in slugs


def test_add_source_fails_outside_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "paper.md"
    src.write_text("content")
    result = CliRunner().invoke(add_source, [str(src)])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_add_source.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.cli.add_source'`

- [ ] **Step 3: Run tests after implementation**

```bash
.venv/bin/pytest tests/test_add_source.py -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -10
```

Expected: all PASS (28 existing + new tests).

- [ ] **Step 5: Smoke test with a real .md file**

```bash
cd /tmp/smoke-vault
echo "## Introduction\n\nThis is a test note about attention mechanisms.\n\n## Methods\n\nDot product attention.\n" > /tmp/test-note.md
LACUNA_EMBED_URL=http://localhost:8005 .../lacuna add-source /tmp/test-note.md --type note --concept machine-learning
```

Replace `...` with the full path to the venv's lacuna binary. Expected output:

```
  Extracting test-note.md...
  2 chunks — embedding...

  Read:    raw/machine-learning/testnote.md
  Cite as: [[testnote.md]]
```

- [ ] **Step 6: Verify DB state**

```bash
cd /tmp/smoke-vault && .../lacuna status
```

Expected: `sources` shows 1 row, `source_chunks` shows 2 rows.

- [ ] **Step 7: Commit**

```bash
git add tests/test_add_source.py
git commit -m "test: add-source integration tests"
```

---

## Self-review notes

**Spec coverage check:**
- ✓ `add-source path/to/paper.pdf [--concept]` — Task 8
- ✓ Canonical key `{firstauthorlastname}{year}` from bibtex — Task 2 (`derive_key_from_bibtex`)
- ✓ Key disambiguation (`b`, `c`, ...) — Task 2 (`_disambiguate`)
- ✓ PDF parse → .md via pdftotext — Task 5
- ✓ Write raw/{concept}/{key}.pdf + .md + .bib — Task 8
- ✓ Register in sources table with registered_at — Task 7
- ✓ Chunk .md → embed → store offsets in source_chunks — Tasks 3, 4, 7
- ✓ Chunking strategy by source_type (heading/paragraph) — Task 3, 8
- ✓ Print "Read: ... Cite as: [[key.ext]]" — Task 8
- ✓ .md input skips PDF parsing — Task 5 + 8 (suffix check)

**Deferred (not in spec for Plan 2):**
- URL input (httpx fetch + html→markdown) — Plan 2b
- Audio/video transcription (yt-dlp + faster-whisper) — Plan 2b
- `--replace` flag to reprocess existing source — Plan 2b

**Type consistency verified:** `Chunk` dataclass defined in Task 3, used correctly in Tasks 7, 8, 9. `register_source` returns `int` (source_id) — used correctly in Task 8. `embed_texts` returns `list[list[float]]` — used correctly in Task 8.
