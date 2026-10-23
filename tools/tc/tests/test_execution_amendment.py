"""Owner-authorized amendment tests: actual SQLite, CLI and Git boundaries."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from tc import api
from tc.db.connection import get_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex
from tc.services.qa_contract import digest
from test_qa_external_sources import make_repo, git


@pytest.fixture
def scope(db_path):
    root = db_path.parent.parent
    (root / 'code.py').write_text('value = 1\n')
    contract = {'schemaVersion': 2, 'sources': ['code.py'],
                'criteria': [{'id': 'DELIVERY', 'expected': 'Install version one.'}]}
    task = api.create_task(title='Amend safely', metadata={
        'requiresQa': True, 'ownerNote': 'retain', 'acceptanceContract': contract}, db_path=db_path)
    ex.register_limits(task_id=task['id'], timeout_seconds=30, db_path=db_path)
    return task['id'], root, contract


def amended(contract):
    result = copy.deepcopy(contract)
    result['criteria'][0]['expected'] = 'Install version two.'
    return result


def apply(db_path, scope, **kwargs):
    task, _, contract = scope
    args = dict(task_id=task, contract=amended(contract),
                expected_contract_sha256=digest(contract), decision='  Approved exact correction.  ', db_path=db_path)
    args.update(kwargs)
    return api.amend_contract(**args)


def dump(db_path):
    with get_db(db_path) as conn:
        tables = ['tasks', 'execution_limits', 'execution_rounds', 'execution_attempts',
                  'execution_checkpoints', 'execution_budgets', 'work_products', 'task_dependencies']
        return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM {name} ORDER BY 1')]
                for name in tables}


def attempt(db_path, scope, success=False):
    task, root, _ = scope
    reservation = ex.begin_attempt(task_id=task, criterion='DELIVERY', label='observed', db_path=db_path)
    artifact = root / (reservation['token'] + '.txt')
    artifact.write_text('same observed failure\n')
    return ex.settle_attempt(token=reservation['token'], succeeded=success, artifact=artifact, db_path=db_path)


def test_atomic_audit_preserves_history_limits_and_failure_stop(db_path, scope):
    attempt(db_path, scope)
    attempt(db_path, scope)
    before = dump(db_path)
    status_before = ex.execution_status(task_id=scope[0], db_path=db_path)
    result = apply(db_path, scope)
    after = dump(db_path)
    for name in before.keys() - {'tasks', 'execution_rounds'}:
        assert after[name] == before[name]
    task = api.get_task(task_id=scope[0], db_path=db_path)
    metadata = json.loads(task['metadata']) if isinstance(task['metadata'], str) else task['metadata']
    assert metadata == {'requiresQa': True, 'ownerNote': 'retain', 'acceptanceContract': amended(scope[2])}
    status_after = ex.execution_status(task_id=scope[0], db_path=db_path)
    assert status_after['usage'] == status_before['usage']
    changed = {'contract_sha256', 'kind', 'predecessor', 'amendment', 'authority', 'new_authority', 'round'}
    assert {k:v for k,v in status_before['limits'].items() if k not in changed} == {
        k:v for k,v in status_after['limits'].items() if k not in changed}
    audit = result['amendment']
    assert audit['decision'] == '  Approved exact correction.  '
    assert audit['before_contract'] == scope[2]
    assert audit['after_contract'] == amended(scope[2])
    assert audit['before_contract_sha256'] == digest(scope[2])
    assert audit['after_contract_sha256'] == digest(amended(scope[2]))
    assert audit['before_source'] == audit['after_source']
    assert result['round'] == 2
    with pytest.raises(ValidationError, match='Two failed attempts'):
        ex.begin_attempt(task_id=scope[0], criterion='DELIVERY', label='retry', db_path=db_path)
    with pytest.raises(ValidationError, match='frozen'):
        api.update_task(task_id=scope[0], metadata={'acceptanceContract': scope[2]}, db_path=db_path)


@pytest.mark.parametrize('case', ['decision', 'hash', 'stale', 'noop', 'invalid', 'ids', 'narrow', 'missing', 'running', 'cancelled'])
def test_refusal_has_no_mutations(db_path, scope, case):
    args = {}
    if case == 'decision': args['decision'] = ' '
    elif case == 'hash': args['expected_contract_sha256'] = 'bad'
    elif case == 'stale': args['expected_contract_sha256'] = '0' * 64
    elif case == 'noop': args['contract'] = scope[2]
    elif case == 'invalid': args['contract'] = {'schemaVersion': 99}
    elif case == 'ids':
        args['contract'] = amended(scope[2]); args['contract']['criteria'][0]['id'] = 'EASIER'
    elif case in ('narrow', 'missing'):
        (scope[1] / 'other.py').write_text('x\n')
        args['contract'] = amended(scope[2])
        args['contract']['sources'] = ['other.py'] if case == 'narrow' else ['code.py', 'missing.py']
    elif case == 'running':
        ex.begin_attempt(task_id=scope[0], criterion='DELIVERY', label='active', db_path=db_path)
    elif case == 'cancelled':
        api.update_task(task_id=scope[0], status='cancelled', db_path=db_path)
    before = dump(db_path)
    with pytest.raises(ValidationError): apply(db_path, scope, **args)
    assert dump(db_path) == before


def test_second_write_failure_rolls_back_both_mutations(db_path, scope):
    with get_db(db_path) as conn:
        conn.execute("CREATE TRIGGER fail_amend BEFORE UPDATE OF metadata ON tasks BEGIN SELECT RAISE(ABORT, 'injected second-write failure'); END")
    before = dump(db_path)
    with pytest.raises(sqlite3.IntegrityError, match='injected'): apply(db_path, scope)
    assert dump(db_path) == before


def test_competing_writers_only_one_commits(db_path, scope):
    def writer(_):
        try: return apply(db_path, scope)['round']
        except ValidationError as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, range(2)))
    assert results.count(2) == 1
    assert sum('changed since review' in str(r) for r in results) == 1
    assert len(dump(db_path)['execution_rounds']) == 1


def test_cli_chain_and_reopen_preserve_audits(db_path, scope, cli):
    path = scope[1] / 'contract.json'
    path.write_text(json.dumps(amended(scope[2])))
    result = cli(['execution', 'amend', str(scope[0]), '--file', str(path),
                  '--expected-contract-sha256', digest(scope[2]), '--decision', 'Approved CLI correction'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['round'] == 2
    second = amended(scope[2]); second['criteria'][0]['expected'] = 'Install version three.'
    apply(db_path, scope, contract=second, expected_contract_sha256=digest(amended(scope[2])))
    ex.reopen_ceiling(task_id=scope[0], decision='Owner raised ceiling', db_path=db_path)
    status = ex.execution_status(task_id=scope[0], db_path=db_path)
    history = status['lineage']
    assert [r['kind'] for r in history] == ['registration', 'amendment', 'amendment', 'reopen']
    assert history[2]['predecessor'] == 2
    assert history[2]['amendment']['before_contract'] == amended(scope[2])


def qa_packet(db_path, scope):
    identity = api.capture_qa_identity(task_id=scope[0], db_path=db_path)['identity_line']
    body = ('CRITERION: DELIVERY\nEXPECTED: Install version one.\nOBSERVED: delivered\n' + identity +
            '\nBASELINE: old failure\nARTIFACT: test-run|fixture exit=0\nUNTESTED: none\nVERDICT: APPROVED\n')
    api.store_wp(task_id=scope[0], type_='test', title='Historical QA', content=body, db_path=db_path)
    assert api.check_task_qa(task_id=scope[0], db_path=db_path)['approved']


def test_old_qa_becomes_stale_without_rewriting_evidence(db_path, scope):
    qa_packet(db_path, scope)
    before = dump(db_path)['work_products']
    apply(db_path, scope)
    assert not api.check_task_qa(task_id=scope[0], db_path=db_path)['approved']
    assert dump(db_path)['work_products'] == before


def test_completed_approved_task_cannot_be_amended(db_path, scope):
    qa_packet(db_path, scope)
    api.update_task(task_id=scope[0], status='completed', db_path=db_path)
    before = dump(db_path)
    with pytest.raises(ValidationError, match='completed'): apply(db_path, scope)
    assert dump(db_path) == before


def test_external_pin_correction_preserves_failure_guard(db_path, tmp_path):
    repo = make_repo(tmp_path / 'external')
    git(repo, 'tag', 'v1'); git(repo, 'tag', 'v2')
    api.add_repo(repo_id='ext', path=repo, db_path=db_path)
    contract = {'schemaVersion': 3, 'sources': [], 'criteria': [{'id': 'DELIVERY', 'expected': 'Install version one.'}],
                'externalSources': [{'repo': 'ext', 'ref': 'v1', 'paths': ['docs']}]}
    task = api.create_task(title='External correction', metadata={'requiresQa': True, 'acceptanceContract': contract}, db_path=db_path)
    ex.register_limits(task_id=task['id'], db_path=db_path)
    scope = task['id'], db_path.parent.parent, contract
    attempt(db_path, scope); attempt(db_path, scope)
    new = amended(contract); new['externalSources'][0]['ref'] = 'v2'
    result = apply(db_path, scope, contract=new)
    assert result['amendment']['before_source'] != result['amendment']['after_source']
    with pytest.raises(ValidationError, match='Two failed attempts'):
        ex.begin_attempt(task_id=task['id'], criterion='DELIVERY', label='retry', db_path=db_path)


def test_no_progress_and_runtime_ceiling_survive(db_path, scope):
    for _ in range(2): attempt(db_path, scope, success=True)
    before = ex.execution_status(task_id=scope[0], db_path=db_path)
    apply(db_path, scope)
    after = ex.execution_status(task_id=scope[0], db_path=db_path)
    assert after['progress'] == before['progress']
    assert after['remaining'] == before['remaining']
    # Simulate recorded long runtime without sleeping; amendment cannot rewrite it.
    with get_db(db_path) as conn:
        conn.execute('UPDATE execution_attempts SET ended=started+22000 WHERE task_id=?', (scope[0],))
    newer = amended(scope[2]); newer['criteria'][0]['expected'] = 'Install version three.'
    apply(db_path, scope, contract=newer, expected_contract_sha256=digest(amended(scope[2])))
    with pytest.raises(ValidationError, match='ceiling'):
        ex.begin_attempt(task_id=scope[0], criterion='DELIVERY', label='over ceiling', db_path=db_path)


def test_legacy_policy_caps_preserved(db_path):
    root = db_path.parent.parent
    (root / 'code.py').write_text('value=1\n')
    contract = {'schemaVersion': 2, 'sources': ['code.py'],
                'criteria': [{'id': 'DELIVERY', 'expected': 'Install version one.'}]}
    task = api.create_task(title='Legacy', metadata={'acceptanceContract': contract}, db_path=db_path)
    ex.register_limits(task_id=task['id'], attempts=5, calls=10, cost_usd=2,
                       authority=['owner: legacy cap'], db_path=db_path)
    scope = task['id'], root, contract
    before = ex.execution_status(task_id=task['id'], db_path=db_path)
    apply(db_path, scope)
    after = ex.execution_status(task_id=task['id'], db_path=db_path)
    assert after['remaining'] == before['remaining']
    assert 'policy_version' not in after['limits']
