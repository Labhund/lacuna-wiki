from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lacuna_wiki.tokens import count_tokens

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$")

_FALLBACK_CHARS = 2048
_FALLBACK_OVERLAP = 200


@dataclass
class Chunk:
    chunk_index: int
    heading: str | None   # section title, timestamp, or None
    start_line: int        # 1-indexed, inclusive
    end_line: int          # 1-indexed, inclusive
    token_count: int
    text: str              # used for embedding — NOT stored in DB


def chunk_md(path: Path, strategy: str = "heading") -> list[Chunk]:
    """Chunk a markdown file. strategy: 'heading' | 'paragraph' | 'fallback'."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if strategy == "heading":
        return _chunk_by_heading(lines)
    elif strategy == "paragraph":
        return _chunk_by_paragraph(lines)
    else:
        return _chunk_fallback(lines)


def _chunk_by_heading(lines: list[str]) -> list[Chunk]:
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m:
            boundaries.append((i, m.group(1).strip()))

    if not boundaries:
        return _chunk_by_paragraph(lines)

    chunks: list[Chunk] = []
    for idx, (start_0, heading) in enumerate(boundaries):
        end_0 = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines) - 1
        text = "\n".join(lines[start_0 : end_0 + 1]).strip()
        if not text:
            continue
        chunks.append(Chunk(
            chunk_index=len(chunks),
            heading=heading,
            start_line=start_0 + 1,
            end_line=end_0 + 1,
            token_count=count_tokens(text),
            text=text,
        ))
    return chunks


def _chunk_by_paragraph(lines: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_start_0 = 0
    current_lines: list[str] = []

    def _flush(end_0: int) -> None:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(Chunk(
                chunk_index=len(chunks),
                heading=None,
                start_line=current_start_0 + 1,
                end_line=end_0,   # i (0-indexed blank) == last content line (1-indexed)
                token_count=count_tokens(text),
                text=text,
            ))

    for i, line in enumerate(lines):
        if line.strip() == "" and current_lines:
            _flush(i)           # i is 0-indexed blank = 1-indexed last content line
            current_lines = []
            current_start_0 = i + 1
        else:
            if not current_lines:
                current_start_0 = i
            current_lines.append(line)

    if current_lines:
        _flush(len(lines))

    return chunks


def _chunk_fallback(lines: list[str]) -> list[Chunk]:
    text = "\n".join(lines)
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + _FALLBACK_CHARS, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            start_line = text[:start].count("\n") + 1
            end_line = text[:end].count("\n") + 1
            chunks.append(Chunk(
                chunk_index=len(chunks),
                heading=None,
                start_line=start_line,
                end_line=end_line,
                token_count=count_tokens(chunk_text),
                text=chunk_text,
            ))
        start = end - _FALLBACK_OVERLAP if end < len(text) else len(text)
    return chunks
