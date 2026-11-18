import queue
import threading
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


class FakeEvent:
    """threading.Event is enough: the cross-process semantics are exercised by the API tests."""

    def __init__(self):
        self._event = threading.Event()

    def set(self):
        self._event.set()

    def clear(self):
        self._event.clear()

    def is_set(self):
        return self._event.is_set()

    def wait(self, timeout=None):
        return self._event.wait(timeout)


class FakeContext:
    def __init__(self):
        self.processes = []
        self.queues = []
        self.events = []

    def Queue(self, maxsize=0):
        q = FakeQueue(maxsize)
        self.queues.append(q)
        return q

    def Process(self, target=None, args=(), daemon=None):
        p = FakeProcess(target, args, daemon)
        self.processes.append(p)
        return p

    def Event(self):
        e = FakeEvent()
        self.events.append(e)
        return e


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


def open_session(**kwargs):
    ctx = FakeContext()
    return ViewerSession({'id': 'gym:Test-v5'}, ctx=ctx, **kwargs), ctx


def test_render_request_follows_the_subscriber_count():
    """Regression for the viewer CPU burn: rendering must follow the subscriber count."""
    session, ctx = open_session()
    try:
        assert session.status()['subscribers'] == 0
        assert session.render_requested.is_set() is False
        assert session.commands.items == [], 'a brand new session must not be told to render'

        assert session.subscribe() == 1
        assert session.render_requested.is_set() is True

        # a second tab viewing the same session keeps rendering on
        assert session.subscribe() == 2
        assert session.render_requested.is_set() is True

        assert session.unsubscribe() == 1
        assert session.render_requested.is_set() is True, 'still one subscriber left'

        assert session.unsubscribe() == 0
        assert session.render_requested.is_set() is False
    finally:
        session.close()
    assert session.commands.items[-1] == {'op': 'stop'}
    assert session.status()['subscribers'] == 0


def test_render_state_never_uses_the_lossy_command_queue():
    """The toggle must not depend on a queue that can be full (it was silently dropped before)."""
    session, _ = open_session()
    try:
        for i in range(20):
            try:
                session.commands.put_nowait({'op': 'filler', 'value': i})
            except queue.Full:
                break
        assert len(session.commands.items) >= session.commands.maxsize
        session.subscribe()
        assert session.render_requested.is_set() is True, 'queue pressure must not matter'
        session.unsubscribe()
        assert session.render_requested.is_set() is False
        assert [c for c in session.commands.items if c.get('op') == 'render'] == []
    finally:
        session.close()


