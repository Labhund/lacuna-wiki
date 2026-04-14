import duckdb
import pytest
from pathlib import Path

from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for
from llm_wiki.daemon.sync import sync_page


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


@pytest.fixture
def fake_embed():
    calls = []
    def _embed(texts):
        calls.append(texts)
        return [[0.1] * 768 for _ in texts]
    _embed.calls = calls
    return _embed


def write_page(vault_root, name, content):
    path = vault_root / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_sync_page_creates_page_row(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "attention.md", "# attention\n\n## Overview\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/attention.md"), fake_embed)
    row = conn.execute("SELECT slug, title FROM pages WHERE slug='attention'").fetchone()
    assert row is not None
    assert row[1] == "attention"


def test_sync_page_sets_cluster(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "ml/transformer.md", "# transformer\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/ml/transformer.md"), fake_embed)
    row = conn.execute("SELECT cluster FROM pages WHERE slug='transformer'").fetchone()
    assert row[0] == "ml"


def test_sync_page_creates_sections(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# Page\n\nIntro.\n\n## Alpha\n\nA.\n\n## Beta\n\nB.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    count = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    assert count == 3  # preamble + Alpha + Beta


def test_sync_page_sections_have_positions(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# P\n\nIntro.\n\n## A\n\nA.\n\n## B\n\nB.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    positions = [r[0] for r in conn.execute(
        "SELECT position FROM sections ORDER BY position"
    ).fetchall()]
    assert positions == [0, 1, 2]


def test_sync_page_sections_have_embeddings(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# P\n\n## Section\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    emb = conn.execute("SELECT embedding FROM sections WHERE name='Section'").fetchone()[0]
    assert len(emb) == 768


def test_sync_page_reuses_embedding_for_unchanged_section(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# P\n\n## Section\n\nSame content.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    first_call_count = len(fake_embed.calls)

    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    unchanged_texts_called = any(
        "Same content" in t
        for batch in fake_embed.calls[first_call_count:]
        for t in batch
    )
    assert not unchanged_texts_called


def test_sync_page_updates_page_on_resync(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# Old Title\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    write_page(vault_root, "page.md", "# New Title\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    title = conn.execute("SELECT title FROM pages WHERE slug='page'").fetchone()[0]
    assert title == "New Title"
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1


def test_sync_page_deletes_page_when_file_missing(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "gone.md", "# Gone\n\nContent.\n")
    sync_page(conn, vault_root, Path("wiki/gone.md"), fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    (vault_root / "wiki" / "gone.md").unlink()
    sync_page(conn, vault_root, Path("wiki/gone.md"), fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_sync_page_creates_wikilinks(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md",
               "# P\n\nSee [[attention-mechanism]] and [[transformer]].\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    page_id = conn.execute("SELECT id FROM pages WHERE slug='page'").fetchone()[0]
    links = {r[0] for r in conn.execute(
        "SELECT target_slug FROM links WHERE source_page_id=?", [page_id]
    ).fetchall()}
    assert links == {"attention-mechanism", "transformer"}


def test_sync_page_replaces_links_on_resync(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# P\n\n[[old-link]].\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    write_page(vault_root, "page.md", "# P\n\n[[new-link]].\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    page_id = conn.execute("SELECT id FROM pages WHERE slug='page'").fetchone()[0]
    targets = {r[0] for r in conn.execute(
        "SELECT target_slug FROM links WHERE source_page_id=?", [page_id]
    ).fetchall()}
    assert targets == {"new-link"}
    assert "old-link" not in targets


def test_sync_page_creates_claims_for_citations(vault, fake_embed):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    write_page(vault_root, "page.md",
               "# P\n\n## Methods\n\nAttention is QK^T/√dk. [[vaswani2017.pdf]]\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    claim = conn.execute("SELECT text FROM claims").fetchone()
    assert claim is not None
    assert "[[vaswani2017.pdf]]" in claim[0]


def test_sync_page_claim_has_embedding(vault, fake_embed):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('src1', 'raw/s.pdf', 'paper')"
    )
    write_page(vault_root, "page.md", "# P\n\nClaim text. [[src1.pdf]]\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    emb = conn.execute("SELECT embedding FROM claims").fetchone()[0]
    assert len(emb) == 768


def test_sync_page_claim_source_row_created(vault, fake_embed):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('src1', 'raw/s.pdf', 'paper')"
    )
    write_page(vault_root, "page.md", "# P\n\nClaim. [[src1.pdf]]\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    row = conn.execute(
        "SELECT cs.citation_number FROM claim_sources cs"
        " JOIN claims c ON cs.claim_id=c.id"
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_sync_page_citation_numbers_sequential(vault, fake_embed):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('a2020', 'raw/a.pdf', 'paper')"
    )
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('b2021', 'raw/b.pdf', 'paper')"
    )
    write_page(vault_root, "page.md",
               "# P\n\nFirst. [[a2020.pdf]] Second. [[b2021.pdf]] Back to first. [[a2020.pdf]]\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    a_num = conn.execute(
        "SELECT cs.citation_number FROM claim_sources cs"
        " JOIN sources s ON cs.source_id=s.id WHERE s.slug='a2020' LIMIT 1"
    ).fetchone()[0]
    b_num = conn.execute(
        "SELECT cs.citation_number FROM claim_sources cs"
        " JOIN sources s ON cs.source_id=s.id WHERE s.slug='b2021' LIMIT 1"
    ).fetchone()[0]
    assert a_num == 1
    assert b_num == 2


def test_sync_page_claim_relationship_preserved(vault, fake_embed):
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('src1', 'raw/s.pdf', 'paper')"
    )
    text = "# P\n\nThis holds. [[src1.pdf]]\n"
    write_page(vault_root, "page.md", text)
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    conn.execute("UPDATE claim_sources SET relationship='supports'")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    rel = conn.execute("SELECT relationship FROM claim_sources").fetchone()[0]
    assert rel == "supports"


def test_sync_page_unknown_source_key_skips_claim_source(vault, fake_embed):
    vault_root, conn = vault
    write_page(vault_root, "page.md", "# P\n\nClaim. [[unknown2020.pdf]]\n")
    sync_page(conn, vault_root, Path("wiki/page.md"), fake_embed)
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM claim_sources").fetchone()[0] == 0
