import duckdb
import pytest
from llm_wiki.db.schema import init_db


@pytest.fixture
def db_conn():
    """In-memory DuckDB connection with schema initialised."""
    conn = duckdb.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()
