import os

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


class StubSession:
    """Records subscribe/unsubscribe so the streaming endpoint can be tested without MuJoCo."""

    class Process:
        @staticmethod
        def is_alive():
            return True

    def __init__(self):
        self.process = StubSession.Process()
        self._closed = False
        self.subscribed = 0
        self.unsubscribed = 0
        self._frames = [b'jpeg-one', b'jpeg-two']

    def touch(self):
        pass

    def subscribe(self):
        self.subscribed += 1
        return self.subscribed

    def unsubscribe(self):
        self.unsubscribed += 1
        return 0

    def status(self):
        return {'id': 'stub'}

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
