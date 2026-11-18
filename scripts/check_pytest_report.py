#!/usr/bin/env python3
"""Fail unless a pytest JUnit XML report shows a complete, clean, skip-free run.

Used by CI instead of grepping stdout for "passed": a pipeline like ``pytest | tee`` can hide a
non-zero exit status, and a text match cannot distinguish "0 skipped" from "3 skipped".

Exit codes: 0 = acceptable, 1 = the run must not be considered green, 2 = the report is unusable.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Tests that must actually execute: each one needs MuJoCo/Gymnasium, so its presence and
# outcome is what proves the suite was not silently degraded to "everything skipped".
REQUIRED_TESTS = (
    'tests/test_integration.py::test_physics_dependencies_are_available_when_required',
    'tests/test_integration.py::test_standard_env_physics',
    'tests/test_integration.py::test_custom_env_physics',
    'tests/test_integration.py::test_custom_double_pendulum_resolves_include_and_mesh',
    'tests/test_integration.py::test_view_only_scene_runs_without_actuators',
)


def test_id(testcase: ET.Element) -> str:
    """Map pytest's JUnit classname/name pair back to a tests/... file::function id."""
    classname = testcase.get('classname', '').replace('.', '/') or 'unknown'
    return f"{classname}.py::{testcase.get('name', '')}"


def outcome(testcase: ET.Element) -> str:
    for child in testcase:
        if child.tag in ('failure', 'error', 'skipped'):
            return child.tag
    return 'passed'


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: check_pytest_report.py <junit.xml> [pytest.log]', file=sys.stderr)
        return 2
    report = Path(argv[1])
    log = Path(argv[2]) if len(argv) > 2 else None

    if not report.is_file() or report.stat().st_size == 0:
        print(f'FATAL: no pytest report at {report} (collection failed or pytest never ran)')
        if log and log.is_file():
            print('--- last 40 lines of the test log ---')
            print('\n'.join(log.read_text(errors='replace').splitlines()[-40:]))
        return 2
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        print(f'FATAL: unreadable pytest report: {exc}')
        return 2

    suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
    if not suites:
        print('FATAL: the report contains no testsuite element')
        return 2

    counters = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    for suite in suites:
        for key in counters:
            counters[key] += int(suite.get(key, 0) or 0)

    cases = list(root.iter('testcase'))
    seen = {test_id(case): outcome(case) for case in cases}
    print(f'junit: {counters["tests"]} tests, {counters["failures"]} failures, '
          f'{counters["errors"]} errors, {counters["skipped"]} skipped ({len(cases)} testcases parsed)')

    problems = []
    if counters['tests'] == 0 or not cases:
        problems.append('no tests were collected')
    if counters['failures'] or counters['errors']:
        problems.append(f'{counters["failures"]} failure(s) and {counters["errors"]} error(s)')
    if counters['skipped']:
        problems.append(f'{counters["skipped"]} skipped test(s); the strict suite must not skip')
    for required in REQUIRED_TESTS:
        if required not in seen:
            problems.append(f'required test missing from the report: {required}')
        elif seen[required] != 'passed':
            problems.append(f'required test did not pass ({seen[required]}): {required}')

    if problems:
        print('FAIL: the test run is not acceptable:')
        for problem in problems:
            print(f'  - {problem}')
        for name, result in sorted(seen.items()):
            if result != 'passed':
                print(f'    {result:8} {name}')
        if log and log.is_file():
            print('--- last 40 lines of the test log ---')
            print('\n'.join(log.read_text(errors='replace').splitlines()[-40:]))
        return 1

    print(f'strict suite OK: {counters["tests"]} passed, 0 failed, 0 errors, 0 skipped')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
