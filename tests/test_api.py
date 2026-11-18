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
