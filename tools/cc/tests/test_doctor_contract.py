"""WS-A contract test: `cc doctor --json` must validate against the vendored
copilot-control-tower `doctor.schema.json`, and must never emit a false
`healthy` verdict.

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copies live in tests/fixtures/schemas/ (see the `$comment` header in
each vendored file) so this test does not depend on a sibling checkout being
present on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _doctor_validator() -> Draft202012Validator:
    doctor_schema = _load_schema("doctor.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (doctor_schema["$id"], Resource.from_contents(doctor_schema)),
        ]
    )
    return Draft202012Validator(doctor_schema, registry=registry)


def _invoke_doctor_json() -> tuple[dict, int]:
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.output)
    return payload, result.exit_code


def test_doctor_json_validates_against_contract_schema():
    """`cc doctor --json` output must be a valid doctor.schema.json instance."""
    payload, exit_code = _invoke_doctor_json()

    validator = _doctor_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)

    # Exit code must be one of the WS-A contract's 0 (clean) / 1 (any fail
    # checker) / 2 (environment error) values -- never the legacy 3.
    assert exit_code in (0, 1, 2)


def test_doctor_json_false_healthy_is_impossible():
    """A `healthy` status must never coexist with a fail checker or offline=True.

    This mirrors the schema's own `allOf` invariant but is asserted directly
    against the real CLI output (not just a hand-built fixture) so a
    regression in build_doctor_report()'s status computation fails loudly
    here, independent of the schema check above.
    """
    payload, _ = _invoke_doctor_json()

    if payload["status"] == "healthy":
        assert payload["offline"] is False
        assert not any(c["severity"] == "fail" for c in payload["checkers"])
        assert not any(
            a.get("state") in ("expired", "revoked") for a in payload.get("auth", [])
        )


@pytest.mark.parametrize(
    "checkers,expect_healthy_allowed",
    [
        ([{"id": "x", "severity": "pass", "destructive": False}], True),
        ([{"id": "x", "severity": "fail", "destructive": False}], False),
    ],
)
def test_schema_rejects_healthy_with_fail_checker(checkers, expect_healthy_allowed):
    """Directly exercise the vendored schema's false-Healthy guard."""
    validator = _doctor_validator()
    instance = {
        "schema_version": "1.0",
        "host": "test-host",
        "score": 100,
        "status": "healthy",
        "offline": False,
        "checkers": checkers,
        "auth": [],
    }
    errors = list(validator.iter_errors(instance))
    if expect_healthy_allowed:
        assert not errors
    else:
        assert errors
