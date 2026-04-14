import pytest
from lacuna_wiki.daemon.parser import (
    Section, CitationEntry, parse_sections, parse_wikilinks, parse_citation_claims,
)


# --- parse_sections ---

def test_parse_sections_splits_on_double_hash():
    text = "# My Page\n\nIntro text.\n\n## Alpha\n\nAlpha content.\n\n## Beta\n\nBeta content.\n"
    sections = parse_sections(text)
    assert len(sections) == 3
    assert sections[0].name == "My Page"
    assert sections[0].position == 0
    assert sections[1].name == "Alpha"
    assert sections[1].position == 1
    assert sections[2].name == "Beta"
    assert sections[2].position == 2


def test_parse_sections_preamble_content_included():
    text = "# Title\n\nHello world.\n\n## Section\n\nContent.\n"
    sections = parse_sections(text)
    assert "Hello world" in sections[0].content


def test_parse_sections_no_headings_returns_single_section():
    text = "Just some content here."
    sections = parse_sections(text)
    assert len(sections) == 1
    assert sections[0].position == 0


def test_parse_sections_no_title_uses_intro():
    # Preamble content exists but no # title — named "intro"
    text = "Some preamble text.\n\n## Only a section\n\nContent.\n"
    sections = parse_sections(text)
    assert sections[0].name == "intro"
    assert sections[1].name == "Only a section"


def test_parse_sections_empty_preamble_not_included():
    # No content before first ## → no preamble section
    text = "## Section One\n\nContent.\n"
    sections = parse_sections(text)
    assert len(sections) == 1
    assert sections[0].name == "Section One"


def test_parse_sections_content_hash_is_stable():
    text = "# T\n\n## A\n\nSame.\n"
    s1 = parse_sections(text)
    s2 = parse_sections(text)
    assert s1[1].content_hash == s2[1].content_hash


def test_parse_sections_different_content_different_hash():
    text_a = "## Section\n\nContent A.\n"
    text_b = "## Section\n\nContent B.\n"
    sections_a = parse_sections(text_a)
    sections_b = parse_sections(text_b)
    assert sections_a[0].content_hash != sections_b[0].content_hash


# --- parse_wikilinks ---

def test_parse_wikilinks_finds_bare_links():
    text = "See [[attention-mechanism]] and [[transformer]]."
    links = parse_wikilinks(text)
    assert set(links) == {"attention-mechanism", "transformer"}


def test_parse_wikilinks_excludes_citations():
    text = "See [[vaswani2017.pdf]] for details. Also [[attention]]."
    links = parse_wikilinks(text)
    assert "attention" in links
    assert "vaswani2017.pdf" not in links
    assert "vaswani2017" not in links


def test_parse_wikilinks_deduplicates():
    text = "[[page]] again [[page]]."
    links = parse_wikilinks(text)
    assert links.count("page") == 1


def test_parse_wikilinks_empty_text():
    assert parse_wikilinks("no links here") == []


# --- parse_citation_claims ---

def test_parse_citation_claims_extracts_single_claim():
    text = "Attention is computed. [[vaswani2017.pdf]]"
    claims = parse_citation_claims(text, "Section", 0)
    assert len(claims) == 1
    assert claims[0].source_key == "vaswani2017"
    assert claims[0].source_ext == ".pdf"
    assert "[[vaswani2017.pdf]]" in claims[0].text


def test_parse_citation_claims_extracts_multiple_claims():
    text = "First claim. [[a2020.pdf]] Second claim. [[b2021.pdf]]"
    claims = parse_citation_claims(text, "Sec", 0)
    assert len(claims) == 2
    assert claims[0].source_key == "a2020"
    assert claims[1].source_key == "b2021"


def test_parse_citation_claims_text_boundary_correct():
    text = "Claim one. [[x2020.pdf]] Claim two. [[y2021.pdf]]"
    claims = parse_citation_claims(text, "Sec", 0)
    assert "Claim one" in claims[0].text
    assert "Claim two" in claims[1].text
    assert "Claim one" not in claims[1].text


def test_parse_citation_claims_md_extension():
    text = "A note claim. [[mynote.md]]"
    claims = parse_citation_claims(text, "Sec", 0)
    assert len(claims) == 1
    assert claims[0].source_ext == ".md"


def test_parse_citation_claims_no_citations():
    text = "No citations here."
    claims = parse_citation_claims(text, "Sec", 0)
    assert claims == []


def test_parse_citation_claims_section_metadata():
    text = "Claim. [[src.pdf]]"
    claims = parse_citation_claims(text, "Methods", 2)
    assert claims[0].section_name == "Methods"
    assert claims[0].section_position == 2
