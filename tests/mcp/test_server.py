import duckdb
import pytest

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.mcp.server import dispatch_wiki


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "vault.db"
    c = duckdb.connect(str(db))
    init_db(c)
    c.execute("LOAD fts")
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('mypage', 'wiki/mypage.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='mypage'").fetchone()[0]
    c.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count, embedding)"
        " VALUES (?, 0, 'Intro', 'Hello wiki content here.', 'h1', 4, ?)",
        [page_id, [0.5] + [0.0] * 767],
    )
    c.execute("PRAGMA create_fts_index('sections', 'id', 'content')")
    return c


def fake_embed(texts):
    return [[0.5] + [0.0] * 767 for _ in texts]


def test_dispatch_search_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, q="wiki content", scope="wiki")
    assert isinstance(result, str)
    assert len(result) > 0


def test_dispatch_navigate_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, page="mypage")
    assert isinstance(result, str)
    assert "mypage" in result


def test_dispatch_multi_read_returns_string(conn):
    result = dispatch_wiki(conn, fake_embed, pages=["mypage"])
    assert isinstance(result, str)
    assert "mypage" in result


def test_dispatch_no_params_raises(conn):
    with pytest.raises(ValueError, match="exactly one"):
        dispatch_wiki(conn, fake_embed)


def test_dispatch_conflicting_params_raises(conn):
    with pytest.raises(ValueError, match="exactly one"):
        dispatch_wiki(conn, fake_embed, q="query", page="mypage")


def test_dispatch_page_not_found(conn):
    result = dispatch_wiki(conn, fake_embed, page="nosuchpage")
    assert "not found" in result.lower()
