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
