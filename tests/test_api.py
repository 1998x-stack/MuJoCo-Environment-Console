import os
os.environ.setdefault('MUJOCO_CONSOLE_PASSWORD', 'test-only-secret')
from fastapi.testclient import TestClient
from app.main import app


def test_auth_health_catalog():
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/api/catalog').status_code == 401
        assert client.post('/api/login',json={'password':'wrong'}).status_code == 401
        result = client.post('/api/login',json={'password':'test-only-secret'})
        assert result.status_code == 200
        assert result.cookies.get('mujoco_session')
        response=client.get('/api/catalog')
        assert response.status_code == 200
        assert any(x['id']=='gym:Hopper-v5' for x in response.json()['environments'])
        assert response.headers['x-frame-options'] == 'DENY'
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/catalog').status_code == 401


def test_invalid_training_request():
    with TestClient(app) as client:
        client.post('/api/login',json={'password':'test-only-secret'})
        assert client.post('/api/training',json={'env_id':'unknown','algorithm':'PPO','timesteps':1000}).status_code == 400
        assert client.post('/api/training',json={'env_id':'gym:Hopper-v5','algorithm':'DQN','timesteps':1000}).status_code == 400
