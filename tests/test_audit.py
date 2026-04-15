"""Tests for the audit module — vault_audit, page_audit, mark_swept."""
from __future__ import annotations

import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import state_dir_for, db_path


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


# ---------------------------------------------------------------------------
# vault_audit
# ---------------------------------------------------------------------------

def test_vault_audit_returns_string(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    result = vault_audit(conn)
    assert isinstance(result, str)


def test_vault_audit_shows_ghost_page(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## Intro\n\nLinks to [[ghost-concept]] here.\n")
    result = vault_audit(conn)
    assert "ghost-concept" in result
    assert "ghost" in result.lower()


def test_vault_audit_shows_research_gap(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "stub-page.md",
                   "# stub-page\n\n## Intro\n\nShort.\n")
    result = vault_audit(conn)
    assert "stub-page" in result


def test_vault_audit_sweep_queue_excludes_stubs(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "stub-page.md",
                   "# stub-page\n\n## Intro\n\nShort.\n")
    result = vault_audit(conn)
    lines = result.split("\n")
    in_sweep = False
    sweep_lines = []
    for line in lines:
        if "sweep queue" in line.lower():
            in_sweep = True
        elif in_sweep and "synthesis queue" in line.lower():
            break
        elif in_sweep:
            sweep_lines.append(line)
    assert not any("stub-page" in l for l in sweep_lines)


def test_vault_audit_sweep_queue_contains_substantive_page(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    content = "# big-page\n\n## Section\n\n" + ("Word " * 120) + "\n"
    write_and_sync(vault_root, conn, "big-page.md", content)
    result = vault_audit(conn)
    assert "big-page" in result
    assert "sweep queue" in result.lower()


# ---------------------------------------------------------------------------
# page_audit
# ---------------------------------------------------------------------------

def test_page_audit_shows_unlinked_candidates(vault):
    from lacuna_wiki.mcp.audit import page_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "attention.md",
                   "# attention\n\n## Overview\n\nAttention is important.\n")
    content = "# transformer\n\n## Arch\n\n" + ("Word " * 50) + "\nattention is key here.\n"
    write_and_sync(vault_root, conn, "transformer.md", content)
    result = page_audit(conn, "transformer", fake_embed)
    assert "attention" in result
    assert "unlinked" in result.lower()


def test_page_audit_not_found(vault):
    from lacuna_wiki.mcp.audit import page_audit
    vault_root, conn = vault
    result = page_audit(conn, "no-such-page", fake_embed)
    assert "not found" in result.lower()


def test_page_audit_shows_synthesis_candidates(vault):
    from lacuna_wiki.mcp.audit import page_audit
    vault_root, conn = vault
    # Two pages with identical embeddings (fake_embed gives same vec for all)
    content_a = "# page-a\n\n## S1\n\n" + ("Alpha " * 60) + "\n"
    content_b = "# page-b\n\n## S1\n\n" + ("Alpha " * 60) + "\n"
    write_and_sync(vault_root, conn, "page-a.md", content_a)
    write_and_sync(vault_root, conn, "page-b.md", content_b)
    result = page_audit(conn, "page-a", fake_embed)
    assert "synthesis" in result.lower()


def test_page_audit_no_unlinked_when_all_wikilinked(vault):
    from lacuna_wiki.mcp.audit import page_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "attention.md",
                   "# attention\n\n## S\n\nAttention mechanism.\n")
    write_and_sync(vault_root, conn, "transformer.md",
                   "# transformer\n\n## S\n\nSee [[attention]] for details.\n")
    result = page_audit(conn, "transformer", fake_embed)
    # attention should NOT appear in the unlinked candidates section
    lines = result.split("\n")
    in_unlinked = False
    unlinked_lines = []
    for line in lines:
        if "unlinked candidates" in line.lower():
            in_unlinked = True
        elif in_unlinked and "synthesis" in line.lower():
            break
        elif in_unlinked:
            unlinked_lines.append(line)
    # attention slug should not appear in the unlinked section
    assert not any("attention" in l for l in unlinked_lines)


def test_page_audit_no_substring_false_positives(vault):
    """Short slug 'ha' must not match inside 'phase', 'that', 'thermal' etc."""
    from lacuna_wiki.mcp.audit import page_audit
    vault_root, conn = vault
    # Create a page whose slug is a short token that appears as a substring elsewhere
    write_and_sync(vault_root, conn, "ha.md",
                   "# ha\n\n## S\n\nHA is a protein.\n")
    # Page whose text contains 'phase', 'that', 'thermal' but NOT standalone 'ha'
    content = "# thermodynamics\n\n## S\n\n" + (
        "The phase transition that happens in thermal systems is fascinating. " * 20
    ) + "\n"
    write_and_sync(vault_root, conn, "thermodynamics.md", content)
    result = page_audit(conn, "thermodynamics", fake_embed)
    lines = result.split("\n")
    in_unlinked = False
    unlinked_lines = []
    for line in lines:
        if "unlinked candidates" in line.lower():
            in_unlinked = True
        elif in_unlinked and "synthesis" in line.lower():
            break
        elif in_unlinked:
            unlinked_lines.append(line)
    assert not any("[[ha]]" in l for l in unlinked_lines), (
        "short slug 'ha' matched as substring — word boundary check failed"
    )


# ---------------------------------------------------------------------------
# mark_swept
# ---------------------------------------------------------------------------

def test_mark_swept_sets_last_swept(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    content = "# big-page\n\n## S\n\n" + ("Word " * 120) + "\n"
    write_and_sync(vault_root, conn, "big-page.md", content)
    row_before = conn.execute(
        "SELECT last_swept FROM pages WHERE slug='big-page'"
    ).fetchone()
    assert row_before[0] is None
    result = mark_swept(conn, "big-page")
    assert "swept" in result.lower()
    row_after = conn.execute(
        "SELECT last_swept FROM pages WHERE slug='big-page'"
    ).fetchone()
    assert row_after[0] is not None


def test_mark_swept_not_found(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    result = mark_swept(conn, "no-such-page")
    assert "not found" in result.lower()


def test_mark_swept_creates_cluster(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    for name in ["page-a.md", "page-b.md"]:
        write_and_sync(vault_root, conn, name,
                       f"# {name[:-3]}\n\n## S\n\n" + ("Word " * 120) + "\n")
    cluster = {
        "members": ["page-a", "page-b"],
        "label": "Test concept",
        "rationale": "Both pages discuss the same idea.",
    }
    mark_swept(conn, "page-a", cluster=cluster)
    row = conn.execute(
        "SELECT id, concept_label, status FROM synthesis_clusters WHERE concept_label='Test concept'"
    ).fetchone()
    assert row is not None
    cluster_id = row[0]
    assert row[2] == "pending"
    members = conn.execute(
        "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cluster_id]
    ).fetchall()
    slugs = {m[0] for m in members}
    assert {"page-a", "page-b"} <= slugs


def test_mark_swept_merges_existing_cluster(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    for name in ["pg-x.md", "pg-y.md", "pg-z.md"]:
        slug = name[:-3]
        write_and_sync(vault_root, conn, name,
                       f"# {slug}\n\n## S\n\n" + ("Word " * 120) + "\n")
    mark_swept(conn, "pg-x", cluster={
        "members": ["pg-x", "pg-y"],
        "label": "Shared concept",
        "rationale": "First cluster.",
    })
    # pg-y already in a pending cluster — should merge pg-z in
    mark_swept(conn, "pg-z", cluster={
        "members": ["pg-y", "pg-z"],
        "label": "Shared concept extended",
        "rationale": "pg-z also covers this.",
    })
    total_clusters = conn.execute(
        "SELECT COUNT(*) FROM synthesis_clusters WHERE status='pending'"
    ).fetchone()[0]
    assert total_clusters == 1
    members = conn.execute("""
        SELECT slug FROM synthesis_cluster_members scm
        JOIN synthesis_clusters sc ON scm.cluster_id = sc.id
        WHERE sc.status='pending'
    """).fetchall()
    slugs = {m[0] for m in members}
    assert {"pg-x", "pg-y", "pg-z"} <= slugs


def test_mark_swept_removes_from_sweep_queue(vault):
    from lacuna_wiki.mcp.audit import mark_swept, vault_audit
    vault_root, conn = vault
    content = "# swept-page\n\n## S\n\n" + ("Word " * 120) + "\n"
    write_and_sync(vault_root, conn, "swept-page.md", content)

    result_before = vault_audit(conn)
    assert "swept-page" in result_before

    mark_swept(conn, "swept-page")

    result_after = vault_audit(conn)
    # Check sweep queue section doesn't contain swept-page anymore
    lines = result_after.split("\n")
    in_sweep = False
    sweep_lines = []
    for line in lines:
        if "sweep queue" in line.lower():
            in_sweep = True
        elif in_sweep and "synthesis queue" in line.lower():
            break
        elif in_sweep:
            sweep_lines.append(line)
    assert not any("swept-page" in l for l in sweep_lines)


def test_sweep_queue_excludes_synthesised_pages(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "concept.md",
                   "# concept\n\n## S\n\n" + ("Word " * 120) + "\n")
    conn.execute("UPDATE pages SET synthesised_into='synthesis-concept' WHERE slug='concept'")
    result = vault_audit(conn)
    # sweep queue must appear in output but concept must not be listed in it
    assert "sweep queue" in result.lower()
    lines = result.split("\n")
    in_queue = False
    queue_lines = []
    for line in lines:
        if "sweep queue" in line.lower():
            in_queue = True
        elif in_queue and line.strip() == "":
            break
        elif in_queue:
            queue_lines.append(line)
    assert not any("concept" in l for l in queue_lines), \
        "synthesised page must not appear in sweep queue"


def test_upsert_cluster_reopens_completed_cluster(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    write_and_sync(vault_root, conn, "page-b.md",
                   "# page-b\n\n## S\n\n" + ("Word " * 120) + "\n")
    # Create and complete a cluster; note the cluster id for assertions
    mark_swept(conn, "page-a", cluster={
        "members": ["page-a", "page-b"],
        "label": "Test",
        "rationale": "Test cluster",
    })
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE synthesis_clusters SET status='completed', synthesis_page_slug='synthesis-test'"
        " WHERE id=?", [cid]
    )
    # Sweep a new page that includes the synthesis page slug as a proposed member
    write_and_sync(vault_root, conn, "page-c.md",
                   "# page-c\n\n## S\n\n" + ("Word " * 120) + "\n")
    mark_swept(conn, "page-c", cluster={
        "members": ["page-c", "synthesis-test"],
        "label": "Test extended",
        "rationale": "New member joins existing synthesis",
    })
    row = conn.execute(
        "SELECT status, concept_label FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "pending", "completed cluster must be reopened when synthesis page is a proposed member"
    assert row[1] == "Test extended", "label should be updated to the incoming value"
    members = {r[0] for r in conn.execute(
        "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cid]
    ).fetchall()}
    assert "page-c" in members
