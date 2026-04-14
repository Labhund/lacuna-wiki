"""URL source fetching — Jina reader API, YouTube, and rxiv PDF download."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import duckdb
import httpx

from lacuna_wiki.sources.key import _disambiguate

_JINA_BASE = "https://r.jina.ai/"


def key_from_url(url: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Derive a stable slug from a URL, disambiguated against existing sources.

    Strategy:
    - YouTube watch URLs (?v=ID): use the video ID directly.
    - Other URLs: take the last non-empty path segment (or domain if path is /),
      strip leading YYYY-MM-DD- date prefix (common in blog URLs),
      strip non-alphanumeric chars, lowercase, truncate to 40 chars.
    """
    parsed = urlparse(url)

    # YouTube: extract video ID from query string
    if parsed.netloc in ("www.youtube.com", "youtube.com") and parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        video_ids = qs.get("v", [])
        if video_ids:
            base = re.sub(r"[^a-z0-9]", "", video_ids[0].lower())[:40] or "url"
            return _disambiguate(base, conn)

    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        raw = segments[-1]
        # Strip leading date prefix common in blog URLs (e.g. "2023-01-27-my-post" → "my-post")
        raw = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", raw)
    else:
        # Root URL — use domain without port
        raw = parsed.netloc.split(":")[0]
    base = re.sub(r"[^a-z0-9]", "", raw.lower())[:40] or "url"
    return _disambiguate(base, conn)


def parse_jina_headers(markdown: str) -> dict:
    """Extract metadata from Jina reader response headers.

    Jina prepends a header block before the first blank line:
        Title: Some Title
        URL Source: https://...
        Published Time: 2023-01-27  (or ISO 8601 with time component)

    Returns a dict with keys 'title' and/or 'published_time' (YYYY-MM-DD string).
    Only includes keys that were present in the response.
    """
    result: dict = {}
    for line in markdown.splitlines():
        if not line.strip():
            break  # end of header block
        if line.startswith("Title:"):
            result["title"] = line[len("Title:"):].strip()
        elif line.startswith("Published Time:"):
            raw = line[len("Published Time:"):].strip()
            # Normalise ISO 8601 with time component to YYYY-MM-DD
            result["published_time"] = raw[:10]
    return result


def arxiv_id_from_url(url: str) -> str | None:
    """Extract the arxiv ID (e.g. '2201.02177') from an arxiv abs URL.

    Strips version suffix (v1, v2, …) — CrossRef uses the bare ID.
    Returns None if the URL is not a recognisable arxiv abs URL.
    """
    m = re.search(r"arxiv\.org/abs/([^\s/?#]+)", url)
    if not m:
        return None
    return re.sub(r"v\d+$", "", m.group(1))


def is_rxiv_url(url: str) -> bool:
    """Return True for arxiv and biorxiv abstract/landing page URLs."""
    return bool(re.search(r"arxiv\.org/abs/|biorxiv\.org/content/", url))


def rxiv_pdf_url(url: str) -> str:
    """Derive the direct PDF download URL from an rxiv landing page URL.

    arxiv:   https://arxiv.org/abs/2201.02177   → https://arxiv.org/pdf/2201.02177
    biorxiv: https://www.biorxiv.org/content/… → …full.pdf  (append .full.pdf)
    """
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/", 1)
    if "biorxiv.org/content/" in url:
        url = url.rstrip("/")
        if not url.endswith(".full.pdf"):
            url += ".full.pdf"
        return url
    return url


def fetch_rxiv_pdf(url: str) -> bytes:
    """Download a PDF from an rxiv landing page URL. Returns raw PDF bytes."""
    pdf_url = rxiv_pdf_url(url)
    resp = httpx.get(
        pdf_url,
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "lacuna/2.0 (research tool)"},
    )
    resp.raise_for_status()
    return resp.content


_CITATION_AUTHOR_RE = re.compile(
    r'<meta\s+name="citation_author"\s+content="([^"]+)"', re.IGNORECASE
)
_CITATION_TITLE_RE = re.compile(
    r'<meta\s+name="citation_title"\s+content="([^"]+)"', re.IGNORECASE
)
_CITATION_DATE_RE = re.compile(
    r'<meta\s+name="citation_date"\s+content="(\d{4})', re.IGNORECASE
)


def fetch_rxiv_html_meta(abs_url: str) -> dict:
    """Fetch an rxiv abstract page and parse Google Scholar citation_* meta tags.

    Works for arxiv and biorxiv — both emit citation_author, citation_title,
    citation_date in the same format.

    Returns a dict with any of: 'first_author_last', 'authors', 'title', 'year'.
    - 'first_author_last': lowercase last name of first author (key derivation)
    - 'authors': "Last, First and Last, First ..." (bib sidecar)
    - 'title': full paper title
    - 'year': four-digit string

    Returns an empty dict on any failure — callers must treat this as optional.
    """
    try:
        resp = httpx.get(
            abs_url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "lacuna/2.0 (research tool)"},
        )
        if resp.status_code != 200:
            return {}
        html = resp.text
    except Exception:
        return {}

    result: dict = {}

    all_authors = _CITATION_AUTHOR_RE.findall(html)  # ["Power, Alethea", "Burda, Yuri", ...]
    if all_authors:
        last = all_authors[0].split(",")[0].strip()
        result["first_author_last"] = re.sub(r"[^a-z]", "", last.lower())
        result["authors"] = " and ".join(all_authors)

    title_m = _CITATION_TITLE_RE.search(html)
    if title_m:
        result["title"] = title_m.group(1)

    date_m = _CITATION_DATE_RE.search(html)
    if date_m:
        result["year"] = date_m.group(1)

    return result


# Keep old name as alias so existing tests don't break
fetch_arxiv_html_meta = fetch_rxiv_html_meta


def fetch_url_as_markdown(url: str) -> str:
    """Fetch a URL via the Jina reader API and return clean markdown.

    Raises httpx.HTTPStatusError on non-2xx responses.
    Raises httpx.RequestError on network failures.
    """
    jina_url = _JINA_BASE + url
    resp = httpx.get(
        jina_url,
        timeout=30.0,
        headers={"User-Agent": "lacuna/2.0 (research tool)"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text
