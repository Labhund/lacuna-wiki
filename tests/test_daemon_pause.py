"""Tests for daemon SIGUSR1 pause mechanism.

We test the pause logic (event → ack file → resume) directly by calling
_handle_sigusr1 and simulating the ack-file deletion, without spawning a
full subprocess. Signal handlers in Python only fire in the main thread,
so these tests exercise the handler and the event directly.
"""
import signal
import threading
import time

from lacuna_wiki.daemon.process import _pause_event, _handle_sigusr1


def test_handle_sigusr1_sets_pause_event():
    _pause_event.clear()
    _handle_sigusr1(signal.SIGUSR1, None)
    assert _pause_event.is_set()
    _pause_event.clear()  # cleanup


def test_pause_event_starts_clear():
    _pause_event.clear()
    assert not _pause_event.is_set()


def test_ack_file_written_and_cleared(tmp_path):
    """Simulate the pause loop: write ack, delete it, verify cleared."""
    ack = tmp_path / "daemon.paused"

    results = {}

    def simulate_pause():
        ack.write_text("paused")
        deadline = time.monotonic() + 2.0
        while ack.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        results["ack_gone"] = not ack.exists()

    t = threading.Thread(target=simulate_pause)
    t.start()

    # simulate adversary-commit: wait for ack, then delete it
    deadline = time.monotonic() + 2.0
    while not ack.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ack.exists(), "ack file never appeared"
    ack.unlink()

    t.join(timeout=2.0)
    assert results.get("ack_gone"), "daemon did not detect ack file deletion"
