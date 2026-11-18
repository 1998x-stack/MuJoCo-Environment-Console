"""Persistent training runs with explicit process-group lifecycle management."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

DATA_ROOT = Path(os.getenv('CONSOLE_DATA_ROOT', './data')).resolve()
RUNS = DATA_ROOT / 'runs'
ACTIVE = ('starting', 'running')


def _now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(descriptor):
    stable = {k: v for k, v in descriptor.items() if k not in ('installed',)}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode())
    if descriptor.get('kind') == 'mjcf':
        xml_path = Path(descriptor['xml_path']).resolve()
        root = xml_path.parent
        # Include meshes, textures and included XML files, not only the entry-point XML.
        for asset in sorted(root.rglob('*')):
            if not asset.is_file() or asset.is_symlink():
                continue
            resolved = asset.resolve()
            if not resolved.is_relative_to(root):
                continue
            digest.update(asset.relative_to(root).as_posix().encode('utf8'))
            with asset.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()


def write_json(path, obj):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f'.{target.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(tmp, target)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def exit_reason(code):
    """Explain how a trainer process ended, including container-level kills."""
    if code is None:
        return 'Trainer exited unexpectedly'
    if code in (-9, 137):
        return ('Trainer was killed (exit code 137/SIGKILL) — usually the container memory '
                'limit, an external docker stop/kill, or the host running out of memory')
    if code in (-15, 143):
        return 'Trainer was terminated (exit code 143/SIGTERM)'
    if code < 0:
        return f'Trainer was killed by signal {-code}'
    return f'Trainer exited unexpectedly (exit code {code})'


def terminate_process_group(pgid, grace_seconds=4):
    """Terminate the detached trainer process group, escalating if it ignores SIGTERM."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class JobManager:
    def __init__(self):
        self.processes = {}
        self.lock = threading.RLock()
        self._closing = False
        RUNS.mkdir(parents=True, exist_ok=True)
        # Recover interrupted runs and terminate a detached trainer left behind by
        # an in-container server restart. Verify its command line before signaling.
        for meta in RUNS.glob('*/status.json'):
            try:
                data = read_json(meta)
                if data.get('status') in ACTIVE:
                    pid = data.get('pid')
                    if isinstance(pid, int) and pid > 1:
                        try:
                            cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode('utf8', 'replace')
                            run_dir = str(meta.parent.resolve())
                            if 'app.trainer' in cmdline and run_dir in cmdline:
                                terminate_process_group(pid, grace_seconds=2)
                        except (OSError, ProcessLookupError):
                            pass
                    data.update({'status': 'interrupted', 'finished': _now(),
                                 'error': 'Server restarted while training was active'})
                    write_json(meta, data)
            except (OSError, ValueError):
                continue

    def start_accepting(self):
        """Allow new runs when the ASGI lifespan starts or restarts."""
        with self.lock:
            self._closing = False

    def _reconcile_finished(self, run_id, proc):
        code = proc.poll()
        if code is None:
            return
        try:
            info = self.get(run_id)
            if info.get('status') in ACTIVE:
                info.update({'status': 'failed', 'error': exit_reason(code),
                             'finished': _now()})
                write_json(RUNS / run_id / 'status.json', info)
        except (KeyError, OSError, ValueError):
            pass
        self.processes.pop(run_id, None)

    def list(self):
        with self.lock:
            for run_id, proc in list(self.processes.items()):
                self._reconcile_finished(run_id, proc)
            result = []
            for status in RUNS.glob('*/status.json'):
                try:
                    result.append(read_json(status))
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
            if self._closing:
                raise ValueError('Server is shutting down')
            for run_id, proc in list(self.processes.items()):
                self._reconcile_finished(run_id, proc)
            if self.processes:
                raise ValueError('One training job at a time in the CPU-first edition')
            run_id = uuid.uuid4().hex
            folder = RUNS / run_id
            folder.mkdir()
            info = {'id': run_id, 'env_id': descriptor['id'], 'algorithm': algorithm,
                    'timesteps': timesteps, 'completed_steps': 0, 'status': 'starting',
                    'created': _now(), 'fingerprint': fingerprint(descriptor),
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
            except Exception as exc:
                info.update({'status': 'failed', 'error': str(exc), 'finished': _now()})
                write_json(folder / 'status.json', info)
                raise
            finally:
                logfile.close()
            info['pid'] = proc.pid
            write_json(folder / 'status.json', info)
            self.processes[run_id] = proc
            return info

    def cancel(self, run_id):
        with self.lock:
            info = self.get(run_id)
            if info.get('status') not in ACTIVE:
                raise ValueError('Run is not active')
            proc = self.processes.get(run_id)
            if proc is None:
                raise ValueError('Run is not managed by this server')
            if proc.poll() is not None:
                self._reconcile_finished(run_id, proc)
                raise ValueError('Run is no longer active')
            terminate_process_group(proc.pid, grace_seconds=4)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                terminate_process_group(proc.pid, grace_seconds=0)
                proc.wait(timeout=1)
            info = self.get(run_id)
            if info.get('status') in ACTIVE:
                info.update({'status': 'cancelled', 'finished': _now()})
                write_json(RUNS / run_id / 'status.json', info)
            self.processes.pop(run_id, None)
            return info

    def stop_all(self):
        """Stop all detached trainer groups before the API process exits."""
        with self.lock:
            self._closing = True
            items = list(self.processes.items())
        for run_id, proc in items:
            if proc.poll() is None:
                terminate_process_group(proc.pid, grace_seconds=4)
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    terminate_process_group(proc.pid, grace_seconds=0)
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            try:
                info = self.get(run_id)
                if info.get('status') in ACTIVE:
                    info.update({'status': 'interrupted', 'finished': _now(),
                                 'error': 'Server is shutting down'})
                    write_json(RUNS / run_id / 'status.json', info)
            except (KeyError, OSError, ValueError):
                pass
        with self.lock:
            self.processes.clear()

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
