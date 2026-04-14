import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.search import bm25_search, vec_search, hybrid_search, SearchHit


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)
    c.execute("LOAD fts")
    # Insert a page with two sections
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attn', 'wiki/attn.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='attn'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'Overview', 'Attention computes queries keys values scaled dot product.', 'h1', 8, ?)",
        [page_id, [0.9] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 1, 'Background', 'Transformer encoder decoder architecture residual connections.', 'h2', 6, ?)",
        [page_id, [0.0] * 767 + [0.9]],
    )
    c.execute("PRAGMA create_fts_index('sections', 'id', 'content')")
    # source chunk for scope=sources testing
    c.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    c.execute(
        "INSERT INTO source_chunks (source_id, chunk_index, start_line, end_line, token_count, content, embedding)"
        " VALUES (?, 0, 1, 20, 10, 'Scaled dot-product attention mechanism query key value softmax.', ?)",
        [src_id, [0.8] + [0.0] * 767],
    )
    c.execute("PRAGMA create_fts_index('source_chunks', 'id', 'content')")
    return c


def test_bm25_search_finds_matching_section(conn):
    hits = bm25_search(conn, "queries", scope="wiki", n=5)
    assert len(hits) >= 1
    assert any(h.section_name == "Overview" for h in hits)


def test_bm25_search_scope_sources(conn):
    hits = bm25_search(conn, "softmax", scope="sources", n=5)
    assert len(hits) >= 1
    assert all(h.source_type == "source" for h in hits)


def test_bm25_search_scope_all(conn):
    hits = bm25_search(conn, "attention", scope="all", n=10)
    types = {h.source_type for h in hits}
    assert "wiki" in types
    assert "source" in types


def test_bm25_search_no_results(conn):
    hits = bm25_search(conn, "zzznomatchzzz", scope="wiki", n=5)
    assert hits == []


def test_vec_search_finds_similar_section(conn):
    # Query vector close to Overview section ([0.9, 0.0, ...])
    query_vec = [0.9] + [0.0] * 767
    hits = vec_search(conn, query_vec, scope="wiki", n=5)
    assert len(hits) >= 1
    assert hits[0].section_name == "Overview"


def test_vec_search_scope_sources(conn):
    query_vec = [0.8] + [0.0] * 767
    hits = vec_search(conn, query_vec, scope="sources", n=5)
    assert len(hits) >= 1
    assert all(h.source_type == "source" for h in hits)


def test_hybrid_search_combines_results(conn):
    query_vec = [0.9] + [0.0] * 767
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    assert len(hits) >= 1
    # Overview should rank highly (matches both BM25 and vec)
    assert hits[0].section_name == "Overview"


def test_hybrid_search_mechanism_label(conn):
    query_vec = [0.9] + [0.0] * 767
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    overview = next(h for h in hits if h.section_name == "Overview")
    # Should match both BM25 and vector
    assert overview.mechanism == "bm25+vec"


def test_hybrid_search_vec_only_mechanism(conn):
    # Vector close to Background section ([0.0, ..., 0.9])
    query_vec = [0.0] * 767 + [0.9]
    # BM25 query that won't match Background
    hits = hybrid_search(conn, "queries", query_vec, scope="wiki", n=5)
    background = next((h for h in hits if h.section_name == "Background"), None)
    if background:
        assert background.mechanism in ("vec", "bm25+vec")


def test_vec_search_min_score_filters_low_similarity(conn):
    # Orthogonal to all stored embeddings — should return nothing above 0.45
    query_vec = [0.0] * 383 + [1.0] + [0.0] * 384  # middle dimension, not used by any stored vec
    hits = vec_search(conn, query_vec, scope="wiki", n=5, min_score=0.45)
    assert hits == []


def test_hybrid_search_returns_empty_when_nothing_relevant(conn):
    # A query vector orthogonal to all stored embeddings and no BM25 match
    query_vec = [0.0] * 383 + [1.0] + [0.0] * 384
    hits = hybrid_search(conn, "zzznomatch", query_vec, scope="wiki", n=5)
    assert hits == []
