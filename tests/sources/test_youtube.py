"""Tests for YouTube transcript extraction."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import duckdb

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.sources.youtube import (
    _dedup_overlapping_cues,
    _parse_vtt_cues,
    _strip_overlap,
    _ts_to_seconds,
    fetch_youtube_transcript,
    is_youtube_url,
    key_from_title,
    vtt_to_markdown,
)


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    init_db(c)
    yield c
    c.close()


# --- key_from_title ---

def test_key_from_title_basic(conn):
    assert key_from_title("Attention Is All You Need", conn) == "attention-is-all-you-need"


def test_key_from_title_strips_special_chars(conn):
    assert key_from_title("Attention Is All You Need — Talk", conn) == "attention-is-all-you-need-talk"


def test_key_from_title_truncates(conn):
    long = "a" * 70
    key = key_from_title(long, conn)
    assert len(key) <= 60


def test_key_from_title_disambiguates(conn):
    conn.execute("INSERT INTO sources (slug, path, source_type) VALUES ('my-talk', 'raw/x.md', 'transcript')")
    key = key_from_title("My Talk", conn)
    assert key == "my-talkb"


# --- is_youtube_url ---

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc123", True),
    ("https://youtube.com/watch?v=abc123", True),
    ("https://m.youtube.com/watch?v=abc123", True),
    ("https://youtu.be/abc123", True),
    ("https://example.com/video", False),
    ("https://arxiv.org/abs/1706.03762", False),
    ("https://vimeo.com/123456", False),
])
def test_is_youtube_url(url, expected):
    assert is_youtube_url(url) == expected


# --- _ts_to_seconds ---

def test_ts_to_seconds_zero():
    assert _ts_to_seconds("00:00:00.000") == 0


def test_ts_to_seconds_minutes():
    assert _ts_to_seconds("00:05:00.000") == 300


def test_ts_to_seconds_hours():
    assert _ts_to_seconds("01:00:00.000") == 3600


def test_ts_to_seconds_mixed():
    assert _ts_to_seconds("01:02:30.500") == 3750


# --- _parse_vtt_cues ---

_SIMPLE_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.500
Hello world

00:00:03.500 --> 00:00:07.000
This is a transcript

00:00:07.000 --> 00:00:10.000
About transformers
"""

_YT_AUTO_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.560 align:start position:0%

 hello<00:00:00.160><c> and</c><00:00:00.400><c> welcome</c>

00:00:03.560 --> 00:00:07.000 align:start position:0%

 to<00:00:03.800><c> this</c><00:00:04.000><c> talk</c>

00:00:07.000 --> 00:00:07.000 align:start position:0%

 to this talk
"""

_DUPLICATE_VTT = """\
WEBVTT

00:00:00.000 --> 00:00:03.000
First line

00:00:02.500 --> 00:00:05.000
First line

