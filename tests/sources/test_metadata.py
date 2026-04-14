import httpx
import pytest
from llm_wiki.sources.metadata import extract_doi, fetch_bibtex, parse_bibtex_fields


def test_extract_doi_finds_doi_in_text():
    text = "See https://doi.org/10.48550/arXiv.1706.03762 for details."
    assert extract_doi(text) == "10.48550/arXiv.1706.03762"


def test_extract_doi_finds_bare_doi():
    text = "Published as 10.1038/nature12345 in Nature."
    assert extract_doi(text) == "10.1038/nature12345"


def test_extract_doi_returns_none_when_absent():
    assert extract_doi("No DOI here.") is None


def test_parse_bibtex_fields_extracts_title():
    bib = "@article{key,\n  title={Attention Is All You Need},\n  author={Vaswani, A},\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert fields["title"] == "Attention Is All You Need"


def test_parse_bibtex_fields_extracts_authors():
    bib = "@article{key,\n  author={Vaswani, Ashish and Shazeer, Noam},\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert "Vaswani" in fields["authors"]


def test_parse_bibtex_fields_extracts_year():
    bib = "@article{key,\n  year={2017}\n}"
    fields = parse_bibtex_fields(bib)
    assert fields["year"] == "2017"


def test_parse_bibtex_fields_missing_field_absent_from_dict():
    bib = "@article{key,\n  year={2020}\n}"
    fields = parse_bibtex_fields(bib)
    assert "title" not in fields
    assert "authors" not in fields


def test_fetch_bibtex_returns_string_on_success(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.1234/test/transform/application/x-bibtex").mock(
        return_value=httpx.Response(200, text="@article{key, title={Test}}")
    )
    result = fetch_bibtex("10.1234/test")
    assert result == "@article{key, title={Test}}"


def test_fetch_bibtex_returns_none_on_404(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.9999/notfound/transform/application/x-bibtex").mock(
        return_value=httpx.Response(404)
    )
    result = fetch_bibtex("10.9999/notfound")
    assert result is None


def test_fetch_bibtex_returns_none_on_network_error(respx_mock):
    respx_mock.get("https://api.crossref.org/works/10.1234/fail/transform/application/x-bibtex").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = fetch_bibtex("10.1234/fail")
    assert result is None
