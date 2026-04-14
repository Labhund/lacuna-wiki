"""Tests for llm-wiki move-source command."""
import duckdb
import pytest
from pathlib import Path
from click.testing import CliRunner

from llm_wiki.cli.main import cli
from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for


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
    result = CliRunner().invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0, result.output
    assert not (vault / "raw" / "hay2026wedon.md").exists()
    assert (vault / "raw" / "machine-learning" / "kv-cache" / "hay2026wedon.md").exists()


def test_move_source_updates_db_path(vault):
    CliRunner().invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    conn = duckdb.connect(str(db_path(vault)), read_only=True)
    row = conn.execute("SELECT path FROM sources WHERE slug='hay2026wedon'").fetchone()
    conn.close()
    assert row[0] == "raw/machine-learning/kv-cache/hay2026wedon.md"


def test_move_source_moves_all_associated_files(vault):
    """All files sharing the slug (.md, .pdf, .bib) must move atomically."""
    (vault / "raw" / "hay2026wedon.bib").write_text("@misc{hay2026wedon}")
    (vault / "raw" / "hay2026wedon.pdf").write_bytes(b"fake pdf")
    CliRunner().invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    dest = vault / "raw" / "machine-learning" / "kv-cache"
    assert (dest / "hay2026wedon.md").exists()
    assert (dest / "hay2026wedon.bib").exists()
    assert (dest / "hay2026wedon.pdf").exists()


def test_move_source_missing_slug_errors(vault):
    result = CliRunner().invoke(cli, [
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
    result = CliRunner().invoke(cli, [
        "move-source", "hay2026wedon", "--concept", "machine-learning/kv-cache",
        "--vault", str(vault),
    ])
    assert result.exit_code != 0
    assert "already exists" in result.output.lower()
