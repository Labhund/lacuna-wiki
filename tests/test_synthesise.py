"""Tests for mcp/synthesise.py — cluster_queue, cluster_detail, commit_synthesis."""
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import db_path, state_dir_for


def fake_embed(texts):
    return [[1.0] + [0.0] * 767 for _ in texts]


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    try:
        conn.execute("LOAD fts")
    except Exception:
        pass
    return vault_root, conn


def write_and_sync(vault_root, conn, name, content):
    path = vault_root / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki") / name, fake_embed)


def make_cluster(conn, members, label="Test cluster"):
    from lacuna_wiki.mcp.audit import mark_swept
    mark_swept(conn, members[0], cluster={
        "members": members,
        "label": label,
        "rationale": "Test rationale.",
    })
    return conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label=?", [label]
    ).fetchone()[0]


def test_cluster_queue_returns_pending(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\n" + "W " * 60)
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\n" + "W " * 60)
    make_cluster(conn, ["a", "b"])
    result = cluster_queue(conn)
    assert "Test cluster" in result
    assert "pending" in result.lower() or "1" in result


def test_cluster_queue_empty(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    _, conn = vault
    result = cluster_queue(conn)
    assert "0" in result or "no pending" in result.lower()


def test_cluster_queue_shows_diversity_note_zero(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    make_cluster(conn, ["a"])
    result = cluster_queue(conn)
    assert "unknown" in result.lower() or "source" in result.lower()


def test_cluster_detail_returns_members(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    result = cluster_detail(conn, cid)
    assert "a" in result
    assert "b" in result
    assert "suggested slug" in result.lower()


def test_cluster_detail_shows_source_diversity(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, title, source_type)"
        " VALUES ('src1', 'raw/s.pdf', 'Source One', 'paper')"
    )
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nCite [[src1.pdf]].\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nCite [[src1.pdf]].\n")
    cid = make_cluster(conn, ["a", "b"])
    result = cluster_detail(conn, cid)
    assert "source" in result.lower()
    assert "single-source" in result.lower() or "1" in result


def test_cluster_detail_existing_synthesis_page(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    conn.execute(
        "UPDATE synthesis_clusters SET synthesis_page_slug='synth-ab' WHERE id=?", [cid]
    )
    result = cluster_detail(conn, cid)
    assert "synth-ab" in result
    assert "existing synthesis page" in result.lower()


def test_commit_synthesis_marks_completed(vault):
    from lacuna_wiki.mcp.synthesise import commit_synthesis
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    result = commit_synthesis(conn, cid, "synthesis-ab")
    assert "synthesis-ab" in result
    row = conn.execute(
        "SELECT status, synthesis_page_slug FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] == "synthesis-ab"


def test_commit_synthesis_not_found(vault):
    from lacuna_wiki.mcp.synthesise import commit_synthesis
    _, conn = vault
    result = commit_synthesis(conn, 9999, "slug")
    assert "not found" in result.lower() or "error" in result.lower()
