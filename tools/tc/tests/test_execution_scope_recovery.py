"""Recovery uses each failed child's own source, real SQLite and local Git only."""
import copy
import hashlib
import json
import subprocess
import sys

import pytest
from tc import api
from tc.commands.execution import execute_command
from tc.db.connection import get_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex
from tc.services.qa_contract import digest


def family(db, root=None):
    root = root or db.parent.parent
    root.mkdir(exist_ok=True)
    for name in ('a.py', 'b.py'):
        (root / name).write_text('VALUE = 1\n')
    def create(name, sources, criterion, parent=None):
        contract = {'schemaVersion': 2, 'sources': sources,
                    'criteria': [{'id': criterion, 'expected': 'The scoped repair works.'}]}
        task = api.create_task(title=name, parent=parent,
            metadata={'requiresQa': True, 'acceptanceContract': contract}, db_path=db)['id']
        ex.register_limits(task_id=task, root=root, ceiling_attempts=20,
                           no_progress_n=20, timeout_seconds=30, db_path=db)
        return task
    parent = create('Governing root', ['a.py', 'b.py'], 'DELIVERY')
    children = [create(name, [name], 'CHECK', parent) for name in ('a.py', 'b.py')]
    for child in children:
        ex.bind_scope(root_task_id=parent, task_id=child,
                      criterion_map={'CHECK': 'DELIVERY'}, db_path=db)
    return root, parent, children


def fail(db, root, child):
    item = ex.begin_attempt(task_id=child, criterion='CHECK', label='real local observation',
                           work_identity=[hashlib.sha256(str(child).encode()).hexdigest()], db_path=db)
    artifact = root / (item['token'] + '.txt')
    artifact.write_text('Observed failure ' + item['token'])
    ex.settle_attempt(token=item['token'], succeeded=False, artifact=artifact, db_path=db)
    return item


def prove(db, task, criterion):
    # Deterministic receipt fixture only; assertions below verify recovery behavior.
    # This arithmetic subprocess is not native/model or product-regression proof.
    return execute_command(task=task, criterion=criterion, db_path=db, offline=True,
                           command=[sys.executable, '-c', 'assert 2 + 2 == 4'])['artifact']


def diagnose(db, task, criterion):
    return ex.diagnosis_checkpoint(task_id=task, criterion=criterion,
                                  regression=prove(db, task, criterion), db_path=db)


def attempts(db):
    with get_db(db) as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM execution_attempts ORDER BY started,token')]


