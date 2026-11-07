"""Real candidate CLI/hook bootstrap boundaries; no mocked permissive authority."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tc.db.connection import init_db
from tests.cycle_stage_fixtures import make_world

ROOT = Path(__file__).resolve().parents[3]


def environment():
    env = os.environ.copy()
    env.pop('TC_WORKTREE_DB', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'tools/tc/src')
    return env


def context(root):
    return subprocess.run([sys.executable, '-m', 'tc.main', 'cycle',
                           'dispatch-context', '--cwd', str(root), '--json'],
                          cwd=root, env=environment(), capture_output=True, text=True)


def hook(root, evidence, *, unavailable=False):
    evidence.mkdir()
    wrapper = evidence / 'tc'
    wrapper.write_text('#!' + sys.executable + '\n' +
                       ('raise SystemExit(2)\n' if unavailable else
                        'from tc.main import app\napp()\n'))
    wrapper.chmod(0o755)
    config = evidence / 'config'
    config.mkdir()
    state = evidence / 'state'
    state.mkdir()
    env = environment()
    env.update(COPILOT_TC_BIN=str(wrapper), CLAUDE_PROJECT_DIR=str(root),
               CLAUDE_CONFIG_DIR=str(config), COPILOT_HOOK_STATE_DIR=str(state))
    env.pop('COPILOT_COORDINATOR', None)
    return subprocess.run(['bash', str(ROOT / '.claude/hooks/pretool-check.sh')],
                          input=json.dumps({'session_id': 'bootstrap-control',
                                            'tool_name': 'Agent', 'tool_input': {}}),
                          cwd=root, env=env, capture_output=True, text=True)


def test_capable_cli_proves_no_database_without_initializing(tmp_path):
    result = context(tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'managed': False, 'cycles': [], 'nativeDispatch': False}
    assert not (tmp_path / '.copilot').exists()


def test_actual_hook_allows_proven_unmanaged_bootstrap(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    result = hook(root, tmp_path / 'hook')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / '.copilot').exists()


def test_existing_legacy_database_remains_unmanaged(tmp_path):
    init_db(tmp_path / '.copilot/tasks.db')
    result = context(tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['managed'] is False


@pytest.mark.parametrize('kind', ['corrupt', 'dangling'])
def test_existing_invalid_authority_never_becomes_unmanaged(tmp_path, kind):
    db = tmp_path / '.copilot/tasks.db'
    db.parent.mkdir()
    if kind == 'corrupt':
        db.write_bytes(b'not a SQLite database')
    else:
        db.symlink_to(tmp_path / 'missing-authority.db')
    result = context(tmp_path)
    assert result.returncode != 0
    assert '"managed": false' not in result.stdout
    assert db.is_symlink() if kind == 'dangling' else db.read_bytes() == b'not a SQLite database'


def test_unresolved_linked_worktree_authority_refuses(tmp_path):
    (tmp_path / '.git').write_text('gitdir: /nonexistent-stage-fixture-authority\n')
    result = context(tmp_path)
    assert result.returncode != 0
    assert '"managed": false' not in result.stdout


def test_unavailable_older_authority_still_denies_actual_hook(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    result = hook(root, tmp_path / 'hook', unavailable=True)
    assert result.returncode == 2
    assert 'stage-authority-unavailable' in result.stdout


def test_managed_database_still_requires_envelope(tmp_path):
    world = make_world(tmp_path, count=1)
    (world.root / '.copilot').symlink_to(world.db.parent, target_is_directory=True)
    result = context(world.root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['managed'] is True
    result = hook(world.root, tmp_path / 'hook')
    assert result.returncode == 2
    assert 'managed-envelope-required' in result.stdout


def test_explicit_local_authority_missing_still_refuses(tmp_path):
    env = environment()
    env['TC_WORKTREE_DB'] = 'local'
    result = subprocess.run([sys.executable, '-m', 'tc.main', 'cycle',
                             'dispatch-context', '--cwd', str(tmp_path), '--json'],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert '"managed": false' not in result.stdout
