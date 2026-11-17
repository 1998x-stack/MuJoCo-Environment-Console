"""Each viewer owns one OS process and one OpenGL context."""
from __future__ import annotations
import io
import os
import queue
import time
import traceback
from pathlib import Path


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


def run_worker(descriptor, commands, frames, states, fps, width, height):
    env = None
    try:
        os.environ.setdefault('MUJOCO_GL', 'osmesa')
        import numpy as np
        from PIL import Image
        from app.env_factory import make_environment
        env = make_environment(descriptor, render=True, width=width, height=height)
        obs, _ = env.reset(seed=42)
        mode, policy, paused = 'random', None, False
        steps, episodes, episode_return = 0, 0, 0.0
        last_reward = 0.0
        _publish(states, {'state': 'ready', 'mode': mode,
                          'observation_space': str(env.observation_space),
                          'action_space': str(env.action_space)})
        tick = 1.0 / fps
        deadline = time.monotonic()
        while True:
            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                op = command.get('op')
                if op == 'stop':
                    return
                if op == 'pause':
                    paused = bool(command.get('value', False))
                    _publish(states, {'paused': paused})
                if op == 'reset':
                    obs, _ = env.reset()
                    episode_return = 0.0
                    _publish(states, {'reset': True})
                if op == 'random':
                    mode, policy = 'random', None
                    _publish(states, {'mode': mode})
                if op == 'policy':
                    try:
                        run_dir = Path(command['run_dir'])
                        from stable_baselines3 import PPO, SAC
                        algo = command['algorithm']
                        cls = {'PPO': PPO, 'SAC': SAC}[algo]
                        loaded = cls.load(str(run_dir / 'model.zip'), device='cpu')
                        if loaded.observation_space != env.observation_space or loaded.action_space != env.action_space:
                            raise ValueError('Policy observation/action spaces do not match current environment')
                        policy = loaded
                        mode = 'policy'
                        _publish(states, {'mode': mode, 'policy_run': run_dir.name, 'error': None})
                    except Exception as exc:
                        _publish(states, {'error': f'Model load failed: {exc}'})
            if not paused:
                if mode == 'policy' and policy is not None:
                    action, _ = policy.predict(obs, deterministic=True)
                else:
                    action = env.action_space.sample()
                obs, reward, terminated, truncated, _ = env.step(action)
                steps += 1
                last_reward = float(np.asarray(reward).mean())
                episode_return += last_reward
                if terminated or truncated:
                    episodes += 1
                    obs, _ = env.reset()
                    episode_return = 0.0
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
            if steps % 6 == 0 or paused:
                _publish(states, {'state': 'ready', 'steps': steps, 'episodes': episodes,
                                  'reward': round(last_reward, 4), 'episode_return': round(episode_return, 3),
                                  'mode': mode, 'paused': paused})
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

