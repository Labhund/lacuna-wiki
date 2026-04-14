import pytest
import httpx
from llm_wiki.sources.embedder import embed_texts


def test_embed_texts_returns_correct_count(respx_mock):
    """embed_texts returns one vector per input text."""
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"index": 0, "embedding": [0.1] * 768},
                {"index": 1, "embedding": [0.2] * 768},
            ]
        })
    )
    result = embed_texts(["hello", "world"])
    assert len(result) == 2


def test_embed_texts_returns_correct_dimensions(respx_mock):
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [{"index": 0, "embedding": [0.1] * 768}]
        })
    )
    result = embed_texts(["hello"])
    assert len(result[0]) == 768


def test_embed_texts_preserves_order(respx_mock):
    """Results are sorted by index even if server returns out of order."""
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"index": 1, "embedding": [0.2] * 768},
                {"index": 0, "embedding": [0.1] * 768},
            ]
        })
    )
    result = embed_texts(["first", "second"])
    assert result[0][0] == pytest.approx(0.1)
    assert result[1][0] == pytest.approx(0.2)


def test_embed_texts_raises_on_http_error(respx_mock):
    respx_mock.post("http://localhost:8005/v1/embeddings").mock(
        return_value=httpx.Response(500, json={"error": "server error"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        embed_texts(["hello"])
