"""Short PPO/SAC train-and-replay smoke test for a fully provisioned container."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from app.catalog import get_env
from app.env_factory import make_environment
from app.jobs import read_json, write_json
from app.trainer import train


def run_algorithm(algorithm: str, descriptor: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix=f'mujoco-{algorithm.lower()}-') as tmp:
        folder = Path(tmp)
        write_json(folder / 'environment.json', descriptor)
        write_json(folder / 'status.json', {
            'id': folder.name,
            'env_id': descriptor['id'],
            'algorithm': algorithm,
            'timesteps': 1000,
            'completed_steps': 0,
            'status': 'starting',
            'fingerprint': 'smoke-test',
            'average_reward': None,
        })
        train(folder)
        status = read_json(folder / 'status.json')
        model_path = folder / 'model.zip'
        assert status['status'] == 'completed', status
        assert model_path.is_file(), f'{algorithm} did not save model.zip'

        from stable_baselines3 import PPO, SAC
        model_class = {'PPO': PPO, 'SAC': SAC}[algorithm]
        model = model_class.load(str(model_path), device='cpu')
        env = make_environment(descriptor)
        try:
            obs, _ = env.reset(seed=7)
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            assert obs is not None
            assert isinstance(float(reward), float)
        finally:
            env.close()
        return {
            'algorithm': algorithm,
            'status': status['status'],
            'completed_steps': status['completed_steps'],
            'eval_returns': status.get('eval_returns', []),
            'replay_step': 'passed',
        }


def main():
    import torch
    torch.set_num_threads(1)
    descriptor = get_env('gym:InvertedPendulum-v5')
    results = [run_algorithm(algorithm, descriptor) for algorithm in ('PPO', 'SAC')]
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
