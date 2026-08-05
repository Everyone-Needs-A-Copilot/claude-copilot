from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.ecosystem.reconciliation import (
    assess_reconciliation,
    build_plan_report,
    build_verify_report,
)
from cc.core.ecosystem.reconciliation_types import (
    RECONCILIATION_REQUEST_SCHEMA_VERSION,
    RequestValidationError,
    canonical_request_json,
    parse_reconciliation_request,
)
from jsonschema import Draft202012Validator

_SCHEMAS = Path(__file__).parent / "fixtures" / "schemas"


@pytest.mark.parametrize(
    "name", ["reconcile-request.schema.json", "reconcile.schema.json"]
)
def test_reconciliation_schemas_are_valid_and_closed(name: str) -> None:
    schema = json.loads((_SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    if name == "reconcile-request.schema.json":
        assert schema["additionalProperties"] is False


def test_request_requires_explicit_roots_projects_and_components() -> None:
    request = parse_reconciliation_request(
        {
            "schema_version": RECONCILIATION_REQUEST_SCHEMA_VERSION,
            "roots": ["/projects"],
            "projects": [{"path": "/projects/one", "components": ["claude", "codex"]}],
        }
    )

    assert request.roots == ("/projects",)
    assert request.projects[0].components == ("claude", "codex")
    assert canonical_request_json(request) == (
        '{"projects":[{"components":["claude","codex"],'
        '"path":"/projects/one"}],"roots":["/projects"],'
        '"schema_version":"1.0"}'
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(schema_version="2.0"),
        lambda value: value.update(roots=[]),
        lambda value: value["roots"].append("relative"),
        lambda value: value["roots"].append("~/projects"),
        lambda value: value.update(projects=[]),
        lambda value: value["projects"][0].update(components=[]),
        lambda value: value["projects"][0].update(components=["other"]),
        lambda value: value["projects"][0].update(path="relative"),
        lambda value: value["projects"][0].update(extra=True),
    ],
)
def test_request_mutations_fail_before_filesystem_inspection(mutation) -> None:
    payload = {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [{"path": "/projects/one", "components": ["claude"]}],
    }
    mutation(payload)

    with pytest.raises(RequestValidationError):
        parse_reconciliation_request(payload)


def test_request_rejects_duplicate_authority() -> None:
    with pytest.raises(RequestValidationError, match="repeats a root"):
        parse_reconciliation_request(
            {
                "schema_version": "1.0",
                "roots": ["/projects", "/projects/./team/.."],
                "projects": [{"path": "/projects/one", "components": ["claude"]}],
            }
        )
    with pytest.raises(RequestValidationError, match="repeats a project"):
        parse_reconciliation_request(
            {
                "schema_version": "1.0",
                "roots": ["/projects"],
                "projects": [
                    {"path": "/projects/one", "components": ["claude"]},
                    {
                        "path": "/projects/nested/../one",
                        "components": ["codex"],
                    },
                ],
            }
        )


def test_request_normalizes_literal_absolute_paths_without_filesystem_access() -> None:
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["//projects/./team/.."],
            "projects": [
                {
                    "path": "/projects/nested/../one/.",
                    "components": ["claude"],
                }
            ],
        }
    )

    assert request.roots == ("/projects",)
    assert request.projects[0].path == "/projects/one"


def test_request_accepts_only_selected_component_scoped_reviewed_recipe_ids() -> None:
    payload = {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [
            {
                "path": "/projects/one",
                "components": ["claude", "codex"],
                "recipe_ids": {
                    "claude": "claude.customized-preserve-entry.v1",
                    "codex": "codex.customized-preserve-entry.v1",
                },
            }
        ],
    }
    schema = json.loads(
        (_SCHEMAS / "reconcile-request.schema.json").read_text(encoding="utf-8")
    )
    request = parse_reconciliation_request(payload)

    assert not list(Draft202012Validator(schema).iter_errors(payload))
    assert dict(request.projects[0].recipe_ids) == payload["projects"][0]["recipe_ids"]

    for invalid_recipe_ids in (
        {"codex": "codex.customized-preserve-entry.v1"},
        {"claude": "UPPERCASE"},
        {"claude": "bad\x00id"},
    ):
        invalid = json.loads(json.dumps(payload))
        invalid["projects"][0]["components"] = ["claude"]
        invalid["projects"][0]["recipe_ids"] = invalid_recipe_ids
        with pytest.raises(RequestValidationError):
            parse_reconciliation_request(invalid)


def test_request_canonicalizes_equivalent_component_order_for_one_fingerprint() -> None:
    forward = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {
                    "path": "/projects/one",
                    "components": ["claude", "codex"],
                }
            ],
        }
    )
    reverse = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {
                    "path": "/projects/one",
                    "components": ["codex", "claude"],
                }
            ],
        }
    )

    assert reverse.projects[0].components == ("claude", "codex")
    assert canonical_request_json(reverse) == canonical_request_json(forward)


def test_request_rejects_control_characters_in_literal_paths() -> None:
    payload = {
        "schema_version": "1.0",
        "roots": ["/projects\x00unsafe"],
        "projects": [{"path": "/projects/one", "components": ["claude"]}],
    }
    schema = json.loads(
        (_SCHEMAS / "reconcile-request.schema.json").read_text(encoding="utf-8")
    )

    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(RequestValidationError, match="control character"):
        parse_reconciliation_request(payload)


