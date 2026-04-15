"""Tests for frontmatter parsing and DB sync."""
import json
import duckdb
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from lacuna_wiki.daemon.parser import parse_frontmatter, tags_to_db
from lacuna_wiki.daemon.watcher import WikiEventHandler
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.vault import db_path, state_dir_for


# ---------------------------------------------------------------------------
# parse_frontmatter unit tests
# ---------------------------------------------------------------------------

def test_no_frontmatter_returns_empty_tags_and_unchanged_text():
    text = "# my page\n\nsome content\n"
    tags, body = parse_frontmatter(text)
    assert tags == []
    assert body == text


def test_frontmatter_stripped_from_body():
    text = "---\ntags: [foo, bar]\n---\n\n# title\n\ncontent\n"
    _, body = parse_frontmatter(text)
    assert "---" not in body
    assert "tags:" not in body
    assert "# title" in body


def test_tags_extracted():
    text = "---\ntags: [attention, transformers, deep-learning]\n---\n\n# title\n"
    tags, _ = parse_frontmatter(text)
    assert tags == ["attention", "transformers", "deep-learning"]


def test_single_tag():
    text = "---\ntags: [attention]\n---\n\n# title\n"
    tags, _ = parse_frontmatter(text)
    assert tags == ["attention"]


def test_empty_tags_list():
    text = "---\ntags: []\n---\n\n# title\n"
    tags, _ = parse_frontmatter(text)
    assert tags == []


def test_unknown_frontmatter_keys_ignored():
    text = "---\nstatus: draft\ntags: [foo]\nauthor: someone\n---\n\n# title\n"
    tags, body = parse_frontmatter(text)
    assert tags == ["foo"]
    assert "status" not in body
    assert "author" not in body


def test_extract_extra_frontmatter_returns_unknown_keys():
    from lacuna_wiki.daemon.parser import extract_extra_frontmatter
    text = "---\ntags: [foo]\nsynthesis: true\ncreated: 2026-01-01\n---\n# title\n"
    extras = extract_extra_frontmatter(text)
    assert extras == ["synthesis: true"]


def test_extract_extra_frontmatter_empty_when_only_managed_keys():
    from lacuna_wiki.daemon.parser import extract_extra_frontmatter
    text = "---\ntags: [foo]\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n# title\n"
    assert extract_extra_frontmatter(text) == []


def test_extract_extra_frontmatter_no_frontmatter():
    from lacuna_wiki.daemon.parser import extract_extra_frontmatter
    assert extract_extra_frontmatter("# title\n\ncontent\n") == []


def test_daemon_preserves_synthesis_flag(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "synth.md"
    page.write_text(
        "---\ntags: [neuroscience]\nsynthesis: true\n---\n\n# synth\n\ncontent\n"
    )
    fire_modified(handler, page)

    text = page.read_text()
    assert "synthesis: true" in text
    assert "created:" in text
    assert "updated:" in text


def test_tags_to_db_returns_json():
    result = tags_to_db(["a", "b"])
    assert json.loads(result) == ["a", "b"]


def test_tags_to_db_empty_returns_none():
    assert tags_to_db([]) is None


# ---------------------------------------------------------------------------
# Sync integration: tags stored in pages table
# ---------------------------------------------------------------------------

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


def fake_embed(texts):
    return [[0.1] * 768 for _ in texts]


def fire_modified(handler, path: Path):
    ev = MagicMock()
    ev.src_path = str(path)
    ev.is_directory = False
    handler.on_modified(ev)


def test_tags_stored_in_db(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "attention.md"
    page.write_text(
        "---\ntags: [attention, transformers]\n---\n\n# attention\n\nsome content\n"
    )
    fire_modified(handler, page)

    row = conn.execute("SELECT tags FROM pages WHERE slug='attention'").fetchone()
    assert row is not None
    assert json.loads(row[0]) == ["attention", "transformers"]


def test_page_without_frontmatter_has_null_tags(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "simple.md"
    page.write_text("# simple\n\nsome content\n")
    fire_modified(handler, page)

    row = conn.execute("SELECT tags FROM pages WHERE slug='simple'").fetchone()
    assert row is not None
    assert row[0] is None


def test_frontmatter_not_indexed_as_section_content(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "tagged.md"
    page.write_text(
        "---\ntags: [foo]\n---\n\n# tagged\n\nreal content here\n"
    )
    fire_modified(handler, page)

    sections = conn.execute(
        "SELECT content FROM sections WHERE page_id IN "
        "(SELECT id FROM pages WHERE slug='tagged')"
    ).fetchall()
    for (content,) in sections:
        assert "tags:" not in content
        assert "---" not in content


def test_tags_updated_on_page_edit(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "evolving.md"
    page.write_text("---\ntags: [old-tag]\n---\n\n# evolving\n\ncontent\n")
    fire_modified(handler, page)

    page.write_text("---\ntags: [new-tag, another]\n---\n\n# evolving\n\ncontent\n")
    fire_modified(handler, page)

    row = conn.execute("SELECT tags FROM pages WHERE slug='evolving'").fetchone()
    assert json.loads(row[0]) == ["new-tag", "another"]


def test_tags_cleared_when_frontmatter_removed(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "clearing.md"
    page.write_text("---\ntags: [foo]\n---\n\n# clearing\n\ncontent\n")
    fire_modified(handler, page)

    page.write_text("# clearing\n\ncontent\n")
    fire_modified(handler, page)

    row = conn.execute("SELECT tags FROM pages WHERE slug='clearing'").fetchone()
    assert row[0] is None


def test_daemon_writes_dates_into_frontmatter(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "dated.md"
    page.write_text("# dated\n\ncontent\n")
    fire_modified(handler, page)

    text = page.read_text()
    assert text.startswith("---\n")
    assert "created:" in text
    assert "updated:" in text


def test_daemon_writes_dates_with_tags(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    page = vault_root / "wiki" / "tagged-dated.md"
    page.write_text("---\ntags: [foo, bar]\n---\n\n# tagged-dated\n\ncontent\n")
    fire_modified(handler, page)

    text = page.read_text()
    assert "tags: [foo, bar]" in text
    assert "created:" in text
    assert "updated:" in text


def test_redundant_sync_is_skipped(vault):
    """Second sync after daemon writes frontmatter must not re-embed (body_hash guard)."""
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    embed_calls = []
    def counting_embed(texts):
        embed_calls.append(len(texts))
        return [[0.1] * 768 for _ in texts]

    handler._embed_fn = counting_embed

    page = vault_root / "wiki" / "idempotent.md"
    page.write_text("# idempotent\n\ncontent\n")
    fire_modified(handler, page)  # first sync — sections embedded

    calls_after_first = len(embed_calls)

    # Simulate the watchdog firing again after daemon wrote the frontmatter
    fire_modified(handler, page)  # body unchanged — should skip

    assert len(embed_calls) == calls_after_first, "re-embed should not happen on body-unchanged event"
