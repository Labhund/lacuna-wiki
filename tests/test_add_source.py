"""Integration tests for llm-wiki add-source.

Embedding calls are monkeypatched — these tests do not require a running server.
PDF extraction is also monkeypatched — these tests do not require pdftotext.
"""
import duckdb
import pytest
import respx
import httpx
from click.testing import CliRunner
from pathlib import Path

from llm_wiki.cli.add_source import add_source
from llm_wiki.db.schema import init_db
from llm_wiki.vault import db_path, state_dir_for


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    state = state_dir_for(tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(tmp_path)))
    init_db(conn)
    conn.close()
    return tmp_path


@pytest.fixture(autouse=True)
def mock_embed(monkeypatch):
    """Replace embed_texts with a function that returns fake 768-dim vectors."""
    def fake_embed(texts, **kwargs):
        return [[0.1] * 768 for _ in texts]
    monkeypatch.setattr("llm_wiki.cli.add_source.embed_texts", fake_embed)


def _write_source(tmp_path, name="paper.md", content=None):
    if content is None:
        content = "## Introduction\n\nThis paper introduces attention.\n\n## Methods\n\nWe use dot products.\n"
    src = tmp_path / name
    src.write_text(content)
    return src


def test_add_md_source_creates_sources_row(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    result = CliRunner().invoke(add_source, [str(src)])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


def test_add_md_source_creates_chunks(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src)])
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0]
    conn.close()
    assert count >= 1


def test_add_md_source_with_concept(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--concept", "machine-learning/attention"])
    assert (vault / "raw" / "machine-learning" / "attention").is_dir()


def test_add_md_source_slug_from_filename(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path, name="vaswani2017.md")
    CliRunner().invoke(add_source, [str(src)])
    conn = duckdb.connect(str(db_path(vault)))
    slug = conn.execute("SELECT slug FROM sources").fetchone()[0]
    conn.close()
    assert slug == "vaswani2017"


def test_add_md_source_output_contains_cite_as(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path, name="vaswani2017.md")
    result = CliRunner().invoke(add_source, [str(src)])
    assert "[[vaswani2017.md]]" in result.output


def test_add_md_source_with_type_override(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--type", "session"])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "session"


def test_add_md_source_with_date(vault, monkeypatch, tmp_path):
    monkeypatch.chdir(vault)
    src = _write_source(tmp_path)
    CliRunner().invoke(add_source, [str(src), "--date", "2024-03-15"])
    conn = duckdb.connect(str(db_path(vault)))
    pub_date = conn.execute("SELECT published_date FROM sources").fetchone()[0]
    conn.close()
    assert str(pub_date) == "2024-03-15"


# --- URL add-source tests ---

_JINA_BLOG = """\
Title: The Transformer Family
URL Source: https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/
Published Time: 2023-01-27

## Overview

Transformers are a type of neural network architecture.

## Key Properties

The attention mechanism is central.
"""

_JINA_ARXIV = """\
Title: Attention Is All You Need
URL Source: https://arxiv.org/abs/1706.03762
Published Time: 2017-06-12

10.48550/arXiv.1706.03762

## Abstract

The dominant sequence transduction models...
"""

_BIBTEX = """@article{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and others},
  year={2017}
}
"""

_BLOG_URL = "https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/"


@respx.mock
def test_add_url_source_creates_sources_row(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    result = CliRunner().invoke(add_source, [_BLOG_URL])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


@respx.mock
def test_add_url_source_type_is_url(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "url"


@respx.mock
def test_add_url_source_title_from_jina_headers(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL])
    conn = duckdb.connect(str(db_path(vault)))
    title = conn.execute("SELECT title FROM sources").fetchone()[0]
    conn.close()
    assert title == "The Transformer Family"


@respx.mock
def test_add_url_source_date_from_jina_headers(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL])
    conn = duckdb.connect(str(db_path(vault)))
    pub_date = conn.execute("SELECT published_date FROM sources").fetchone()[0]
    conn.close()
    assert str(pub_date) == "2023-01-27"


@respx.mock
def test_add_url_source_writes_md_file(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL])
    md_files = list((vault / "raw").rglob("*.md"))
    assert len(md_files) == 1
    assert "Transformers" in md_files[0].read_text()


@respx.mock
def test_add_url_source_with_concept(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL, "--concept", "machine-learning"])
    assert (vault / "raw" / "machine-learning").is_dir()


