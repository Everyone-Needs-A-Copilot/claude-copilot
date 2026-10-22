"""schemaVersion 3 externalSources: real SQLite databases and real temporary git repositories.

Only the argv recorder (X-7) wraps git; every other test lets git run.
"""
import hashlib
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from tc import api
from tc.db.connection import find_db_path, init_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex
from tc.services import external_sources as ext
from tc.services.qa_contract import digest, source_manifest, validate_contract

CRITERION = {"id": "X-1", "expected": "The delivered docs describe the contract"}
REMOTE = "https://example.invalid/team/ext.git"


def git(repo, *args, check=True):
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "protocol.file.allow=always", *args], cwd=repo, capture_output=True, text=True)
    if check:
        assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def make_repo(path: Path, remote=REMOTE, branch="delivery") -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", branch)
    if remote:
        git(path, "remote", "add", "origin", remote)
    (path / "docs").mkdir()
    (path / "docs/a.md").write_text("alpha\n")
    (path / "docs/b.md").write_text("beta\n")
    (path / "other").mkdir()
    (path / "other/x.txt").write_text("outside\n")
    (path / "tool.sh").write_text("#!/bin/sh\n")
    (path / "tool.sh").chmod(0o755)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "ext")


def contract_v3(paths=("docs", "tool.sh"), ref="delivery", sources=(), repo_id="ext"):
    return {"schemaVersion": 3, "criteria": [CRITERION], "sources": list(sources),
            "externalSources": [{"repo": repo_id, "ref": ref, "paths": list(paths)}]}


def new_task(db_path, repo, contract=None, register=True):
    if register:
        api.add_repo(repo_id="ext", path=repo, db_path=db_path)
    task = api.create_task(title="Cross-repo delivery", metadata={"requiresQa": True}, db_path=db_path)
    api.update_task(task_id=task["id"], metadata={"requiresQa": True, "acceptanceContract": contract or contract_v3()}, db_path=db_path)
    return task


def packet(task, db_path, identity_line=None):
    identity_line = identity_line or api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity_line"]
    return (f"CRITERION: {CRITERION['id']}\nEXPECTED: {CRITERION['expected']}\nOBSERVED: verified at the resolved commit\n"
            f"{identity_line}\nBASELINE: absent before\nARTIFACT: file-check|docs read at the commit\nUNTESTED: none\nVERDICT: APPROVED\n")


def store(task, db_path, body):
    return api.store_wp(task_id=task["id"], type_="test", title="QA", content=body, db_path=db_path)


def approved(task, db_path):
    return api.check_task_qa(task_id=task["id"], db_path=db_path)


@pytest.fixture
def delivered(db_path, repo):
    task = new_task(db_path, repo)
    store(task, db_path, packet(task, db_path))
    return task


# --- X-1, X-3, X-4: happy path --------------------------------------------------

def test_v3_task_completes_through_the_existing_gate(db_path, delivered):
    assert approved(delivered, db_path)["approved"]
    api.update_task(task_id=delivered["id"], status="completed", db_path=db_path)
    assert api.get_task(task_id=delivered["id"], db_path=db_path)["status"] == "completed"


def test_completion_refused_when_scope_changes_after_qa(db_path, delivered, repo):
    (repo / "docs/a.md").write_text("changed\n")
    git(repo, "commit", "-q", "-am", "edit")
    with pytest.raises(ValidationError):
        api.update_task(task_id=delivered["id"], status="completed", db_path=db_path)


def test_identity_block_and_receipt_shape(db_path, repo):
    task = new_task(db_path, repo)
    receipt = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    identity = receipt["identity"]
    assert identity["schemaVersion"] == 3
    expected = [{"path": "docs", "kind": "directory"},
                {"path": "docs/a.md", "kind": "file", "sha256": hashlib.sha256(b"alpha\n").hexdigest(), "executable": False},
                {"path": "docs/b.md", "kind": "file", "sha256": hashlib.sha256(b"beta\n").hexdigest(), "executable": False},
                {"path": "tool.sh", "kind": "file", "sha256": hashlib.sha256(b"#!/bin/sh\n").hexdigest(), "executable": True}]
    assert identity["external"] == [{"repo": "ext", "remote": REMOTE, "ref": "delivery",
                                     "source_sha256": digest(expected), "source_count": 4}]
    assert identity["source_count"] == 0
    commit = git(repo, "rev-parse", "delivery")
    assert receipt["external"][0]["commit"] == commit and receipt["external"][0]["path"] == str(repo.resolve())
    assert commit not in receipt["identity_line"] and str(repo.resolve()) not in receipt["identity_line"]


