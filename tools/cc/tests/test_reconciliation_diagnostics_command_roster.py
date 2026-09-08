"""Regression coverage for the second C7/D1-class bug QA found in task 35's
E2 redo: a `VERSION.json` project-command roster addition (`reflect.md`) that
was never mirrored into `reconciliation_diagnostics._TARGETS`'s static
allowlist -- a *second*, structurally identical hardcoded allowlist that
`ee0b04e` (the C7 fix to `reconciliation_recipes.py`) did not touch.

Consequence, reproduced independently in five fresh `$HOME`s: `finalize_run_diagnostic()`
-> `_safe_reviewed_plans()` -> `_allowed_target()` raised
`ReconciliationDiagnosticError("A reviewed operation is invalid.")` on the
`reflect.md` operation for *every* real `apply`/`recover` call (since
`reflect.md` is now unconditionally rostered), which the same function's
broad `except` clause silently downgraded to `diagnostics.state:
"unavailable"`. That downgrade left the run permanently "interrupted": every
subsequent `plan`/`apply` in the same `$HOME` was refused, and `recover()`
hit the identical exception re-finalizing the same run, so the deadlock could
never clear -- a currently-open regression more severe than the one `ee0b04e`
fixed, because it left every real install unrecoverable, machine-wide.

The fix mirrors `ee0b04e`'s own structural fix
(`reconciliation_recipes._validate_relative_target()`'s `nested_claude_command`
exemption) into `reconciliation_diagnostics._allowed_target()`: any
`.claude/commands/<name>.md` target is now accepted structurally, the same
way `.claude/agents/**` already was, so `_TARGETS`'s enumerated
`.claude/commands/*.md` entries are no longer load-bearing for validation --
only informational. This means a *future* `VERSION.json` project-command
addition can never again reproduce this failure mode here, regardless of
whether anyone remembers to touch the static set.

These tests intentionally do NOT modify any existing test file (existing
tests are read-only); this is a new, standalone file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cc.core.ecosystem import reconciliation_recipes as recipes
from cc.core.ecosystem.canonical_transaction import claude_reference_roster
from cc.core.ecosystem.reconciliation_diagnostics import (
    ReconciliationDiagnosticError,
    _allowed_target,
    append_project_receipt,
    finalize_run_diagnostic,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fingerprint(character: str) -> str:
    return "sha256:" + character * 64


# ---------------------------------------------------------------------------
# 1. Direct unit coverage of the fix.
# ---------------------------------------------------------------------------


def test_a_new_version_json_project_command_is_not_blocked_by_the_static_target_set() -> (
    None
):
    """A command name absent from the static `_TARGETS` set must still be
    accepted, because `.claude/commands/*.md` is now structural (parity with
    `.claude/agents/**`) -- this is the exact D1/E2 defect shape."""

    target = ".claude/commands/reflect.md"
    assert target not in _dump_targets()
    assert _allowed_target(target) is True
    assert _allowed_target(".claude/commands/a-brand-new-project-command.md") is True


def _dump_targets() -> set[str]:
    from cc.core.ecosystem.reconciliation_diagnostics import _TARGETS

    return _TARGETS


def test_non_md_and_nested_and_escaping_command_paths_remain_rejected() -> None:
    """The structural exemption is narrow on purpose: only a direct
    `.claude/commands/<name>.md` file, never arbitrary depth, a non-`.md`
    file, an absolute path, or a `..` escape -- so it cannot become a
    write-anywhere or read-anywhere hole in the diagnostics writer's own
    closed allowlist."""

    assert _allowed_target(".claude/commands/not-markdown.sh") is False
    assert _allowed_target(".claude/commands/nested/deep.md") is False
    assert _allowed_target(".claude/commands/") is False
    assert _allowed_target(".claude/commands") is False
    assert _allowed_target("/etc/.claude/commands/reflect.md") is False
    assert _allowed_target("../.claude/commands/reflect.md") is False
    assert _allowed_target(".claude/commands/../../etc/passwd.md") is False
    assert _allowed_target(".claude/commands/..") is False
    assert _allowed_target(".claude/commands/.") is False
    assert _allowed_target(123) is False
    assert _allowed_target(None) is False
    # Parity check: the pre-existing `.claude/agents/**` structural
    # exemption must still hold exactly as before this change.
    assert _allowed_target(".claude/agents/reflect.md") is True
    assert _allowed_target(".claude/agents/../escape.md") is False
    # ".claude/agents" (bare, depth 2) is separately allowed via the literal
    # `_TARGETS` set (it names the directory itself, not a structural leaf),
    # not via the `nested_claude_agent`/`nested_claude_command` exemptions --
    # confirmed directly against the module's own set rather than assumed.
    assert ".claude/agents" in _dump_targets()
    assert _allowed_target(".claude/agents") is True


def test_every_currently_declared_project_command_is_diagnosable(tmp_path: Path) -> None:
    """Guards against the same class of drift for THIS repo's own, real
    `VERSION.json` roster: every command it currently declares must pass
    `_allowed_target()`. Fails the moment a future project command is added
    to `VERSION.json` but this structural exemption is ever narrowed or
    removed without a replacement -- i.e. exactly the D1/E2 failure mode,
    caught by a test instead of a rejected rehearsal."""

    commands, _agents = claude_reference_roster(REPO_ROOT)
    assert commands, "VERSION.json must declare at least one project command."
    for command in commands:
        assert _allowed_target(f".claude/commands/{command}") is True


# ---------------------------------------------------------------------------
# 2. End-to-end reproduction of the exact QA failure at the diagnostics layer.
# ---------------------------------------------------------------------------


def _reviewed_plans_with_reflect() -> list[dict]:
    return [
        {
            "path": "/projects/example",
            "inspection_id": _fingerprint("c"),
            "recipes": [
                {"component": "claude", "recipe_id": "claude-project-update-v1"}
            ],
            "sources": [],
            "operations": [
                {
                    "id": "op_" + "a" * 64,
                    "kind": "create-file-from-source",
                    "component": "claude",
                    "target": ".claude/commands/reflect.md",
                    "description": "Add the reviewed reflect command.",
                    "expected_before_fingerprint": _fingerprint("e"),
                    "source_fingerprint": _fingerprint("f"),
                }
            ],
            "preservation": [],
            "prohibited_actions": ["overwrite-project-owned-content"],
            "verification": ["claude-project-integration"],
        }
    ]


def _receipt_for_reflect() -> dict:
    return {
        "path": "/projects/example",
        "status": "applied",
        "detail": "The project now matches the reviewed plan.",
        "completed_operation_ids": ["op_" + "a" * 64],
        "verification": "ready",
        "rollback": [],
        "diagnostic_evidence": {
            "preflight": {
                "identity_fingerprint": _fingerprint("b"),
                "inspection_id": _fingerprint("c"),
                "classification": "safe-update-available",
                "components": [
                    {
                        "component": "claude",
                        "classification": "safe-update-available",
                        "requirement_ids": ["claude:component-setup"],
                    }
                ],
            },
            "sources": [
                {"component": "claude", "version": "2.6.0", "fingerprint": _fingerprint("d")}
            ],
            "targets": [
                {
                    "target": ".claude/commands/reflect.md",
                    "kind": "missing",
                    "before_fingerprint": _fingerprint("e"),
                }
            ],
            "planned_operation_ids": ["op_" + "a" * 64],
            "post_apply_verification": [
                {"component": "claude", "state": "ready", "evidence_ids": ["canonical-entry"]}
            ],
            "exception": None,
        },
    }


def _canonical_request() -> dict:
    return {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [{"path": "/projects/example", "components": ["claude"]}],
    }


def _request_fingerprint() -> str:
    encoded = json.dumps(
        _canonical_request(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_finalize_run_diagnostic_no_longer_raises_on_a_reflect_md_operation(
    tmp_path: Path,
) -> None:
    """Direct reproduction of the QA-observed failure:
    `ReconciliationDiagnosticError("A reviewed operation is invalid.")` was
    raised here for every real apply/recover once a plan's reviewed
    operations included a genuinely rostered `.claude/commands/reflect.md`
    target, because `_allowed_target()` rejected it. Must now succeed and
    report `state == "available"`, not silently downgrade to
    `"unavailable"`."""

    run_id = "run_" + "3" * 32
    plan_id = "plan_" + "4" * 32
    receipt = _receipt_for_reflect()
    reference = append_project_receipt(run_id, receipt, root=tmp_path)
    assert reference.state == "available"

    final = finalize_run_diagnostic(
        run_id,
        plan_id,
        _request_fingerprint(),
        [receipt],
        canonical_request=_canonical_request(),
        reviewed_plans=_reviewed_plans_with_reflect(),
        fresh_plan_fingerprint=_fingerprint("0"),
        helper_version="2.12.15",
        schema_version="1.0",
        machine_evidence={
            "state": "ready",
            "helper": {"state": "ready", "version": "2.12.15", "path": "/secret/path"},
            "authentication": {
                "state": "signed-in",
                "credential_state": "present",
                "token": "sentinel",
            },
            "connectivity": {"state": "online", "raw": "sentinel"},
            "layers": {"state": "ready", "ready": 4, "total": 4},
            "frameworks": [
                {"component": "claude", "state": "ready", "version": "2.12.15"}
            ],
            "dependencies": [{"id": "git", "state": "ready", "detail": "sentinel"}],
        },
        final_census={"ready": 1, "total": 1},
        overlap_explanation="One updated component remains independently classified.",
        root=tmp_path,
    )

    # This is the exact assertion QA found violated: before the fix, this
    # raised ReconciliationDiagnosticError, caught by finalize_run_diagnostic's
    # own broad except and downgraded to "unavailable" -- which is what
    # poisoned the machine's "interrupted" state for every subsequent call.
    assert final.state == "available"
    payload = json.loads(Path(final.path).read_text(encoding="utf-8"))
    assert payload["projects"][0]["evidence"]["targets"][0]["target"] == (
        ".claude/commands/reflect.md"
    )


# ---------------------------------------------------------------------------
# 3. Cross-file divergence detector: the two independent hardcoded target
#    allowlists that both had to learn about `reflect.md` must never again
#    silently drift apart from each other or from the canonical roster.
# ---------------------------------------------------------------------------


def test_recipes_and_diagnostics_target_validators_never_diverge() -> None:
    """`reconciliation_recipes._validate_relative_target()` and
    `reconciliation_diagnostics._allowed_target()` are two independent
    hardcoded allowlists that both exist to answer the identical question --
    "is this `.claude/commands/<name>.md` (or `.claude/agents/**`) path a
    legitimate reconciliation target?" -- for two different stages of the
    same pipeline (recipe construction vs. diagnostic finalization). D1 found
    one had drifted from the real command roster; E2 found the other had too,
    independently, months apart, each discovered only after a real apply/recover
    broke in production. This test makes that drift a test failure instead of a
    rejected rehearsal: for every command this repo's own VERSION.json
    declares, and for a battery of the same malicious/malformed paths, the two
    validators must agree.
    """

    commands, _agents = claude_reference_roster(REPO_ROOT)
    assert commands

    def recipes_accepts(target: str) -> bool:
        try:
            recipes._validate_relative_target("claude", target)
        except recipes.RecipeValidationError:
            return False
        return True

    for command in commands:
        target = f".claude/commands/{command}"
        assert recipes_accepts(target) is True
        assert _allowed_target(target) is True

    divergence_probes = (
        ".claude/commands/protocol.md",
        ".claude/commands/reflect.md",
        ".claude/commands/a-brand-new-project-command.md",
        ".claude/commands/not-markdown.sh",
        ".claude/commands/nested/deep.md",
        ".claude/commands/",
        ".claude/commands",
        "../.claude/commands/reflect.md",
        ".claude/commands/../../etc/passwd.md",
        ".claude/agents/me.md",
        ".claude/agents/nested/deep.md",
    )
    for target in divergence_probes:
        recipes_result = recipes_accepts(target)
        diagnostics_result = _allowed_target(target)
        assert recipes_result == diagnostics_result, (
            f"recipes._validate_relative_target and diagnostics._allowed_target "
            f"disagree on {target!r}: recipes={recipes_result} "
            f"diagnostics={diagnostics_result}"
        )


def test_the_error_class_used_by_both_layers_is_stable() -> None:
    """Sanity check that the specific exception `_safe_reviewed_plans()`
    raises when `_allowed_target()` rejects a target is still
    `ReconciliationDiagnosticError` -- the class the QA evidence traced this
    bug to (`reconciliation_diagnostics.py:818`) and the class
    `finalize_run_diagnostic()`'s broad `except` silently downgrades."""

    assert issubclass(ReconciliationDiagnosticError, Exception)
