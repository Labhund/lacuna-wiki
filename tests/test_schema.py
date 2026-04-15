from lacuna_wiki.db.schema import init_db


def test_init_db_creates_all_tables(db_conn):
    tables = {
        row[0]
        for row in db_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    expected = {"pages", "sections", "links", "sources", "claims", "claim_sources", "source_chunks",
                "synthesis_clusters", "synthesis_cluster_members", "synthesis_cluster_edges"}
    assert expected <= tables


def test_pages_has_required_columns(db_conn):
    cols = _column_names(db_conn, "pages")
    assert {"id", "slug", "path", "title", "cluster", "last_modified"} <= cols


def test_sections_has_position_and_embedding(db_conn):
    cols = _column_names(db_conn, "sections")
    assert {"id", "page_id", "position", "name", "content_hash", "token_count", "embedding"} <= cols


def test_links_has_composite_pk(db_conn):
    cols = _column_names(db_conn, "links")
    assert {"source_page_id", "target_slug"} <= cols


def test_sources_has_registered_at(db_conn):
    cols = _column_names(db_conn, "sources")
    assert {"id", "slug", "path", "published_date", "registered_at", "source_type"} <= cols


def test_claims_has_adversary_fields(db_conn):
    cols = _column_names(db_conn, "claims")
    assert {"id", "page_id", "section_id", "text", "embedding", "superseded_by",
            "last_adversary_check"} <= cols


def test_claim_sources_has_relationship(db_conn):
    cols = _column_names(db_conn, "claim_sources")
    assert {"claim_id", "source_id", "citation_number", "relationship", "checked_at"} <= cols


def test_source_chunks_has_no_preview_column(db_conn):
    cols = _column_names(db_conn, "source_chunks")
    assert "preview" not in cols
    assert {"id", "source_id", "chunk_index", "heading", "start_line", "end_line",
            "token_count", "embedding"} <= cols


def test_init_db_is_idempotent(db_conn):
    init_db(db_conn)  # second call — must not raise
    tables = db_conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchone()[0]
    assert tables >= 12  # 7 core + schema_version + page_embeddings + 3 synthesis tables


def test_pages_has_last_swept_column(db_conn):
    cols = _column_names(db_conn, "pages")
    assert "last_swept" in cols


def test_page_embeddings_table_exists(db_conn):
    cols = _column_names(db_conn, "page_embeddings")
    assert {"slug", "mean_embedding"} <= cols


def test_synthesis_cluster_tables_exist(db_conn):
    tables = {
        row[0]
        for row in db_conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert {"synthesis_clusters", "synthesis_cluster_members", "synthesis_cluster_edges",
            "page_embeddings"} <= tables


def test_synthesis_clusters_columns(db_conn):
    cols = _column_names(db_conn, "synthesis_clusters")
    assert {"id", "concept_label", "agent_rationale", "status", "queued_at"} <= cols


def test_synthesis_cluster_members_columns(db_conn):
    cols = _column_names(db_conn, "synthesis_cluster_members")
    assert {"cluster_id", "slug"} <= cols


def test_synthesis_cluster_edges_columns(db_conn):
    cols = _column_names(db_conn, "synthesis_cluster_edges")
    assert {"cluster_id", "slug_a", "slug_b", "coverage_ratio"} <= cols


def test_sections_has_content_column(db_conn):
    db_conn.execute("INSERT INTO pages (slug, path, last_modified) VALUES ('p', 'wiki/p.md', now())")
    page_id = db_conn.execute("SELECT id FROM pages WHERE slug='p'").fetchone()[0]
    db_conn.execute(
        "INSERT INTO sections (page_id, position, name, content, content_hash, token_count)"
        " VALUES (?, 0, 'Intro', 'Hello world text.', 'abc123', 3)",
        [page_id],
    )
    text = db_conn.execute("SELECT content FROM sections WHERE name='Intro'").fetchone()[0]
    assert text == "Hello world text."


def test_source_chunks_has_content_column(db_conn):
    db_conn.execute(
        "INSERT INTO sources (slug, path, source_type) VALUES ('s1', 'raw/s.pdf', 'paper')"
    )
    src_id = db_conn.execute("SELECT id FROM sources WHERE slug='s1'").fetchone()[0]
    db_conn.execute(
        "INSERT INTO source_chunks (source_id, chunk_index, start_line, end_line, content)"
        " VALUES (?, 0, 1, 10, 'Chunk text here.')",
        [src_id],
    )
    text = db_conn.execute("SELECT content FROM source_chunks").fetchone()[0]
    assert text == "Chunk text here."


def test_v4_pages_has_synthesised_into(db_conn):
    cols = _column_names(db_conn, "pages")
    assert "synthesised_into" in cols


def test_v4_clusters_has_synthesis_page_slug(db_conn):
    cols = _column_names(db_conn, "synthesis_clusters")
    assert "synthesis_page_slug" in cols


def test_init_db_is_idempotent_v4(db_conn):
    init_db(db_conn)  # second call must not raise
    tables = db_conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main'"
    ).fetchone()[0]
    assert tables >= 12  # v4 adds no new tables; guard against regression not exact count


def _column_names(conn, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND table_schema = 'main'"
        ).fetchall()
    }
