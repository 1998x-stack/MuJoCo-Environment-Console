"""Integration tests skip if MuJoCo/Gymnasium not installed on test host."""
import pytest


def test_standard_env_physics():
    pytest.importorskip('gymnasium')
    pytest.importorskip('mujoco')
    from app.catalog import get_env
    from app.env_factory import make_environment
    env = make_environment(get_env('gym:InvertedPendulum-v5'))
    try:
        o, info = env.reset(seed=42)
        for _ in range(5):
            obs, reward, t, tr, inf = env.step(env.action_space.sample())
            assert obs is not None
    finally:
        env.close()


def test_custom_env_physics():
    pytest.importorskip('gymnasium')
    pytest.importorskip('mujoco')
    from app.catalog import get_env
    from app.env_factory import make_environment
    env = make_environment(get_env('custom:custom_pendulum'))
    try:
        obs, info = env.reset(seed=42)
        assert obs.shape == (2,)
        assert env.action_space.shape == (1,)
        obs, reward, t, tr, inf = env.step([0.1])
        assert isinstance(reward, float)
    finally:
        env.close()
