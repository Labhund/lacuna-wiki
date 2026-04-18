import duckdb
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for
from lacuna_wiki.daemon.watcher import WikiEventHandler, initial_sync


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


def _make_event(src_path: str, is_directory: bool = False):
    ev = MagicMock()
    ev.src_path = src_path
    ev.is_directory = is_directory
    return ev


def test_on_modified_syncs_md_file(vault):
    vault_root, conn = vault
    md = vault_root / "wiki" / "page.md"
    md.write_text("# Page\n\nContent.\n")
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    handler.on_modified(_make_event(str(md)))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1


def test_on_modified_ignores_directories(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    handler.on_modified(_make_event(str(vault_root / "wiki"), is_directory=True))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_on_modified_ignores_non_md_files(vault):
    vault_root, conn = vault
    other = vault_root / "wiki" / "notes.txt"
    other.write_text("not markdown")
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    handler.on_modified(_make_event(str(other)))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_on_deleted_removes_page(vault):
    vault_root, conn = vault
    md = vault_root / "wiki" / "page.md"
    md.write_text("# Page\n\nContent.\n")
    handler = WikiEventHandler(conn, vault_root, fake_embed)
    handler.on_modified(_make_event(str(md)))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    md.unlink()
    handler.on_deleted(_make_event(str(md)))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_initial_sync_processes_existing_pages(vault):
    vault_root, conn = vault
    (vault_root / "wiki" / "alpha.md").write_text("# Alpha\n\nContent.\n")
    (vault_root / "wiki" / "beta.md").write_text("# Beta\n\nContent.\n")
    initial_sync(conn, vault_root, fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2


def test_initial_sync_handles_empty_wiki(vault):
    vault_root, conn = vault
    initial_sync(conn, vault_root, fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_initial_sync_parallel_embeds_all_pages(tmp_path):
    """initial_sync with n_workers>1 processes all pages."""
    from lacuna_wiki.db.schema import init_db
    from lacuna_wiki.vault import db_path, state_dir_for

    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)

    for i in range(5):
        (vault_root / "wiki" / f"page-{i}.md").write_text(
            f"# page-{i}\n\n## Intro\n\nContent for page {i}.\n"
        )

    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)

    initial_sync(conn, vault_root, fake_embed, n_workers=2, embed_concurrency=2)

    count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    assert count == 5


def test_initial_sync_rebuilds_fts_once(tmp_path, monkeypatch):
    """FTS rebuild happens exactly once after all pages are processed."""
    import lacuna_wiki.daemon.sync as sync_mod
    fts_calls = []
    monkeypatch.setattr(sync_mod, "_rebuild_fts", lambda conn: fts_calls.append(1))

    from lacuna_wiki.db.schema import init_db
    from lacuna_wiki.vault import db_path, state_dir_for

    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)

    for i in range(3):
        (vault_root / "wiki" / f"page-{i}.md").write_text(
            f"# page-{i}\n\n## Intro\n\nContent {i}.\n"
        )

    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)

    initial_sync(conn, vault_root, fake_embed, n_workers=2, embed_concurrency=2)
    assert len(fts_calls) == 1, f"Expected 1 FTS rebuild, got {len(fts_calls)}"
