"""Authorized regression coverage for TASK-40/41; real SQLite writes and files."""
import json
import pytest
from tc import api
from tc.db.connection import init_db
from tc.db.exceptions import ValidationError


def register(task, db_path, criteria=None):
    root = db_path.parent.parent
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src/main.py').write_text('value = 1\n')
    contract = {'schemaVersion': 2, 'criteria': criteria or [{'id': 'C1', 'expected': 'value equals one'}], 'sources': ['src']}
    api.update_task(task_id=task['id'], metadata={'acceptanceContract': contract, 'requiresQa': True}, db_path=db_path)
    return contract


def packet(task, db_path, criteria=None):
    contract = register(task, db_path, criteria)
    records = ''.join(f"CRITERION: {c['id']}\nEXPECTED: {c['expected']}\nOBSERVED: verified actual behavior\n" for c in contract['criteria'])
    return records + api.capture_qa_identity(task_id=task['id'], db_path=db_path)['identity_line'] + '\nBASELINE: old behavior reproduced\nARTIFACT: test-run|local behavior assertion exit=0\nUNTESTED: none\nVERDICT: APPROVED\n'


def store(task, db_path, body):
    return api.store_wp(task_id=task['id'], type_='test', title='QA', content=body, db_path=db_path)


def test_correct_contract_allows_real_completion(db_path):
    task = api.create_task(title='Bound behavior', metadata={'requiresQa': True}, db_path=db_path)
    store(task, db_path, packet(task, db_path))
    assert api.check_task_qa(task_id=task['id'], db_path=db_path)['approved']
    api.update_task(task_id=task['id'], status='completed', db_path=db_path)
    assert api.get_task(task_id=task['id'], db_path=db_path)['status'] == 'completed'


@pytest.mark.parametrize('mutation', ['other_task', 'other_database', 'criteria', 'expected', 'source', 'new_file', 'deletion', 'scope', 'title', 'description', 'malformed_identity'])
def test_rejects_misbound_or_stale_evidence(db_path, mutation, tmp_path):
    task = api.create_task(title='Bound behavior', metadata={'requiresQa': True}, db_path=db_path)
    body = packet(task, db_path)
    target, database = task, db_path
    if mutation == 'other_task':
        target = api.create_task(title='Other behavior', metadata={'requiresQa': True}, db_path=db_path)
        register(target, db_path)
    elif mutation == 'other_database':
        database = tmp_path / 'other' / '.copilot/tasks.db'
        init_db(database)
        target = api.create_task(title='Bound behavior', metadata={'requiresQa': True}, db_path=database)
        assert target['id'] == task['id']
        register(target, database)
    elif mutation == 'criteria': body = body.replace('CRITERION: C1', 'CRITERION: unrelated')
    elif mutation == 'expected': body = body.replace('EXPECTED: value equals one', 'EXPECTED: unrelated behavior')
    elif mutation == 'source': (db_path.parent.parent / 'src/main.py').write_text('value = 2\n')
    elif mutation == 'new_file': (db_path.parent.parent / 'src/new.py').write_text('new behavior\n')
    elif mutation == 'deletion': (db_path.parent.parent / 'src/main.py').unlink()
    elif mutation == 'scope':
        api.update_task(task_id=task['id'], metadata={'acceptanceContract': {'schemaVersion': 2, 'criteria': [{'id': 'C1', 'expected': 'value equals one'}], 'sources': ['src/main.py']}}, db_path=db_path)
    elif mutation in ('title', 'description'): api.update_task(task_id=task['id'], **{mutation: 'Changed work'}, db_path=db_path)
    else: body = body.replace('IDENTITY: {', 'IDENTITY: invalid {')
    store(target, database, body)
    assert not api.check_task_qa(task_id=target['id'], db_path=database)['approved']
    with pytest.raises(ValidationError, match='QA gate'):
        api.update_task(task_id=target['id'], status='completed', db_path=database)
    assert api.get_task(task_id=target['id'], db_path=database)['status'] == 'pending'


def test_changed_contract_cannot_be_combined_with_completion(db_path):
    task = api.create_task(title='Original task', metadata={'requiresQa': True}, db_path=db_path)
    store(task, db_path, packet(task, db_path))
    with pytest.raises(ValidationError, match='QA gate'):
        api.update_task(task_id=task['id'], title='Different task', status='completed', db_path=db_path)
    assert api.get_task(task_id=task['id'], db_path=db_path)['title'] == 'Original task'


def test_downgrade_cannot_bypass_in_two_steps(db_path):
    task = api.create_task(title='Guarded', metadata={'requiresQa': True}, db_path=db_path)
    with pytest.raises(ValidationError, match='QA gate'):
        api.update_task(task_id=task['id'], metadata={'requiresQa': False}, db_path=db_path)
    assert json.loads(api.get_task(task_id=task['id'], db_path=db_path)['metadata'])['requiresQa']


def test_source_symlink_does_not_read_external_target(db_path, tmp_path):
    task = api.create_task(title='Guarded', metadata={'requiresQa': True}, db_path=db_path)
    register(task, db_path)
    outside = tmp_path / 'external'
    outside.write_text('private example')
    (tmp_path / 'src/link').symlink_to(outside)
    with pytest.raises(ValidationError, match='symlink'):
        api.capture_qa_identity(task_id=task['id'], db_path=db_path)


def test_cli_api_identity_and_verdict_match(db_path, cli):
    task = api.create_task(title='CLI bound', metadata={'requiresQa': True}, db_path=db_path)
    store(task, db_path, packet(task, db_path))
    identity = cli(['task', 'evidence-identity', str(task['id']), '--json'])
    assert identity.exit_code == 0, identity.output
    assert json.loads(identity.output) == api.capture_qa_identity(task_id=task['id'], db_path=db_path)
    verdict = cli(['task', 'check-qa', str(task['id']), '--json'])
    assert verdict.exit_code == 0, verdict.output
    assert json.loads(verdict.output) == api.check_task_qa(task_id=task['id'], db_path=db_path)


def test_dirty_git_tree_changes_twice_invalidate_evidence(db_path):
    import subprocess
    root = db_path.parent.parent
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    task = api.create_task(title='Dirty source', metadata={'requiresQa': True}, db_path=db_path)
    register(task, db_path)
    subprocess.run(['git', 'add', 'src'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Baseline'], cwd=root, check=True)
    target = root / 'src/main.py'
    target.write_text('value = 2\n')
    identity = api.capture_qa_identity(task_id=task['id'], db_path=db_path)['identity_line']
    body = 'CRITERION: C1\nEXPECTED: value equals one\nOBSERVED: exercised check\n' + identity + '\nBASELINE: baseline commit\nARTIFACT: test-run|assertion\nVERDICT: APPROVED\n'
    store(task, db_path, body)
    assert api.check_task_qa(task_id=task['id'], db_path=db_path)['approved']
    before = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root)
    target.write_text('value = 3\n')
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=root) == before
    with pytest.raises(ValidationError, match='QA gate'):
        api.update_task(task_id=task['id'], status='completed', db_path=db_path)


def test_unfinished_dependency_blocks_persisted_completion(db_path):
    release = api.create_task(title='Release', db_path=db_path)
    rollout = api.create_task(title='Rollout', db_path=db_path)
    api.add_dependency(task_id=rollout['id'], depends_on=release['id'], db_path=db_path)
    with pytest.raises(ValidationError, match='Incomplete task dependencies'):
        api.update_task(task_id=rollout['id'], status='completed', db_path=db_path)
    assert api.get_task(task_id=rollout['id'], db_path=db_path)['status'] == 'pending'
