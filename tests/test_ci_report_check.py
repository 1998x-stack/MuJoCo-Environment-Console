"""Tests for the CI gate that decides whether a pytest run is acceptable.

The gate exists because ``docker run ... pytest | tee`` can hide a non-zero exit status and a
substring match for "passed" cannot tell "0 skipped" from "3 skipped". These tests feed the
checker synthetic JUnit reports, including deliberately broken ones, and assert it refuses
them. A gate that cannot fail is worse than no gate.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'scripts/check_pytest_report.py'

REQUIRED = (
    'tests/test_integration.py::test_physics_dependencies_are_available_when_required',
    'tests/test_integration.py::test_standard_env_physics',
    'tests/test_integration.py::test_custom_env_physics',
    'tests/test_integration.py::test_custom_double_pendulum_resolves_include_and_mesh',
    'tests/test_integration.py::test_view_only_scene_runs_without_actuators',
)


def case(case_id, result='passed'):
    path, name = case_id.split('::')
    classname = path[:-3].replace('/', '.')
    body = '' if result == 'passed' else f'<{result} message="synthetic" />'
    return f'<testcase classname="{classname}" name="{name}" time="0.01">{body}</testcase>'


def report(tmp_path, cases):
    passed = sum(1 for _, r in cases if r == 'passed')
    failures = sum(1 for _, r in cases if r == 'failure')
    errors = sum(1 for _, r in cases if r == 'error')
    skipped = sum(1 for _, r in cases if r == 'skipped')
    xml = (
        f'<testsuites><testsuite name="pytest" tests="{len(cases)}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}">' + ''.join(case(i, r) for i, r in cases)
        + '</testsuite></testsuites>'
    )
    path = tmp_path / 'junit.xml'
    path.write_text(xml)
    return path, passed


def run(report_path, log_path=None):
    args = [sys.executable, str(SCRIPT), str(report_path)]
    if log_path is not None:
        args.append(str(log_path))
    return subprocess.run(args, capture_output=True, text=True)


def all_required_passing(extra=()):
    return [(name, 'passed') for name in REQUIRED] + list(extra)


def test_clean_report_is_accepted(tmp_path):
    path, _ = report(tmp_path, all_required_passing([('tests/test_api.py::test_auth', 'passed')]))
    result = run(path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'strict suite OK' in result.stdout


@pytest.mark.parametrize('outcome', ['failure', 'error', 'skipped'])
def test_bad_outcomes_are_rejected(tmp_path, outcome):
    cases = all_required_passing([('tests/test_api.py::test_something', outcome)])
    path, _ = report(tmp_path, cases)
    result = run(path)
    assert result.returncode == 1, f'{outcome} must be rejected'
    assert 'FAIL' in result.stdout


def test_zero_collected_is_rejected(tmp_path):
    path, _ = report(tmp_path, [])
    result = run(path)
    assert result.returncode == 1
    assert 'no tests were collected' in result.stdout


def test_missing_required_integration_test_is_rejected(tmp_path):
    cases = [(name, 'passed') for name in REQUIRED[:-1]]
    path, _ = report(tmp_path, cases)
    result = run(path)
    assert result.returncode == 1
    assert 'required test missing' in result.stdout


def test_required_test_marked_skipped_is_rejected(tmp_path):
    cases = [(name, 'passed') for name in REQUIRED]
    cases[1] = (REQUIRED[1], 'skipped')
    path, _ = report(tmp_path, cases)
    result = run(path)
    assert result.returncode == 1
    assert 'did not pass (skipped)' in result.stdout


def test_missing_report_is_a_hard_error(tmp_path):
    result = run(tmp_path / 'nope.xml')
    assert result.returncode == 2
    assert 'no pytest report' in result.stdout


def test_empty_report_is_a_hard_error(tmp_path):
    path = tmp_path / 'junit.xml'
    path.write_text('')
    assert run(path).returncode == 2


def test_malformed_report_is_a_hard_error(tmp_path):
    path = tmp_path / 'junit.xml'
    path.write_text('<testsuites><testsuite')
    result = run(path)
    assert result.returncode == 2
    assert 'unreadable' in result.stdout


def test_failure_keeps_diagnostics(tmp_path):
    log = tmp_path / 'pytest.log'
    log.write_text('\n'.join(f'line {i}' for i in range(100)) + '\nE   AssertionError: boom\n')
    cases = all_required_passing([('tests/test_api.py::test_broken', 'failure')])
    path, _ = report(tmp_path, cases)
    result = run(path, log)
    assert result.returncode == 1
    assert 'AssertionError: boom' in result.stdout, 'the log tail must survive a failure'
    assert 'test_broken' in result.stdout


def test_checker_is_wired_into_ci():
    """The workflow must call the structured gate and must not rely on grepping stdout."""
    workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf8')
    assert 'scripts/check_pytest_report.py' in workflow
    assert '--junit-xml' in workflow
    assert 'set -euo pipefail' in workflow, 'the pipe to tee would otherwise hide pytest failures'
    assert "grep -qE" not in workflow.split('Run the full test suite')[1].split('- name:')[0]
