"""Integration tests for llm-wiki add-source.

Embedding calls are monkeypatched — these tests do not require a running server.
PDF extraction is also monkeypatched — these tests do not require pdftotext.
"""
import duckdb
import pytest
from click.testing import CliRunner
from pathlib import Path

from llm_wiki.cli.add_source import add_source
from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for


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
    monkeypatch.setattr("llm_wiki.cli.add_source.embed_texts", fake_embed)


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
