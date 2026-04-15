from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

_DEFAULT_URL = "http://localhost:8005"
_DEFAULT_MODEL = "nomic-embed-text:v1.5"


_BATCH_SIZE = 32
# nomic-embed-text:v1.5 (and most local models) cap at 2048 tokens.
# count_tokens() estimates 1 token ≈ 4 chars, so 2000 tokens ≈ 8000 chars.
# Truncate at 8000 chars to stay safely under the limit rather than crashing.
_MAX_EMBED_CHARS = 8000


@dataclass
class EmbedCheck:
    ok: bool
    url: str
    model: str
    error: str = ""


def check_embed_server(url: str | None = None, model: str | None = None) -> EmbedCheck:
    """Probe the embedding server with a minimal request.

    Returns an EmbedCheck with ok=True if the server responds correctly,
    or ok=False with a human-readable error message.
    """
    url = (url or os.environ.get("LACUNA_EMBED_URL", _DEFAULT_URL)).rstrip("/")
    model = model or os.environ.get("LACUNA_EMBED_MODEL", _DEFAULT_MODEL)
    try:
        response = httpx.post(
            f"{url}/v1/embeddings",
            json={"model": model, "input": ["ping"]},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data or "embedding" not in data[0]:
            return EmbedCheck(ok=False, url=url, model=model,
                              error="Server responded but returned unexpected data format.")
        return EmbedCheck(ok=True, url=url, model=model)
    except httpx.ConnectError:
        return EmbedCheck(ok=False, url=url, model=model,
                          error=f"Connection refused — is the embedding server running at {url}?")
    except httpx.TimeoutException:
        return EmbedCheck(ok=False, url=url, model=model,
                          error=f"Timed out connecting to {url} (5s limit).")
    except httpx.HTTPStatusError as e:
        return EmbedCheck(ok=False, url=url, model=model,
                          error=f"HTTP {e.response.status_code} from {url}: {e.response.text[:200]}")
    except Exception as e:
        return EmbedCheck(ok=False, url=url, model=model, error=str(e))


def embed_texts(
    texts: list[str],
    url: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts via the local Ollama-compatible HTTP server.

    Returns one 768-dim float vector per input text.
    Large inputs are split into batches of _BATCH_SIZE to avoid 500s from servers
    with request-size limits.
    Raises httpx.HTTPStatusError on non-2xx responses.

    Config (env vars override defaults):
      LACUNA_EMBED_URL   — default http://localhost:8005
      LACUNA_EMBED_MODEL — default nomic-embed-text:v1.5
    """
    url = (url or os.environ.get("LACUNA_EMBED_URL", _DEFAULT_URL)).rstrip("/")
    model = model or os.environ.get("LACUNA_EMBED_MODEL", _DEFAULT_MODEL)

    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = [t[:_MAX_EMBED_CHARS] for t in texts[i : i + _BATCH_SIZE]]
        response = httpx.post(
            f"{url}/v1/embeddings",
            json={"model": model, "input": batch},
            timeout=60.0,
        )
        response.raise_for_status()
        items = sorted(response.json()["data"], key=lambda x: x["index"])
        results.extend(item["embedding"] for item in items)
    return results
