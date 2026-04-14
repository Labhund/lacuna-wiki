from lacuna_wiki.mcp.format import format_search_results, extract_passage
from lacuna_wiki.mcp.search import SearchHit


def _hit(slug, section, content, score=0.9, mechanism="bm25+vec", tok=300):
    return SearchHit(
        id=1, slug=slug, section_name=section,
        content=content, token_count=tok,
        score=score, mechanism=mechanism, source_type="wiki",
    )


def test_format_search_results_header():
    hits = [_hit("attention-mechanism", "Overview", "Attention computes queries.")]
    result = format_search_results(hits, "attention")
    assert "attention-mechanism › Overview" in result
    assert "bm25+vec" in result


def test_format_search_results_score():
    hits = [_hit("attn", "Sec", "Content.", score=0.94)]
    result = format_search_results(hits, "content")
    assert "0.94" in result


def test_format_search_results_passage_shown():
    hits = [_hit("attn", "Sec", "Background text. Attention mechanism here. More text.")]
    result = format_search_results(hits, "attention")
    assert "Attention mechanism" in result


def test_format_search_results_empty():
    result = format_search_results([], "query")
    assert "no results" in result.lower()


def test_format_search_results_multiple_hits():
    hits = [
        _hit("page1", "Sec1", "First result content.", score=0.9),
        _hit("page2", "Sec2", "Second result content.", score=0.7),
    ]
    result = format_search_results(hits, "content")
    assert "page1 › Sec1" in result
    assert "page2 › Sec2" in result


def test_extract_passage_finds_term():
    content = "A" * 100 + " attention mechanism " + "B" * 100
    passage = extract_passage(content, "attention", max_chars=60)
    assert "attention" in passage.lower()


def test_extract_passage_fallback_to_start():
    content = "Start of the text. More words here."
    passage = extract_passage(content, "notfound", max_chars=20)
    assert passage.startswith("Start")


def test_format_search_results_source_type_shown():
    hit = SearchHit(
        id=2, slug="vaswani2017", section_name="chunk-2",
        content="Source chunk content.", token_count=50,
        score=0.8, mechanism="vec", source_type="source",
    )
    result = format_search_results([hit], "content")
    assert "source" in result.lower()
