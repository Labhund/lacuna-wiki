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


def test_synthesise_true_returns_queue(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    result = dispatch_wiki(conn, fake_embed, synthesise=True)
    assert "Test" in result or "pending" in result.lower()


def test_synthesise_int_returns_detail(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    result = dispatch_wiki(conn, fake_embed, synthesise=cid)
    assert "page-a" in result
    assert "suggested slug" in result.lower()


def test_synthesise_commit(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    result = dispatch_wiki(conn, fake_embed, synthesise=cid,
                           commit={"slug": "synthesis-test"})
    assert "synthesis-test" in result
    row = conn.execute(
        "SELECT status FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "completed"


def test_synthesise_string_true_normalised(vault):
    """Agents may pass synthesise='true' as a string."""
    _, conn = vault
    result = dispatch_wiki(conn, fake_embed, synthesise="true")
    assert "0" in result or "no pending" in result.lower()


def test_synthesise_and_link_audit_mutual_exclusion(vault):
    _, conn = vault
    result = dispatch_wiki(conn, fake_embed, synthesise=True, link_audit=True)
    assert "error" in result.lower() or "mutually exclusive" in result.lower()


def test_audit_cache_hit_on_second_call(vault):
    """Second vault_audit call with same limit returns cached result (vault_audit called once)."""
    import unittest.mock as mock
    import lacuna_wiki.mcp.audit as audit_mod
    import lacuna_wiki.mcp.server as server_mod
    from lacuna_wiki.mcp.server import dispatch_wiki, _audit_cache_invalidate

    vault_root, conn = vault

    # Reset cache between test runs
    _audit_cache_invalidate()

    call_count = [0]
    _real_vault_audit = audit_mod.vault_audit

    def counting_audit(conn, limit=None, claim=False):
        call_count[0] += 1
        return _real_vault_audit(conn, limit=limit, claim=claim)

    with mock.patch.object(audit_mod, "vault_audit", counting_audit):
        r1 = dispatch_wiki(conn, lambda t: [[0.0]*768]*len(t),
                           link_audit=True, limit=10, vault_root=vault_root)
        r2 = dispatch_wiki(conn, lambda t: [[0.0]*768]*len(t),
                           link_audit=True, limit=10, vault_root=vault_root)

    assert call_count[0] == 1, f"vault_audit called {call_count[0]} times, expected 1 (cache hit)"
    assert r1 == r2

    # Clean up
    _audit_cache_invalidate()


def test_audit_cache_invalidated_on_mark_swept(vault):
    """After mark_swept, next vault_audit call re-scans (cache miss)."""
    import unittest.mock as mock
    import lacuna_wiki.mcp.audit as audit_mod
    from lacuna_wiki.mcp.server import dispatch_wiki, _audit_cache_invalidate
    from lacuna_wiki.daemon.sync import sync_page
    from pathlib import Path

    vault_root, conn = vault
    _audit_cache_invalidate()

    filler = "Word " * 60
    page_body = f"# alpha\n\n## Introduction\n\n{filler}\n\n## Background\n\n{filler}\n"
    p = vault_root / "wiki" / "alpha.md"
    p.write_text(page_body, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki/alpha.md"), lambda t: [[0.0]*768]*len(t))

    call_count = [0]
    _real = audit_mod.vault_audit

    def counting_audit(conn, limit=None, claim=False):
        call_count[0] += 1
        return _real(conn, limit=limit, claim=claim)

    with mock.patch.object(audit_mod, "vault_audit", counting_audit):
        dispatch_wiki(conn, lambda t: [[0.0]*768]*len(t),
                      link_audit=True, limit=10, vault_root=vault_root)
        # mark_swept should invalidate the cache
        dispatch_wiki(conn, lambda t: [[0.0]*768]*len(t),
                      sweep="alpha", mark_swept=True, vault_root=vault_root)
        dispatch_wiki(conn, lambda t: [[0.0]*768]*len(t),
                      link_audit=True, limit=10, vault_root=vault_root)

    assert call_count[0] == 2, f"vault_audit called {call_count[0]} times, expected 2 (invalidation)"
    _audit_cache_invalidate()