def test_missing_scope_is_recorded(db_path, repo):
    task = new_task(db_path, repo, contract_v3(paths=("docs", "nowhere")))
    records = ext.manifest(repo, git(repo, "rev-parse", "delivery"), ["docs", "nowhere"], ext.Budget())
    assert {"path": "nowhere", "kind": "missing"} in records
    assert approved(task, db_path)["reason"] == "No task-bound evidence"


def test_v3_may_mix_local_and_external_sources(db_path, repo):
    (db_path.parent.parent / "local.txt").write_text("local\n")
    task = new_task(db_path, repo, contract_v3(sources=("local.txt",)))
    store(task, db_path, packet(task, db_path))
    assert approved(task, db_path)["approved"]
    (db_path.parent.parent / "local.txt").write_text("changed\n")
    assert not approved(task, db_path)["approved"]


def test_v2_identity_keeps_its_shape(db_path):
    root = db_path.parent.parent
    (root / "f.txt").write_text("x\n")
    task = api.create_task(title="v2", metadata={"requiresQa": True}, db_path=db_path)
    api.update_task(task_id=task["id"], metadata={"acceptanceContract": {"schemaVersion": 2, "criteria": [CRITERION], "sources": ["f.txt"]}}, db_path=db_path)
    receipt = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    assert "external" not in receipt and "external" not in receipt["identity"]
    assert receipt["identity"]["schemaVersion"] == 2
    assert set(receipt["identity"]) == {"schemaVersion", "database", "task_id", "contract_sha256", "source_sha256", "source_count", "runtime"}


# --- X-5: stale and non-stale mutations ------------------------------------------

def _edit(repo):
    (repo / "docs/a.md").write_text("changed\n"); git(repo, "commit", "-q", "-am", "edit")

def _new_file(repo):
    (repo / "docs/c.md").write_text("new\n"); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "new")

def _delete(repo):
    git(repo, "rm", "-q", "docs/b.md"); git(repo, "commit", "-q", "-m", "rm")

def _delete_ref(repo):
    git(repo, "checkout", "-q", "-b", "scratch"); git(repo, "branch", "-q", "-D", "delivery")

def _move_ref(repo):
    git(repo, "checkout", "-q", "-b", "other"); (repo / "docs/a.md").write_text("elsewhere\n")
    git(repo, "commit", "-q", "-am", "other"); git(repo, "branch", "-q", "-f", "delivery", "other")
    git(repo, "checkout", "-q", "other")

def _origin_changed(repo):
    git(repo, "remote", "set-url", "origin", "git@example.invalid:team/ext.git")

def _exec_bit(repo):
    (repo / "tool.sh").chmod(0o644); git(repo, "update-index", "--chmod=-x", "tool.sh"); git(repo, "commit", "-q", "-m", "mode")

STALE = {"edit": _edit, "new_file": _new_file, "deletion": _delete, "ref_deleted": _delete_ref,
         "ref_moved": _move_ref, "origin_changed": _origin_changed, "exec_bit": _exec_bit}


@pytest.mark.parametrize("mutation", sorted(STALE))
def test_scoped_change_makes_evidence_stale(db_path, delivered, repo, mutation):
    STALE[mutation](repo)
    verdict = approved(delivered, db_path)
    assert not verdict["approved"]
    with pytest.raises(ValidationError):
        api.update_task(task_id=delivered["id"], status="completed", db_path=db_path)


def test_unregistered_repo_is_stale(db_path, delivered):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM source_repos"); conn.commit(); conn.close()
    assert "not registered" in approved(delivered, db_path)["reason"]


def test_changed_contract_paths_are_stale(db_path, delivered):
    api.update_task(task_id=delivered["id"], metadata={"acceptanceContract": contract_v3(paths=("docs",))}, db_path=db_path)
    assert not approved(delivered, db_path)["approved"]


def test_hand_edited_identity_is_stale(db_path, repo):
    task = new_task(db_path, repo)
    line = api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity_line"]
    forged = json.loads(line[len("IDENTITY: "):])
    forged["external"][0]["source_sha256"] = "0" * 64
    store(task, db_path, packet(task, db_path, "IDENTITY: " + json.dumps(forged, sort_keys=True, separators=(",", ":"))))
    assert not approved(task, db_path)["approved"]


