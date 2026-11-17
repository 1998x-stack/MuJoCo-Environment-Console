import time

from app.sessions import SessionManager


class DummySession:
    def __init__(self, last_seen):
        self.last_seen = last_seen
        self.closed = False

    def close(self):
        self.closed = True


def test_cleanup_closes_idle_sessions():
    manager = SessionManager(idle_seconds=1)
    stale = DummySession(time.monotonic() - 5)
    fresh = DummySession(time.monotonic())
    manager.sessions = {'stale': stale, 'fresh': fresh}
    manager.cleanup()
    assert stale.closed
    assert not fresh.closed
    assert list(manager.sessions) == ['fresh']
    manager.stop_all()


def test_background_reaper_closes_idle_sessions():
    manager = SessionManager(idle_seconds=1)
    stale = DummySession(time.monotonic() - 5)
    manager.sessions = {'stale': stale}
    manager.start_reaper()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not stale.closed:
        time.sleep(0.05)
    manager.stop_all()
    assert stale.closed
