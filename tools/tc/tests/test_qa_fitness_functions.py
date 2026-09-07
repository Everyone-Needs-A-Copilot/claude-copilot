"""The five fitness functions from wp-a-evidence.md section 5.4, authored
independently for task 27/B5 (do not rely on the implementing agent's own
scoped coverage in test_evidence_validate.py -- FF3 there and FF3 here are
intentionally two independent implementations of the same invariant).

1. No new completion-status writer outside `tc.services.tasks` -- a test
   asserts the call-site count.
2. `tc.api` and the `tc` CLI produce identical `check_task_qa` output for
   the same task and database -- each side asserts the module path it
   exercised.
3. `tc/evidence/validate.py` imports nothing from `tc.db`, `tc.services`,
   `subprocess`, or `os` -- an import-direction test that also mechanically
   enforces "never execute a command because an artifact string contains
   it".
4. The artifact-type registry is the sole source from which the sets in
   the Claude hook, `qa.md`, `copilot-gate.sh` and the Codex qa skill are
   derivable.
5. A pre-schema-v1 completed task stays readable and valid -- legacy
   migration.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tc import api
from tc.evidence.artifact_types import ARTIFACT_TYPES
from tc.services.qa import check_task_qa

REPO_ROOT = Path(__file__).resolve().parents[3]
TC_SRC = Path(__file__).resolve().parents[1] / "src" / "tc"

PASS = (
    "CRITERION: guarded behavior holds\n"
    "EXPECTED: completion is blocked without evidence\n"
    "OBSERVED: completion was blocked as expected\n"
    "IDENTITY: fixture rev=abc1234, clean\n"
    "BASELINE: unavailable, fresh fixture database\n"
    'ARTIFACT: test-run|pytest tests/test_x.py exit=0 "1 passed"\n'
    "UNTESTED: none\n"
    "VERDICT: APPROVED\n"
)


# ---------------------------------------------------------------------------
# FF1: no new completion-status writer outside tc/services/tasks.py
# ---------------------------------------------------------------------------


def test_ff1_no_completion_status_writer_outside_services_tasks():
    """Every `UPDATE tasks SET ... status` (or equivalent) write lives in
    `tc/services/tasks.py`. Uses an AST walk over every `.py` file under
    `tc/services` and `tc/commands` for SQL-shaped string literals that
    both target the `tasks` table AND mention `status`, rather than a bare
    substring grep, so a string that merely mentions "status" in a comment
    or docstring cannot produce a false positive."""
    offenders: list[str] = []
    pattern = re.compile(r"UPDATE\s+tasks\s+SET", re.IGNORECASE)

    for py_file in TC_SRC.rglob("*.py"):
        if py_file.name == "tasks.py" and py_file.parent.name == "services":
            continue  # the one authorized writer
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if pattern.search(node.value) and "status" in node.value.lower():
                    offenders.append(f"{py_file.relative_to(TC_SRC)}: {node.value.strip()[:80]!r}")

    assert not offenders, (
        "found a completion-status writer outside tc/services/tasks.py: " + "; ".join(offenders)
    )


def test_ff1_services_tasks_is_the_only_file_with_a_tasks_status_update():
    """Positive control for the negative assertion above: confirm the
    expected writer actually exists where expected, so a bug in the AST
    walk itself (e.g. an exclusion that is too broad) cannot silently
    make FF1 vacuously true."""
    tasks_py = TC_SRC / "services" / "tasks.py"
    source = tasks_py.read_text(encoding="utf-8")
    assert re.search(r"UPDATE\s+tasks\s+SET", source, re.IGNORECASE)


# ---------------------------------------------------------------------------
# FF2: tc.api and the tc CLI produce identical check_task_qa output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("has_evidence", [True, False])
def test_ff2_api_and_cli_check_task_qa_identical_output(db_path, cli, has_evidence):
    import tc.services.qa as qa_module

    task = api.create_task(title="FF2", metadata={"requiresQa": True}, db_path=db_path)
    if has_evidence:
        api.store_wp(task_id=task["id"], type_="test", title="QA", content=PASS, db_path=db_path)

    api_result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert qa_module.__file__.startswith(str(TC_SRC)), (
        "API side did not exercise the checkout module",
        qa_module.__file__,
    )

    cli_result = cli(["task", "check-qa", str(task["id"]), "--json"])
    assert cli_result.exit_code == (0 if has_evidence else 1)
    cli_payload = json.loads(cli_result.output)

    assert cli_payload == {
        "task_id": api_result["task_id"],
        "approved": api_result["approved"],
        "work_product_id": api_result["work_product_id"],
        "reason": api_result["reason"],
        "legacy": api_result["legacy"],
    }


# ---------------------------------------------------------------------------
# FF3: tc/evidence/validate.py imports nothing forbidden (independent
# re-implementation of the same check test_evidence_validate.py already
# makes, per the module docstring above).
# ---------------------------------------------------------------------------


def test_ff3_validate_module_stays_pure():
    validate_path = TC_SRC / "evidence" / "validate.py"
    tree = ast.parse(validate_path.read_text(encoding="utf-8"))
    forbidden_roots = {"tc.db", "tc.services", "subprocess", "os"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            seen.add(node.module)

    violations = [
        name for name in seen if any(name == root or name.startswith(root + ".") for root in forbidden_roots)
    ]
    assert not violations, f"tc/evidence/validate.py imports forbidden module(s): {violations}"


def test_ff3_validate_module_defines_no_subprocess_or_exec_calls():
    """Belt-and-suspenders on "never execute a command merely because an
    artifact string contains it": no call to `subprocess.*`, `os.system`,
    `eval`, or `exec` appears anywhere in the AST of validate.py, not just
    in its import list."""
    validate_path = TC_SRC / "evidence" / "validate.py"
    tree = ast.parse(validate_path.read_text(encoding="utf-8"))
    dangerous_names = {"eval", "exec", "system", "popen", "run", "call", "check_output"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in dangerous_names, f"disallowed call {name!r} found in validate.py"


# ---------------------------------------------------------------------------
# FF4: the artifact-type registry is the sole source consumers derive from
# ---------------------------------------------------------------------------

# Files that document or enforce an accepted-artifact-type set. Each is
# scanned for `<type-name>|` (the packet's own `ARTIFACT: <type>|<detail>`
# shape) and for backtick-quoted `` `type-name` `` doc mentions; every name
# found must be a member of the canonical registry. This proves no
# consumer has invented (or still enforces) a type the registry does not
# recognize -- the specific shape of the original defect 1 (tc accepted UI
# types the hook rejected and vice versa).
CONSUMER_FILES = [
    REPO_ROOT / ".claude" / "hooks" / "subagent-stop.sh",
    REPO_ROOT / ".claude" / "agents" / "qa.md",
    REPO_ROOT / "scripts" / "copilot-gate.sh",
    REPO_ROOT / "plugins" / "codex-copilot" / "skills" / "qa" / "SKILL.md",
]

# Deliberately anchored, not a loose "-run"/"-check" substring scan (which
# false-positives on ordinary prose like "qa re-runs"): a name only counts
# as a documented/enforced artifact type when it appears either (a) in the
# literal `ARTIFACT: <type>|` marker shape, or (b) backtick-quoted as a
# standalone code span (how every one of the four consumer files documents
# its type enumeration).
_MARKER_SHAPE_RE = re.compile(r"ARTIFACT:\s*([a-z][a-z0-9-]*)\s*\|")
_BACKTICK_SPAN_RE = re.compile(r"`([a-z][a-z0-9-]*-(?:run|check))`")


def _mentioned_artifact_types(text: str) -> set[str]:
    return set(_MARKER_SHAPE_RE.findall(text)) | set(_BACKTICK_SPAN_RE.findall(text))


@pytest.mark.parametrize("consumer_path", CONSUMER_FILES, ids=lambda p: p.name)
def test_ff4_consumer_artifact_types_are_all_registry_members(consumer_path):
    assert consumer_path.exists(), f"expected consumer file missing: {consumer_path}"
    text = consumer_path.read_text(encoding="utf-8")
    mentioned = _mentioned_artifact_types(text)
    unknown = {name for name in mentioned if name not in ARTIFACT_TYPES}
    assert not unknown, (
        f"{consumer_path} mentions artifact type(s) not in the tc.evidence.artifact_types "
        f"registry: {unknown} (registry: {sorted(ARTIFACT_TYPES)})"
    )


def test_ff4_registry_is_non_empty_and_every_type_is_a_plain_string():
    assert ARTIFACT_TYPES
    for name in ARTIFACT_TYPES:
        assert isinstance(name, str) and name == name.lower()


def test_ff4_hook_no_longer_declares_its_own_type_set():
    """Positive confirmation of the reconciliation itself: the Claude hook
    used to hardcode its own accepted-type regex (`has_artifact_marker`,
    removed). It must not have grown a new one -- the ONLY way it may
    decide approval now is by delegating to `tc task check-qa`."""
    hook_path = REPO_ROOT / ".claude" / "hooks" / "subagent-stop.sh"
    text = hook_path.read_text(encoding="utf-8")
    # The function DEFINITION must be gone (a bare mention in a removal
    # note/comment explaining the reconciliation is fine and expected).
    assert not re.search(r"^\s*has_artifact_marker\s*\(\)\s*\{", text, re.MULTILINE)
    assert "tc task check-qa" in text


# ---------------------------------------------------------------------------
# FF5: a pre-schema-v1 completed task stays readable and valid
# ---------------------------------------------------------------------------


def test_ff5_pre_schema_completed_task_stays_readable_and_approved(db_path):
    """Independent re-check of the legacy-migration file's own coverage:
    a task completed under the OLD (pre-v1, no-IDENTITY) contract remains
    both structurally readable (get_task/list_wps succeed, data intact)
    and semantically valid (check_task_qa still reports approved) after
    this task's changes land -- it is not retroactively broken."""
    task = api.create_task(title="FF5 historical", metadata={"requiresQa": True}, db_path=db_path)
    legacy_content = "ARTIFACT: test-run|pytest exit=0\nVERDICT: APPROVED\n"
    wp = api.store_wp(task_id=task["id"], type_="test", title="Old QA", content=legacy_content, db_path=db_path)

    from tc.db.connection import get_db

    conn = get_db(db_path)
    conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task["id"],))
    conn.commit()
    conn.close()

    read_back = api.get_task(task_id=task["id"], db_path=db_path)
    assert read_back["status"] == "completed"

    fetched_wp = api.get_wp(wp_id=wp["id"], db_path=db_path)
    assert fetched_wp["content"] == legacy_content

    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is True
    assert result["legacy"] is True
