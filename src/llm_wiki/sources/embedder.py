from __future__ import annotations

import os

import httpx

_DEFAULT_URL = "http://localhost:8005"
_DEFAULT_MODEL = "nomic-embed-text:v1.5"


def embed_texts(
    texts: list[str],
    url: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts via the local Ollama-compatible HTTP server.

    Returns one 768-dim float vector per input text.
    Raises httpx.HTTPStatusError on non-2xx responses.

    Config (env vars override defaults):
      LLM_WIKI_EMBED_URL   — default http://localhost:8005
      LLM_WIKI_EMBED_MODEL — default nomic-embed-text:v1.5
    """
    url = (url or os.environ.get("LLM_WIKI_EMBED_URL", _DEFAULT_URL)).rstrip("/")
    model = model or os.environ.get("LLM_WIKI_EMBED_MODEL", _DEFAULT_MODEL)

    response = httpx.post(
        f"{url}/v1/embeddings",
        json={"model": model, "input": texts},
        timeout=60.0,
    )
    response.raise_for_status()
    items = sorted(response.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]
