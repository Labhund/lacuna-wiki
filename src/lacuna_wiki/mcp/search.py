from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import duckdb

Scope = Literal["wiki", "sources", "all"]


@dataclass
class SearchHit:
    id: int
    slug: str
    section_name: str
    content: str
    token_count: int
    score: float
    mechanism: str   # "bm25", "vec", "bm25+vec"
    source_type: Literal["wiki", "source"]


def bm25_search(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    scope: Scope = "wiki",
    n: int = 10,
) -> list[SearchHit]:
    """BM25 text search against sections and/or source_chunks."""
    hits: list[SearchHit] = []

    if scope in ("wiki", "all"):
        try:
            rows = conn.execute(
                """
                SELECT s.id, p.slug, s.name, s.content, s.token_count,
                       fts_main_sections.match_bm25(s.id, ?) AS bm25_score
                FROM sections s
                JOIN pages p ON s.page_id = p.id
                WHERE bm25_score IS NOT NULL
                ORDER BY bm25_score DESC
                LIMIT ?
                """,
                [query, n],
            ).fetchall()
            for row in rows:
                hits.append(SearchHit(
                    id=row[0], slug=row[1], section_name=row[2],
                    content=row[3] or "", token_count=row[4] or 0,
                    score=row[5], mechanism="bm25", source_type="wiki",
                ))
        except Exception:
            pass  # FTS index not built yet

    if scope in ("sources", "all"):
        try:
            rows = conn.execute(
                """
                SELECT sc.id, s.slug, sc.heading, sc.content, sc.token_count,
                       fts_main_source_chunks.match_bm25(sc.id, ?) AS bm25_score
                FROM source_chunks sc
                JOIN sources s ON sc.source_id = s.id
                WHERE bm25_score IS NOT NULL
                ORDER BY bm25_score DESC
                LIMIT ?
                """,
                [query, n],
            ).fetchall()
            for row in rows:
                hits.append(SearchHit(
                    id=row[0], slug=row[1],
                    section_name=row[2] or f"chunk-{row[0]}",
                    content=row[3] or "", token_count=row[4] or 0,
                    score=row[5], mechanism="bm25", source_type="source",
                ))
        except Exception:
            pass

    return hits


def vec_search(
    conn: duckdb.DuckDBPyConnection,
    query_embedding: list[float],
    scope: Scope = "wiki",
    n: int = 10,
    min_score: float = 0.0,
    dim: int = 768,
) -> list[SearchHit]:
    """Cosine similarity search using array_inner_product (normalized embeddings)."""
    hits: list[SearchHit] = []

    if scope in ("wiki", "all"):
        rows = conn.execute(
            f"""
            SELECT s.id, p.slug, s.name, s.content, s.token_count,
                   array_inner_product(s.embedding, ?::FLOAT[{dim}]) AS vec_score
            FROM sections s
            JOIN pages p ON s.page_id = p.id
            WHERE s.embedding IS NOT NULL
            ORDER BY vec_score DESC
            LIMIT ?
            """,
            [query_embedding, n],
        ).fetchall()
        for row in rows:
            hits.append(SearchHit(
                id=row[0], slug=row[1], section_name=row[2],
                content=row[3] or "", token_count=row[4] or 0,
                score=row[5], mechanism="vec", source_type="wiki",
            ))

    if scope in ("sources", "all"):
        rows = conn.execute(
            f"""
            SELECT sc.id, s.slug, sc.heading, sc.content, sc.token_count,
                   array_inner_product(sc.embedding, ?::FLOAT[{dim}]) AS vec_score
            FROM source_chunks sc
            JOIN sources s ON sc.source_id = s.id
            WHERE sc.embedding IS NOT NULL
            ORDER BY vec_score DESC
            LIMIT ?
            """,
            [query_embedding, n],
        ).fetchall()
        for row in rows:
            hits.append(SearchHit(
                id=row[0], slug=row[1],
                section_name=row[2] or f"chunk-{row[0]}",
                content=row[3] or "", token_count=row[4] or 0,
                score=row[5], mechanism="vec", source_type="source",
            ))

    if min_score > 0.0:
        hits = [h for h in hits if h.score >= min_score]

    return hits


# Cosine similarity floor for vector hits entering RRF fusion.
# Chunks below this score are semantically unrelated to the query and are
# dropped before ranking — prevents noise from always-populated nearest-neighbour
# results polluting the agent's context when the wiki has no relevant content.
_VEC_MIN_SCORE = 0.45


def hybrid_search(
    conn: duckdb.DuckDBPyConnection,
    query_text: str,
    query_embedding: list[float],
    scope: Scope = "wiki",
    n: int = 10,
    dim: int = 768,
) -> list[SearchHit]:
    """Hybrid BM25 + vector search combined with Reciprocal Rank Fusion (k=60)."""
    bm25_hits = bm25_search(conn, query_text, scope, n * 2)
    vec_hits = vec_search(conn, query_embedding, scope, n * 2, min_score=_VEC_MIN_SCORE, dim=dim)

    def _key(h: SearchHit) -> tuple[str, int]:
        return (h.source_type, h.id)

    bm25_ranks = {_key(h): i for i, h in enumerate(bm25_hits)}
    vec_ranks = {_key(h): i for i, h in enumerate(vec_hits)}
    hit_map: dict[tuple[str, int], SearchHit] = {_key(h): h for h in bm25_hits + vec_hits}

    K = 60
    rrf_scores: dict[tuple[str, int], float] = {}
    for key in hit_map:
        score = 0.0
        if key in bm25_ranks:
            score += 1.0 / (K + bm25_ranks[key])
        if key in vec_ranks:
            score += 1.0 / (K + vec_ranks[key])
        rrf_scores[key] = score

    ranked = sorted(rrf_scores.items(), key=lambda x: -x[1])[:n]

    results: list[SearchHit] = []
    for key, rrf_score in ranked:
        hit = hit_map[key]
        in_bm25 = key in bm25_ranks
        in_vec = key in vec_ranks
        mechanism = "bm25+vec" if in_bm25 and in_vec else "bm25" if in_bm25 else "vec"
        results.append(SearchHit(
            id=hit.id, slug=hit.slug, section_name=hit.section_name,
            content=hit.content, token_count=hit.token_count,
            score=rrf_score, mechanism=mechanism, source_type=hit.source_type,
        ))
    return results
