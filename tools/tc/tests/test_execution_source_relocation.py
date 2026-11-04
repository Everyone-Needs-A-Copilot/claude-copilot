"""Safe local-worktree -> committed external-source relocation, real Git/SQLite."""
import copy
import json

import pytest

from tc import api
from tc.db.connection import get_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex
from tc.services.qa_contract import digest
from .test_qa_external_sources import make_repo, git


@pytest.fixture
def relocation(db_path):
    root = db_path.parent.parent
    repository = make_repo(root / "repository")
    authoring = root / "authoring"
    git(repository, "worktree", "add", "-b", "authoring", str(authoring), "delivery")
    api.add_repo(repo_id="delivered", path=repository, db_path=db_path)
    original = {"schemaVersion": 2, "sources": ["authoring/docs"], "criteria": [{"id": "DELIVERY", "expected": "Deliver the documented behavior."}]}
    task = api.create_task(title="Retire authoring checkout safely", metadata={"requiresQa": True, "acceptanceContract": original}, db_path=db_path)
    ex.register_limits(task_id=task["id"], timeout_seconds=30, db_path=db_path)
    proposal = {**copy.deepcopy(original), "schemaVersion": 3, "sources": [], "externalSources": [{"repo": "delivered", "ref": git(repository, "rev-parse", "HEAD"), "paths": ["docs"]}]}
    return {"task": task["id"], "root": root, "repo": repository, "authoring": authoring, "original": original, "proposal": proposal}


def amend(db_path, fixture, proposal=None):
    return ex.amend_contract(task_id=fixture["task"], contract=proposal or fixture["proposal"], expected_contract_sha256=digest(fixture["original"]), decision="Owner-approved relocation preserves same repository/path coverage before retiring the merged worktree.", db_path=db_path)


def snapshot(db_path):
    with get_db(db_path) as conn:
        names = ["tasks", "execution_limits", "execution_rounds", "execution_attempts", "execution_budgets", "execution_checkpoints", "work_products"]
        return {name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name} ORDER BY 1")] for name in names}


def test_equivalent_committed_relocation_preserves_attempts_budgets_and_audit(db_path, relocation):
    token = ex.begin_attempt(task_id=relocation["task"], criterion="DELIVERY", label="retained observation", db_path=db_path)
    evidence = relocation["root"] / "failure.txt"; evidence.write_text("Original failure retained\n")
    ex.settle_attempt(token=token["token"], succeeded=False, artifact=evidence, db_path=db_path)
    before = snapshot(db_path)
    status = ex.execution_status(task_id=relocation["task"], db_path=db_path)
    result = amend(db_path, relocation)
    after = snapshot(db_path)
    for table in before.keys() - {"tasks", "execution_rounds"}:
        assert after[table] == before[table]
    assert ex.execution_status(task_id=relocation["task"], db_path=db_path)["usage"] == status["usage"]
    proof = result["amendment"]["source_relocations"][0]
    assert proof["local_source"] == "authoring/docs"
    assert proof["repository_scope"] == "docs"
    assert proof["external_repo"] == "delivered"
    assert proof["coverage_path"] == "docs"
    assert proof["commit"] == git(relocation["repo"], "rev-parse", "HEAD")
    assert proof["common_dir"] == str((relocation["repo"] / ".git").resolve())
    assert result["amendment"]["before_contract"]["criteria"] == result["amendment"]["after_contract"]["criteria"]
    assert relocation["authoring"].exists() and evidence.exists()


@pytest.mark.parametrize("case", ["unrelated", "same_origin_clone", "narrower", "bad_ref", "escaping_alias", "in_root_alias", "changed_origin", "missing_local"])
def test_source_relocation_refusals_leave_registered_history_unchanged(db_path, relocation, case):
    proposal = copy.deepcopy(relocation["proposal"])
    if case in {"unrelated", "same_origin_clone"}:
        remote = "https://example.invalid/unrelated/repo.git" if case == "unrelated" else "https://example.invalid/team/ext.git"
        other = make_repo(relocation["root"] / "other-repo", remote=remote)
        api.add_repo(repo_id="other", path=other, db_path=db_path)
        proposal["externalSources"] = [{"repo": "other", "ref": "delivery", "paths": ["docs"]}]
    elif case == "narrower":
        proposal["externalSources"][0]["paths"] = ["docs/a.md"]
    elif case == "bad_ref":
        proposal["externalSources"][0]["ref"] = "does-not-exist"
    elif case in {"escaping_alias", "in_root_alias"}:
        # Preserve the real checkout, then introduce locator drift after its
        # valid registration. This exercises relocation's refusal, not an
        # invalid initial source fixture.
        preserved = relocation["root"] / "preserved-authoring"
        relocation["authoring"].rename(preserved)
        target = preserved if case == "in_root_alias" else relocation["root"].parent
        relocation["authoring"].symlink_to(target, target_is_directory=True)
    elif case == "changed_origin":
        git(relocation["repo"], "remote", "set-url", "origin", "https://example.invalid/changed.git")
    elif case == "missing_local":
        # Move preserves original data and invalidates the registered locator.
        relocation["authoring"].rename(relocation["root"] / "preserved-authoring")
    before = snapshot(db_path)
    with pytest.raises(ValidationError):
        amend(db_path, relocation, proposal)
    assert snapshot(db_path) == before


def test_retained_local_scope_and_broader_same_repo_external_scope_can_coexist(db_path, relocation):
    original = {**relocation["original"], "sources": ["authoring/docs/a.md", "authoring/tool.sh"]}
    task = api.create_task(title="Mixed source relocation", metadata={"acceptanceContract": original}, db_path=db_path)
    ex.register_limits(task_id=task["id"], db_path=db_path)
    fixture = {**relocation, "task": task["id"], "original": original}
    proposal = {**relocation["proposal"], "sources": ["authoring/tool.sh"]}
    result = amend(db_path, fixture, proposal)
    proof = result["amendment"]["source_relocations"][0]
    assert proof["repository_scope"] == "docs/a.md"
    assert proof["coverage_path"] == "docs"


def test_broad_external_path_cannot_hide_missing_committed_local_file(db_path, relocation):
    original = {**relocation["original"], "sources": ["authoring/docs/a.md"]}
    task = api.create_task(title="Preserve exact file coverage", metadata={"acceptanceContract": original}, db_path=db_path)
    ex.register_limits(task_id=task["id"], db_path=db_path)
    fixture = {**relocation, "task": task["id"], "original": original}
    # Preserve content under another path, but remove its former path from the
    # candidate commit. Broad docs coverage must not silently substitute it.
    (relocation["repo"] / "docs/a.md").rename(relocation["repo"] / "preserved-a.md")
    git(relocation["repo"], "add", "-A")
    git(relocation["repo"], "commit", "-m", "synthetic path relocation")
    proposal = copy.deepcopy(relocation["proposal"])
    proposal["externalSources"][0]["ref"] = git(relocation["repo"], "rev-parse", "HEAD")
    before = snapshot(db_path)
    with pytest.raises(ValidationError, match="narrow"):
        amend(db_path, fixture, proposal)
    assert snapshot(db_path) == before
