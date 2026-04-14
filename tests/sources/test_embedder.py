import pytest
import httpx
from lacuna_wiki.sources.embedder import embed_texts


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


def test_embed_texts_batches_large_input(respx_mock):
    """Input larger than _BATCH_SIZE is split into multiple requests."""
    from lacuna_wiki.sources.embedder import _BATCH_SIZE

    n = _BATCH_SIZE + 5  # force two batches
    # Each POST returns embeddings for however many texts were sent
    call_count = 0

    def make_response(request):
        nonlocal call_count
        call_count += 1
        import json
        body = json.loads(request.content)
        count = len(body["input"])
        data = [{"index": i, "embedding": [float(call_count)] * 768} for i in range(count)]
        return httpx.Response(200, json={"data": data})

    respx_mock.post("http://localhost:8005/v1/embeddings").mock(side_effect=make_response)
    result = embed_texts(["text"] * n)
    assert len(result) == n
    assert call_count == 2  # two batches
