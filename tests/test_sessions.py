import queue
import time

import pytest

import app.sessions as sessions
from app.sessions import (VIEWER_FPS_DEFAULT, VIEWER_HEIGHT_DEFAULT, VIEWER_WIDTH_DEFAULT,
                          SessionManager, ViewerSession, viewer_config)


class DummySession:
    def __init__(self, last_seen):
        self.last_seen = last_seen
        self.closed = False

    def close(self):
        self.closed = True


class FakeQueue:
    """Enough of multiprocessing.Queue for ViewerSession's bookkeeping."""

    def __init__(self, maxsize=0):
        self.items = []
        self.maxsize = maxsize
        self.closed = False

    def put_nowait(self, item):
        self.items.append(item)

    def get(self, timeout=None):
        raise queue.Empty

    def get_nowait(self):
        raise queue.Empty

    def close(self):
        self.closed = True

    def cancel_join_thread(self):
        pass


class FakeProcess:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.pid = 4242
        self._alive = False
        self.terminated = False
        self.killed = False

    def start(self):
        self._alive = True

    def join(self, timeout=None):
        self._alive = False

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False


class FakeContext:
    def __init__(self):
        self.processes = []
        self.queues = []

    def Queue(self, maxsize=0):
        q = FakeQueue(maxsize)
        self.queues.append(q)
        return q

    def Process(self, target=None, args=(), daemon=None):
        p = FakeProcess(target, args, daemon)
        self.processes.append(p)
        return p


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


def test_viewer_config_defaults():
    assert viewer_config() == {'fps': VIEWER_FPS_DEFAULT,
                               'width': VIEWER_WIDTH_DEFAULT,
                               'height': VIEWER_HEIGHT_DEFAULT}


def test_viewer_config_parses_and_clamps():
    assert viewer_config('8', '320', '240') == {'fps': 8, 'width': 320, 'height': 240}
    # out of range values are clamped instead of rejected
    assert viewer_config('999', '4', '99999') == {'fps': 60, 'width': 64, 'height': 1920}
    # unparsable values fall back to the defaults
    assert viewer_config('fast', '', 'tall') == {'fps': VIEWER_FPS_DEFAULT,
                                                 'width': VIEWER_WIDTH_DEFAULT,
                                                 'height': VIEWER_HEIGHT_DEFAULT}


def test_viewer_config_reads_environment(monkeypatch):
    monkeypatch.setenv('VIEWER_FPS', '6')
    monkeypatch.setenv('VIEWER_WIDTH', '480')
    monkeypatch.setenv('VIEWER_HEIGHT', '360')
    assert viewer_config() == {'fps': 6, 'width': 480, 'height': 360}


def test_session_manager_passes_viewer_config(monkeypatch):
    recorded = {}

    class Recorder:
        def __init__(self, descriptor, **kwargs):
            recorded.update(kwargs)
            recorded['descriptor'] = descriptor
            self.id = 'recorded'

    monkeypatch.setattr(sessions, 'ViewerSession', Recorder)
    manager = SessionManager(limit=2, idle_seconds=60, fps='7', width='512', height='384')
    manager.start({'id': 'gym:Test-v5'})
    assert recorded['descriptor'] == {'id': 'gym:Test-v5'}
    assert (recorded['fps'], recorded['width'], recorded['height']) == (7, 512, 384)


def test_render_only_while_subscribed():
    """Regression for the viewer CPU burn: rendering must follow the subscriber count."""
    ctx = FakeContext()
    session = ViewerSession({'id': 'gym:Test-v5'}, ctx=ctx)
    commands = session.commands
    try:
        assert session.status()['subscribers'] == 0
        assert commands.items == [], 'a brand new session must not be told to render'

        assert session.subscribe() == 1
        assert commands.items == [{'op': 'render', 'value': True}]

        # a second tab viewing the same session must not re-send the command
        assert session.subscribe() == 2
        assert commands.items == [{'op': 'render', 'value': True}]

        assert session.unsubscribe() == 1
        assert commands.items == [{'op': 'render', 'value': True}], 'still one subscriber left'

        assert session.unsubscribe() == 0
        assert commands.items == [{'op': 'render', 'value': True}, {'op': 'render', 'value': False}]
    finally:
        session.close()
    # close() asks the worker to stop and resets the subscriber accounting
    assert commands.items[-1] == {'op': 'stop'}
    assert session.status()['subscribers'] == 0


def test_unsubscribe_after_worker_exit_is_not_an_error():
    ctx = FakeContext()
    session = ViewerSession({'id': 'gym:Test-v5'}, ctx=ctx)
    session.subscribe()
    session.process.terminate()          # worker died
    assert session.unsubscribe() == 0    # must not raise
    session.close()


def test_status_exposes_viewer_settings():
    ctx = FakeContext()
    session = ViewerSession({'id': 'gym:Test-v5'}, fps=6, width=320, height=240, ctx=ctx)
    try:
        status = session.status()
        assert (status['fps'], status['width'], status['height']) == (6, 320, 240)
    finally:
        session.close()


@pytest.mark.parametrize('value,expected', [
    ('12', 12), ('abc', VIEWER_FPS_DEFAULT), ('0', 1), ('-3', 1), ('1000', 60), (None, VIEWER_FPS_DEFAULT),
])
def test_viewer_fps_bounds(monkeypatch, value, expected):
    monkeypatch.delenv('VIEWER_FPS', raising=False)
    assert viewer_config(value, 640, 480)['fps'] == expected
