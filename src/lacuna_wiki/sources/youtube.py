"""YouTube transcript extraction via yt-dlp."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import duckdb
from urllib.parse import urlparse

from lacuna_wiki.sources.key import _disambiguate


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc in (
        "www.youtube.com", "youtube.com",
        "m.youtube.com", "youtu.be",
    )


def fetch_youtube_transcript(url: str) -> tuple[str, dict]:
    """Download auto-generated captions via yt-dlp and convert to markdown.

    Returns (markdown_text, meta) where meta has optional keys:
      title, upload_date (YYYY-MM-DD string), channel

    Raises FileNotFoundError if yt-dlp is not installed.
    Raises RuntimeError if yt-dlp fails or the video has no captions.
    """
    yt_dlp_bin = shutil.which("yt-dlp") or str(Path(sys.executable).parent / "yt-dlp")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                yt_dlp_bin,
                "--write-auto-sub",
                "--sub-langs", "en",
                "--sub-format", "vtt",
                "--skip-download",
                "--write-info-json",
                "--quiet",
                "--no-warnings",
                "-o", str(Path(tmp) / "%(id)s"),
                url,
            ],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"yt-dlp failed (exit {result.returncode}): {stderr[:300]}"
            )

        tmp_path = Path(tmp)

        vtt_files = list(tmp_path.glob("*.vtt"))
        if not vtt_files:
            raise RuntimeError(
                "yt-dlp ran but found no captions. "
                "The video may have no auto-generated English subtitles."
            )

        vtt_text = vtt_files[0].read_text(encoding="utf-8")
        markdown = vtt_to_markdown(vtt_text)

        meta: dict = {}
        info_files = list(tmp_path.glob("*.info.json"))
        if info_files:
            info = json.loads(info_files[0].read_text(encoding="utf-8"))
            if info.get("title"):
                meta["title"] = info["title"]
            upload_date = info.get("upload_date")  # YYYYMMDD
            if upload_date and len(upload_date) == 8:
                meta["upload_date"] = (
                    f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                )
            meta["channel"] = info.get("channel") or info.get("uploader")

    return markdown, meta


def key_from_title(title: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Derive a hyphenated slug from a video title, disambiguated against existing sources.

    "Attention Is All You Need — Talk" → "attention-is-all-you-need-talk"
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(slug) > 60:
        slug = slug[:60].rstrip("-")
    return _disambiguate(slug, conn)


def vtt_to_markdown(vtt: str, window_seconds: int = 60) -> str:
    """Convert a VTT subtitle file to markdown with ## [HH:MM:SS] headings.

    Cues are grouped into windows of window_seconds (default 5 minutes).
    Each window becomes a ## heading + paragraph of transcript text.
    Duplicate lines (common in YouTube auto-subs due to word-level timing) are
    deduplicated before grouping.
    """
    cues = _parse_vtt_cues(vtt)
    if not cues:
        return ""

    def seconds_to_hms(s: int) -> str:
        h, m = divmod(s, 3600)
        m, sec = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    blocks: list[str] = []
    current_window_start = 0
    current_heading = f"[{seconds_to_hms(0)}]"
    current_texts: list[str] = []

    for start_sec, text in cues:
        window_boundary = (start_sec // window_seconds) * window_seconds
        if window_boundary > current_window_start:
            if current_texts:
                blocks.append(f"## {current_heading}\n\n" + " ".join(current_texts))
            current_window_start = window_boundary
            current_heading = f"[{seconds_to_hms(current_window_start)}]"
            current_texts = []
        current_texts.append(text)

    if current_texts:
        blocks.append(f"## {current_heading}\n\n" + " ".join(current_texts))

    return "\n\n".join(blocks)


def _ts_to_seconds(ts: str) -> int:
    """Convert HH:MM:SS.mmm timestamp to integer seconds."""
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(float(rest))


def _parse_vtt_cues(vtt: str) -> list[tuple[int, str]]:
    """Parse VTT content into (start_seconds, clean_text) pairs.

    Handles YouTube auto-generated VTT which includes:
    - Inline timing tags like <00:00:01.000>
    - Formatting tags like <c> and </c>
    - align/position attributes on timestamp lines
    - Overlapping sliding-window cues (deduplicated by _dedup_overlapping_cues)
    """
    lines = vtt.splitlines()
    raw_cues: list[tuple[int, str]] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->", line)
        if m:
            start_sec = _ts_to_seconds(m.group(1))
            i += 1
            text_parts: list[str] = []
            while i < len(lines) and lines[i].strip():
                raw = lines[i].strip()
                clean = re.sub(r"<[^>]+>", "", raw).strip()
                if clean:
                    text_parts.append(clean)
                i += 1
            text = " ".join(text_parts).strip()
            if text:
                raw_cues.append((start_sec, text))
        else:
            i += 1

    return _dedup_overlapping_cues(raw_cues)


def _dedup_overlapping_cues(cues: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Remove overlapping text between consecutive YouTube auto-sub cues.

    YouTube generates a sliding window of words: each cue repeats the last few
    words of the previous cue plus a few new ones. This emits only the novel
    words from each cue, preventing tripled or doubled text in the output.
    """
    result: list[tuple[int, str]] = []
    accumulated: list[str] = []

    for ts, text in cues:
        words = text.split()
        new_words = _strip_overlap(accumulated, words)
        if new_words:
            accumulated.extend(new_words)
            result.append((ts, " ".join(new_words)))

    return result


def _strip_overlap(accumulated: list[str], candidate: list[str]) -> list[str]:
    """Return the words from candidate that are not already at the end of accumulated.

    Finds the longest prefix of candidate that matches a suffix of accumulated
    and returns only the remainder — the truly new words.
    """
    max_check = min(len(accumulated), len(candidate))
    for overlap in range(max_check, 0, -1):
        if accumulated[-overlap:] == candidate[:overlap]:
            return candidate[overlap:]
    return candidate
