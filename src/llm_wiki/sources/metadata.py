from __future__ import annotations

import re

import httpx

_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s\]>\"']+)")


def extract_doi(text: str) -> str | None:
    """Find the first DOI in text. Returns the bare DOI (e.g. '10.48550/arXiv.1706.03762')."""
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".,;)") if m else None


def fetch_bibtex(doi: str) -> str | None:
    """Fetch BibTeX from CrossRef for a DOI. Returns None on any failure."""
    url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            headers={"User-Agent": "llm-wiki/2.0 (mailto:research@local.dev)"},
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def parse_bibtex_fields(bibtex: str) -> dict:
    """Extract title, authors, year from a BibTeX string.

    Returns a dict with only the keys that were found.
    """
    result: dict = {}

    title_m = re.search(r"title\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    if title_m:
        result["title"] = re.sub(r"[{}]", "", title_m.group(1)).strip()

    author_m = re.search(r"author\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    if author_m:
        result["authors"] = author_m.group(1).strip()

    year_m = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex, re.IGNORECASE)
    if year_m:
        result["year"] = year_m.group(1)

    return result
