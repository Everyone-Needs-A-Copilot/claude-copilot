import pytest

from tc import api
from tc.db.exceptions import ValidationError
from tc.services.qa import check_task_qa

PASS = "ARTIFACT: test-run|pytest exit=0\nVERDICT: APPROVED"


def test_completion_requires_current_task_bound_evidence(db_path):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    other = api.create_task(title="Other", db_path=db_path)
    api.store_wp(task_id=other["id"], type_="test", title="Other QA", content=PASS, db_path=db_path)
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", metadata={"qaStatus": "approved"}, db_path=db_path)
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"
    api.store_wp(task_id=task["id"], type_="test", title="QA", content=PASS, db_path=db_path)
    assert check_task_qa(task_id=task["id"], db_path=db_path)["approved"]
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"


@pytest.mark.parametrize("new_type,content", [("test", "VERDICT: REJECTED"), ("test", "VERDICT: APPROVED"), ("code", "Changed implementation")])
def test_later_rejection_missing_artifact_or_implementation_invalidates_qa(db_path, new_type, content):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old QA", content=PASS, db_path=db_path)
    api.store_wp(task_id=task["id"], type_=new_type, title="New evidence", content=content, db_path=db_path)
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", db_path=db_path)
    assert not check_task_qa(task_id=task["id"], db_path=db_path)["approved"]


def test_metadata_downgrade_cannot_bypass_completion_check(db_path):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", metadata={"requiresQa": False}, db_path=db_path)
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"


def test_ordinary_task_remains_completable(db_path):
    task = api.create_task(title="Ordinary", db_path=db_path)
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"