def test_identity_without_external_block_is_stale(db_path, repo):
    task = new_task(db_path, repo)
    forged = api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"]
    del forged["external"]
    store(task, db_path, packet(task, db_path, "IDENTITY: " + json.dumps(forged, sort_keys=True, separators=(",", ":"))))
    assert not approved(task, db_path)["approved"]


def _unrelated(repo):
    (repo / "other/x.txt").write_text("moved on\n"); git(repo, "commit", "-q", "-am", "unrelated")

def _identical_content(repo):
    git(repo, "commit", "-q", "--amend", "-m", "squashed with a different message")

def _uncommitted(repo):
    (repo / "docs/a.md").write_text("dirty\n"); (repo / "docs/untracked.md").write_text("u\n"); (repo / "tool.sh").unlink()

NOT_STALE = {"unrelated_commit": _unrelated, "identical_content_new_commit": _identical_content, "uncommitted_edits": _uncommitted}


@pytest.mark.parametrize("mutation", sorted(NOT_STALE))
def test_out_of_scope_change_keeps_approval(db_path, delivered, repo, mutation):
    before = git(repo, "rev-parse", "delivery")
    NOT_STALE[mutation](repo)
    if mutation != "uncommitted_edits":
        assert git(repo, "rev-parse", "delivery") != before
    assert approved(delivered, db_path)["approved"]


def test_tc_never_modifies_the_external_checkout(db_path, delivered, repo):
    before = git(repo, "status", "--porcelain=v1", "-uall"), git(repo, "rev-parse", "HEAD", "delivery")
    approved(delivered, db_path)
    assert (git(repo, "status", "--porcelain=v1", "-uall"), git(repo, "rev-parse", "HEAD", "delivery")) == before


# --- X-2: validation ---------------------------------------------------------------

def _c(**over):
    entry = {"repo": "ext", "ref": "origin/main", "paths": ["docs"]}
    entry.update(over)
    return {"schemaVersion": 3, "criteria": [CRITERION], "sources": [], "externalSources": [entry]}


def test_validation_accepts_the_documented_shape():
    assert validate_contract(_c())["externalSources"][0]["repo"] == "ext"
    assert validate_contract({**_c(), "sources": ["local"], "externalSources": []})["sources"] == ["local"]


@pytest.mark.parametrize("bad", [
    {"repo": ""}, {"repo": "a b"}, {"repo": "a/b"}, {"repo": "x" * 101}, {"repo": 5},
    {"ref": "-main"}, {"ref": "/main"}, {"ref": "a..b"}, {"ref": "a@{1}"}, {"ref": "a:b"}, {"ref": "a^"},
    {"ref": "a~1"}, {"ref": "a b"}, {"ref": "a\nb"}, {"ref": "r" * 201}, {"ref": ""}, {"ref": None},
    {"paths": []}, {"paths": "docs"}, {"paths": ["/abs"]}, {"paths": ["../up"]}, {"paths": ["a/../b"]},
    {"paths": [".git/config"]}, {"paths": ["node_modules/x"]}, {"paths": ["docs/"]}, {"paths": ["a\\b"]},
    {"paths": ["docs", "docs"]}, {"paths": [""]},
])
def test_validation_rejects(bad):
    with pytest.raises(ValidationError):
        validate_contract(_c(**bad))


def test_validation_rejects_structure():
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "externalSources": [{**_c()["externalSources"][0], "extra": 1}]})
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "externalSources": [_c()["externalSources"][0]] * 2})  # duplicate repo id
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "externalSources": "ext"})
    bare = _c(); del bare["externalSources"]
    with pytest.raises(ValidationError):
        validate_contract(bare)
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "externalSources": []})  # zero scopes
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "schemaVersion": 4})
    with pytest.raises(ValidationError):  # v2 cannot smuggle external scopes
        validate_contract({**_c(), "schemaVersion": 2, "sources": ["x"]})
    with pytest.raises(ValidationError):  # v2 still requires local sources
        validate_contract({"schemaVersion": 2, "criteria": [CRITERION], "sources": []})


def test_scope_count_bounds():
    ok = _c(paths=[f"p{i}" for i in range(100)])
    assert validate_contract(ok)
    with pytest.raises(ValidationError):
        validate_contract(_c(paths=[f"p{i}" for i in range(101)]))
    with pytest.raises(ValidationError):  # local plus external together
        validate_contract({**_c(paths=[f"p{i}" for i in range(100)]), "sources": ["one-more"]})
    with pytest.raises(ValidationError):
        validate_contract({**_c(), "sources": [f"s{i}" for i in range(101)]})