def test_request_schema_and_parser_reject_tilde_expansion() -> None:
    payload = {
        "schema_version": "1.0",
        "roots": ["~/projects"],
        "projects": [{"path": "~/projects/one", "components": ["claude"]}],
    }
    schema = json.loads(
        (_SCHEMAS / "reconcile-request.schema.json").read_text(encoding="utf-8")
    )

    assert list(Draft202012Validator(schema).iter_errors(payload))
    with pytest.raises(RequestValidationError, match="literal absolute path"):
        parse_reconciliation_request(payload)


def _machine() -> dict:
    return {
        "state": "ready",
        "helper": {
            "state": "ready",
            "version": "2.6.0",
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
            "approved_roots": ["/projects"],
            "detail": "The machine configuration is readable.",
        },
        "authentication": {
            "state": "ready",
            "credential_state": "present",
            "detail": "Sign-in is available.",
        },
        "connectivity": {"state": "online", "detail": "Network checks passed."},
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


def _project(*, selected: bool = False) -> dict:
    opaque = "sha256:" + ("a" * 64)
    return {
        "path": "/projects/one",
        "root": "/projects",
        "name": "one",
        "scope": {"kind": "product-project"},
        "inspection_id": opaque,
        "presence": "both",
        "route": "ready",
        "selected_components": ["claude"] if selected else [],
        "components": [
            {
                "component": component,
                "state": "ready",
                "selected": selected and component == "claude",
                "recommended": True,
                "recommendation_reason": f"{component.title()} is available.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            }
            for component in ("claude", "codex")
        ],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _response_errors(report: dict) -> list:
    schema = json.loads(
        (_SCHEMAS / "reconcile.schema.json").read_text(encoding="utf-8")
    )
    return list(Draft202012Validator(schema).iter_errors(report))


def _definition_errors(name: str, payload: dict) -> list:
    schema = json.loads(
        (_SCHEMAS / "reconcile.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}
    )
    return list(validator.iter_errors(payload))


@pytest.mark.parametrize("mutation", ["duplicate", "reversed"])
def test_project_components_require_exact_claude_codex_identity(mutation: str) -> None:
    project = _project()
    assert not _definition_errors("project", project)
    if mutation == "duplicate":
        project["components"][1] = dict(project["components"][0])
    else:
        project["components"].reverse()

    assert _definition_errors("project", project)


@pytest.mark.parametrize("mutation", ["duplicate", "reversed"])
def test_machine_frameworks_require_exact_claude_codex_identity(mutation: str) -> None:
    machine = _machine()
    assert not _definition_errors("machine", machine)
    if mutation == "duplicate":
        machine["frameworks"][1] = dict(machine["frameworks"][0])
    else:
        machine["frameworks"].reverse()

    assert _definition_errors("machine", machine)


@pytest.mark.parametrize("mutation", ["duplicate", "reversed"])
def test_plan_sources_require_exact_claude_codex_identity_when_both_present(
    mutation: str,
) -> None:
    plan = {
        "path": "/projects/one",
        "inspection_id": "sha256:" + ("a" * 64),
        "recipes": [
            {"component": "claude", "recipe_id": "claude-project-setup-v1"},
            {"component": "codex", "recipe_id": "codex-project-setup-v1"},
        ],
        "sources": [
            {
                "component": "claude",
                "version": "5.13.3",
                "fingerprint": "sha256:" + ("b" * 64),
            },
            {
                "component": "codex",
                "version": "0.6.1",
                "fingerprint": "sha256:" + ("c" * 64),
            },
        ],
        "operations": [],
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration", "codex-project-integration"],
    }
    assert not _definition_errors("projectPlan", plan)
    if mutation == "duplicate":
        plan["sources"][1]["component"] = "claude"
    else:
        plan["sources"].reverse()

    assert _definition_errors("projectPlan", plan)


def test_assess_and_verify_reports_validate_against_closed_schema() -> None:
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": "/projects/one", "components": ["claude"]}],
        }
    )
    assess = assess_reconciliation(
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        run_id="run_" + ("1" * 32),
    )
    verify = build_verify_report(
        request,
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project(selected=True)],
        run_id="run_" + ("2" * 32),
    )

    assert not _response_errors(assess)
    assert not _response_errors(verify)
    assert assess["summary"]["project_counts"] == {
        "ready": 1,
        "copilot-not-present": 0,
        "safe-setup-available": 0,
        "safe-update-available": 0,
        "customized-guided-route": 0,
        "held": 0,
        "owner-decision": 0,
        "could-not-verify": 0,
        "excluded": 0,
        "source-unavailable": 0,
        "ecosystem-managed": 0,
        "total": 1,
    }


def test_plan_report_uses_random_store_authority_not_state_hash_as_id() -> None:
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": "/projects/one", "components": ["claude"]}],
        }
    )
    public_plan = {
        "path": "/projects/one",
        "inspection_id": "sha256:" + ("a" * 64),
        "recipes": [{"component": "claude", "recipe_id": "claude-project-setup-v1"}],
        "sources": [],
        "operations": [],
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration"],
    }
    captured: dict = {}

    def issue(**kwargs):
        captured.update(kwargs)
        return {
            "id": "plan_" + ("3" * 32),
            "expires_at": "2026-08-04T18:15:00Z",
        }

    report = build_plan_report(
        request,
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project(selected=True)],
        plan_builder=lambda **_kwargs: (
            [public_plan],
            [{"path": "/projects/one", "operations": []}],
        ),
        plan_issuer=issue,
        run_id="run_" + ("4" * 32),
    )

    assert not _response_errors(report)
    assert report["plan_id"] == "plan_" + ("3" * 32)
    assert captured["fresh_plan_fingerprint"].startswith("sha256:")
    assert captured["request_fingerprint"].startswith("sha256:")
    assert captured["schema_version"] == "2.0"
