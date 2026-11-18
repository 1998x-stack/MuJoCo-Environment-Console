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


def run_metadata(repo_dir: Path, *args: str):
    result = subprocess.run([sys.executable, str(SCRIPT), '--repo', str(repo_dir), '--base',
                             'origin/main', *args], capture_output=True, text=True)
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
    """On this checkout the helper must agree with git and mark unvalidated doc heads."""
    report, _ = run_metadata(ROOT, '--base', 'HEAD')
    head = git(ROOT, 'rev-parse', 'HEAD')
    assert report['pr_head_sha'] == head
    assert report['base_sha'] == head, 'merge-base with HEAD is HEAD'

    report2, _ = run_metadata(ROOT)
    codes = git(ROOT, 'log', '--format=%H', f"{report2['base_sha']}..HEAD").splitlines()
    assert report2['code_sha'] in codes or report2['code_sha'] == report2['base_sha']
    assert report2['validated_sha'] == report2['code_sha']
