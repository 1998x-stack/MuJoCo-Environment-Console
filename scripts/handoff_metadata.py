#!/usr/bin/env python3
"""Derive the five SHAs a handoff must keep apart, so documentation never masquerades as code.

The confusion this prevents: a run ends with commits that only touch ``docs/``. The branch head
then differs from the commit whose behaviour was actually validated, and a later reader cannot
tell whether the CI evidence covers the code they are looking at.

Definitions
  base_sha       merge base with the target branch (``origin/main`` by default)
  code_sha       newest commit in ``base_sha..HEAD`` that touched non-documentation files
  pr_head_sha    current ``HEAD`` (what the PR points at)
  validated_sha  the commit the recorded evidence belongs to (``--validated-sha``, default code_sha)
  ci_run_id      the Actions run id the evidence came from (``--ci-run-id``, optional)

Exit codes: 0 = usable, 2 = could not determine a SHA.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

# Paths whose content changes behaviour. Anything else (docs/AGENTS.md/README) is documentation.
CODE_PATHS = ('app', 'envs', 'scripts', 'tests', 'schemas', '.github',
              'Dockerfile', 'compose.yaml', 'requirements.txt', 'requirements-robotics.txt',
              'pytest.ini')
DOC_PATHS = ('docs', 'AGENTS.md', 'README.md')


def git(*args: str, cwd: str | None = None) -> str:
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f'git {" ".join(args)} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def classify(paths: list[str]) -> str:
    if not paths:
        return 'unknown'
    if all(any(p == d or p.startswith(d + '/') for d in DOC_PATHS) for p in paths):
        return 'docs'
    if all(any(p == d or p.startswith(d + '/') for d in CODE_PATHS) for p in paths):
        return 'code'
    return 'mixed'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--validated-sha')
    parser.add_argument('--ci-run-id')
    args = parser.parse_args()

    base_sha = git('merge-base', 'HEAD', args.base, cwd=args.repo)
    pr_head_sha = git('rev-parse', 'HEAD', cwd=args.repo)
    history = git('log', '--format=%H%x1f%h%x1f%s', f'{base_sha}..HEAD', cwd=args.repo)
    commits = []
    for line in filter(None, history.splitlines()):
        sha, short, subject = line.split('\x1f')
        files = [f for f in git('show', '--name-only', '--format=', sha, cwd=args.repo).splitlines() if f]
        commits.append({'sha': sha, 'short': short, 'subject': subject,
                        'files': files, 'kind': classify(files)})

    # git log is newest first: the first code commit is the one whose behaviour was tested,
    # everything before it in this list is documentation written afterwards.
    code_index = next((i for i, c in enumerate(commits) if c['kind'] in ('code', 'mixed')), None)
    code_sha = commits[code_index]['sha'] if code_index is not None else base_sha
    docs_after = [c for c in commits[:code_index or 0] if c['kind'] == 'docs']
    validated_sha = args.validated_sha or code_sha

    report = {
        'base': args.base,
        'base_sha': base_sha,
        'code_sha': code_sha,
        'code_short': code_sha[:7],
        'pr_head_sha': pr_head_sha,
        'pr_head_short': pr_head_sha[:7],
        'validated_sha': validated_sha,
        'validated_matches_pr_head': validated_sha == pr_head_sha,
        'ci_run_id': args.ci_run_id,
        'documentation_only_commits_after_code': [
            {'sha': c['sha'][:7], 'subject': c['subject']} for c in docs_after],
        'commit_count_since_base': len(commits),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report['validated_sha'] != report['pr_head_sha']:
        print('\nNOTE: the evidence belongs to validated_sha; later commits only touch docs.',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
