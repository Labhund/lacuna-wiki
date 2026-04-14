import duckdb
import pytest
from click.testing import CliRunner

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
    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert str(vault) in result.output


def test_status_shows_all_table_names(vault, monkeypatch):
    monkeypatch.chdir(vault)
    result = CliRunner().invoke(status)
    for table in ["pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"]:
        assert table in result.output


def test_status_shows_zero_counts_on_empty_db(vault, monkeypatch):
    monkeypatch.chdir(vault)
    result = CliRunner().invoke(status)
    assert "0" in result.output


def test_status_fails_outside_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(status)
    assert result.exit_code != 0


def test_status_shows_row_counts(vault, monkeypatch):
    monkeypatch.chdir(vault)
    conn = duckdb.connect(str(db_path(vault)))
    conn.execute(
        "INSERT INTO pages (id, slug, path) VALUES (1, 'test-page', 'wiki/test-page.md')"
    )
    conn.close()
    result = CliRunner().invoke(status)
    assert "1" in result.output
