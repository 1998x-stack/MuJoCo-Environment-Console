"""Each viewer owns one OS process and one OpenGL context.

Measured on the reference Ubuntu host (12 logical CPUs, OSMesa/llvmpipe): a single
640x480 frame costs roughly 0.5 CPU-seconds because the software rasteriser spawns one
worker thread per core and those threads spin. Physics (0.12 ms) and JPEG encoding
(0.84 ms) are negligible next to it. Two consequences shape this module:

* rendering is only enabled while a client is actually subscribed to the MJPEG stream,
  otherwise an abandoned session would keep burning a whole core per viewer;
* the viewer process caps its own thread pools so it cannot oversubscribe the host.

Measured steady-state cost on that host (640x480, 12 fps target):

| llvmpipe threads | 1 viewer | 3 viewers | per-viewer fps |
|------------------|----------|-----------|----------------|
| 12 (unset)       |  522%    |   645%    | 11.4           |
| 4                |  214%    |   617%    | 11.2           |
| 2                |  170%    |   430%    | 11.6           |

Two threads keeps every shipped environment (including Humanoid-v5) at 11.6+ fps while using a
third of the CPU of the default pool. ``VIEWER_RENDER_THREADS`` raises it when a heavier scene
or a larger render size needs more headroom.
"""
from __future__ import annotations
import io
import os
import queue
import time
import traceback
from pathlib import Path

VIEWER_THREAD_ENV = {
    'LP_NUM_THREADS': 'VIEWER_RENDER_THREADS',
    'OMP_NUM_THREADS': 'VIEWER_BLAS_THREADS',
    'OPENBLAS_NUM_THREADS': 'VIEWER_BLAS_THREADS',
    'MKL_NUM_THREADS': 'VIEWER_BLAS_THREADS',
    'NUMEXPR_NUM_THREADS': 'VIEWER_BLAS_THREADS',
}
DEFAULT_RENDER_THREADS = '2'
DEFAULT_BLAS_THREADS = '1'


def _positive_int(value, fallback):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 1 else fallback


def apply_process_limits(environ=None):
    """Cap viewer thread pools. Must run before numpy/MuJoCo create their pools.

    ``LP_NUM_THREADS`` bounds the llvmpipe rasteriser; the BLAS/OpenMP variables keep
    numpy from creating a second pool of idle threads. Both are configurable through
    ``VIEWER_RENDER_THREADS`` / ``VIEWER_BLAS_THREADS`` (see VIEWER_THREAD_ENV).
    """
    env = os.environ if environ is None else environ
    defaults = {'VIEWER_RENDER_THREADS': int(DEFAULT_RENDER_THREADS),
                'VIEWER_BLAS_THREADS': int(DEFAULT_BLAS_THREADS)}
    resolved = {key: _positive_int(env.get(key), fallback) for key, fallback in defaults.items()}
    for target, source in VIEWER_THREAD_ENV.items():
        env[target] = str(resolved[source])
    return {'render_threads': resolved['VIEWER_RENDER_THREADS'],
            'blas_threads': resolved['VIEWER_BLAS_THREADS']}


class ViewerRuntime:
    """Mutable viewer state.

    ``render`` is not controlled by the command queue: the worker reads the shared
    ``render_requested`` event every loop and copies it into ``render``. A legacy ``render``
    command is ignored on purpose, so a stale queue entry can never fight the event.
    """

    def __init__(self, fps=12.0):
        self.fps = max(1.0, float(fps))
        self.mode = 'random'
        self.paused = False
        self.render = False
        self.policy = None
        self.steps = 0
        self.episodes = 0
        self.episode_return = 0.0
        self.last_reward = 0.0

    def apply(self, command):
        """Apply one control command. Returns 'stop', 'changed' or 'ignored'."""
        op = command.get('op')
        if op == 'stop':
            return 'stop'
        if op == 'pause':
            self.paused = bool(command.get('value', False))
            return 'changed'
        if op == 'reset':
            return 'reset'
        if op == 'random':
            self.mode, self.policy = 'random', None
            return 'changed'
        if op == 'policy':
            return 'policy'
        return 'ignored'

    def status(self):
        return {'steps': self.steps, 'episodes': self.episodes,
                'reward': round(self.last_reward, 4),
                'episode_return': round(self.episode_return, 3),
                'mode': self.mode, 'paused': self.paused, 'render': self.render}


