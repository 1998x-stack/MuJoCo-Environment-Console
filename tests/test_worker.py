"""Viewer worker unit tests: opt-in rendering and thread-pool capping."""
import pytest

from app.worker import DEFAULT_BLAS_THREADS, DEFAULT_RENDER_THREADS, ViewerRuntime, apply_process_limits

BLAS_KEYS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def test_render_is_opt_in():
    """A viewer must not rasterise anything until a client subscribes."""
    runtime = ViewerRuntime(fps=12)
    assert runtime.render is False
    assert runtime.status()['render'] is False

    assert runtime.apply({'op': 'render', 'value': True}) == 'changed'
    assert runtime.render is True
    assert runtime.status()['render'] is True

    assert runtime.apply({'op': 'render', 'value': False}) == 'changed'
    assert runtime.render is False


def test_runtime_command_semantics():
    runtime = ViewerRuntime(fps=8)
    assert runtime.fps == 8
    assert runtime.apply({'op': 'pause', 'value': True}) == 'changed'
    assert runtime.paused is True
    runtime.apply({'op': 'pause', 'value': False})
    assert runtime.paused is False

    runtime.apply({'op': 'render', 'value': True})
    runtime.mode = 'policy'
    assert runtime.apply({'op': 'random'}) == 'changed'
    assert (runtime.mode, runtime.policy) == ('random', None)
    assert runtime.apply({'op': 'reset'}) == 'reset'
    assert runtime.apply({'op': 'policy'}) == 'policy'
    assert runtime.apply({'op': 'stop'}) == 'stop'
    assert runtime.apply({'op': 'not-a-real-op'}) == 'ignored'


def test_runtime_status_reports_counters():
    runtime = ViewerRuntime()
    runtime.steps, runtime.episodes, runtime.last_reward, runtime.episode_return = 42, 3, 0.5, 12.25
    assert runtime.status() == {'steps': 42, 'episodes': 3, 'reward': 0.5,
                                'episode_return': 12.25, 'mode': 'random',
                                'paused': False, 'render': False}


def test_default_thread_budgets_are_the_measured_optimum():
    """Pinned on purpose: see the llvmpipe cost table in app/worker.py before changing."""
    assert DEFAULT_RENDER_THREADS == '2'
    assert DEFAULT_BLAS_THREADS == '1'


def test_apply_process_limits_caps_every_pool():
    env = {}
    limits = apply_process_limits(env)
    assert env['LP_NUM_THREADS'] == DEFAULT_RENDER_THREADS
    for key in BLAS_KEYS:
        assert env[key] == DEFAULT_BLAS_THREADS
    assert limits == {'render_threads': int(DEFAULT_RENDER_THREADS),
                      'blas_threads': int(DEFAULT_BLAS_THREADS)}


def test_apply_process_limits_honours_operator_overrides():
    env = {'VIEWER_RENDER_THREADS': '2', 'VIEWER_BLAS_THREADS': '3'}
    apply_process_limits(env)
    assert env['LP_NUM_THREADS'] == '2'
    assert all(env[key] == '3' for key in BLAS_KEYS)


@pytest.mark.parametrize('bad', ['nonsense', '0', '-4', '', None])
def test_apply_process_limits_sanitises_bad_values(bad):
    env = {'VIEWER_RENDER_THREADS': bad, 'VIEWER_BLAS_THREADS': bad}
    apply_process_limits(env)
    assert env['LP_NUM_THREADS'] == DEFAULT_RENDER_THREADS
    for key in BLAS_KEYS:
        assert env[key] == DEFAULT_BLAS_THREADS


def test_apply_process_limits_mutates_real_environ(monkeypatch):
    """The real call site passes no mapping and must touch os.environ before numpy loads."""
    monkeypatch.delenv('LP_NUM_THREADS', raising=False)
    apply_process_limits()
    import os
    assert os.environ['LP_NUM_THREADS'] == DEFAULT_RENDER_THREADS
