"""New coverage for the never-serialized `MachineVerification` attribution.

Companion to `test_machine_assessment.py` (which stays untouched -- existing
tests are read-only). This file only exercises the new
`build_machine_assessment_with_verification` split and the legacy
`build_machine_assessment` wrapper's shape compatibility.

See docs/30-operations/12-cse-gap-closure-and-release-handoff.md and the
layer-fix design (`Fix (a)`) this covers: machine unverifiability must be
attributable PER COMPONENT so a claude-only request is never blocked by an
unrelated Codex source problem, while staying fail-closed for every other
contributor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from cc.core.ecosystem.machine_assessment import (
    MachineVerification,
    build_machine_assessment,
    build_machine_assessment_with_verification,
)
from jsonschema import Draft202012Validator

# Reuse the established fixture from test_machine_assessment.py (untouched --
# existing tests are read-only) the same way other suites in this package
# import sibling test modules directly by file location.
sys.path.insert(0, str(Path(__file__).parent))

from test_machine_assessment import _healthy_context, _validate_machine  # noqa: E402


def test_framework_unknown_is_attributed_to_its_component(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    kwargs = dict(context["kwargs"])
    kwargs["framework_source_validator"] = (
        lambda component, path: component != "codex"
    )

    machine, verification = build_machine_assessment_with_verification(**kwargs)

    _validate_machine(machine)
    assert isinstance(verification, MachineVerification)
    assert verification.unknown_framework_components == frozenset({"codex"})
    assert verification.unknown_beyond_frameworks is False
    assert machine["state"] == "could-not-verify"
    assert "codex-framework-recipe-source-unverified" in {
        item["code"] for item in machine["blockers"]
    }
    codex_row = next(
        row for row in machine["frameworks"] if row["component"] == "codex"
    )
    assert codex_row["state"] == "could-not-verify"
    claude_row = next(
        row for row in machine["frameworks"] if row["component"] == "claude"
    )
    assert claude_row["state"] == "ready"


def test_non_framework_unknown_sets_beyond_frameworks(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    kwargs = dict(context["kwargs"])

    def raising_doctor_builder() -> dict[str, Any]:
        raise RuntimeError("doctor is unavailable in this test")

    kwargs["doctor_builder"] = raising_doctor_builder

    machine, verification = build_machine_assessment_with_verification(**kwargs)

    _validate_machine(machine)
    assert verification.unknown_beyond_frameworks is True
    assert verification.unknown_framework_components == frozenset()
    assert machine["state"] == "could-not-verify"


def test_silent_connections_failure_sets_beyond_frameworks(tmp_path: Path) -> None:
    """The connections-builder failure branch sets could-not-verify with NO
    blocker emitted -- the exact regression this refactor must not reintroduce
    by deriving attribution from `machine["blockers"]` instead of tracking it
    directly."""
    context = _healthy_context(tmp_path)
    kwargs = dict(context["kwargs"])

    def raising_connections_builder() -> dict[str, Any]:
        raise RuntimeError("connections are unavailable in this test")

    kwargs["connections_builder"] = raising_connections_builder

    machine, verification = build_machine_assessment_with_verification(**kwargs)

    _validate_machine(machine)
    assert verification.unknown_beyond_frameworks is True
    assert verification.unknown_framework_components == frozenset()
    assert machine["state"] == "could-not-verify"
    # The `except Exception: connections = None` branch that actually catches
    # this failure (machine_assessment.py's build function, connections
    # try/except) emits NO blocker of its own -- any "connections-unavailable"
    # code present in `blockers` here comes from the separate, later
    # `_connection_blockers(connections)` call fed the resulting `None`, a
    # DIFFERENT code path with the SAME symptom. A caller deriving
    # attribution from blocker codes alone cannot tell these apart; the
    # explicit `MachineVerification.unknown_beyond_frameworks` flag can.
    assert verification.unknown_framework_components == frozenset()


def test_legacy_build_machine_assessment_shape_is_unchanged(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)

    assessment = build_machine_assessment(**context["kwargs"])

    schema_path = Path(__file__).parent / "fixtures/schemas/reconcile.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    machine_def = schema["$defs"]["machine"]
    assert set(assessment.keys()) == set(machine_def["required"])
    Draft202012Validator(
        {"$ref": "#/$defs/machine", "$defs": schema["$defs"]}
    ).validate(assessment)
    assert "MachineVerification" not in json.dumps(assessment)
