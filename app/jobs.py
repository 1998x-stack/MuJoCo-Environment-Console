"""Persistent local training run metadata; never load external model uploads."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

DATA_ROOT = Path(os.getenv('CONSOLE_DATA_ROOT', './data')).resolve()
RUNS = DATA_ROOT / 'runs'

def fingerprint(descriptor):
    stable = {k: v for k, v in descriptor.items() if k not in ('installed',)}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode())
    if descriptor.get('kind') == 'mjcf':
        digest.update(Path(descriptor['xml_path']).read_bytes())
    return digest.hexdigest()

def write_json(path, obj):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(tmp, target)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

class JobManager:
    def __init__(self):
        self.processes = {}
        self.lock = threading.RLock()
        RUNS.mkdir(parents=True, exist_ok=True)
        # In-flight processes are container-scoped; restarting the server interrupts them.
        for meta in RUNS.glob('*/status.json'):
            try:
                data = read_json(meta)
                if data.get('status') in ('starting', 'running'):
                    data['status'] = 'interrupted'
                    write_json(meta, data)
            except (OSError, ValueError):
                continue

    def list(self):
        result = []
        for status in RUNS.glob('*/status.json'):
            try:
                item = read_json(status)
                result.append(item)
            except (OSError, ValueError):
                pass
        return sorted(result, key=lambda x: x.get('created', ''), reverse=True)[:100]

    def get(self, run_id):
        if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
            raise KeyError('Invalid run id')
        file = RUNS / run_id / 'status.json'
        if not file.is_file():
            raise KeyError('Training run not found')
        return read_json(file)

    def start(self, descriptor, algorithm, timesteps):
        if algorithm not in ('PPO', 'SAC'):
            raise ValueError('Supported algorithms: PPO, SAC')
        if not isinstance(timesteps, int) or not 1000 <= timesteps <= 5_000_000:
            raise ValueError('timesteps must be an integer between 1000 and 5000000')
        if not descriptor['installed']:
            raise ValueError('Environment is not installed')
        with self.lock:
            for rid, proc in list(self.processes.items()):
                if proc.poll() is not None:
                    self.processes.pop(rid)
            if self.processes:
                raise ValueError('One training job at a time in the CPU-first edition')
            run_id = uuid.uuid4().hex
            folder = RUNS / run_id
            folder.mkdir()
            info = {'id': run_id, 'env_id': descriptor['id'], 'algorithm': algorithm,
                    'timesteps': timesteps, 'completed_steps': 0, 'status': 'starting',
                    'created': datetime.now(timezone.utc).isoformat(), 'fingerprint': fingerprint(descriptor),
                    'average_reward': None}
            write_json(folder / 'status.json', info)
            write_json(folder / 'environment.json', descriptor)
            logfile = open(folder / 'output.log', 'a', buffering=1, encoding='utf8')
            try:
                proc = subprocess.Popen(
                    [sys.executable, '-m', 'app.trainer', '--run-dir', str(folder)],
                    cwd=str(Path(__file__).resolve().parent.parent),
                    stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
                    env=os.environ.copy())
            except Exception:
                info['status'] = 'failed'
                write_json(folder / 'status.json', info)
                raise
            finally:
                logfile.close()
            self.processes[run_id] = proc
            return info

    def cancel(self, run_id):
        with self.lock:
            proc = self.processes.get(run_id)
            info = self.get(run_id)
            if info['status'] not in ('starting', 'running'):
                raise ValueError('Run is not active')
            if proc is None or proc.poll() is not None:
                raise ValueError('Run is not managed by this server')
            os.killpg(proc.pid, signal.SIGTERM)
            info['status'] = 'cancelled'
            write_json(RUNS / run_id / 'status.json', info)
            self.processes.pop(run_id, None)
            return info

    def model(self, run_id, env_id, current_fingerprint):
        run = self.get(run_id)
        if run['status'] != 'completed' or run['env_id'] != env_id:
            raise ValueError('Completed model for this environment is required')
        if run['fingerprint'] != current_fingerprint:
            raise ValueError('Environment definition changed; train a new model')
        folder = RUNS / run_id
        if not (folder / 'model.zip').is_file():
            raise ValueError('Model file is missing')
        return folder, run
