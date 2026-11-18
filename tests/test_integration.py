"""Integration tests skip if MuJoCo/Gymnasium not installed on test host."""
import numpy as np
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


def test_custom_double_pendulum_resolves_include_and_mesh():
    """<include> plus a relative mesh asset must load and render through the adapter."""
    pytest.importorskip('gymnasium')
    pytest.importorskip('mujoco')
    from app.catalog import get_env
    from app.env_factory import make_environment
    descriptor = get_env('custom:custom_double_pendulum')
    env = make_environment(descriptor, render=True, width=160, height=120)
    try:
        assert env.model.nq == 2 and env.model.nv == 2 and env.model.nu == 2
        assert env.model.nmesh == 1, 'the relative STL mesh from the included XML did not load'
        obs, _ = env.reset(seed=42)
        assert obs.shape == (4,)
        assert env.action_space.shape == (2,)
        for _ in range(5):
            obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
            assert np.isfinite(reward)
        frame = env.render()
        assert frame is not None and frame.shape == (120, 160, 3)
    finally:
        env.close()


def test_view_only_scene_runs_without_actuators():
    pytest.importorskip('gymnasium')
    pytest.importorskip('mujoco')
    from app.catalog import get_env
    from app.env_factory import make_environment
    descriptor = get_env('custom:scene_demo_viewer')
    assert descriptor['trainable'] is False
    env = make_environment(descriptor, render=True, width=160, height=120)
    try:
        assert env.model.nu == 0 and env.model.nmesh == 1
        env.reset(seed=42)
        _, reward, terminated, truncated, _ = env.step(env.action_space.sample())
        assert np.isfinite(reward)
        assert env.render() is not None
    finally:
        env.close()