# --- X-3: registry -----------------------------------------------------------------

def test_repo_add_and_list_via_cli(cli, tmp_path):
    repo = make_repo(tmp_path / "ext")
    added = cli(["repo", "add", "ext", "--path", str(repo), "--json"])
    assert added.exit_code == 0, added.output
    row = json.loads(added.output)
    assert row["id"] == "ext" and row["path"] == str(repo.resolve()) and row["remote"] == REMOTE
    listed = json.loads(cli(["repo", "list", "--json"]).output)
    assert [r["id"] for r in listed] == ["ext"] and listed[0]["path"] == str(repo.resolve())
    assert "ext" in cli(["repo", "list"]).output


def test_repo_list_is_empty_before_any_registration(db_path):
    assert api.list_repos(db_path=db_path) == []


def test_repo_add_refuses_unsuitable_directories(db_path, tmp_path):
    plain = tmp_path / "plain"; plain.mkdir()
    repo = make_repo(tmp_path / "ext")
    no_origin = make_repo(tmp_path / "noorigin", remote=None)
    link = tmp_path / "link"; link.symlink_to(repo)
    for target in (plain, repo / "docs", no_origin, link, tmp_path / "absent"):
        with pytest.raises(ValidationError):
            api.add_repo(repo_id="ext", path=target, db_path=db_path)
    with pytest.raises(ValidationError):
        api.add_repo(repo_id="bad id", path=repo, db_path=db_path)
    assert api.list_repos(db_path=db_path) == []


def test_repo_add_cli_reports_refusal(cli, tmp_path):
    plain = tmp_path / "plain"; plain.mkdir()
    assert cli(["repo", "add", "ext", "--path", str(plain)]).exit_code != 0


def test_repoint_only_with_unchanged_remote(db_path, tmp_path, repo):
    api.add_repo(repo_id="ext", path=repo, db_path=db_path)
    first = api.list_repos(db_path=db_path)[0]
    moved = make_repo(tmp_path / "moved")
    again = api.add_repo(repo_id="ext", path=moved, db_path=db_path)
    assert again["path"] == str(moved.resolve()) and again["registered_at"] == first["registered_at"]
    stranger = make_repo(tmp_path / "stranger", remote="https://example.invalid/other/repo.git")
    with pytest.raises(ValidationError):
        api.add_repo(repo_id="ext", path=stranger, db_path=db_path)
    assert api.list_repos(db_path=db_path)[0]["path"] == str(moved.resolve())


def test_moving_a_checkout_does_not_change_the_contract_or_identity_scope(db_path, repo, tmp_path):
    task = new_task(db_path, repo)
    before = api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"]["external"]
    moved = tmp_path / "relocated"
    repo.rename(moved)
    api.add_repo(repo_id="ext", path=moved, db_path=db_path)
    assert api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"]["external"] == before


def test_repointing_the_registered_path_at_a_stranger_is_caught_by_the_remote_check(db_path, delivered, repo, tmp_path):
    import sqlite3
    stranger = make_repo(tmp_path / "stranger", remote="https://example.invalid/other/repo.git")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE source_repos SET path=?", (str(stranger.resolve()),)); conn.commit(); conn.close()
    assert "origin changed" in approved(delivered, db_path)["reason"]


# --- X-6: fail closed ----------------------------------------------------------------

def test_symlink_in_scope_fails_closed(db_path, repo):
    (repo / "docs/link").symlink_to("a.md")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "link")
    task = new_task(db_path, repo)
    with pytest.raises(ValidationError, match="symlink or submodule"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_symlink_outside_scope_is_ignored(db_path, repo):
    (repo / "other/link").symlink_to("x.txt")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "link")
    task = new_task(db_path, repo)
    assert api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"]["external"]


