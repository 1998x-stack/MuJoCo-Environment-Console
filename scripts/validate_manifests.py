#!/usr/bin/env python3
"""Validate every shipped envs/*/manifest.json against schemas/environment.schema.json.

Used by CI; requires the `jsonschema` package (declared in the CI dependency install step).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    schema = json.loads((ROOT / 'schemas/environment.schema.json').read_text(encoding='utf8'))
    validator = jsonschema.Draft202012Validator(schema)
    manifests = sorted((ROOT / 'envs').glob('*/manifest.json'))
    if not manifests:
        print('no manifests found', file=sys.stderr)
        return 1
    failures = 0
    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding='utf8'))
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        except (OSError, ValueError) as exc:
            print(f'FAIL {manifest.relative_to(ROOT)}: {exc}')
            failures += 1
            continue
        if errors:
            failures += 1
            print(f'FAIL {manifest.relative_to(ROOT)}')
            for error in errors:
                print(f'     {"/".join(str(p) for p in error.path) or "<root>"}: {error.message}')
        else:
            print(f'OK   {manifest.relative_to(ROOT)}')
    print(f'{len(manifests) - failures}/{len(manifests)} manifests valid')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
