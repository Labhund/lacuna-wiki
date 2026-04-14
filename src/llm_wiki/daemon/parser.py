from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[\[([a-z0-9][a-z0-9_-]*)\.(pdf|md|bib|txt)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]|.]+?)\]\]")  # no dot in target = wikilink


@dataclass
class Section:
    position: int
    name: str
    content: str
    content_hash: str


@dataclass
class CitationEntry:
    source_key: str       # e.g. "vaswani2017"
    source_ext: str       # e.g. ".pdf" (with dot)
    text: str             # full claim text up to and including [[key.ext]]
    section_name: str
    section_position: int


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def parse_sections(text: str) -> list[Section]:
    """Split markdown into sections on ## headings.

    Content before the first ## is the preamble, named after the # title
    or 'intro' if no # title exists. Empty preambles are omitted.
    """
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else None

    boundaries: list[tuple[int, str]] = []
    for m in re.finditer(r"^##\s+(.+)$", text, re.MULTILINE):
        boundaries.append((m.start(), m.group(1).strip()))

    sections: list[Section] = []

    preamble_end = boundaries[0][0] if boundaries else len(text)
    preamble_content = text[:preamble_end].strip()

    if preamble_content:
        sections.append(Section(
            position=0,
            name=title or "intro",
            content=preamble_content,
            content_hash=_sha(preamble_content),
        ))
    elif not boundaries:
        # No ## headings and no preamble content — whole file is one section
        sections.append(Section(
            position=0,
            name=title or "intro",
            content=text.strip(),
            content_hash=_sha(text.strip()),
        ))

    for idx, (start, heading) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(text)
        content = text[start:end].strip()
        sections.append(Section(
            position=len(sections),
            name=heading,
            content=content,
            content_hash=_sha(content),
        ))

    return sections


def parse_wikilinks(text: str) -> list[str]:
    """Return unique target slugs from [[target]] wikilinks (no file extension)."""
    no_citations = _CITATION_RE.sub("", text)
    seen: list[str] = []
    for m in _WIKILINK_RE.finditer(no_citations):
        target = m.group(1).strip()
        if target not in seen:
            seen.append(target)
    return seen


def parse_citation_claims(
    section_content: str,
    section_name: str,
    section_position: int,
) -> list[CitationEntry]:
    """Split section content on [[key.ext]] boundaries.

    Returns one CitationEntry per citation marker. The claim text is the
    accumulated text from the previous boundary (or section start) up to
    and including the current [[key.ext]] marker.
    """
    parts = _CITATION_RE.split(section_content)
    # re.split with 2 capture groups → [text0, key0, ext0, text1, key1, ext1, ..., textN]
    claims: list[CitationEntry] = []
    accumulated = parts[0]
    i = 1
    while i < len(parts):
        key = parts[i]
        ext = parts[i + 1]
        text_after = parts[i + 2] if i + 2 < len(parts) else ""
        claim_text = (accumulated + f"[[{key}.{ext}]]").strip()
        if claim_text:
            claims.append(CitationEntry(
                source_key=key,
                source_ext="." + ext,
                text=claim_text,
                section_name=section_name,
                section_position=section_position,
            ))
        accumulated = text_after
        i += 3
    return claims
