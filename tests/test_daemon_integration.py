"""End-to-end daemon integration tests.

Uses WikiEventHandler directly (no subprocess) with monkeypatched embedder.
Verifies the full path: file write → event → DB rows.
"""
import duckdb
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for
from llm_wiki.daemon.watcher import WikiEventHandler, initial_sync


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    (vault_root / "raw").mkdir()
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    return vault_root, conn


def fake_embed(texts):
    return [[0.1] * 768 for _ in texts]


def fire_modified(handler, path: Path):
    ev = MagicMock()
    ev.src_path = str(path)
    ev.is_directory = False
    handler.on_modified(ev)


def test_write_page_creates_page_and_sections(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    md = vault_root / "wiki" / "attention.md"
    md.write_text(
        "# attention\n\n"
        "## Overview\n\nAttention computes QK^T/√dk.\n\n"
        "## Methods\n\nScaled dot-product.\n"
    )
    fire_modified(handler, md)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 3


def test_write_page_with_wikilinks(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    md = vault_root / "wiki" / "transformer.md"
    md.write_text("# transformer\n\nSee [[attention]] and [[positional-encoding]].\n")
    fire_modified(handler, md)
    page_id = conn.execute("SELECT id FROM pages WHERE slug='transformer'").fetchone()[0]
    links = {r[0] for r in conn.execute(
        "SELECT target_slug FROM links WHERE source_page_id=?", [page_id]
    ).fetchall()}
    assert links == {"attention", "positional-encoding"}


def test_write_page_with_citation(vault):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    md = vault_root / "wiki" / "sdpa.md"
    md.write_text(
        "# sdpa\n\n"
        "## Background\n\n"
        "Attention scores scale by 1/√dk to avoid saturation. [[vaswani2017.pdf]]\n"
    )
    fire_modified(handler, md)
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM claim_sources").fetchone()[0] == 1


def test_modify_page_updates_sections(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    md = vault_root / "wiki" / "page.md"
    md.write_text("# page\n\n## One\n\nOriginal.\n")
    fire_modified(handler, md)
    md.write_text("# page\n\n## One\n\nUpdated.\n\n## Two\n\nNew section.\n")
    fire_modified(handler, md)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 3


def test_delete_page_removes_all_rows(vault):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('src1', 'raw/s.pdf', 'paper')"
    )
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    md = vault_root / "wiki" / "page.md"
    md.write_text("# page\n\n## S\n\nClaim. [[src1.pdf]]\n")
    fire_modified(handler, md)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1

    md.unlink()
    ev = MagicMock()
    ev.src_path = str(md)
    ev.is_directory = False
    handler.on_deleted(ev)

    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_initial_sync_on_startup(vault):
    vault_root, conn = vault
    (vault_root / "wiki" / "alpha.md").write_text("# alpha\n\nContent A.\n")
    (vault_root / "wiki" / "beta.md").write_text("# beta\n\nContent B.\n")
    initial_sync(conn, vault_root, fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
    slugs = {r[0] for r in conn.execute("SELECT slug FROM pages").fetchall()}
    assert slugs == {"alpha", "beta"}


def test_sessions_directory_not_synced(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    sessions_dir = vault_root / "wiki" / ".sessions"
    sessions_dir.mkdir()
    manifest = sessions_dir / "hay2026wedon-2026-04-14.md"
    manifest.write_text("## Source: hay2026wedon\n## Completed: kv-cache\n")

    fire_modified(handler, manifest)

    row = conn.execute(
        "SELECT id FROM pages WHERE slug='hay2026wedon-2026-04-14'"
    ).fetchone()
    assert row is None, "Session manifest must not be indexed as a wiki page"


def test_sessions_directory_skipped_on_initial_sync(vault):
    vault_root, conn = vault
    (vault_root / "wiki" / "real-page.md").write_text("# real\n\nContent.\n")
    sessions_dir = vault_root / "wiki" / ".sessions"
    sessions_dir.mkdir()
    (sessions_dir / "hay2026wedon-2026-04-14.md").write_text("## Source: hay2026wedon\n")

    initial_sync(conn, vault_root, fake_embed)

    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    slug = conn.execute("SELECT slug FROM pages").fetchone()[0]
    assert slug == "real-page"
