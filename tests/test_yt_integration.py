"""Integration test: add-source with a real YouTube URL.

Requires: yt-dlp installed, network access to YouTube.
Embedding is monkeypatched — no embed server needed.

Run with:
    pytest -m integration tests/test_yt_integration.py -v

Vault:  tests/fixtures/yt-integration-vault/
State:  ~/.lacuna/vaults/<hash>/vault.db  (reset before each run)
"""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest
from click.testing import CliRunner

from lacuna_wiki.cli.add_source import add_source
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for

_VAULT = Path(__file__).parent / "fixtures" / "yt-integration-vault"
_YT_URL = "https://www.youtube.com/watch?v=Zn4fApSAtsc"


@pytest.fixture
def vault(monkeypatch):
    """Reset the state dir for the integration vault, then yield vault root."""
    state = state_dir_for(_VAULT)
    if state.exists():
        shutil.rmtree(state)
    state.mkdir(parents=True)
    conn = duckdb.connect(str(db_path(_VAULT)))
    init_db(conn)
    conn.close()
    monkeypatch.chdir(_VAULT)
    yield _VAULT


@pytest.fixture(autouse=True)
def mock_embed(monkeypatch):
    monkeypatch.setattr(
        "lacuna_wiki.cli.add_source.embed_texts",
        lambda texts, **kw: [[0.1] * 768 for _ in texts],
    )


@pytest.mark.integration
def test_yt_add_source_exit_zero(vault):
    result = CliRunner().invoke(add_source, [_YT_URL])
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_yt_add_source_creates_sources_row(vault):
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(_VAULT)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


@pytest.mark.integration
def test_yt_add_source_type_is_transcript(vault):
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(_VAULT)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "transcript"


@pytest.mark.integration
def test_yt_add_source_writes_md_with_headings(vault):
    CliRunner().invoke(add_source, [_YT_URL])
    md_files = list((_VAULT / "raw").rglob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "## [00:" in content


@pytest.mark.integration
def test_yt_add_source_chunks_embedded(vault):
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(_VAULT)))
    count = conn.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0]
    conn.close()
    assert count >= 1


@pytest.mark.integration
def test_yt_add_source_output_contains_cite_as(vault):
    result = CliRunner().invoke(add_source, [_YT_URL])
    assert "Cite as:" in result.output
    assert "[[" in result.output


@pytest.fixture(autouse=True)
def cleanup_raw(request):
    """Remove any .md/.bib files written to raw/ after each test."""
    yield
    if request.node.get_closest_marker("integration"):
        for f in (_VAULT / "raw").rglob("*"):
            if f.is_file():
                f.unlink()
