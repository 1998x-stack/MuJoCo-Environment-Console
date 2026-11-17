from __future__ import annotations
import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from app.jobs import read_json, write_json

class ProgressUpdater:
    def __init__(self, folder):
        self.folder = folder
        self.last = 0

    def update(self, steps, reward=None):
        if steps - self.last < 250 and steps != 0:
            return
        self.last = steps
        path = self.folder / 'status.json'
        data = read_json(path)
        if data['status'] in ('cancelled', 'interrupted'):
            return
        data.update({'status': 'running', 'completed_steps': steps,
                     'average_reward': reward})
        write_json(path, data)


def train(folder):
    import gymnasium as gym
    from stable_baselines3 import PPO, SAC
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.monitor import Monitor
    import numpy as np
    from app.env_factory import make_environment
    info = read_json(folder / 'status.json')
    descriptor = read_json(folder / 'environment.json')
    progress = ProgressUpdater(folder)

    class Callback(BaseCallback):
        def _on_step(self):
            recent = [ep['r'] for ep in self.model.ep_info_buffer if 'r' in ep]
            mean = float(np.mean(recent[-10:])) if recent else None
            progress.update(self.num_timesteps, mean)
            return True

    env = Monitor(make_environment(descriptor))
    cls = {'PPO': PPO, 'SAC': SAC}[info['algorithm']]
    policy = 'MultiInputPolicy' if isinstance(env.observation_space, gym.spaces.Dict) else 'MlpPolicy'
    try:
        model = cls(policy, env, verbose=1, seed=42, device='auto')
        model.learn(total_timesteps=info['timesteps'], callback=Callback())
        model.save(str(folder / 'model'))
        actual_steps = int(model.num_timesteps)
        print(f'Model saved after {actual_steps} steps', flush=True)
    finally:
        env.close()
    # Independent evaluation uses a separate env, not the training env.
    eval_env = make_environment(descriptor)
    returns = []
    try:
        for seed in (101, 202, 303):
            obs, _ = eval_env.reset(seed=seed)
            total = 0.0
            for _ in range(1000):
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, _ = eval_env.step(action)
                total += float(reward)
                if terminated or truncated:
                    break
            returns.append(total)
    finally:
        eval_env.close()
    status = read_json(folder / 'status.json')
    if status.get('status') not in ('cancelled', 'interrupted'):
        status.update({'status': 'completed', 'completed_steps': actual_steps,
                       'average_reward': float(np.mean(returns)),
                       'eval_returns': returns,
                       'finished': datetime.now(timezone.utc).isoformat()})
        write_json(folder / 'status.json', status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path, required=True)
    folder = parser.parse_args().run_dir
    try:
        train(folder)
    except Exception as exc:
        traceback.print_exc()
        status = read_json(folder / 'status.json')
        if status.get('status') not in ('cancelled', 'interrupted'):
            status.update({'status': 'failed', 'error': str(exc)})
            write_json(folder / 'status.json', status)
        sys.exit(1)

if __name__ == '__main__':
    main()
