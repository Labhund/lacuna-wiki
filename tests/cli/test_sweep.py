"""Tests for lacuna sweep CLI."""
from __future__ import annotations

import os

import duckdb
import pytest
from click.testing import CliRunner
from pathlib import Path

from lacuna_wiki.cli.sweep import sweep
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import db_path, state_dir_for


def fake_embed(texts):
    return [[0.0] * 768 for _ in texts]


@pytest.fixture(autouse=True)
def no_daemon(tmp_path, monkeypatch):
    """Redirect PID file so tests run without daemon routing by default."""
    import lacuna_wiki.daemon.process as proc_mod
    monkeypatch.setattr(proc_mod, "_PID_FILE", tmp_path / "nonexistent.pid")


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    (vault_root / "raw").mkdir(parents=True)
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    return vault_root, conn


def write_page(vault_root, conn, name, content):
    p = vault_root / "wiki" / name
    p.write_text(content, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki") / name, fake_embed)


def test_sweep_standalone_populates_unlinked_candidates(vault, monkeypatch):
    """lacuna sweep (no daemon) writes unlinked_candidates rows."""
    vault_root, conn = vault
    write_page(vault_root, conn, "alpha.md",
               "# alpha\n\n## Intro\n\nMentions beta here.\n\n## Body\n\nMore.\n")
    write_page(vault_root, conn, "beta.md",
               "# beta\n\n## Intro\n\nSome content.\n\n## Body\n\nMore.\n")
    conn.close()

    monkeypatch.chdir(vault_root)
    result = CliRunner().invoke(sweep, [])
    assert result.exit_code == 0, result.output

    conn2 = duckdb.connect(str(db_path(vault_root)))
    rows = conn2.execute("SELECT COUNT(*) FROM unlinked_candidates").fetchone()[0]
    assert rows > 0
    conn2.close()


def test_sweep_batch_limits_pages(vault, monkeypatch):
    vault_root, conn = vault
    for i in range(5):
        write_page(vault_root, conn, f"page-{i}.md",
                   f"# page-{i}\n\n## Intro\n\nContent {i}.\n\n## Body\n\nMore.\n")
    conn.close()

    monkeypatch.chdir(vault_root)
    result = CliRunner().invoke(sweep, ["--batch", "2"])
    assert result.exit_code == 0, result.output

    conn2 = duckdb.connect(str(db_path(vault_root)))
    processed = conn2.execute(
        "SELECT COUNT(DISTINCT page_id) FROM unlinked_candidates"
    ).fetchone()[0]
    assert processed <= 2
    conn2.close()


def test_sweep_routes_to_api_when_daemon_running(vault, monkeypatch):
    vault_root, conn = vault
    conn.close()

    import lacuna_wiki.daemon.process as proc_mod
    fake_pid_file = vault_root / "daemon.pid"
    fake_pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(proc_mod, "_PID_FILE", fake_pid_file)

    posted = []

    def fake_urlopen(url, data=None, timeout=None):
        import io, json
        url_str = str(url) if not hasattr(url, "full_url") else url.full_url
        posted.append(url_str)
        if "/sweep/status" in url_str:
            body = json.dumps({"done": 5, "total": 5, "running": False}).encode()
        else:
            body = json.dumps({"status": "accepted"}).encode()
        return io.BytesIO(body)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.chdir(vault_root)

    result = CliRunner().invoke(sweep, [])
    assert result.exit_code == 0, result.output
    assert any("/sweep" in u for u in posted), f"Expected /sweep API call, got: {posted}"
