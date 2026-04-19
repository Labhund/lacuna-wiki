import duckdb
import pytest
from click.testing import CliRunner

from lacuna_wiki.cli.status import status
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for


@pytest.fixture(autouse=True)
def no_daemon(tmp_path, monkeypatch):
    """Redirect PID file to a non-existent path so tests run without daemon routing."""
    import lacuna_wiki.daemon.process as proc_mod
    monkeypatch.setattr(proc_mod, "_PID_FILE", tmp_path / "nonexistent.pid")


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


def test_status_shows_sweep_rows(vault, monkeypatch):
    monkeypatch.chdir(vault)
    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert "research gaps" in result.output
    assert "ghost pages" in result.output
    assert "sweep backlog" in result.output
    assert "synthesis queue" in result.output


def test_status_shows_synthesised_pages_row(vault, monkeypatch):
    monkeypatch.chdir(vault)
    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert "synthesised pages" in result.output


def test_status_sweep_backlog_counts_unswept_pages(vault, monkeypatch):
    from lacuna_wiki.daemon.sync import sync_page
    from pathlib import Path

    monkeypatch.chdir(vault)

    conn = duckdb.connect(str(db_path(vault)))
    try:
        conn.execute("LOAD fts")
    except Exception:
        pass

    def fake_embed(texts):
        return [[1.0] + [0.0] * 767 for _ in texts]

    page = vault / "wiki" / "concept.md"
    page.write_text("# concept\n\n## S1\n\n" + ("Word " * 120) + "\n")
    sync_page(conn, vault, Path("wiki/concept.md"), fake_embed)
    conn.close()

    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert "sweep backlog" in result.output


def test_status_routes_through_api_when_daemon_running(vault, monkeypatch):
    """When PID file points to running process, status hits HTTP API."""
    import io, json, os
    from lacuna_wiki.daemon import process as proc_mod

    fake_pid_file = vault / "daemon.pid"
    fake_pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(proc_mod, "_PID_FILE", fake_pid_file)

    api_hit = []

    def fake_urlopen(url, timeout=None):
        api_hit.append(str(url))
        data = json.dumps({
            "tables": {t: 0 for t in ["pages", "sections", "sources", "claims",
                                       "claim_sources", "source_chunks", "links"]},
            "sweep": {"research gaps": 0, "ghost pages": 0, "sweep backlog": 0,
                      "synthesis queue": 0, "synthesised pages": 0},
        }).encode()
        resp = io.BytesIO(data)
        resp.read = resp.read
        return resp

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.chdir(vault)

    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert any("/status" in u for u in api_hit), f"Expected /status API call, got: {api_hit}"
