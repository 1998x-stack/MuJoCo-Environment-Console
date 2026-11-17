import subprocess
import sys

import app.jobs as jobs


def test_mjcf_fingerprint_includes_dependent_assets(tmp_path):
    xml = tmp_path / 'scene.xml'
    mesh = tmp_path / 'mesh.stl'
    xml.write_text('<mujoco/>')
    mesh.write_bytes(b'mesh-a')
    descriptor = {'id': 'custom:test', 'kind': 'mjcf', 'xml_path': str(xml), 'params': {}}
    first = jobs.fingerprint(descriptor)
    mesh.write_bytes(b'mesh-b')
    assert jobs.fingerprint(descriptor) != first


def test_stop_all_terminates_trainer_and_marks_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'RUNS', tmp_path / 'runs')
    manager = jobs.JobManager()
    run_id = 'a' * 32
    folder = jobs.RUNS / run_id
    folder.mkdir()
    jobs.write_json(folder / 'status.json', {
        'id': run_id, 'status': 'running', 'created': '2026-01-01T00:00:00+00:00'
    })
    proc = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(60)'],
        start_new_session=True,
    )
    manager.processes[run_id] = proc
    manager.stop_all()
    assert proc.poll() is not None
    assert jobs.read_json(folder / 'status.json')['status'] == 'interrupted'


def test_finished_unreconciled_process_does_not_stay_running(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'RUNS', tmp_path / 'runs')
    manager = jobs.JobManager()
    run_id = 'b' * 32
    folder = jobs.RUNS / run_id
    folder.mkdir()
    jobs.write_json(folder / 'status.json', {
        'id': run_id, 'status': 'running', 'created': '2026-01-01T00:00:00+00:00'
    })
    proc = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    proc.wait(timeout=5)
    manager.processes[run_id] = proc
    result = manager.list()
    assert result[0]['status'] == 'failed'
    assert 'exit code 0' in result[0]['error']
