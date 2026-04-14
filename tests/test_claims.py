import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.cli.claims import list_claims


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "v.db"))
    init_db(c)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attn', 'wiki/attn.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='attn'").fetchone()[0]
    c.execute(
        "INSERT INTO sources (slug, path, source_type, registered_at)"
        " VALUES ('vaswani2017', 'raw/v.pdf', 'paper', '2026-01-01')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    # Claim 1 — never evaluated
    c.execute(
        "INSERT INTO claims (page_id, text) VALUES (?, 'Attention computes QKT. [[vaswani2017.pdf]]')",
        [page_id],
    )
    claim1 = c.execute("SELECT id FROM claims ORDER BY id LIMIT 1").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 1)",
        [claim1, src_id],
    )
    # Claim 2 — already evaluated (last_adversary_check set)
    c.execute(
        "INSERT INTO claims (page_id, text, last_adversary_check)"
        " VALUES (?, 'Softmax normalises weights. [[vaswani2017.pdf]]', now())",
        [page_id],
    )
    claim2 = c.execute("SELECT id FROM claims ORDER BY id DESC LIMIT 1").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 2)",
        [claim2, src_id],
    )
    return c


def test_list_claims_virgin_returns_unevaluated(conn):
    results = list_claims(conn, "virgin")
    assert len(results) == 1
    assert results[0]["claim_id"] is not None
    assert "Attention computes" in results[0]["text"]


def test_list_claims_virgin_excludes_evaluated(conn):
    results = list_claims(conn, "virgin")
    texts = [r["text"] for r in results]
    assert not any("Softmax" in t for t in texts)


def test_list_claims_stale_includes_virgin(conn):
    results = list_claims(conn, "stale")
    assert len(results) >= 1


def test_list_claims_page_mode(conn):
    results = list_claims(conn, "page", page_slug="attn")
    assert len(results) == 2  # both claims on this page (superseded_by IS NULL for both)


def test_list_claims_page_mode_wrong_slug(conn):
    results = list_claims(conn, "page", page_slug="nonexistent")
    assert results == []


def test_list_claims_result_has_expected_keys(conn):
    results = list_claims(conn, "virgin")
    r = results[0]
    assert "claim_id" in r
    assert "page_slug" in r
    assert "section_name" in r
    assert "text" in r
    assert "source_slug" in r
    assert "published_date" in r
