"""Real linked-worktree regressions; preserves old source evidence and budgets."""
import json
import subprocess

import pytest
from tc import api
from tc.db.exceptions import ValidationError
from tc.services import execution as ex


def setup_repo(db_path, tmp_path):
    root=db_path.parent.parent
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)
    git('init', '-q')
    (root/'code.py').write_text('value = 1\n')
    git('add', 'code.py')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','baseline')
    linked=root.parent/(root.name+'-linked')
    git('worktree','add','--detach',str(linked),'HEAD')
    task=api.create_task(title='Linked evidence',metadata={'requiresQa':True,'acceptanceContract':{'schemaVersion':2,'criteria':[{'id':'C1','expected':'Usable result'}],'sources':['code.py']}},db_path=db_path)
    return task,root,linked


def test_linked_source_is_bound_and_rechecked(db_path,tmp_path):
    task,root,linked=setup_repo(db_path,tmp_path)
    (linked/'code.py').write_text('value = 2\n')
    before=api.capture_qa_identity(task_id=task['id'],db_path=db_path)
    identity=api.capture_qa_identity(task_id=task['id'],root=linked,db_path=db_path)
    assert before['identity']['source_sha256'] != identity['identity']['source_sha256']
    assert identity['identity']['source_root']==str(linked.resolve())
    body='CRITERION: C1\nEXPECTED: Usable result\nOBSERVED: local verification passed\n'+identity['identity_line']+'\nBASELINE: different linked source\nARTIFACT: test-run|local\nVERDICT: APPROVED\n'
    api.store_wp(task_id=task['id'],type_='test',title='Linked QA',content=body,db_path=db_path)
    assert api.check_task_qa(task_id=task['id'],db_path=db_path)['approved']
    (linked/'code.py').write_text('value = 3\n')
    assert not api.check_task_qa(task_id=task['id'],db_path=db_path)['approved']
    with pytest.raises(ValidationError):
        api.capture_qa_identity(task_id=task['id'],root=tmp_path/'unrelated',db_path=db_path)


def test_successor_changes_root_without_resetting_history(db_path,tmp_path):
    task,root,linked=setup_repo(db_path,tmp_path)
    ex.register_limits(task_id=task['id'],attempts=2,calls=3,cost_usd=1,authority=['initial'],db_path=db_path)
    attempt=ex.begin_attempt(task_id=task['id'],criterion='C1',label='original',reserve_calls=1,reserve_usd=.1,db_path=db_path)
    log=root/'original.log'; log.write_text('failed output')
    ex.settle_attempt(token=attempt['token'],succeeded=False,artifact=log,calls=1,cost_usd=.1,db_path=db_path)
    old=ex.execution_status(task_id=task['id'],db_path=db_path)
    successor=ex.succeed_limits(task_id=task['id'],attempts=2,calls=3,cost_usd=1,root=linked,authority=['explicit root correction'],db_path=db_path)
    new=ex.execution_status(task_id=task['id'],db_path=db_path)
    assert successor['root']==str(linked.resolve())
    assert new['usage']==old['usage']
    assert new['usage']['attempts']==1 and new['usage']['calls']==1
    assert new['limits']['contract_sha256']==old['limits']['contract_sha256']
    with pytest.raises(ValidationError):
        ex.succeed_limits(task_id=task['id'],attempts=2,calls=3,cost_usd=1,root=tmp_path/'unrelated',authority=['bad root'],db_path=db_path)


def test_registered_execution_root_is_default_qa_root(db_path,tmp_path):
    task,root,linked=setup_repo(db_path,tmp_path)
    (linked/'code.py').write_text('value = 5\n')
    ex.register_limits(task_id=task['id'],attempts=2,calls=0,cost_usd=0,root=linked,authority=['owner registered checkout'],db_path=db_path)
    receipt=api.capture_qa_identity(task_id=task['id'],db_path=db_path)
    assert receipt['identity']['source_root']==str(linked.resolve())
    assert receipt==api.capture_qa_identity(task_id=task['id'],root=linked,db_path=db_path)
