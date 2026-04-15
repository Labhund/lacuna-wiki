"""End-to-end MCP integration tests.

Wires sync → FTS build → search → navigate through dispatch_wiki.
No subprocess, no live embedding server — fake embedder.
"""
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import db_path, state_dir_for
from lacuna_wiki.mcp.server import dispatch_wiki


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    (vault_root / "raw").mkdir()
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    conn.execute("LOAD fts")
    return vault_root, conn


def fake_embed(texts):
    # Deterministic: [1.0, 0.0, ...] for all
    return [[1.0] + [0.0] * 767 for _ in texts]


def write_and_sync(vault_root, conn, name, content):
    path = vault_root / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki") / name, fake_embed)


def test_search_finds_synced_page(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "attention.md",
                   "# attention\n\n## Overview\n\nAttention computes queries keys values.\n")
    result = dispatch_wiki(conn, fake_embed, q="queries", scope="wiki")
    assert "attention" in result
    assert "Overview" in result


def test_search_no_results_message(vault):
    vault_root, conn = vault
    # Empty DB — no sections in either BM25 or vec index
    result = dispatch_wiki(conn, fake_embed, q="zzznomatchzzz", scope="wiki")
    assert "no results" in result.lower()


def test_navigate_returns_page_content(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "transformer.md",
                   "# transformer\n\n## Architecture\n\nEncoder decoder structure.\n")
    result = dispatch_wiki(conn, fake_embed, page="transformer")
    assert "transformer" in result
    assert "Architecture" in result


def test_navigate_unknown_page(vault):
    vault_root, conn = vault
    result = dispatch_wiki(conn, fake_embed, page="unknown-slug")
    assert "not found" in result.lower()


def test_multi_read_both_pages(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md", "# page-a\n\nContent A.\n")
    write_and_sync(vault_root, conn, "page-b.md", "# page-b\n\nContent B.\n")
    result = dispatch_wiki(conn, fake_embed, pages=["page-a", "page-b"])
    assert "page-a" in result
    assert "page-b" in result


def test_navigate_shows_links_in(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "target.md", "# target\n\nTarget content.\n")
    write_and_sync(vault_root, conn, "source.md",
                   "# source\n\nLinks to [[target]] here.\n")
    result = dispatch_wiki(conn, fake_embed, page="target")
    assert "source" in result  # links in


def test_navigate_shows_citation(vault):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, title, source_type)"
        " VALUES ('vaswani2017', 'raw/v.pdf', 'Attention Is All You Need', 'paper')"
    )
    write_and_sync(vault_root, conn, "attn.md",
                   "# attn\n\n## S\n\nThe mechanism. [[vaswani2017.pdf]]\n")
    result = dispatch_wiki(conn, fake_embed, page="attn")
    assert "vaswani2017" in result
    assert "Attention Is All You Need" in result


def test_link_audit_true_returns_vault_audit(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    result = dispatch_wiki(conn, fake_embed, link_audit=True)
    assert "sweep queue" in result.lower() or "research gaps" in result.lower()


def test_link_audit_string_true_normalised(vault):
    """Agents sometimes pass link_audit='true' (string) instead of True (bool)."""
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    result = dispatch_wiki(conn, fake_embed, link_audit="true")
    assert "sweep queue" in result.lower() or "research gaps" in result.lower()
    result2 = dispatch_wiki(conn, fake_embed, link_audit="True")
    assert "sweep queue" in result2.lower() or "research gaps" in result2.lower()


def test_link_audit_slug_returns_page_audit(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\nSome content.\n")
    result = dispatch_wiki(conn, fake_embed, link_audit="page-a")
    assert "page-a" in result
    assert "unlinked" in result.lower()


def test_link_audit_mark_swept(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\nSome content.\n")
    result = dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True)
    assert "swept" in result.lower()
    row = conn.execute("SELECT last_swept FROM pages WHERE slug='page-a'").fetchone()
    assert row[0] is not None


def test_link_audit_true_mark_swept_returns_error(vault):
    vault_root, conn = vault
    result = dispatch_wiki(conn, fake_embed, link_audit=True, mark_swept=True)
    assert "error" in result.lower() or "slug" in result.lower()
