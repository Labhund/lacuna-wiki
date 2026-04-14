from __future__ import annotations

import duckdb
import pytest
import respx
import httpx

from lacuna_wiki.sources.fetcher import key_from_url, parse_jina_headers, fetch_url_as_markdown
from lacuna_wiki.db.schema import init_db


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    init_db(c)
    yield c
    c.close()


# --- key_from_url ---

def test_key_from_url_blog_post(conn):
    url = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"
    key = key_from_url(url, conn)
    assert key == "thetransformerfamilyv2"


def test_key_from_url_arxiv(conn):
    url = "https://arxiv.org/abs/1706.03762"
    key = key_from_url(url, conn)
    assert key == "170603762"


def test_key_from_url_root_falls_back(conn):
    url = "https://example.com/"
    key = key_from_url(url, conn)
    assert key == "examplecom"


def test_key_from_url_disambiguates(conn):
    conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('mypost', 'raw/x.md', 'url')"
    )
    url = "https://example.com/my-post"
    key = key_from_url(url, conn)
    assert key == "mypostb"


def test_key_from_url_strips_query_and_fragment(conn):
    url = "https://example.com/articles/deep-learning?ref=newsletter#section"
    key = key_from_url(url, conn)
    assert key == "deeplearning"


def test_key_from_url_youtube_uses_video_id(conn):
    url = "https://www.youtube.com/watch?v=TYgCRPCAFhE"
    key = key_from_url(url, conn)
    assert key == "tygcrpcafhe"


def test_key_from_url_youtube_without_www(conn):
    url = "https://youtube.com/watch?v=abc123XYZ"
    key = key_from_url(url, conn)
    assert key == "abc123xyz"


# --- parse_jina_headers ---

_JINA_RESPONSE = """\
Title: Attention Is All You Need
URL Source: https://arxiv.org/abs/1706.03762
Published Time: 2017-06-12

## Abstract

The dominant sequence transduction models are based on complex recurrent...
"""

_JINA_ISO_TIME = """\
Title: My Blog Post
URL Source: https://example.com/my-post
Published Time: 2023-01-27T00:00:00.000Z

Content here.
"""

_JINA_NO_DATE = """\
Title: Some Page
URL Source: https://example.com/page

Content without a date.
"""


def test_parse_jina_headers_title():
    meta = parse_jina_headers(_JINA_RESPONSE)
    assert meta["title"] == "Attention Is All You Need"


def test_parse_jina_headers_date():
    meta = parse_jina_headers(_JINA_RESPONSE)
    assert meta["published_time"] == "2017-06-12"


def test_parse_jina_headers_iso_date_truncated():
    meta = parse_jina_headers(_JINA_ISO_TIME)
    assert meta["published_time"] == "2023-01-27"


def test_parse_jina_headers_no_date():
    meta = parse_jina_headers(_JINA_NO_DATE)
    assert "published_time" not in meta


def test_parse_jina_headers_no_title():
    meta = parse_jina_headers("Just some content without headers.\n")
    assert "title" not in meta


# --- fetch_url_as_markdown ---

@respx.mock
def test_fetch_url_returns_markdown():
    url = "https://example.com/my-article"
    respx.get("https://r.jina.ai/https://example.com/my-article").mock(
        return_value=httpx.Response(200, text="Title: My Article\n\nContent here.")
    )
    result = fetch_url_as_markdown(url)
    assert "Title: My Article" in result
    assert "Content here" in result


@respx.mock
def test_fetch_url_raises_on_404():
    url = "https://example.com/not-found"
    respx.get("https://r.jina.ai/https://example.com/not-found").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_url_as_markdown(url)
