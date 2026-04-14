from datetime import date, datetime
import duckdb
import pytest
from lacuna_wiki.db.schema import init_db
from lacuna_wiki.sources.chunker import Chunk
from lacuna_wiki.sources.register import register_chunks, register_source


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    init_db(c)
    return c


def test_register_source_inserts_row(conn):
    source_id = register_source(conn, "vaswani2017", "raw/vaswani2017.pdf",
                                "Attention Is All You Need", "Vaswani et al.",
                                date(2017, 6, 12), "paper")
    row = conn.execute("SELECT slug, path, title, source_type FROM sources WHERE id = ?",
                       [source_id]).fetchone()
    assert row == ("vaswani2017", "raw/vaswani2017.pdf", "Attention Is All You Need", "paper")


def test_register_source_sets_registered_at(conn):
    source_id = register_source(conn, "test2024", "raw/test.md", None, None, None, "note")
    ts = conn.execute("SELECT registered_at FROM sources WHERE id = ?", [source_id]).fetchone()[0]
    assert ts is not None


def test_register_source_returns_id(conn):
    id1 = register_source(conn, "paper1", "raw/p1.pdf", None, None, None, "paper")
    id2 = register_source(conn, "paper2", "raw/p2.pdf", None, None, None, "paper")
    assert id1 != id2


def _make_chunk(idx: int, text: str = "some text") -> Chunk:
    return Chunk(
        chunk_index=idx, heading=f"Section {idx}",
        start_line=idx * 10 + 1, end_line=idx * 10 + 5,
        token_count=len(text) // 4, text=text,
    )


def test_register_chunks_inserts_rows(conn):
    source_id = register_source(conn, "src1", "raw/src1.md", None, None, None, "note")
    chunks = [_make_chunk(0, "text one"), _make_chunk(1, "text two")]
    embeddings = [[0.1] * 768, [0.2] * 768]
    register_chunks(conn, source_id, chunks, embeddings)
    count = conn.execute("SELECT COUNT(*) FROM source_chunks WHERE source_id = ?",
                         [source_id]).fetchone()[0]
    assert count == 2


def test_register_chunks_stores_offsets(conn):
    source_id = register_source(conn, "src2", "raw/src2.md", None, None, None, "note")
    chunk = _make_chunk(0, "hello")
    register_chunks(conn, source_id, [chunk], [[0.5] * 768])
    row = conn.execute(
        "SELECT chunk_index, heading, start_line, end_line FROM source_chunks WHERE source_id = ?",
        [source_id]
    ).fetchone()
    assert row == (0, "Section 0", 1, 5)


def test_register_chunks_stores_embedding(conn):
    source_id = register_source(conn, "src3", "raw/src3.md", None, None, None, "note")
    embedding = [float(i) / 768 for i in range(768)]
    register_chunks(conn, source_id, [_make_chunk(0)], [embedding])
    stored = conn.execute(
        "SELECT embedding FROM source_chunks WHERE source_id = ?", [source_id]
    ).fetchone()[0]
    assert len(stored) == 768
    assert abs(stored[0] - 0.0) < 1e-6
