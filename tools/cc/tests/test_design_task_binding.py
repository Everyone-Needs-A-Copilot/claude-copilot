"""Design criteria must match the named project's actual task contract."""
import pytest
from tc import api
from tc.db.connection import init_db
from cc.core.design.contracts import task_binding


def test_design_task_binding_checks_criteria_and_source_scope(tmp_path):
    database = init_db(tmp_path / '.copilot/tasks.db')
    task = api.create_task(title='Surface', db_path=database)
    criteria = [{'id': 'C1', 'expected': 'Button works'}]
    api.update_task(task_id=task['id'], metadata={'acceptanceContract': {'schemaVersion': 2, 'criteria': criteria, 'sources': ['design', 'ui']}}, db_path=database)
    contract = {'task_id': task['id'], 'criteria': criteria, 'targets': ['ui/page.html'], 'authority': {'product': ['design/SOUL.md'], 'design': ['design/system.md']}}
    bound = task_binding(contract, tmp_path)
    assert bound['task_id'] == task['id']
    with pytest.raises(ValueError, match='criteria differ'):
        task_binding({**contract, 'criteria': [{'id': 'C1', 'expected': 'Different behavior'}]}, tmp_path)
    with pytest.raises(ValueError, match='source scope'):
        task_binding({**contract, 'targets': ['outside/page.html']}, tmp_path)
    api.update_task(task_id=task['id'], description='Changed task', db_path=database)
    assert task_binding(contract, tmp_path) != bound


def test_design_missing_database_never_invents_task_membership(tmp_path):
    with pytest.raises(ValueError, match='database'):
        task_binding({'task_id': 1}, tmp_path)
