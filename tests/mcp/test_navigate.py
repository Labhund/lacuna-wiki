import duckdb
import pytest

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.navigate import navigate_page, multi_read, PageNotFoundError


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)

    # Page 1: attention-mechanism
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('attention-mechanism', 'wiki/attention-mechanism.md', now())")
    attn_id = c.execute("SELECT id FROM pages WHERE slug='attention-mechanism'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'attention-mechanism', 'Intro text.', 'h0', 2, ?)",
        [attn_id, [0.9] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 1, 'Scaled Dot-Product', 'Attention computes QKT over sqrt dk.', 'h1', 7, ?)",
        [attn_id, [0.8, 0.1] + [0.0] * 766],
    )
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 2, 'Multi-Head', 'Multiple heads in parallel.', 'h2', 4, ?)",
        [attn_id, [0.0] * 767 + [0.9]],
    )

    # Page 2: transformer (links to attention-mechanism)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('transformer', 'wiki/transformer.md', now())")
    trans_id = c.execute("SELECT id FROM pages WHERE slug='transformer'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'transformer', 'Transformer uses attention.', 'h3', 4, ?)",
        [trans_id, [0.7] + [0.0] * 767],
    )
    c.execute(
        "INSERT INTO links (source_page_id, target_slug) VALUES (?, 'attention-mechanism')",
        [trans_id],
    )

    # Source + claim on attention-mechanism
    c.execute("INSERT INTO sources (slug, path, title, published_date, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'Attention Is All You Need', '2017-06-12', 'paper')")
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    sec_id = c.execute("SELECT id FROM sections WHERE name='Scaled Dot-Product'").fetchone()[0]
    c.execute(
        "INSERT INTO claims (page_id, section_id, text, embedding) VALUES (?, ?, 'Attention claim.', NULL)",
        [attn_id, sec_id],
    )
    claim_id = c.execute("SELECT id FROM claims WHERE text='Attention claim.'").fetchone()[0]
    c.execute(
        "INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?, ?, 1)",
        [claim_id, src_id],
    )
    return c


def test_navigate_page_returns_section_content(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "Intro text." in result


def test_navigate_page_full_read_returns_all_section_content(conn):
    """Full-page read (no section_name) must include content from every section."""
    result = navigate_page(conn, "attention-mechanism")
    assert "Attention computes QKT" in result   # Scaled Dot-Product section
    assert "Multiple heads in parallel" in result  # Multi-Head section


def test_navigate_page_specific_section(conn):
    result = navigate_page(conn, "attention-mechanism", section_name="Scaled Dot-Product")
    assert "Attention computes QKT" in result


def test_navigate_page_specific_section_excludes_other_sections(conn):
    """When a section is specified, other sections' content is NOT included."""
    result = navigate_page(conn, "attention-mechanism", section_name="Scaled Dot-Product")
    assert "Multiple heads in parallel" not in result


def test_navigate_page_lists_all_sections(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "Scaled Dot-Product" in result
    assert "Multi-Head" in result


def test_navigate_page_links_in(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "transformer" in result


def test_navigate_page_sources_cited(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "vaswani2017" in result
    assert "Attention Is All You Need" in result
    assert "[1]" in result


def test_navigate_page_not_found_raises(conn):
    with pytest.raises(PageNotFoundError):
        navigate_page(conn, "nonexistent-page")


def test_navigate_page_semantically_close(conn):
    result = navigate_page(conn, "attention-mechanism")
    assert "semantically close" in result.lower()


def test_multi_read_concatenates_pages(conn):
    result = multi_read(conn, ["attention-mechanism", "transformer"])
    assert "attention-mechanism" in result
    assert "transformer" in result
    assert "---" in result
