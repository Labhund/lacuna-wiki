import duckdb
import pytest
from click.testing import CliRunner

from lacuna_wiki.cli.init import init
from lacuna_wiki.vault import db_path, find_vault_root


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def no_mcp_wiring(monkeypatch):
    """Prevent init tests from touching ~/.claude/mcp.json or ~/.hermes/config.yaml."""
    monkeypatch.setattr("lacuna_wiki.cli.init._offer_mcp_config", lambda vault_root: None)


def test_init_creates_wiki_and_raw_dirs(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(init)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "wiki").is_dir()
    assert (tmp_path / "raw").is_dir()


def test_init_creates_git_repo(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    assert (tmp_path / ".git").is_dir()


def test_init_creates_database(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    assert db_path(tmp_path).exists()


def test_init_database_has_tables(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    conn = duckdb.connect(str(db_path(tmp_path)))
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}
    conn.close()
    assert {"pages", "sections", "sources", "claims", "claim_sources", "source_chunks", "links"} <= tables


def test_init_creates_gitignore(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    assert (tmp_path / ".gitignore").exists()


def test_init_gitignore_includes_sessions(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    assert "wiki/.sessions/" in (tmp_path / ".gitignore").read_text()


def test_init_gitignore_sessions_appended_if_exists(tmp_path, runner, monkeypatch):
    """If .gitignore already exists without the sessions entry, it is appended."""
    (tmp_path / ".gitignore").write_text("some-existing-entry\n")
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    content = (tmp_path / ".gitignore").read_text()
    assert "wiki/.sessions/" in content
    assert "some-existing-entry" in content


def test_init_is_idempotent(tmp_path, runner, monkeypatch):
    """Running init twice on the same directory must not raise."""
    monkeypatch.chdir(tmp_path)
    r1 = runner.invoke(init)
    r2 = runner.invoke(init)
    assert r1.exit_code == 0, r1.output
    assert r2.exit_code == 0, r2.output


def test_init_vault_root_detectable_after_init(tmp_path, runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(init)
    assert find_vault_root(tmp_path) == tmp_path