def test_submodule_in_scope_fails_closed(db_path, repo):
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{git(repo, 'rev-parse', 'HEAD')},docs/sub")
    git(repo, "commit", "-q", "-m", "submodule")
    task = new_task(db_path, repo)
    with pytest.raises(ValidationError, match="symlink or submodule"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_oversized_blob_fails_closed(db_path, repo):
    (repo / "docs/big.bin").write_bytes(b"\0" * (20 * 1024 * 1024 + 1))
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "big")
    task = new_task(db_path, repo)
    with pytest.raises(ValidationError, match="oversized"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_file_count_cap_fails_closed(db_path, repo, monkeypatch):
    monkeypatch.setattr(ext, "MAX_FILES", 3)
    task = new_task(db_path, repo)
    with pytest.raises(ValidationError, match="inventory exceeds"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_byte_cap_fails_closed(db_path, repo, monkeypatch):
    monkeypatch.setattr(ext, "MAX_BYTES", 8)
    task = new_task(db_path, repo)
    with pytest.raises(ValidationError, match="bytes exceed"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_caps_are_shared_with_local_sources(db_path, repo, monkeypatch):
    (db_path.parent.parent / "l1.txt").write_text("1\n"); (db_path.parent.parent / "l2.txt").write_text("2\n")
    task = new_task(db_path, repo, contract_v3(sources=("l1.txt", "l2.txt")))
    monkeypatch.setattr(ext, "MAX_FILES", 5)  # 2 local + 4 external records
    with pytest.raises(ValidationError, match="inventory exceeds"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_empty_external_scope_fails_closed(db_path, repo):
    task = new_task(db_path, repo, contract_v3(paths=("nowhere",)))
    with pytest.raises(ValidationError, match="no materialized files"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_unresolvable_ref_and_git_failure_fail_closed(db_path, repo, monkeypatch):
    task = new_task(db_path, repo, contract_v3(ref="nonexistent"))
    with pytest.raises(ValidationError, match="does not resolve"):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    task = new_task(db_path, repo)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ValidationError):
        api.capture_qa_identity(task_id=task["id"], db_path=db_path)


def test_special_characters_in_paths_are_literal(db_path, repo):
    (repo / "docs/a[1].md").write_text("bracket\n"); (repo / "docs/sp ace.md").write_text("space\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "names")
    records = ext.manifest(repo, git(repo, "rev-parse", "delivery"), ["docs/a[1].md", "docs/sp ace.md"], ext.Budget())
    assert [r["path"] for r in records] == ["docs/a[1].md", "docs/sp ace.md"]
    with pytest.raises(ValidationError, match="no materialized files"):  # a glob is a literal name, never a pattern
        ext.manifest(repo, git(repo, "rev-parse", "delivery"), ["docs/*"], ext.Budget())


def test_dot_scope_covers_the_tree_but_not_ignored_directories(db_path, repo):
    (repo / "node_modules").mkdir(); (repo / "node_modules/dep.js").write_text("x\n")
    git(repo, "add", "-f", "-A"); git(repo, "commit", "-q", "-m", "dep")
    records = ext.manifest(repo, git(repo, "rev-parse", "delivery"), ["."], ext.Budget())
    names = {r["path"] for r in records}
    assert {"docs/a.md", "other/x.txt", "tool.sh", "."} <= names and not any("node_modules" in n for n in names)


# --- X-7: offline and read-only ------------------------------------------------------

def test_only_local_git_plumbing_runs(db_path, delivered, repo, monkeypatch):
    seen = []
    real = subprocess.run

    def record(argv, *a, **k):
        if Path(k["cwd"]).resolve() == repo.resolve():  # tc's own database housekeeping runs elsewhere
            seen.append(list(argv))
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", record)
    api.capture_qa_identity(task_id=delivered["id"], db_path=db_path)
    approved(delivered, db_path)
    api.add_repo(repo_id="ext", path=repo, db_path=db_path)
    api.update_task(task_id=delivered["id"], status="completed", db_path=db_path)

    def subcommand(argv):
        rest = argv[1:]
        i = 0
        while rest[i].startswith("-") or rest[i - 1] == "-c":
            i += 1
        return rest[i]

    assert seen and {a[0] for a in seen} == {"git"}
    assert {subcommand(a) for a in seen} == {"rev-parse", "ls-tree", "cat-file", "remote"}
    assert all("core.fsmonitor=false" in a for a in seen)
    assert not {"fetch", "pull", "clone", "ls-remote", "push", "checkout", "gc"} & {x for a in seen for x in a}


def test_ambient_git_environment_cannot_redirect_the_read(db_path, delivered, tmp_path, monkeypatch):
    other = make_repo(tmp_path / "decoy")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert approved(delivered, db_path)["approved"]


def test_single_completion_authority():
    src = Path(ext.__file__).read_text()
    cmd = (Path(ext.__file__).parents[1] / "commands/repo.py").read_text()
    for text in (src, cmd):
        assert "check_task_qa" not in text and "UPDATE tasks" not in text and "'completed'" not in text and '"completed"' not in text


# --- X-8: execution limits -------------------------------------------------------------

def _limits(db_path, task):
    return ex.register_limits(task_id=task["id"], db_path=db_path, timeout_seconds=30)


def test_execution_digest_sees_external_in_scope_changes(db_path, repo):
    task = new_task(db_path, repo)
    policy = _limits(db_path, task)
    assert policy["externalSources"] == contract_v3()["externalSources"] and policy["database"] == str(db_path.resolve())
    base = ex._source(policy)
    _unrelated(repo)
    assert ex._source(policy) == base
    _edit(repo)
    assert ex._source(policy) != base
    assert ex.execution_status(task_id=task["id"], db_path=db_path)


def test_execution_scope_freezes_external_sources(db_path, repo):
    task = new_task(db_path, repo)
    _limits(db_path, task)
    with pytest.raises(ValidationError):
        api.update_task(task_id=task["id"], metadata={"acceptanceContract": contract_v3(paths=("docs",))}, db_path=db_path)


def test_v2_policy_and_digest_are_unchanged(db_path):
    root = db_path.parent.parent
    (root / "code.py").write_text("x = 1\n")
    contract = {"schemaVersion": 2, "criteria": [CRITERION], "sources": ["code.py"]}
    task = api.create_task(title="v2", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    policy = _limits(db_path, task)
    assert "externalSources" not in policy and "database" not in policy
    assert ex._source(policy) == digest(source_manifest(root, ["code.py"]))


# --- X-9: older tc and provenance -------------------------------------------------------

def test_tc_2_7_1_rejects_schema_version_3():
    module = types.ModuleType("tc_2_7_1_qa_contract")
    source = (Path(__file__).parent / "data/tc_2_7_1_qa_contract.py.txt").read_text()
    exec(compile(source, "tc_2_7_1_qa_contract.py", "exec"), module.__dict__)
    assert module.validate_contract({"schemaVersion": 2, "criteria": [CRITERION], "sources": ["x"]})
    with pytest.raises(ValidationError, match="schemaVersion 2"):
        module.validate_contract(contract_v3())


def test_receipt_capabilities_name_external_sources():
    from tc import provenance
    assert provenance._capabilities() == ["check-qa", "contract", "evidence-identity", "external-sources"]


# --- X-10: worktree-local parent database -----------------------------------------------

def _flow(db_path, repo):
    task = new_task(db_path, repo)
    store(task, db_path, packet(task, db_path))
    assert approved(task, db_path)["approved"]
    api.update_task(task_id=task["id"], status="completed", db_path=db_path)
    return api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"]["external"]


def test_worktree_local_database_behaves_like_the_main_checkout(tmp_path, repo, monkeypatch):
    main = tmp_path / "proj"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "f.txt").write_text("f\n")
    git(main, "add", "-A"); git(main, "commit", "-q", "-m", "init")
    main_db = main / ".copilot/tasks.db"
    init_db(main_db)
    wt = tmp_path / "linked"
    git(main, "worktree", "add", "-q", "-b", "feature", str(wt))
    init_db(wt / ".copilot/tasks.db")
    monkeypatch.chdir(wt)
    monkeypatch.delenv("TC_WORKTREE_DB", raising=False)
    assert find_db_path().resolve() == main_db.resolve()  # default: shared main database
    monkeypatch.setenv("TC_WORKTREE_DB", "local")
    local_db = find_db_path()
    assert local_db.resolve() == (wt / ".copilot/tasks.db").resolve()
    from_main = _flow(main_db, repo)
    from_worktree = _flow(local_db, repo)
    assert from_worktree == from_main


# --- CLI and API agree -------------------------------------------------------------------

def test_cli_and_api_identity_agree(cli, db_path, repo, tmp_path):
    task = new_task(db_path, repo)
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(contract_v3()))
    assert cli(["task", "contract", str(task["id"]), "--file", str(contract_file)]).exit_code == 0
    via_cli = json.loads(cli(["task", "evidence-identity", str(task["id"]), "--json"]).output)
    via_api = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    assert via_cli["identity"] == via_api["identity"] and via_cli["external"] == via_api["external"]
    line = cli(["task", "evidence-identity", str(task["id"])]).output.strip()
    assert line == via_api["identity_line"]
    checked = cli(["task", "check-qa", str(task["id"])])
    assert checked.exit_code != 0 or "No task-bound evidence" in checked.output


def test_cli_rejects_invalid_v3_contract(cli, db_path, repo, tmp_path):
    task = new_task(db_path, repo)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_c(ref="a..b")))
    assert cli(["task", "contract", str(task["id"]), "--file", str(bad)]).exit_code != 0