@respx.mock
def test_add_url_source_output_contains_cite_as(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    result = CliRunner().invoke(add_source, [_BLOG_URL])
    assert "Cite as:" in result.output
    assert "[[" in result.output


@respx.mock
def test_add_url_source_doi_uses_bibtex_key(vault, monkeypatch):
    """When Jina content contains a DOI, the key is derived from bibtex author+year."""
    monkeypatch.chdir(vault)
    arxiv_url = "https://arxiv.org/abs/1706.03762"
    respx.get(f"https://r.jina.ai/{arxiv_url}").mock(
        return_value=httpx.Response(200, text=_JINA_ARXIV)
    )
    respx.get(
        "https://api.crossref.org/works/10.48550/arXiv.1706.03762/transform/application/x-bibtex"
    ).mock(return_value=httpx.Response(200, text=_BIBTEX))

    result = CliRunner().invoke(add_source, [arxiv_url])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    slug = conn.execute("SELECT slug FROM sources").fetchone()[0]
    conn.close()
    assert slug == "vaswani2017"


@respx.mock
def test_add_url_source_type_override(vault, monkeypatch):
    monkeypatch.chdir(vault)
    respx.get(f"https://r.jina.ai/{_BLOG_URL}").mock(
        return_value=httpx.Response(200, text=_JINA_BLOG)
    )
    CliRunner().invoke(add_source, [_BLOG_URL, "--type", "blog"])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "blog"


# --- YouTube add-source tests ---

import json
import subprocess as _subprocess

_FAKE_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:04.000
Hello and welcome to this talk

00:00:04.000 --> 00:00:08.000
about attention mechanisms
"""

_FAKE_YT_INFO = {
    "title": "Attention Is All You Need — Talk",
    "upload_date": "20230601",
    "channel": "ML Conference",
}

_YT_URL = "https://www.youtube.com/watch?v=TYgCRPCAFhE"


def _make_fake_yt_dlp(vtt_content, info_content):
    """Return a fake subprocess.run that writes VTT and info JSON to the output dir."""
    def fake_run(cmd, **kwargs):
        o_idx = cmd.index("-o")
        out_dir = cmd[o_idx + 1].rsplit("/", 1)[0]
        Path(f"{out_dir}/TYgCRPCAFhE.en.vtt").write_text(vtt_content)
        Path(f"{out_dir}/TYgCRPCAFhE.info.json").write_text(json.dumps(info_content))
        return _subprocess.CompletedProcess(cmd, 0, b"", b"")
    return fake_run


def test_add_youtube_source_creates_row(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr("subprocess.run", _make_fake_yt_dlp(_FAKE_VTT, _FAKE_YT_INFO))
    result = CliRunner().invoke(add_source, [_YT_URL])
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path(vault)))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1


def test_add_youtube_source_type_is_transcript(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr("subprocess.run", _make_fake_yt_dlp(_FAKE_VTT, _FAKE_YT_INFO))
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(vault)))
    src_type = conn.execute("SELECT source_type FROM sources").fetchone()[0]
    conn.close()
    assert src_type == "transcript"


def test_add_youtube_source_key_uses_title_slug(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr("subprocess.run", _make_fake_yt_dlp(_FAKE_VTT, _FAKE_YT_INFO))
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(vault)))
    slug = conn.execute("SELECT slug FROM sources").fetchone()[0]
    conn.close()
    # "Attention Is All You Need — Talk" → "attention-is-all-you-need-talk"
    assert slug == "attention-is-all-you-need-talk"


def test_add_youtube_source_title_and_date(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr("subprocess.run", _make_fake_yt_dlp(_FAKE_VTT, _FAKE_YT_INFO))
    CliRunner().invoke(add_source, [_YT_URL])
    conn = duckdb.connect(str(db_path(vault)))
    row = conn.execute("SELECT title, published_date FROM sources").fetchone()
    conn.close()
    assert row[0] == "Attention Is All You Need — Talk"
    assert str(row[1]) == "2023-06-01"


def test_add_youtube_source_writes_md_with_headings(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr("subprocess.run", _make_fake_yt_dlp(_FAKE_VTT, _FAKE_YT_INFO))
    CliRunner().invoke(add_source, [_YT_URL])
    md_files = list((vault / "raw").rglob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "## [00:00:00]" in content
    assert "Hello and welcome" in content


def test_add_youtube_source_no_captions_exits_nonzero(vault, monkeypatch):
    monkeypatch.chdir(vault)
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _subprocess.CompletedProcess(cmd, 0, b"", b""),
    )
    result = CliRunner().invoke(add_source, [_YT_URL])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# key_from_author_year
# ---------------------------------------------------------------------------

from llm_wiki.sources.key import key_from_author_year


def test_key_from_author_year_basic():
    # Last name "Hay" → "hay", 2026, title first 5 alphanumeric → "wedon"
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Chris Hay", 2026, "We Don't Need KV Cache Anymore?", conn)
    assert key == "hay2026wedon"


def test_key_from_author_year_title_truncated():
    # Single-name author: "Vaswani" → "vaswani"; title first 5 alphanumeric → "atten"
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Vaswani", 2017, "Attention Is All You Need", conn)
    assert key == "vaswani2017atten"


def test_key_from_author_year_disambiguates():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    conn.execute("INSERT INTO sources VALUES ('hay2026wedon')")
    key = key_from_author_year("Chris Hay", 2026, "We Don't Need KV Cache Anymore?", conn)
    assert key == "hay2026wedonb"


def test_key_from_author_year_no_title():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    key = key_from_author_year("Chris Hay", 2026, None, conn)
    assert key == "hay2026"
