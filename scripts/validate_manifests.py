#!/usr/bin/env python3
"""Validate the shipped environments: manifest schema + discovery diagnostics.

This is the CI guard for `envs/`. It fails when any shipped environment directory would be
rejected or degraded by `app.catalog.scan()`, which is also what the running console reports
through `GET /api/catalog` -> `problems`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    failures = 0

    # 1. Every manifest must satisfy the shipped JSON Schema.
    schema = json.loads((ROOT / 'schemas/environment.schema.json').read_text(encoding='utf8'))
    validator = jsonschema.Draft202012Validator(schema)
    manifests = sorted((ROOT / 'envs').glob('*/manifest.json'))
    if not manifests:
        print('no manifests found', file=sys.stderr)
        return 1
    for manifest in manifests:
        relative = manifest.relative_to(ROOT)
        try:
            data = json.loads(manifest.read_text(encoding='utf8'))
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        except (OSError, ValueError) as exc:
            print(f'FAIL {relative}: {exc}')
            failures += 1
            continue
        if errors:
            failures += 1
            print(f'FAIL {relative}')
            for error in errors:
                print(f'     {"/".join(str(p) for p in error.path) or "<root>"}: {error.message}')
        else:
            print(f'OK   {relative}')
    print(f'{len(manifests) - failures}/{len(manifests)} manifests valid')

    # 2. Discovery must accept every shipped environment without diagnostics.
    import app.catalog as catalog
    entries, problems = catalog.scan(ROOT / 'envs')
    custom = [e for e in entries if e['id'].startswith('custom:')]
    print(f'discovery: {len(entries)} environments ({len(custom)} custom), {len(problems)} problem(s)')
    for problem in problems:
        print(f'  {problem["severity"].upper():7} {problem["id"]} [{problem["reason"]}] {problem["detail"]}')
    if problems:
        print('FAIL: shipped environments must not produce discovery problems', file=sys.stderr)
        failures += 1

    print('PASS' if not failures else f'FAIL ({failures})')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
