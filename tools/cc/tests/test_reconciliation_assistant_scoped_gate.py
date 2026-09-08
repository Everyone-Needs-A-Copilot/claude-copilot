"""New coverage for Fix (a) section 5.3: the bounded Claude Code assistant
preparation gate (`reconciliation_assistant.py::_fresh_context`) must scope
machine unverifiability to the request's own components the same way the
coordinator's `plan`/`apply`/`verify` reports do.

Companion to `test_reconciliation_assistant_product.py`, which stays
untouched (existing tests are read-only). That file's full fixture builds a
real signed candidate catalog through subprocess-driven fake-Claude
sessions; this file unit-tests `_fresh_context` directly -- the exact
function Fix (a) section 5.3 changes -- without needing that heavier
end-to-end harness.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from cc.core.ecosystem import reconciliation as coordinator  # noqa: E402
from cc.core.ecosystem import reconciliation_assistant as assistant  # noqa: E402
from cc.core.ecosystem.machine_assessment import MachineVerification  # noqa: E402
from cc.core.ecosystem.reconciliation_types import (  # noqa: E402
    parse_reconciliation_request,
)


def _request(components: list[str]):
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": "/projects/example", "components": components}],
        }
    )


def _machine() -> dict[str, Any]:
    return {
        "state": "could-not-verify",
        "helper": {
            "state": "ready",
            "version": "2.6.0",
            "path": "/usr/local/bin/cc",
            "detail": "The helper is available.",
        },
        "frameworks": [
            {
                "component": "claude",
                "state": "ready",
                "path": "/claude-framework",
                "version": "5.13.3",
                "detail": "The Claude framework is ready.",
            },
            {
                "component": "codex",
                "state": "could-not-verify",
                "path": "/codex-framework",
                "version": None,
                "detail": (
                    "The configured Codex framework source cannot supply a "
                    "verified reconciliation recipe."
                ),
            },
        ],
        "configuration": {
            "state": "ready",
            "path": "/config.json",
            "approved_roots": ["/projects"],
            "detail": "The machine configuration is readable.",
        },
        "authentication": {
            "state": "signed-in",
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
        "blockers": [
            {
                "code": "codex-framework-recipe-source-unverified",
                "responsible_actor": "ecosystem-owner",
                "evidence": [],
                "next_action": "Restore the authoritative Codex recipe source.",
            }
        ],
        "next_action": "Nothing needs to be changed.",
    }


def _project(components: list[str]) -> dict[str, Any]:
    all_components = ["claude", "codex"]
    return {
        "path": "/projects/example",
        "root": "/projects",
        "name": "example",
        "inspection_id": "sha256:" + ("a" * 64),
        "presence": "both" if set(components) == {"claude", "codex"} else "claude-only",
        "route": "ready",
        "selected_components": list(components),
        "components": [
            {
                "component": component,
                "state": "ready" if component in components else "not-selected",
                "selected": component in components,
                "recommended": component in components,
                "recommendation_reason": f"{component.title()} is ready.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            }
            for component in all_components
        ],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def test_assistant_prepare_scopes_machine_block_to_requested_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine()
    verification = MachineVerification(frozenset({"codex"}), False)
    monkeypatch.setattr(
        coordinator, "_default_verified_machine_builder", lambda: (machine, verification)
    )

    claude_only_project = _project(["claude"])
    claude_only_request = _request(["claude"])
    returned_machine, returned_projects = assistant._fresh_context(
        claude_only_request,
        census_builder=lambda **_kwargs: [claude_only_project],
    )
    assert returned_machine is machine
    assert [project["path"] for project in returned_projects] == ["/projects/example"]

    codex_project = _project(["codex"])
    codex_request = _request(["codex"])
    with pytest.raises(Exception) as excinfo:
        assistant._fresh_context(
            codex_request,
            census_builder=lambda **_kwargs: [codex_project],
        )
    assert getattr(excinfo.value, "code", None) == "assistant-machine-blocked"


def test_assistant_prepare_fails_closed_for_an_injected_bare_dict_machine_builder() -> (
    None
):
    """Guards `_conservative_verification` on the assistant path too: an
    injected bare-dict `machine_builder` (no attribution) must still block a
    claude-only request when the machine is could-not-verify."""
    machine = _machine()
    project = _project(["claude"])
    request = _request(["claude"])

    with pytest.raises(Exception) as excinfo:
        assistant._fresh_context(
            request,
            machine_builder=lambda: machine,
            census_builder=lambda **_kwargs: [project],
        )
    assert getattr(excinfo.value, "code", None) == "assistant-machine-blocked"
