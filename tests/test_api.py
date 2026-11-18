import json
import os

import pytest

os.environ.setdefault('MUJOCO_CONSOLE_PASSWORD', 'test-only-secret')

from fastapi.testclient import TestClient
import app.main as main


def test_auth_health_catalog():
    with TestClient(main.app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/api/catalog').status_code == 401
        assert client.post('/api/login', json={'password': 'wrong'}).status_code == 401
        result = client.post('/api/login', json={'password': 'test-only-secret'})
        assert result.status_code == 200
        assert result.cookies.get('mujoco_session')
        response = client.get('/api/catalog')
        assert response.status_code == 200
        assert any(x['id'] == 'gym:Hopper-v5' for x in response.json()['environments'])
        assert response.headers['x-frame-options'] == 'DENY'
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/catalog').status_code == 401


def test_catalog_reports_environment_problems():
    """The catalog response must carry per-environment diagnostics, empty for shipped envs."""
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        payload = client.get('/api/catalog').json()
        assert 'environments' in payload and 'problems' in payload
        assert isinstance(payload['problems'], list)
        assert payload['problems'] == [], payload['problems']


def test_catalog_stays_up_with_a_broken_environment(tmp_path, monkeypatch):
    """A broken custom environment must degrade to a diagnostic, not break the console."""
    (tmp_path / 'half_written').mkdir()
    (tmp_path / 'half_written' / 'manifest.json').write_text('{oops')
    import app.catalog as catalog
    monkeypatch.setattr(main, 'scan', lambda: catalog.scan(tmp_path))
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        response = client.get('/api/catalog')
        assert response.status_code == 200
        body = response.json()
        assert body['environments'], 'built-in environments must still be listed'
        assert any(p['id'] == 'custom:half_written' and p['reason'] == 'invalid_manifest_json'
                   for p in body['problems'])


def test_stream_rejects_an_inactive_session(monkeypatch):
    """A dead worker must produce a clear 409 instead of an endless empty stream."""
    import asyncio

    stub = StubSession(alive=False)
    monkeypatch.setitem(main.manager.sessions, 'deadid', stub)
    with pytest.raises(main.HTTPException) as excinfo:
        asyncio.run(main.session_stream('deadid', True))
    assert excinfo.value.status_code == 409
    assert 'not running' in excinfo.value.detail
    assert stub.subscribed == 0, 'an inactive session must never be subscribed'


def test_session_list_reports_public_state_only(monkeypatch):
    """GET /api/sessions: inventory for operators, without leaking internals or reviving sessions."""
    stub = StubSession('listed')
    stub._last_seen = 0.0
    monkeypatch.setitem(main.manager.sessions, 'listed', stub)
    stub.subscribe()
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        payload = client.get('/api/sessions').json()
        assert payload['limit'] == main.manager.limit
        assert payload['idle_seconds'] == main.manager.idle_seconds
        entry = next(s for s in payload['sessions'] if s['id'] == 'listed')
        assert entry['env_id'] == 'gym:Stub-v5'
        assert entry['subscribers'] == 1
        assert entry['render_requested'] is True
        assert entry['alive'] is True and entry['closed'] is False
        assert entry['state'] == 'ready'
        assert 'created' in entry and 'last_seen' in entry and 'idle_seconds' in entry
        # no credentials, no traceback, no filesystem locations
        flat = json.dumps(payload)
        for forbidden in ('token', 'cookie', 'mujoco_session', 'trace', '/app/', 'xml_path'):
            assert forbidden not in flat
    stub.unsubscribe()


def test_session_list_requires_authentication():
    with TestClient(main.app) as client:
        assert client.get('/api/sessions').status_code == 401


def test_invalid_training_request():
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        assert client.post('/api/training', json={
            'env_id': 'unknown', 'algorithm': 'PPO', 'timesteps': 1000
        }).status_code == 400
        assert client.post('/api/training', json={
            'env_id': 'gym:Hopper-v5', 'algorithm': 'DQN', 'timesteps': 1000
        }).status_code == 400


def test_login_rate_limit():
    main.LOGIN_FAILURES.clear()
    with TestClient(main.app) as client:
        for _ in range(main.LOGIN_MAX_ATTEMPTS):
            assert client.post('/api/login', json={'password': 'wrong'}).status_code == 401
        assert client.post('/api/login', json={'password': 'test-only-secret'}).status_code == 429
    main.LOGIN_FAILURES.clear()


def test_secure_cookie_can_be_enabled(monkeypatch):
    main.LOGIN_FAILURES.clear()
    monkeypatch.setattr(main, 'COOKIE_SECURE', True)
    with TestClient(main.app) as client:
        response = client.post('/api/login', json={'password': 'test-only-secret'})
        assert response.status_code == 200
        assert 'secure' in response.headers['set-cookie'].lower()


def test_mjpeg_part_is_rfc2046_framed():
    """A part must end in a real CRLF so spec-conformant clients can find the boundary."""
    jpeg = b'\xff\xd8\xff\xe0payload\xff\xd9'
    part = main.mjpeg_part(jpeg)
    assert part.startswith(b'--' + main.MJPEG_BOUNDARY.encode() + b'\r\n')
    assert part.endswith(b'\r\n\r\n' + jpeg + b'\r\n')
    assert b'Content-Length: ' + str(len(jpeg)).encode() in part
    assert b'\\r\\n' not in part, 'boundary terminator must not be an escaped backslash literal'

    stream = part + main.mjpeg_part(jpeg)
    # exactly one CRLF-delimited delimiter joins the two parts
    assert stream.count(b'\r\n--' + main.MJPEG_BOUNDARY.encode()) == 1
    assert stream.count(b'--' + main.MJPEG_BOUNDARY.encode()) == 2


def test_view_only_environment_rejects_training():
    """Selection-only scenes must never be trainable, regardless of installed libraries."""
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        response = client.post('/api/training', json={
            'env_id': 'custom:scene_demo_viewer', 'algorithm': 'PPO', 'timesteps': 2000
        })
        assert response.status_code == 400
        assert 'trainable' in response.json()['detail'] or 'extra package' in response.json()['detail']


class StubProcess:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


class StubSession:
    """Records subscribe/unsubscribe so the endpoints can be tested without MuJoCo."""

    def __init__(self, sid='stubid', alive=True):
        self.id = sid
        self.env_id = 'gym:Stub-v5'
        self.process = StubProcess(alive)
        self._closed = False
        self.subscribed = 0
        self.unsubscribed = 0
        self._frames = [b'jpeg-one', b'jpeg-two']
        self._last_seen = 0.0

    def touch(self):
        import time
        self._last_seen = time.monotonic()

    def is_active(self):
        return not self._closed and self.process.is_alive()

    def subscribe(self):
        if not self.is_active():
            return 0
        self.subscribed += 1
        self.touch()
        return self.subscribed

    def unsubscribe(self):
        self.unsubscribed += 1
        return 0

    def subscribers(self):
        return self.subscribed - self.unsubscribed

    def info(self):
        return {'id': self.id, 'env_id': self.env_id, 'alive': self.process.is_alive(),
                'closed': self._closed, 'state': 'ready', 'subscribers': self.subscribers(),
                'render_requested': self.subscribers() > 0, 'render': self.subscribers() > 0,
                'created': 0.0, 'last_seen': self._last_seen, 'idle_seconds': 0.0,
                'fps': 12, 'width': 640, 'height': 480, 'steps': 0, 'episodes': 0, 'error': None}

    def status(self):
        self.touch()
        return self.info()

    def wait_frame(self, seq, timeout=5):
        if seq < len(self._frames):
            return seq + 1, self._frames[seq]
        return seq, None


def test_stream_subscribes_then_unsubscribes(monkeypatch):
    """A closed MJPEG connection must switch viewer rendering back off."""
    import asyncio

    stub = StubSession()
    monkeypatch.setitem(main.manager.sessions, 'stubid', stub)

    async def drive():
        response = await main.session_stream('stubid', True)
        iterator = response.body_iterator
        chunks = []
        async for chunk in iterator:
            chunks.append(chunk)
            if len(chunks) >= 2:
                break
        await iterator.aclose()          # what Starlette does when the client disconnects
        return chunks

    chunks = asyncio.run(drive())
    assert stub.subscribed == 1
    assert stub.unsubscribed == 1
    body = b''.join(chunks)
    assert body.count(b'--' + main.MJPEG_BOUNDARY.encode()) == 2
    assert b'Content-Type: image/jpeg' in body


def test_catalog_reports_whether_schema_validation_is_active():
    """Clients must be able to tell "no problems" from "not checking"."""
    with TestClient(main.app) as client:
        client.post('/api/login', json={'password': 'test-only-secret'})
        payload = client.get('/api/catalog').json()
        assert payload['schema']['available'] is True, payload['schema']
        assert payload['schema']['reason'] is None
