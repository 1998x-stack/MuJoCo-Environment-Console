"""Tests for the handoff SHA taxonomy helper.

The helper exists because a run often ends with documentation-only commits: the branch head then
differs from the commit whose behaviour was validated, and a reader cannot tell which one the CI
evidence covers.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'scripts/handoff_metadata.py'

def test_git_is_available():
    """Metadata verification needs git; a missing git must be a loud failure, not a skip.

    The CI job installs git before running the strict suite, so this can never be "not tested".
    """
    assert shutil.which('git'), 'git is required by tests/test_handoff_metadata.py'


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture()
def repo(tmp_path):
    """A throwaway repository whose 'main' is the base branch."""
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'test@example.com')
    git(root, 'config', 'user.name', 'Test')
    commit(root, 'chore: base', {'README.md': 'base\n'})
    git(root, 'branch', '-f', 'origin/main')       # stand-in for the remote base
    git(root, 'checkout', '-q', '-b', 'feature')
    return root


def run_metadata(repo_dir: Path, *args: str, base: str = 'origin/main'):
    result = subprocess.run([sys.executable, str(SCRIPT), '--repo', str(repo_dir), '--base',
                             base, *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stderr


def test_code_sha_is_the_last_commit_that_changed_code(repo):
    code = commit(repo, 'fix(app): change behaviour', {'app/thing.py': 'x = 1\n'})
    docs = commit(repo, 'docs: describe it', {'docs/handoff/latest.md': 'text\n'})
    report, stderr = run_metadata(repo)
    assert report['code_sha'] == code
    assert report['pr_head_sha'] == docs
    assert report['validated_sha'] == code, 'evidence defaults to the code commit'
    assert report['validated_matches_pr_head'] is False
    assert [c['sha'] for c in report['documentation_only_commits_after_code']] == [docs[:7]]
    assert 'later commits only touch docs' in stderr


def test_validated_sha_can_be_pinned_and_matches_head_when_code_is_last(repo):
    code = commit(repo, 'feat: last commit is code', {'scripts/run.py': 'print(1)\n'})
    report, stderr = run_metadata(repo)
    assert report['code_sha'] == code
    assert report['pr_head_sha'] == code
    assert report['validated_matches_pr_head'] is True
    assert report['documentation_only_commits_after_code'] == []
    assert 'later commits only touch docs' not in stderr

    pinned, _ = run_metadata(repo, '--validated-sha', 'a' * 40, '--ci-run-id', '12345')
    assert pinned['validated_sha'] == 'a' * 40
    assert pinned['ci_run_id'] == '12345'


def test_base_sha_is_the_merge_base(repo):
    base = git(repo, 'rev-parse', 'origin/main')
    commit(repo, 'code', {'app/a.py': '1\n'})
    report, _ = run_metadata(repo)
    assert report['base_sha'] == base


def test_mixed_commit_counts_as_code(repo):
    mixed = commit(repo, 'feat: code plus docs', {'app/b.py': '2\n', 'docs/note.md': 'n\n'})
    report, _ = run_metadata(repo)
    assert report['code_sha'] == mixed


def test_reports_a_clean_json_document(repo):
    commit(repo, 'docs only', {'docs/only.md': 'x\n'})
    report, _ = run_metadata(repo)
    for key in ('base_sha', 'code_sha', 'pr_head_sha', 'validated_sha'):
        assert report[key] is not None
        assert len(report[key]) >= 7
    assert report['commit_count_since_base'] >= 1


def test_real_repository_reports_a_consistent_taxonomy():
    """On this checkout the helper must agree with git.

    The base is given explicitly as HEAD: CI checks out a single ref, so origin/main does not
    exist there and a test that assumed it would fail (which is how this was found).
    """
    report, _ = run_metadata(ROOT, base='HEAD')
    head = git(ROOT, 'rev-parse', 'HEAD')
    assert report['pr_head_sha'] == head
    assert report['base_sha'] == head, 'merge-base with HEAD is HEAD'
    assert report['base_ref_resolved'] is True
    assert report['commit_count_since_base'] >= 0


def test_a_missing_base_ref_falls_back_instead_of_crashing(repo):
    """A shallow or single-branch checkout must not make the helper unusable."""
    commit(repo, 'feat: work', {'app/x.py': '1\n'})
    commit(repo, 'docs: notes', {'docs/n.md': 'n\n'})
    root = git(repo, 'rev-list', '--max-parents=0', 'HEAD').splitlines()[-1]
    report, stderr = run_metadata(repo, base='refs/heads/definitely-absent')
    assert report['base_ref_resolved'] is False
    assert report['base_sha'] == root, 'the fallback base is the root commit'
    assert 'is not available in this checkout' in stderr


def test_a_shallow_range_is_reported_rather_than_guessed(repo):
    """With no commits in base..HEAD the helper says so instead of inventing a code_sha."""
    commit(repo, 'feat: only commit', {'app/y.py': '1\n'})
    report, stderr = run_metadata(repo, base='HEAD')
    assert report['commit_count_since_base'] == 0
    assert report['code_sha'] == report['base_sha']
    assert 'no commits found in base..HEAD' in stderr