00:00:05.000 --> 00:00:08.000
Second line
"""


def test_parse_vtt_cues_simple():
    cues = _parse_vtt_cues(_SIMPLE_VTT)
    assert len(cues) == 3
    assert cues[0] == (0, "Hello world")
    assert cues[1] == (3, "This is a transcript")
    assert cues[2] == (7, "About transformers")


def test_parse_vtt_cues_strips_inline_tags():
    cues = _parse_vtt_cues(_YT_AUTO_VTT)
    texts = [c[1] for c in cues]
    # No raw tags should appear
    for text in texts:
        assert "<c>" not in text
        assert "<00:" not in text


def test_parse_vtt_cues_deduplicates():
    cues = _parse_vtt_cues(_DUPLICATE_VTT)
    texts = [c[1] for c in cues]
    # "First line" appears once in the merged stream
    full_text = " ".join(texts)
    assert full_text.count("First") == 1
    assert "Second line" in full_text


# --- _strip_overlap ---

def test_strip_overlap_no_overlap():
    assert _strip_overlap(["a", "b"], ["c", "d"]) == ["c", "d"]


def test_strip_overlap_full_overlap():
    assert _strip_overlap(["a", "b", "c"], ["a", "b", "c"]) == []


def test_strip_overlap_partial():
    assert _strip_overlap(["hello", "world"], ["world", "today"]) == ["today"]


def test_strip_overlap_empty_accumulated():
    assert _strip_overlap([], ["a", "b"]) == ["a", "b"]


# --- _dedup_overlapping_cues (the YouTube sliding-window pattern) ---

def test_dedup_overlapping_cues_sliding_window():
    # Simulate YouTube's overlapping cue pattern
    cues = [
        (0,   "This is Gemma 312B"),
        (2,   "is Gemma 312B a production"),
        (4,   "312B a production size model"),
    ]
    result = _dedup_overlapping_cues(cues)
    full = " ".join(t for _, t in result)
    # Each word should appear once
    assert full.count("Gemma") == 1
    assert full.count("production") == 1
    assert "This is Gemma 312B a production size model" == full


def test_dedup_overlapping_cues_no_overlap():
    # Non-overlapping cues pass through unchanged
    cues = [(0, "Hello world"), (5, "Goodbye world")]
    result = _dedup_overlapping_cues(cues)
    assert result[0][1] == "Hello world"
    assert result[1][1] == "Goodbye world"


def test_dedup_overlapping_cues_exact_duplicate_dropped():
    cues = [(0, "Hello"), (2, "Hello"), (4, "Goodbye")]
    result = _dedup_overlapping_cues(cues)
    texts = [t for _, t in result]
    assert texts.count("Hello") == 1
    assert "Goodbye" in texts


def test_parse_vtt_cues_ignores_empty_cues():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n\n"
    cues = _parse_vtt_cues(vtt)
    assert cues == []


# --- vtt_to_markdown ---

_LONG_VTT = "\n".join(
    [
        "WEBVTT",
        "",
    ]
    + [
        f"00:{str(m).zfill(2)}:00.000 --> 00:{str(m).zfill(2)}:55.000\nLine at minute {m}\n"
        for m in range(12)
    ]
)


def test_vtt_to_markdown_has_headings():
    md = vtt_to_markdown(_SIMPLE_VTT)
    assert "## [00:00:00]" in md


def test_vtt_to_markdown_contains_text():
    md = vtt_to_markdown(_SIMPLE_VTT)
    assert "Hello world" in md
    assert "About transformers" in md


def test_vtt_to_markdown_groups_into_windows():
    # 12 minutes of content with 5-minute windows → 3 sections
    md = vtt_to_markdown(_LONG_VTT, window_seconds=300)
    assert "## [00:00:00]" in md
    assert "## [00:05:00]" in md
    assert "## [00:10:00]" in md


def test_vtt_to_markdown_empty_input():
    assert vtt_to_markdown("WEBVTT\n\n") == ""


# --- fetch_youtube_transcript (mocked subprocess) ---

_FAKE_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:04.000
Hello and welcome to this talk

00:00:04.000 --> 00:00:08.000
about attention mechanisms
"""

_FAKE_INFO = {
    "title": "Attention Is All You Need — Talk",
    "upload_date": "20230601",
    "channel": "ML Conference",
}


def test_fetch_youtube_transcript_returns_markdown(monkeypatch):
    def fake_run(cmd, **kwargs):
        # Find output dir from -o argument
        o_idx = cmd.index("-o")
        template = cmd[o_idx + 1]  # e.g. /tmp/xyz/%(id)s
        out_dir = template.rsplit("/", 1)[0]
        Path(f"{out_dir}/abc123.en.vtt").write_text(_FAKE_VTT)
        Path(f"{out_dir}/abc123.info.json").write_text(json.dumps(_FAKE_INFO))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("subprocess.run", fake_run)

    markdown, meta = fetch_youtube_transcript("https://www.youtube.com/watch?v=abc123")
    assert "Hello and welcome" in markdown
    assert "## [00:00:00]" in markdown


def test_fetch_youtube_transcript_returns_meta(monkeypatch):
    def fake_run(cmd, **kwargs):
        o_idx = cmd.index("-o")
        out_dir = cmd[o_idx + 1].rsplit("/", 1)[0]
        Path(f"{out_dir}/abc123.en.vtt").write_text(_FAKE_VTT)
        Path(f"{out_dir}/abc123.info.json").write_text(json.dumps(_FAKE_INFO))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("subprocess.run", fake_run)

    _, meta = fetch_youtube_transcript("https://www.youtube.com/watch?v=abc123")
    assert meta["title"] == "Attention Is All You Need — Talk"
    assert meta["upload_date"] == "2023-06-01"
    assert meta["channel"] == "ML Conference"


def test_fetch_youtube_transcript_raises_on_no_captions(monkeypatch):
    def fake_run(cmd, **kwargs):
        # yt-dlp succeeds but writes no VTT file
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="no captions"):
        fetch_youtube_transcript("https://www.youtube.com/watch?v=nocaps")


def test_fetch_youtube_transcript_raises_on_yt_dlp_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"ERROR: video unavailable")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="yt-dlp failed"):
        fetch_youtube_transcript("https://www.youtube.com/watch?v=bad")