def _publish(q, payload):
    try:
        q.put_nowait(payload)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def run_worker(descriptor, commands, frames, states, render_requested, fps, width, height):
    env = None
    try:
        os.environ.setdefault('MUJOCO_GL', 'osmesa')
        os.environ.setdefault('PYOPENGL_PLATFORM', 'osmesa')
        limits = apply_process_limits()
        import numpy as np
        from PIL import Image
        from app.env_factory import make_environment
        env = make_environment(descriptor, render=True, width=width, height=height)
        obs, _ = env.reset(seed=42)
        runtime = ViewerRuntime(fps)
        runtime.render = bool(render_requested.is_set())
        _publish(states, {'state': 'ready', 'mode': runtime.mode, 'render': runtime.render,
                          'observation_space': str(env.observation_space),
                          'action_space': str(env.action_space),
                          'viewer_limits': limits})
        tick = 1.0 / runtime.fps
        deadline = time.monotonic()
        while True:
            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                action = runtime.apply(command)
                if action == 'stop':
                    return
                if action == 'changed':
                    _publish(states, runtime.status())
                if action == 'reset':
                    obs, _ = env.reset()
                    runtime.episode_return = 0.0
                    _publish(states, {'reset': True})
                if action == 'policy':
                    try:
                        run_dir = Path(command['run_dir'])
                        from stable_baselines3 import PPO, SAC
                        algo = command['algorithm']
                        cls = {'PPO': PPO, 'SAC': SAC}[algo]
                        loaded = cls.load(str(run_dir / 'model.zip'), device='cpu')
                        if loaded.observation_space != env.observation_space or loaded.action_space != env.action_space:
                            raise ValueError('Policy observation/action spaces do not match current environment')
                        runtime.policy = loaded
                        runtime.mode = 'policy'
                        _publish(states, {'mode': runtime.mode, 'policy_run': run_dir.name, 'error': None})
                    except Exception as exc:
                        _publish(states, {'error': f'Model load failed: {exc}'})
            if not runtime.paused:
                if runtime.mode == 'policy' and runtime.policy is not None:
                    action, _ = runtime.policy.predict(obs, deterministic=True)
                else:
                    action = env.action_space.sample()
                obs, reward, terminated, truncated, _ = env.step(action)
                runtime.steps += 1
                runtime.last_reward = float(np.asarray(reward).mean())
                runtime.episode_return += runtime.last_reward
                if terminated or truncated:
                    runtime.episodes += 1
                    obs, _ = env.reset()
                    runtime.episode_return = 0.0
            # Single source of truth for rendering. The event is written atomically with the
            # subscriber count, so it cannot disagree with it, and reading it every loop means
            # a missed transition self-corrects instead of being lost (a queued toggle could be
            # dropped when the command queue is full).
            runtime.render = bool(render_requested.is_set())
            # Rendering is skipped entirely while nobody subscribes: that avoids creating the
            # rasteriser thread pool at all, and physics/state reporting keep running so the
            # UI still shows progress and commands stay responsive.
            if runtime.render:
                try:
                    rendered = env.render()
                    if rendered is not None:
                        image = Image.fromarray(np.asarray(rendered, dtype=np.uint8))
                        output = io.BytesIO()
                        image.save(output, 'JPEG', quality=72, optimize=False)
                        _publish(frames, output.getvalue())
                except Exception as exc:
                    _publish(states, {'error': f'Render failed: {exc}'})
                    raise
            if runtime.steps % 6 == 0 or runtime.paused:
                _publish(states, {'state': 'ready', **runtime.status()})
            deadline += tick
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                deadline = time.monotonic()
    except Exception as exc:
        _publish(states, {'state': 'error', 'error': str(exc), 'trace': traceback.format_exc(limit=6)})
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
