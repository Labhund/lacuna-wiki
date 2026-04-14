import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.cli.adversary_commit import (
    Verdict, Supersession, parse_verdict, parse_supersession, write_verdicts,
)


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "v.db"))
    init_db(c)
    c.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('p', 'wiki/p.md', now())")
    page_id = c.execute("SELECT id FROM pages WHERE slug='p'").fetchone()[0]
    c.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('vaswani2017', 'raw/v.pdf', 'paper')"
    )
    src_id = c.execute("SELECT id FROM sources WHERE slug='vaswani2017'").fetchone()[0]
    # claim 1
    c.execute("INSERT INTO claims (page_id, text) VALUES (?, 'Claim A. [[vaswani2017.pdf]]')", [page_id])
    claim1 = c.execute("SELECT id FROM claims ORDER BY id LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?,?,1)", [claim1, src_id])
    # claim 2
    c.execute("INSERT INTO claims (page_id, text) VALUES (?, 'Claim B. [[vaswani2017.pdf]]')", [page_id])
    claim2 = c.execute("SELECT id FROM claims ORDER BY id DESC LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO claim_sources (claim_id, source_id, citation_number) VALUES (?,?,2)", [claim2, src_id])
    return c, claim1, claim2


def test_parse_verdict_supports():
    v = parse_verdict("claim_id=42,rel=supports")
    assert v == Verdict(claim_id=42, rel="supports")


def test_parse_verdict_gap():
    v = parse_verdict("claim_id=7,rel=gap")
    assert v == Verdict(claim_id=7, rel="gap")


def test_parse_verdict_refutes():
    v = parse_verdict("claim_id=1,rel=refutes")
    assert v == Verdict(claim_id=1, rel="refutes")


def test_parse_verdict_bad_rel_raises():
    with pytest.raises(ValueError, match="rel must be"):
        parse_verdict("claim_id=1,rel=maybe")


def test_parse_supersession():
    s = parse_supersession("old=3,new=9")
    assert s == Supersession(old_id=3, new_id=9)


def test_write_verdicts_sets_relationship(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="supports")], [])
    rel = c.execute(
        "SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]
    ).fetchone()[0]
    assert rel == "supports"


def test_write_verdicts_sets_checked_at(conn):
    c, claim1, _ = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="gap")], [])
    checked = c.execute(
        "SELECT checked_at FROM claim_sources WHERE claim_id=?", [claim1]
    ).fetchone()[0]
    assert checked is not None


def test_write_verdicts_sets_last_adversary_check(conn):
    c, claim1, _ = conn
    write_verdicts(c, [Verdict(claim_id=claim1, rel="supports")], [])
    ts = c.execute(
        "SELECT last_adversary_check FROM claims WHERE id=?", [claim1]
    ).fetchone()[0]
    assert ts is not None


def test_write_verdicts_multiple(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [
        Verdict(claim_id=claim1, rel="supports"),
        Verdict(claim_id=claim2, rel="gap"),
    ], [])
    r1 = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]).fetchone()[0]
    r2 = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim2]).fetchone()[0]
    assert r1 == "supports"
    assert r2 == "gap"


def test_write_supersession_sets_superseded_by(conn):
    c, claim1, claim2 = conn
    write_verdicts(c, [], [Supersession(old_id=claim1, new_id=claim2)])
    sup = c.execute(
        "SELECT superseded_by FROM claims WHERE id=?", [claim1]
    ).fetchone()[0]
    assert sup == claim2


def test_write_verdicts_and_supersession_together(conn):
    c, claim1, claim2 = conn
    write_verdicts(
        c,
        [Verdict(claim_id=claim1, rel="refutes")],
        [Supersession(old_id=claim1, new_id=claim2)],
    )
    rel = c.execute("SELECT relationship FROM claim_sources WHERE claim_id=?", [claim1]).fetchone()[0]
    sup = c.execute("SELECT superseded_by FROM claims WHERE id=?", [claim1]).fetchone()[0]
    assert rel == "refutes"
    assert sup == claim2