def test_root_diagnoses_changed_child_without_resetting_usage_or_history(db_path):
    root, parent, children = family(db_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    before = attempts(db_path)
    (root / 'a.py').write_text('VALUE = 2\n')
    diagnose(db_path, parent, 'DELIVERY')
    diagnose(db_path, children[0], 'CHECK')
    assert attempts(db_path) == before
    with get_db(db_path) as conn:
        cp = conn.execute("SELECT * FROM execution_checkpoints WHERE task_id=? AND kind='diagnosis'", (parent,)).fetchone()
        assert cp['through_started'] == before[-1]['started']
    retry = ex.begin_attempt(task_id=children[0], criterion='CHECK', label='actual retry', db_path=db_path)
    assert retry['task_id'] == children[0]
    assert ex.scope_usage(task_id=parent, db_path=db_path)['usage']['attempts'] == 3
    assert ex.budget_status(db_path=db_path)['used_calls'] == 0


@pytest.mark.parametrize('changed', [None, 'b.py'])
def test_root_digest_difference_or_other_child_change_cannot_clear_failed_child(db_path, changed):
    root, parent, children = family(db_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    before = attempts(db_path)
    if changed:
        (root / changed).write_text('VALUE = 2\n')
    with pytest.raises(ValidationError, match='unchanged'):
        diagnose(db_path, parent, 'DELIVERY')
    assert attempts(db_path) == before


def test_changed_latest_child_cannot_clear_unchanged_sibling_failure(db_path):
    root, parent, children = family(db_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[1])
    (root / 'b.py').write_text('VALUE = 2\n')
    with pytest.raises(ValidationError, match='unchanged'):
        diagnose(db_path, parent, 'DELIVERY')


def git(root, *args):
    result = subprocess.run(['git', '-c', 'commit.gpgsign=false', '-c', 'user.name=fixture',
        '-c', 'user.email=fixture@example.invalid', *args], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def relocate(db, root, parent, children, tmp, changed=False):
    git(root, 'init', '-q')
    git(root, 'remote', 'add', 'origin', 'https://example.invalid/recovery.git')
    git(root, 'add', 'a.py', 'b.py')
    git(root, 'commit', '-qm', 'baseline')
    baseline = git(root, 'rev-parse', 'HEAD')
    successor = tmp / 'successor'
    git(root, 'worktree', 'add', '--detach', str(successor), baseline)
    if changed:
        (successor / 'a.py').write_text('VALUE = 2\n')
        git(successor, 'add', 'a.py')
        git(successor, 'commit', '-qm', 'repair')
    commit = git(successor, 'rev-parse', 'HEAD')
    api.add_repo(repo_id='candidate', path=successor, db_path=db)
    for task in (parent, *children):
        data = api.get_task(task_id=task, db_path=db)['metadata']
        contract = (json.loads(data) if isinstance(data, str) else data)['acceptanceContract']
        amended = copy.deepcopy(contract)
        amended.update(schemaVersion=3, sources=[], externalSources=[
            {'repo': 'candidate', 'ref': commit, 'paths': contract['sources']}])
        ex.amend_contract(task_id=task, contract=amended, expected_contract_sha256=digest(contract),
                          decision='Preserve scope in exact same repository successor.', db_path=db)
    return successor


@pytest.mark.parametrize('changed', [False, True])
def test_same_repository_relocation_needs_changed_bytes_not_digest_representation(db_path, tmp_path, changed):
    root, parent, children = family(db_path, tmp_path / 'source')
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    before = attempts(db_path)
    relocate(db_path, root, parent, children, tmp_path, changed)
    if changed:
        diagnose(db_path, parent, 'DELIVERY')
        diagnose(db_path, children[0], 'CHECK')
    else:
        with pytest.raises(ValidationError, match='unchanged'):
            diagnose(db_path, parent, 'DELIVERY')
        with pytest.raises(ValidationError, match='unchanged'):
            diagnose(db_path, children[0], 'CHECK')
    assert attempts(db_path) == before


def test_relocated_historical_baseline_mismatch_stays_held(db_path, tmp_path):
    root, parent, children = family(db_path, tmp_path / 'source')
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    relocate(db_path, root, parent, children, tmp_path, True)
    (root / 'a.py').write_text('unverifiable historical source\n')
    with pytest.raises(ValidationError, match='historical|baseline'):
        diagnose(db_path, parent, 'DELIVERY')


def test_diagnosis_does_not_raise_shared_ceiling(db_path):
    root, parent, children = family(db_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    before = ex.execution_status(task_id=parent, db_path=db_path)
    (root / 'a.py').write_text('VALUE = 2\n')
    diagnose(db_path, parent, 'DELIVERY')
    after = ex.execution_status(task_id=parent, db_path=db_path)
    assert after['limits'] == before['limits']
    assert after['usage'] == before['usage']
    assert after['remaining'] == before['remaining']


@pytest.mark.parametrize('changed', [False, True])
def test_external_reference_change_requires_prior_scoped_content_change(db_path, tmp_path, changed):
    root, parent, children = family(db_path, tmp_path / 'source')
    successor = relocate(db_path, root, parent, children, tmp_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    if changed:
        (successor / 'a.py').write_text('VALUE = 2\n')
        git(successor, 'add', 'a.py')
    git(successor, 'commit', '--allow-empty', '-qm', 'new reference identity')
    commit = git(successor, 'rev-parse', 'HEAD')
    for task in (parent, children[0]):
        data = api.get_task(task_id=task, db_path=db_path)['metadata']
        contract = (json.loads(data) if isinstance(data, str) else data)['acceptanceContract']
        amended = copy.deepcopy(contract)
        amended['externalSources'][0]['ref'] = commit
        ex.amend_contract(task_id=task, contract=amended, expected_contract_sha256=digest(contract),
                          decision='Advance the same source scope.', db_path=db_path)
    if changed:
        diagnose(db_path, parent, 'DELIVERY')
    else:
        with pytest.raises(ValidationError, match='unchanged'):
            diagnose(db_path, parent, 'DELIVERY')


def test_prior_verified_failure_window_stays_covered_when_next_child_is_repaired(db_path):
    root, parent, children = family(db_path)
    fail(db_path, root, children[0])
    fail(db_path, root, children[0])
    (root / 'a.py').write_text('VALUE = 2\n')
    diagnose(db_path, parent, 'DELIVERY')
    diagnose(db_path, children[0], 'CHECK')
    fail(db_path, root, children[1])
    fail(db_path, root, children[1])
    (root / 'b.py').write_text('VALUE = 2\n')
    before = attempts(db_path)
    diagnose(db_path, parent, 'DELIVERY')
    assert attempts(db_path) == before
    assert ex.scope_usage(task_id=parent, db_path=db_path)['usage']['attempts'] == 4
