"""End-to-end PPO/SAC job, checkpoint, and isolated viewer-policy smoke test."""
from __future__ import annotations

import json
import os
import tempfile
import time

# Keep the smoke test isolated from the user's persistent training history.
_smoke_data = tempfile.TemporaryDirectory(prefix='mujoco-training-smoke-')
os.environ['CONSOLE_DATA_ROOT'] = _smoke_data.name
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

from app.catalog import get_env
from app.jobs import JobManager, fingerprint
from app.sessions import ViewerSession


def run_algorithm(manager: JobManager, algorithm: str, descriptor: dict) -> dict:
    info = manager.start(descriptor, algorithm, 1000)
    run_id = info['id']
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        status = manager.get(run_id)
        if status.get('status') in ('completed', 'failed', 'cancelled', 'interrupted'):
            break
        time.sleep(0.25)
    else:
        try:
            manager.cancel(run_id)
        finally:
            raise TimeoutError(f'{algorithm} training exceeded 240 seconds')

    proc = manager.processes.get(run_id)
    if proc is not None:
        proc.wait(timeout=10)
    status = manager.get(run_id)
    assert status['status'] == 'completed', status

    folder, _ = manager.model(run_id, descriptor['id'], fingerprint(descriptor))
    viewer = ViewerSession(descriptor, fps=8, width=320, height=240)
    try:
        viewer.command({
            'op': 'policy',
            'run_dir': str(folder),
            'algorithm': algorithm,
        })
        seq = 0
        replay_deadline = time.monotonic() + 30
        while time.monotonic() < replay_deadline:
            seq, jpeg = viewer.wait_frame(seq, timeout=2)
            state = viewer.status()
            if state.get('state') == 'error':
                raise RuntimeError(f'{algorithm} viewer failed: {state.get("error")}')
            if state.get('mode') == 'policy' and state.get('steps', 0) > 0 and jpeg:
                break
        else:
            raise TimeoutError(f'{algorithm} policy viewer did not produce a frame')
    finally:
        viewer.close()

    return {
        'algorithm': algorithm,
        'status': status['status'],
        'requested_steps': status['timesteps'],
        'actual_steps': status['completed_steps'],
        'eval_returns': status.get('eval_returns', []),
        'checkpoint': 'saved and validated',
        'isolated_policy_viewer': 'passed',
    }


def main():
    import torch
    torch.set_num_threads(1)
    descriptor = get_env('gym:InvertedPendulum-v5')
    manager = JobManager()
    try:
        results = [
            run_algorithm(manager, algorithm, descriptor)
            for algorithm in ('PPO', 'SAC')
        ]
        print(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        manager.stop_all()
        _smoke_data.cleanup()


if __name__ == '__main__':
    main()
