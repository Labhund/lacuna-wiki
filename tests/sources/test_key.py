import duckdb
import pytest
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex


@pytest.fixture
def empty_conn():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE sources (slug TEXT)")
    return conn


@pytest.fixture
def conn_with_vaswani(empty_conn):
    empty_conn.execute("INSERT INTO sources VALUES ('vaswani2017')")
    return empty_conn


def test_derive_key_from_clean_stem(empty_conn):
    assert derive_key("vaswani2017", empty_conn) == "vaswani2017"


def test_derive_key_lowercases(empty_conn):
    assert derive_key("Vaswani2017", empty_conn) == "vaswani2017"


def test_derive_key_strips_non_alnum(empty_conn):
    assert derive_key("vaswani_2017_attention", empty_conn) == "vaswani2017attention"


def test_derive_key_disambiguates(conn_with_vaswani):
    assert derive_key("vaswani2017", conn_with_vaswani) == "vaswani2017b"


def test_derive_key_disambiguates_twice(conn_with_vaswani):
    conn_with_vaswani.execute("INSERT INTO sources VALUES ('vaswani2017b')")
    assert derive_key("vaswani2017", conn_with_vaswani) == "vaswani2017c"


def test_derive_key_from_bibtex_last_name_year(empty_conn):
    bibtex = """@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam},
  year = {2017},
  title = {Attention Is All You Need},
}"""
    assert derive_key_from_bibtex(bibtex, empty_conn) == "vaswani2017"


def test_derive_key_from_bibtex_non_comma_author(empty_conn):
    bibtex = """@article{ho2020denoising,
  author = {Jonathan Ho and Ajay Jain and Pieter Abbeel},
  year = {2020},
  title = {Denoising Diffusion Probabilistic Models},
}"""
    assert derive_key_from_bibtex(bibtex, empty_conn) == "abbeel2020"


def test_derive_key_from_bibtex_disambiguates(conn_with_vaswani):
    bibtex = """@article{vaswani2017,
  author = {Vaswani, Ashish},
  year = {2017},
  title = {Attention Is All You Need},
}"""
    assert derive_key_from_bibtex(bibtex, conn_with_vaswani) == "vaswani2017b"
