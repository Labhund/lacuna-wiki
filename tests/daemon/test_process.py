import os
import pytest
from pathlib import Path

from lacuna_wiki.daemon.process import write_pid, read_pid, is_running, _PID_FILE


@pytest.fixture(autouse=True)
def clean_pid(tmp_path, monkeypatch):
    """Redirect PID file to tmp_path for test isolation."""
    fake_pid = tmp_path / "daemon.pid"
    monkeypatch.setattr("lacuna_wiki.daemon.process._PID_FILE", fake_pid)
    yield fake_pid
    if fake_pid.exists():
        fake_pid.unlink()


def test_write_pid_creates_file(clean_pid):
    write_pid(12345)
    assert clean_pid.exists()
    assert clean_pid.read_text().strip() == "12345"


def test_read_pid_returns_none_when_absent(clean_pid):
    assert read_pid() is None


def test_read_pid_returns_written_pid(clean_pid):
    write_pid(99999)
    assert read_pid() == 99999


def test_read_pid_returns_none_on_corrupt_file(clean_pid):
    clean_pid.write_text("not_a_number")
    assert read_pid() is None


def test_is_running_true_for_own_pid():
    assert is_running(os.getpid()) is True


def test_is_running_false_for_nonexistent_pid():
    assert is_running(99999999) is False


def test_close_all_for_pause_releases_file_lock(tmp_path):
    """After _close_all_for_pause, an external connection can open the DB."""
    import duckdb
    from lacuna_wiki.daemon.connections import ConnectionPool
    from lacuna_wiki.daemon.process import _close_all_for_pause
    from lacuna_wiki.db.connection import get_connection
    from lacuna_wiki.db.schema import init_db

    db = tmp_path / "test.db"
    setup = duckdb.connect(str(db))
    init_db(setup)
    setup.close()

    write_conn = get_connection(db)
    reader_pool = ConnectionPool(db, size=2)
    reader_pool.open()

    _close_all_for_pause(write_conn, reader_pool)

    # After full close, another connection must be able to open the DB
    ext_conn = duckdb.connect(str(db))
    assert ext_conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    ext_conn.close()