def test_render_flag_is_written_together_with_the_count():
    """Every flag write must observe a count that agrees with it (atomicity, not luck)."""
    session, _ = open_session()
    observations = []
    real_set, real_clear = session.render_requested.set, session.render_requested.clear

    def observe(kind):
        observations.append((kind, session.subscribers()))   # re-entrant lock: same thread

    session.render_requested.set = lambda: (observe('set'), real_set())
    session.render_requested.clear = lambda: (observe('clear'), real_clear())
    errors = []

    def churn():
        for _ in range(150):
            session.subscribe()
            session.unsubscribe()

    threads = [threading.Thread(target=churn) for _ in range(4)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
    finally:
        session.render_requested.set, session.render_requested.clear = real_set, real_clear
        session.close()

    assert observations, 'the hooks must have recorded writes'
    for kind, count in observations:
        if kind == 'set':
            assert count >= 1, f'render requested with subscribers={count}'
        else:
            assert count == 0, f'render cleared with subscribers={count}'


def test_concurrent_subscribe_unsubscribe_keeps_the_invariant():
    """Barrier-synchronised storm: flag and count must agree after every single operation."""
    session, _ = open_session()
    workers, rounds = 8, 200
    barrier = threading.Barrier(workers)
    violations = []

    def worker(seed):
        barrier.wait()
        for i in range(rounds):
            if (i + seed) % 2:
                session.subscribe()
            else:
                session.unsubscribe()
            if session.render_requested.is_set() != (session.subscribers() > 0):
                violations.append((session.subscribers(), session.render_requested.is_set()))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
    finally:
        pass
    assert violations == [], f'{len(violations)} invariant violations, e.g. {violations[:3]}'

    # convergence: one more subscriber turns rendering on, and the last one turns it off
    session.subscribe()
    assert session.render_requested.is_set() is True
    while session.subscribers():
        session.unsubscribe()
    assert session.render_requested.is_set() is False
    session.close()


def test_simultaneous_disconnect_never_leaves_rendering_on():
    """Four clients attached, all released at once: the flag must end up off."""
    session, _ = open_session()
    try:
        for _ in range(4):
            session.subscribe()
        assert session.subscribers() == 4
        barrier = threading.Barrier(4)

        def drop():
            barrier.wait()
            session.unsubscribe()

        threads = [threading.Thread(target=drop) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        assert session.subscribers() == 0
        assert session.render_requested.is_set() is False
    finally:
        session.close()


def test_rapid_reconnect_converges():
    """Fast disconnect/reconnect churn must not lose the final request."""
    session, _ = open_session()
    try:
        for _ in range(50):
            session.subscribe()
            session.unsubscribe()
        assert session.render_requested.is_set() is False
        session.subscribe()
        assert session.render_requested.is_set() is True
        session.unsubscribe()
        assert session.render_requested.is_set() is False
    finally:
        session.close()


def test_closed_session_cannot_be_reactivated():
    session, _ = open_session()
    session.subscribe()
    session.close()
    assert session.render_requested.is_set() is False
    assert session.subscribe() == 0, 'a closed session must not accept subscribers'
    assert session.render_requested.is_set() is False
    session.unsubscribe()                # must stay harmless
    assert session.render_requested.is_set() is False


def test_subscribe_on_dead_worker_does_not_request_render():
    session, _ = open_session()
    try:
        session.process.terminate()       # worker died while a client was connecting
        assert session.is_active() is False
        assert session.subscribe() == 0
        assert session.render_requested.is_set() is False
        assert session.unsubscribe() == 0  # must not raise
    finally:
        session.close()


def test_worker_start_failure_is_a_valueerror():
    class BrokenProcess(FakeProcess):
        def start(self):
            raise OSError('fork failed')

    class BrokenContext(FakeContext):
        def Process(self, target=None, args=(), daemon=None):
            return BrokenProcess(target, args, daemon)

    with pytest.raises(ValueError) as excinfo:
        ViewerSession({'id': 'gym:Test-v5'}, ctx=BrokenContext())
    assert 'Could not start the simulation worker' in str(excinfo.value)


def test_info_does_not_refresh_last_seen_but_status_does():
    session, _ = open_session()
    try:
        session.last_seen = time.monotonic() - 120
        before = session.info()
        assert before['idle_seconds'] >= 120
        assert session.info()['last_seen'] == before['last_seen'], 'info() must not touch'
        after = session.status()
        assert after['last_seen'] > before['last_seen'], 'status() is the heartbeat'
    finally:
        session.close()


def test_manager_list_is_read_only():
    manager = SessionManager(limit=3, idle_seconds=60)
    session, _ = open_session()
    session.last_seen = time.monotonic() - 300
    manager.sessions = {session.id: session}
    try:
        first = manager.list()
        second = manager.list()
        assert len(first) == 1 and len(second) == 1
        assert first[0]['id'] == session.id
        assert first[0]['last_seen'] == second[0]['last_seen'], 'listing must not keep it alive'
        assert first[0]['idle_seconds'] >= 300
        assert 'trace' not in first[0]
        assert not any(isinstance(v, str) and v.startswith('/') for v in first[0].values())
        manager.cleanup()                 # the session is idle, so it must still be reaped
        assert manager.sessions == {}
    finally:
        session.close()
        manager.stop_all()


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
