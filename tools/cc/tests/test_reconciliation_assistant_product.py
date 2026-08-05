"""Product-bound QA for the bounded Claude reconciliation lifecycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from reconciliation_assistant_harness import (  # noqa: E402
    capture_record,
    decoded_stdin,
    snapshot_tree,
)
from test_reconciliation_assistant_security import (  # noqa: E402
    _claude_source,
    _codex_source,
    _configure_source,
    _customized_project,
)

from cc.core.config_paths import machine_diagnostics_root  # noqa: E402
from cc.core.ecosystem import reconciliation_assistant as assistant  # noqa: E402
from cc.core.ecosystem.assistant_job_store import (  # noqa: E402
    claim_session,
    complete_session,
    create_session,
    fingerprint,
    issue_proposal,
    load_session,
    session_directory,
)
from cc.core.ecosystem.project_reconciliation import assess_project  # noqa: E402
from cc.core.ecosystem.reconciliation import (  # noqa: E402
    ReconciliationError,
    build_apply_report,
    build_plan_report,
    build_verify_report,
    prepare_reconciliation,
)
from cc.core.ecosystem.reconciliation_types import (  # noqa: E402
    ReconciliationRequest,
    parse_reconciliation_request,
)


FAKE_CLAUDE = (
    Path(__file__).parent / "fixtures" / "reconciliation" / "fake_claude.py"
)
RECONCILE_SCHEMA = Path(__file__).parent / "fixtures" / "schemas" / "reconcile.schema.json"


def _schema_errors(report: dict[str, Any]) -> list[Any]:
    schema = json.loads(RECONCILE_SCHEMA.read_text(encoding="utf-8"))
    return list(Draft202012Validator(schema).iter_errors(report))


def _machine(root: Path) -> dict[str, Any]:
    return {
        "state": "ready",
        "helper": {
            "state": "ready",
            "version": "2.6.1",
            "path": "/usr/local/bin/cc",
            "detail": "The helper is available.",
        },
        "frameworks": [
            {
                "component": component,
                "state": "ready",
                "path": f"/{component}-framework",
                "version": "1.0.0",
                "detail": f"The {component.title()} framework is ready.",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {
            "state": "ready",
            "path": "/config.json",
            "approved_roots": [str(root)],
            "detail": "The machine configuration is readable.",
        },
        "authentication": {
            "state": "signed-in",
            "credential_state": "present",
            "detail": "Sign-in is available.",
        },
        "connectivity": {"state": "online", "detail": "Connectivity is ready."},
        "layers": {
            "state": "ready",
            "ready": 2,
            "total": 2,
            "detail": "Layers are ready.",
        },
        "dependencies": [],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _census(project: Path, root: Path):
    def build(**kwargs: Any) -> list[dict[str, Any]]:
        selections = kwargs.get("selections") or {}
        selected = tuple(selections.get(str(project), ("claude", "codex")))
        return [
            assess_project(
                project,
                approved_root=root,
                selected_components=selected,
            )
        ]

    return build


def _request(project: Path, root: Path) -> ReconciliationRequest:
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(root)],
            "projects": [
                {
                    "path": str(project),
                    "components": ["claude", "codex"],
                    "recipe_ids": {"codex": "codex-project-setup-v1"},
                }
            ],
        }
    )


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, ReconciliationRequest, Any, Any]:
    claude_source = _claude_source(tmp_path)
    codex_source = _codex_source(tmp_path)
    _configure_source(monkeypatch, claude_source, codex_source)
    project = _customized_project(tmp_path)
    request = _request(project, tmp_path)
    machine_builder = lambda: _machine(tmp_path)
    census_builder = _census(project, tmp_path)
    return project, request, machine_builder, census_builder


def _prepare(
    request: ReconciliationRequest,
    machine_builder: Any,
    census_builder: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = assistant.build_assistant_prepare_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    return report, load_session(report["session_id"])


def _valid_fake(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session: dict[str, Any],
) -> Path:
    capture = tmp_path / f"{session['session_id']}.capture.json"
    selections = [
        {"candidate_id": candidate["candidate_id"]}
        for candidate in session["candidates"]
    ]
    monkeypatch.setenv("CC_ASSISTANT_TEST_MODE", "1")
    monkeypatch.setenv("FAKE_CLAUDE_CAPTURE", str(capture))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "valid")
    monkeypatch.setenv("FAKE_CLAUDE_ENVELOPE", "structured-output")
    monkeypatch.setenv(
        "FAKE_CLAUDE_PAYLOAD_JSON", json.dumps({"selections": selections})
    )
    monkeypatch.setenv("ASSISTANT_SECRET_CANARY", "must-not-reach-child")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "assistant-api-secret-canary")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-canary")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret-canary")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "secret-git-config"))
    monkeypatch.setenv("SSH_AUTH_SOCK", str(tmp_path / "secret-agent.sock"))
    return capture


def _attached(
    request: ReconciliationRequest, proposal_id: str
) -> ReconciliationRequest:
    value = request.as_dict()
    value["assistant_proposal_id"] = proposal_id
    return parse_reconciliation_request(value)


def test_prepare_run_status_plan_apply_and_fresh_verify_both_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    unchanged = snapshot_tree(project)
    custom_agent = (project / ".claude/agents/me.md").read_bytes()
    custom_command = (project / ".claude/commands/project.md").read_bytes()
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    capture_path = _valid_fake(monkeypatch, tmp_path, session)

    assert not _schema_errors(prepare_report)

    run_report = assistant.run_assistant_session(
        prepare_report["session_id"], claude_path=FAKE_CLAUDE
    )

    assert run_report["result"] == "ready"
    assert not _schema_errors(run_report)
    assert snapshot_tree(project) == unchanged
    capture = capture_record(capture_path)
    expected_prefix = [
        "--safe-mode",
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--print",
        "--input-format",
        "text",
        "--output-format",
        "json",
        "--json-schema",
    ]
    assert capture["argv"][:-1] == expected_prefix
    assert capture["cwd"] == str(
        session_directory(prepare_report["session_id"]) / "work"
    )
    assert "ASSISTANT_SECRET_CANARY" not in capture["environment_keys"]
    assert not {
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "GIT_CONFIG_GLOBAL",
        "SSH_AUTH_SOCK",
    } & set(capture["environment_keys"])
    assert str(project) not in json.dumps(capture["argv"])
    schema = json.loads(capture["argv"][-1])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["selections"]["items"]["additionalProperties"] is False
    prompt = decoded_stdin(capture)
    assert str(project).encode() not in prompt
    assert project.name.encode() not in prompt
    assert b"Project-owned instructions" not in prompt
    assert b"project-owned agent" not in prompt
    assert b"claude-source" not in prompt

    plan_preparer = lambda resolved: prepare_reconciliation(
        resolved,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    status = assistant.build_assistant_status_report(
        prepare_report["session_id"], plan_preparer=plan_preparer
    )
    assert status["result"] == "ready"


    assert not _schema_errors(status)
    repeated_status = assistant.build_assistant_status_report(
        prepare_report["session_id"], plan_preparer=plan_preparer
    )
    assert repeated_status["proposal_id"] == status["proposal_id"]
    attached = _attached(request, status["proposal_id"])
    resolved, proposal = assistant.resolve_assistant_request(attached)
    assert resolved.projects[0].recipe_ids == {
        "claude": "claude.assistant-preserve-entry.v1",
        "codex": "codex-project-setup-v1",
    }
    assert proposal["owned_components"] == {str(project): ["claude"]}

    plan = build_plan_report(
        attached,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert plan["result"] == "action-required"
    assert snapshot_tree(project) == unchanged
    applied = build_apply_report(
        attached,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert applied["result"] == "applied"
    assert (project / ".claude/agents/me.md").read_bytes() == custom_agent
    assert (project / ".claude/commands/project.md").read_bytes() == custom_command
    assert b"# Project-owned instructions" in (project / "CLAUDE.md").read_bytes()
    verified = build_verify_report(
        attached,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert verified["result"] == "ready"
    states = {
        item["component"]: item["state"]
        for item in verified["projects"][0]["components"]
    }
    assert states == {"claude": "ready", "codex": "ready"}


def test_safe_environment_drops_credential_bearing_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy-user:proxy-secret@example.invalid")
    monkeypatch.setenv("HTTP_PROXY", "proxy-user:proxy-secret@example.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    environment = assistant._safe_environment()

    assert "HTTPS_PROXY" not in environment
    assert "HTTP_PROXY" not in environment
    assert environment["NO_PROXY"] == "localhost,127.0.0.1"


def _write_executable(path: Path, script: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_registry_hit_outranks_hostile_path_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory prepended to PATH must never preempt a registry hit.

    The Finding B defect was that a PATH-order-dependent lookup ran *before*
    the closed registry and could steer resolution to an attacker-controlled
    binary even when a legitimate, trusted `claude` was already installed at
    a known location (STRIDE: Tampering). The planted PATH binary here is
    deliberately owned by the current user and mode 0755 -- it would pass
    `_supported_claude_path`'s ownership/permission checks on its own -- but
    resolution must still prefer the registry location because ordering,
    not the mere existence of a PATH fallback, is the control.
    """
    monkeypatch.delenv("CC_ASSISTANT_CLAUDE_PATH", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    home.mkdir()
    trusted = _write_executable(home / ".local" / "bin" / "claude")
    malicious = _write_executable(
        tmp_path / "attacker-path" / "claude", "#!/bin/sh\necho pwned\n"
    )
    monkeypatch.setenv("PATH", f"{malicious.parent}{os.pathsep}{os.environ.get('PATH', '')}")

    resolved = assistant._supported_claude_path()

    assert resolved == trusted.resolve()


def test_path_only_claude_binary_resolves_when_registry_has_no_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression case: PATH is the only source that knows the location.

    When the closed registry has no answer (e.g. `claude` is installed
    somewhere outside `core/executables.py`'s known absolute locations),
    resolution must still fall back to the ambient PATH rather than failing
    closed -- but the resolved binary remains subject to the same
    ownership/permission checks as any other candidate.
    """
    monkeypatch.delenv("CC_ASSISTANT_CLAUDE_PATH", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    home.mkdir()
    only_on_path = _write_executable(tmp_path / "path-only" / "claude")
    monkeypatch.setenv("PATH", f"{only_on_path.parent}{os.pathsep}{os.environ.get('PATH', '')}")

    resolved = assistant._supported_claude_path()

    assert resolved == only_on_path.resolve()


def test_unsafe_path_only_claude_binary_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PATH-resolved candidate still fails closed if it is unsafe.

    Falling back to PATH does not relax the ownership/permission checks: a
    group- or other-writable binary is refused with the same clean,
    unambiguous `claude-code-unsafe` ReconciliationError that any other
    unsafe candidate (registry or explicit override) would receive, even
    though it is the only candidate PATH or the registry could offer.
    """
    monkeypatch.delenv("CC_ASSISTANT_CLAUDE_PATH", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    home.mkdir()
    unsafe = _write_executable(tmp_path / "path-only" / "claude")
    unsafe.chmod(0o775)
    monkeypatch.setenv("PATH", f"{unsafe.parent}{os.pathsep}{os.environ.get('PATH', '')}")

    with pytest.raises(ReconciliationError) as excinfo:
        assistant._supported_claude_path()

    assert excinfo.value.code == "claude-code-unsafe"


def test_env_override_still_resolves_a_trustworthy_claude_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = _write_executable(tmp_path / "trusted" / "claude")
    malicious = _write_executable(
        tmp_path / "attacker-path" / "claude", "#!/bin/sh\necho pwned\n"
    )
    monkeypatch.setenv("PATH", f"{malicious.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CC_ASSISTANT_CLAUDE_PATH", str(trusted))

    resolved = assistant._supported_claude_path()

    assert resolved == trusted.resolve()


def test_unresolvable_claude_refuses_session_cleanly_and_deterministic_path_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When neither the registry nor PATH knows of a `claude` install, the
    bounded-assistant path fails closed cleanly and the documented
    deterministic-only fallback remains fully usable.

    PATH is deliberately narrowed to standard system directories -- not
    stripped entirely -- so `git` stays available for the census below while
    guaranteeing no `claude`, real or planted, is reachable through it. This
    is the last-resort-PATH design's genuine failure case: no source, in
    priority order, has an answer.
    """
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    unchanged = snapshot_tree(project)
    monkeypatch.delenv("CC_ASSISTANT_CLAUDE_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    prepare_report, _session = _prepare(request, machine_builder, census_builder)

    with pytest.raises(ReconciliationError) as excinfo:
        assistant.run_assistant_session(prepare_report["session_id"])

    assert excinfo.value.code == "claude-code-unavailable"
    assert snapshot_tree(project) == unchanged
    status = assistant.build_assistant_status_report(prepare_report["session_id"])
    assert status["result"] == "blocked"
    assert status["proposal_id"] is None
    assert not _schema_errors(status)

    # The bounded-assistant path refused cleanly; the documented fallback --
    # deterministic-only reconciliation for a component that never touches
    # `claude` at all -- must still be fully usable and untouched by the
    # unresolvable-executable failure above.
    deterministic_request = request.as_dict()
    deterministic_request["projects"][0]["components"] = ["codex"]
    deterministic_request = parse_reconciliation_request(deterministic_request)
    plan = build_plan_report(
        deterministic_request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert plan["result"] == "action-required"
    assert snapshot_tree(project) == unchanged


@pytest.mark.parametrize(
    "mode",
    [
        "wrong-id",
        "command",
        "path",
        "content",
        "patch",
        "operation",
        "free-text",
        "malformed",
        "duplicate",
        "nan",
        "invalid-utf8",
        "empty",
        "exit-1",
        "exit-2",
    ],
)
def test_hostile_claude_output_is_blocked_without_project_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    before = snapshot_tree(project)
    prepare_report, _session = _prepare(request, machine_builder, census_builder)
    monkeypatch.setenv("CC_ASSISTANT_TEST_MODE", "1")
    monkeypatch.setenv(
        "FAKE_CLAUDE_CAPTURE", str(tmp_path / f"{mode}.capture.json")
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

    with pytest.raises(ReconciliationError):
        assistant.run_assistant_session(
            prepare_report["session_id"], claude_path=FAKE_CLAUDE
        )

    assert snapshot_tree(project) == before
    status = assistant.build_assistant_status_report(prepare_report["session_id"])
    assert status["result"] == "blocked"
    assert status["proposal_id"] is None
    assert not _schema_errors(status)


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value"),
    [
        ("command", "rm -rf project"),
        ("path", "../../outside"),
        ("content", "assistant-authored bytes"),
        ("patch", "@@ -1 +1 @@"),
        ("operation", {"kind": "shell"}),
    ],
)
def test_structured_wrapper_rejects_unsafe_assistant_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_field: str,
    unsafe_value: Any,
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    before = snapshot_tree(project)
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "structured_output": {
            "selections": [
                {"candidate_id": item["candidate_id"]}
                for item in session["candidates"]
            ]
        },
        unsafe_field: unsafe_value,
    }
    response = tmp_path / f"{unsafe_field}.response.json"
    response.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("CC_ASSISTANT_TEST_MODE", "1")
    monkeypatch.setenv(
        "FAKE_CLAUDE_CAPTURE", str(tmp_path / f"{unsafe_field}.capture.json")
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "exact")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE_FILE", str(response))

    with pytest.raises(ReconciliationError):
        assistant.run_assistant_session(
            prepare_report["session_id"], claude_path=FAKE_CLAUDE
        )

    assert snapshot_tree(project) == before
    status = assistant.build_assistant_status_report(prepare_report["session_id"])
    assert status["result"] == "blocked"


def test_structured_wrapper_rejects_provider_error_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    before = snapshot_tree(project)
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    response = tmp_path / "provider-error.response.json"
    response.write_text(
        json.dumps(
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "structured_output": {
                    "selections": [
                        {"candidate_id": item["candidate_id"]}
                        for item in session["candidates"]
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CC_ASSISTANT_TEST_MODE", "1")
    monkeypatch.setenv(
        "FAKE_CLAUDE_CAPTURE", str(tmp_path / "provider-error.capture.json")
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "exact")
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE_FILE", str(response))

    with pytest.raises(ReconciliationError):
        assistant.run_assistant_session(
            prepare_report["session_id"], claude_path=FAKE_CLAUDE
        )

    assert snapshot_tree(project) == before


def test_timeout_interrupts_fake_and_changes_zero_project_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    before = snapshot_tree(project)
    prepare_report, _session = _prepare(request, machine_builder, census_builder)
    ready = tmp_path / "fake.ready"
    monkeypatch.setenv("CC_ASSISTANT_TEST_MODE", "1")
    monkeypatch.setenv("FAKE_CLAUDE_CAPTURE", str(tmp_path / "wait.capture.json"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "wait")
    monkeypatch.setenv("FAKE_CLAUDE_READY_FILE", str(ready))

    with pytest.raises(ReconciliationError, match="timed out"):
        assistant.run_assistant_session(
            prepare_report["session_id"],
            claude_path=FAKE_CLAUDE,
            timeout_seconds=1,
        )

    assert ready.exists()
    assert snapshot_tree(project) == before
    status = assistant.build_assistant_status_report(prepare_report["session_id"])
    assert status["result"] == "blocked"


def test_project_drift_after_capture_yields_no_proposal_or_additional_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    _valid_fake(monkeypatch, tmp_path, session)
    assistant.run_assistant_session(
        prepare_report["session_id"], claude_path=FAKE_CLAUDE
    )
    (project / "CLAUDE.md").write_text("drift after capture\n", encoding="utf-8")
    drifted = snapshot_tree(project)
    plan_preparer = lambda resolved: prepare_reconciliation(
        resolved,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )

    with pytest.raises(ReconciliationError):
        assistant.build_assistant_status_report(
            prepare_report["session_id"], plan_preparer=plan_preparer
        )

    assert snapshot_tree(project) == drifted
    assert load_session(prepare_report["session_id"])["proposal_id"] is None


def test_hybrid_authority_overlap_is_rejected_at_proposal_resolution(
    tmp_path: Path,
) -> None:
    project = str(tmp_path / "project")
    base = {
        "schema_version": "1.0",
        "roots": [str(tmp_path)],
        "projects": [
            {
                "path": project,
                "components": ["claude", "codex"],
                "recipe_ids": {"codex": "codex-project-setup-v1"},
            }
        ],
    }
    session = create_session(
        base_request=base,
        packet={"schema_version": "1.0", "projects": []},
        candidates=[],
        selected_projects=[project],
        policy_fingerprint=assistant._POLICY_FINGERPRINT,
    )
    claim_session(session["session_id"])
    complete_session(session["session_id"], [])
    proposal = issue_proposal(
        session["session_id"],
        resolved_request=base,
        owned_components={project: ["codex"]},
        plans_fingerprint=fingerprint([]),
    )
    request_value = json.loads(json.dumps(base))
    request_value["assistant_proposal_id"] = proposal["proposal_id"]

    with pytest.raises(ReconciliationError) as captured:
        assistant.resolve_assistant_request(
            parse_reconciliation_request(request_value)
        )

    assert captured.value.code == "assistant-authority-overlap"


def test_tampered_proposal_is_rejected_before_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    _valid_fake(monkeypatch, tmp_path, session)
    assistant.run_assistant_session(
        prepare_report["session_id"], claude_path=FAKE_CLAUDE
    )
    status = assistant.build_assistant_status_report(
        prepare_report["session_id"],
        plan_preparer=lambda resolved: prepare_reconciliation(
            resolved,
            machine_builder=machine_builder,
            census_builder=census_builder,
        ),
    )
    proposal_path = (
        machine_diagnostics_root()
        / "reconciliation"
        / "assistant"
        / "proposals"
        / f"{status['proposal_id']}.json"
    )
    before = proposal_path.read_bytes()
    after = before.replace(b"codex-project-setup-v1", b"codex-project-setup-v2")
    assert after != before
    proposal_path.write_bytes(after)
    attached = _attached(request, status["proposal_id"])

    with pytest.raises(ReconciliationError) as captured:
        build_plan_report(
            attached,
            machine_builder=machine_builder,
            census_builder=census_builder,
        )

    assert captured.value.code == "assistant-proposal-unavailable"


def test_proposal_becomes_stale_after_project_drift_without_more_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    _valid_fake(monkeypatch, tmp_path, session)
    assistant.run_assistant_session(
        prepare_report["session_id"], claude_path=FAKE_CLAUDE
    )
    status = assistant.build_assistant_status_report(
        prepare_report["session_id"],
        plan_preparer=lambda resolved: prepare_reconciliation(
            resolved,
            machine_builder=machine_builder,
            census_builder=census_builder,
        ),
    )
    attached = _attached(request, status["proposal_id"])
    (project / "CLAUDE.md").write_text("stale proposal drift\n", encoding="utf-8")
    drifted = snapshot_tree(project)

    with pytest.raises(ReconciliationError):
        build_plan_report(
            attached,
            machine_builder=machine_builder,
            census_builder=census_builder,
        )

    assert snapshot_tree(project) == drifted


def test_cli_assistant_verbs_dispatch_the_same_bounded_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cli,
) -> None:
    _project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request.as_dict()), encoding="utf-8")
    request_path.chmod(0o600)
    original_prepare = assistant.build_assistant_prepare_report
    original_status = assistant.build_assistant_status_report
    monkeypatch.setattr(
        assistant,
        "build_assistant_prepare_report",
        lambda selected: original_prepare(
            selected,
            machine_builder=machine_builder,
            census_builder=census_builder,
        ),
    )

    prepared = cli(
        [
            "reconcile",
            "assistant-prepare",
            "--request",
            str(request_path),
            "--json",
        ]
    )

    assert prepared.exit_code == 0
    prepare_report = json.loads(prepared.stdout)
    session = load_session(prepare_report["session_id"])
    _valid_fake(monkeypatch, tmp_path, session)
    monkeypatch.setenv("CC_ASSISTANT_CLAUDE_PATH", str(FAKE_CLAUDE))
    ran = cli(
        [
            "reconcile",
            "assistant-run",
            "--session-id",
            prepare_report["session_id"],
            "--json",
        ]
    )
    assert ran.exit_code == 0
    assert json.loads(ran.stdout)["result"] == "ready"

    monkeypatch.setattr(
        assistant,
        "build_assistant_status_report",
        lambda session_id: original_status(
            session_id,
            plan_preparer=lambda resolved: prepare_reconciliation(
                resolved,
                machine_builder=machine_builder,
                census_builder=census_builder,
            ),
        ),
    )
    status = cli(
        [
            "reconcile",
            "assistant-status",
            "--session-id",
            prepare_report["session_id"],
            "--json",
        ]
    )
    assert status.exit_code == 0
    status_report = json.loads(status.stdout)
    assert status_report["result"] == "ready"
    assert status_report["selected_projects"] == [request.projects[0].path]
    assert not _schema_errors(prepare_report)
    assert not _schema_errors(json.loads(ran.stdout))
    assert not _schema_errors(status_report)


def test_dirty_project_is_refused_and_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    (project / "human-work.txt").write_text("uncommitted\n", encoding="utf-8")
    dirty = snapshot_tree(project)

    with pytest.raises(ReconciliationError):
        assistant.build_assistant_prepare_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
        )

    assert snapshot_tree(project) == dirty


def test_external_symlink_project_is_refused_and_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    outside = tmp_path / "outside-agent.md"
    outside.write_text("outside bytes\n", encoding="utf-8")
    agent = project / ".claude/agents/me.md"
    agent.unlink()
    agent.symlink_to(outside)
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(
        ("git", "commit", "-qm", "external symlink fixture"),
        cwd=project,
        check=True,
    )
    symlinked = snapshot_tree(project)

    with pytest.raises(ReconciliationError):
        assistant.build_assistant_prepare_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
        )

    assert snapshot_tree(project) == symlinked
    assert outside.read_bytes() == b"outside bytes\n"


def test_concurrent_session_runs_have_one_winner_and_zero_project_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, machine_builder, census_builder = _fixture(
        tmp_path, monkeypatch
    )
    before = snapshot_tree(project)
    prepare_report, session = _prepare(request, machine_builder, census_builder)
    _valid_fake(monkeypatch, tmp_path, session)

    def run() -> str:
        try:
            assistant.run_assistant_session(
                prepare_report["session_id"], claude_path=FAKE_CLAUDE
            )
        except ReconciliationError:
            return "refused"
        return "ready"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: run(), range(2)))

    assert sorted(outcomes) == ["ready", "refused"]
    assert snapshot_tree(project) == before
