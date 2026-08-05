"""WS-A-style contract test for `cc connections --json` (WP-388/389/390
stage B, task 221): must validate against the vendored copilot-control-tower
`connections.schema.json`, must never claim `secret_state: "ready"` for a
store/any-hinted secret this run could not actually verify present, and
must never let a secret VALUE (as opposed to a name) reach the payload.

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/connections.schema.json (see
test_freshness_contract.py for the identical precedent this mirrors).

Every `run` fake below is a pure function -- no real `copilot`/Infisical
subprocess is ever invoked by this suite.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from cc.commands.connections import build_connections_report
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _connections_validator() -> Draft202012Validator:
    connections_schema = _load_schema("connections.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (connections_schema["$id"], Resource.from_contents(connections_schema)),
        ]
    )
    return Draft202012Validator(connections_schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _connections_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


_CONNECTED_STORE_CFG = {
    "org": "Acme",
    "store": {
        "status": "connected",
        "type": "infisical",
        "workspace_id": "ws-1",
        "environment": "prod",
        "secret_path": "/shared",
    },
}


def _layers_payload(services: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "component": "cli",
        "manifest": {"path": "/tmp/copilot.layers.yml", "cli_layers_resolved": True},
        "chain": [],
        "services": services,
    }


def _cp(args: Sequence[str], returncode: int, stdout: str, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def _fake_run(
    *,
    layers_services: list[dict[str, Any]],
    secret_keys: list[str] | None = None,
    layers_returncode: int = 0,
    secret_list_returncode: int = 0,
    secret_list_stderr: str = "",
) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if tuple(args[:3]) == ("copilot", "--json", "layers"):
            if layers_returncode != 0:
                return _cp(args, layers_returncode, "", "layers failed")
            return _cp(args, 0, json.dumps(_layers_payload(layers_services)))
        if tuple(args[:4]) == ("copilot", "infisical", "--json", "secret"):
            if secret_list_returncode != 0:
                return _cp(args, secret_list_returncode, "", secret_list_stderr or "unreachable")
            payload = [{"secretKey": key} for key in (secret_keys or [])]
            return _cp(args, 0, json.dumps(payload))
        raise AssertionError(f"unexpected run() call: {args}")

    return run


def test_ready_service_with_no_required_secret_validates():
    services = [
        {"name": "git", "help": "Git ops", "tier": "org-internal", "mode": "adopt", "id": "git", "requires_secret": [], "store_scope": None}
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    _validate(report)
    assert report["result"] == "ok"
    assert report["org"] == "Acme"
    assert report["store"] == {
        "type": "infisical",
        "reachable": True,
        "scope": "prod:/shared",
        "detail": None,
        "diagnostic": None,
    }
    assert report["connections"] == [
        {
            "id": "git",
            "name": "git",
            "description": "Git ops",
            "tier": "org-internal",
            "mode": "adopt",
            "requires_secret": [],
            "store_scope": None,
            "secret_state": "ready",
            "missing": [],
        }
    ]


def test_present_secret_reads_ready():
    services = [
        {
            "name": "coolify",
            "help": "Coolify infrastructure management",
            "tier": "org-internal",
            "mode": "provides",
            "id": "coolify",
            "requires_secret": [{"name": "COOLIFY_API_KEY", "from": "store"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=["COOLIFY_API_KEY", "OTHER_KEY"]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    _validate(report)
    row = report["connections"][0]
    assert row["secret_state"] == "ready"
    assert row["missing"] == []


def test_missing_secret_names_are_reported_by_name():
    """Generic store-checked names (NOT in `_NEVER_FROM_STORE`) -- exercises
    the plain store-presence path. See the dedicated
    `TestInfisicalBootstrapCredsRouteToKeychain` tests below for the G-1
    bootstrap-name routing behavior, which these names deliberately avoid."""
    services = [
        {
            "name": "sample-store-service",
            "help": "Sample store-backed service",
            "tier": "org-internal",
            "mode": "adopt",
            "id": "sample-store-service",
            "requires_secret": [
                {"name": "SAMPLE_API_KEY", "from": "any"},
                {"name": "SAMPLE_API_SECRET", "from": "any"},
            ],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=["UNRELATED_KEY"]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    _validate(report)
    row = report["connections"][0]
    assert row["secret_state"] == "needs-connect"
    assert row["missing"] == ["SAMPLE_API_KEY", "SAMPLE_API_SECRET"]


def test_partial_presence_reports_only_the_absent_names():
    services = [
        {
            "name": "project",
            "help": "Project Copilot task orchestration",
            "tier": "org-internal",
            "mode": "provides",
            "id": "project",
            "requires_secret": [
                {"name": "PROJECT_COPILOT_API_KEY", "from": "any"},
                {"name": "PROJECT_COPILOT_AGENT_API_SECRET_KEY", "from": "store"},
                {"name": "PROJECT_COPILOT_BROWSE_KEY", "from": "store"},
            ],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(
            layers_services=services,
            secret_keys=["PROJECT_COPILOT_API_KEY", "PROJECT_COPILOT_BROWSE_KEY"],
        ),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    row = report["connections"][0]
    assert row["secret_state"] == "needs-connect"
    assert row["missing"] == ["PROJECT_COPILOT_AGENT_API_SECRET_KEY"]


def test_keychain_only_secret_present_reads_ready():
    """The real `discord` service declares DISCORD_BOT_TOKEN with `from:
    keychain` -- this verb has nothing store-checkable to prove for it, but
    (WP-395 G-1) it IS genuinely presence-checked against the local OS
    keychain rather than assumed ready. Present -> `ready`."""
    services = [
        {
            "name": "discord",
            "help": "Discord handoff threads",
            "tier": "org-internal",
            "mode": "provides",
            "id": "discord",
            "requires_secret": [{"name": "DISCORD_BOT_TOKEN", "from": "keychain"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: True,
    )
    _validate(report)
    row = report["connections"][0]
    assert row["requires_secret"] == [{"name": "DISCORD_BOT_TOKEN", "from": "keychain"}]
    assert row["secret_state"] == "ready"
    assert row["missing"] == []


def test_keychain_only_secret_absent_reads_needs_connect():
    """Same row, but the OS keychain does NOT have the name -- WP-395 G-1's
    whole point is that this state must be verified, never assumed away."""
    services = [
        {
            "name": "discord",
            "help": "Discord handoff threads",
            "tier": "org-internal",
            "mode": "provides",
            "id": "discord",
            "requires_secret": [{"name": "DISCORD_BOT_TOKEN", "from": "keychain"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: False,
    )
    _validate(report)
    row = report["connections"][0]
    assert row["secret_state"] == "needs-connect"
    assert row["missing"] == ["DISCORD_BOT_TOKEN"]


class TestInfisicalBootstrapCredsRouteToKeychain:
    """WP-395 G-1: the Infisical bootstrap pair is `_NEVER_FROM_STORE` --
    even if a tier's overlay still (incorrectly) declares them `from: "any"`
    (the exact live defect this WP fixed at the `cli.overlay.yml` source),
    this verb must route them to the OS keychain, never the shared store,
    so the row can never read a permanent false `needs-connect` again."""

    _SERVICES = [
        {
            "name": "infisical",
            "help": "Infisical secrets management",
            "tier": "org-internal",
            "mode": "adopt",
            "id": "infisical",
            "requires_secret": [
                {"name": "INFISICAL_CLIENT_ID", "from": "any"},
                {"name": "INFISICAL_CLIENT_SECRET", "from": "any"},
            ],
            "store_scope": None,
        }
    ]

    def test_present_in_keychain_reads_ready_even_though_store_cannot_have_them(self):
        # secret_keys deliberately empty -- the store never holds these
        # names (and never will); `ready` must come from the keychain check.
        report = build_connections_report(
            run=_fake_run(layers_services=self._SERVICES, secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
            check_keychain=lambda name: True,
        )
        _validate(report)
        row = report["connections"][0]
        assert row["secret_state"] == "ready"
        assert row["missing"] == []

    def test_absent_from_keychain_reads_needs_connect_by_name(self):
        report = build_connections_report(
            run=_fake_run(layers_services=self._SERVICES, secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
            check_keychain=lambda name: False,
        )
        _validate(report)
        row = report["connections"][0]
        assert row["secret_state"] == "needs-connect"
        assert row["missing"] == ["INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"]

    def test_present_in_the_store_is_never_treated_as_ready(self):
        """Even if the (impossible in practice) store response somehow
        carried these keys, this verb must never consult it for a
        `_NEVER_FROM_STORE` name -- only the keychain result counts."""
        report = build_connections_report(
            run=_fake_run(
                layers_services=self._SERVICES,
                secret_keys=["INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"],
            ),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
            check_keychain=lambda name: False,
        )
        row = report["connections"][0]
        assert row["secret_state"] == "needs-connect"
        assert row["missing"] == ["INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"]

    def test_default_check_keychain_calls_the_security_cli_with_no_value_flag(self, monkeypatch):
        """The production `_check_keychain` default -- verifies the exact
        macOS `security` invocation (presence-only: no `-w`) and that a
        faked subprocess controls the found/not-found outcome, per WP-395
        G-1's "tests with faked subprocess for both found/not-found."."""
        import subprocess as subprocess_module

        calls: list[Sequence[str]] = []

        def fake_subprocess_run(args, **kwargs):
            calls.append(args)
            assert "-w" not in args
            if args[-1] == "INFISICAL_CLIENT_ID":
                return subprocess_module.CompletedProcess(args, 0, "found\n", "")
            return subprocess_module.CompletedProcess(args, 44, "", "not found")

        monkeypatch.setattr(
            "cc.commands.connections.subprocess.run", fake_subprocess_run
        )
        report = build_connections_report(
            run=_fake_run(layers_services=self._SERVICES, secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
        )
        row = report["connections"][0]
        assert row["secret_state"] == "needs-connect"
        assert row["missing"] == ["INFISICAL_CLIENT_SECRET"]
        assert len(calls) == 2
        assert all(c[:4] == ["security", "find-generic-password", "-s", "copilot-cli"] for c in calls)


def test_store_unreachable_reads_no_store_with_every_required_name_listed():
    """WP-395 G-2: the store's underlying call failure must never leak its
    raw stderr into the human-facing `detail` -- `cc` authors a
    plain-language, actor-routed sentence instead, and keeps the raw text
    only in the additive, machine-only `diagnostic` field."""
    services = [
        {
            "name": "brevo",
            "help": "Brevo email marketing",
            "tier": "org-internal",
            "mode": "provides",
            "id": "brevo",
            "requires_secret": [{"name": "BREVO_API_KEY", "from": "any"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_list_returncode=1, secret_list_stderr="network unreachable"),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    _validate(report)
    assert report["result"] == "ok"
    assert report["store"]["reachable"] is False
    assert report["store"]["detail"] == (
        "This Mac isn't connected to your organization's shared credential "
        "store yet. Your IT admin can set that up — nothing is wrong with "
        "your setup."
    )
    assert "network unreachable" not in report["store"]["detail"]
    assert report["store"]["diagnostic"] == "network unreachable"
    row = report["connections"][0]
    assert row["secret_state"] == "no-store"
    assert row["missing"] == ["BREVO_API_KEY"]


def test_store_unreachable_diagnostic_never_leaks_into_the_json_detail_field():
    """Belt-and-suspenders: no substring of the raw stderr should reach
    `detail` even under a different underlying error message."""
    services = [
        {
            "name": "brevo",
            "help": "Brevo email marketing",
            "tier": "org-internal",
            "mode": "provides",
            "id": "brevo",
            "requires_secret": [{"name": "BREVO_API_KEY", "from": "any"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(
            layers_services=services,
            secret_list_returncode=1,
            secret_list_stderr=(
                "Infisical credentials not configured. Set INFISICAL_CLIENT_ID "
                "and INFISICAL_CLIENT_SECRET in your .env."
            ),
        ),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    assert ".env" not in report["store"]["detail"]
    assert "Set INFISICAL_CLIENT_ID" not in report["store"]["detail"]
    assert ".env" in report["store"]["diagnostic"]


def test_store_deferred_status_reads_no_store_honestly():
    services = [
        {
            "name": "n8n",
            "help": "n8n workflow automation",
            "tier": "org-internal",
            "mode": "provides",
            "id": "n8n",
            "requires_secret": [{"name": "N8N_API_KEY", "from": "any"}],
            "store_scope": None,
        }
    ]
    cfg = {"org": "Acme", "store": {"status": "deferred"}}
    report = build_connections_report(
        run=_fake_run(layers_services=services),
        ecosystem_cfg=cfg,
    )
    _validate(report)
    assert report["result"] == "ok"
    assert report["store"]["type"] is None
    assert report["store"]["reachable"] is False
    row = report["connections"][0]
    assert row["secret_state"] == "no-store"
    assert row["missing"] == ["N8N_API_KEY"]


def test_org_config_unavailable_still_lists_the_roster():
    services = [
        {"name": "git", "help": "Git ops", "tier": "foundation", "mode": "base", "id": "git", "requires_secret": [], "store_scope": None},
        {
            "name": "coolify",
            "help": "Coolify infrastructure management",
            "tier": "org-internal",
            "mode": "provides",
            "id": "coolify",
            "requires_secret": [{"name": "COOLIFY_API_KEY", "from": "store"}],
            "store_scope": None,
        },
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services),
        ecosystem_cfg={},
    )
    _validate(report)
    assert report["result"] == "org-config-unavailable"
    assert report["org"] is None
    assert report["store"] == {
        "type": None,
        "reachable": False,
        "scope": None,
        "detail": report["detail"],
        "diagnostic": None,
    }
    assert len(report["connections"]) == 2
    assert report["connections"][0]["secret_state"] == "ready"  # no secrets required
    assert report["connections"][1]["secret_state"] == "no-store"
    assert report["connections"][1]["missing"] == ["COOLIFY_API_KEY"]


def test_copilot_unavailable_returns_an_empty_honest_roster():
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _cp(args, 127, "", "copilot is not installed.")

    report = build_connections_report(run=run, ecosystem_cfg=_CONNECTED_STORE_CFG)
    _validate(report)
    assert report["result"] == "copilot-unavailable"
    assert report["connections"] == []
    assert report["store"]["reachable"] is False
    assert "copilot is not installed" in report["detail"]


def test_unfamiliar_layers_output_is_also_copilot_unavailable():
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if tuple(args[:3]) == ("copilot", "--json", "layers"):
            return _cp(args, 0, "not json")
        raise AssertionError(args)

    report = build_connections_report(run=run, ecosystem_cfg=_CONNECTED_STORE_CFG)
    assert report["result"] == "copilot-unavailable"
    assert report["connections"] == []


def test_id_and_store_scope_fall_back_for_a_pre_v0_3_2_copilot():
    """N-1 compatibility: an older `copilot --json layers` predates
    id/requires_secret/store_scope entirely -- this row must still project
    cleanly (id falls back to name; requires_secret/store_scope default
    empty/null), mirroring `onboard.py`'s own `.get()`-projection tolerance
    for this exact payload."""
    services = [{"name": "git", "help": "Git ops", "tier": "foundation", "mode": "base"}]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    _validate(report)
    row = report["connections"][0]
    assert row["id"] == "git"
    assert row["requires_secret"] == []
    assert row["store_scope"] is None
    assert row["secret_state"] == "ready"


def test_bare_from_defaults_to_any():
    services = [
        {
            "name": "uspto",
            "help": "USPTO patent and trademark data access",
            "tier": "org-internal",
            "mode": "adopt",
            "id": "uspto",
            "requires_secret": [{"name": "USPTO_CLI_API_KEY"}],
            "store_scope": None,
        }
    ]
    report = build_connections_report(
        run=_fake_run(layers_services=services, secret_keys=["USPTO_CLI_API_KEY"]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
    )
    row = report["connections"][0]
    assert row["requires_secret"] == [{"name": "USPTO_CLI_API_KEY", "from": "any"}]
    assert row["secret_state"] == "ready"


def test_no_secret_value_reaches_the_payload():
    """Only `secretKey` names ever feed this report -- a fake store response
    carrying a `secretValue` must never leak it into any field."""
    services = [
        {
            "name": "coolify",
            "help": "Coolify infrastructure management",
            "tier": "org-internal",
            "mode": "provides",
            "id": "coolify",
            "requires_secret": [{"name": "COOLIFY_API_KEY", "from": "store"}],
            "store_scope": None,
        }
    ]

    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if tuple(args[:3]) == ("copilot", "--json", "layers"):
            return _cp(args, 0, json.dumps(_layers_payload(services)))
        if tuple(args[:4]) == ("copilot", "infisical", "--json", "secret"):
            payload = [{"secretKey": "COOLIFY_API_KEY", "secretValueHidden": True, "secretValue": "top-secret-should-never-leak"}]
            return _cp(args, 0, json.dumps(payload))
        raise AssertionError(args)

    report = build_connections_report(run=run, ecosystem_cfg=_CONNECTED_STORE_CFG)
    serialized = json.dumps(report)
    assert "top-secret-should-never-leak" not in serialized
    assert report["connections"][0]["secret_state"] == "ready"


def test_connections_cmd_json_matches_schema(monkeypatch):
    services = [
        {"name": "git", "help": "Git ops", "tier": "org-internal", "mode": "adopt", "id": "git", "requires_secret": [], "store_scope": None},
        {
            "name": "infisical",
            "help": "Infisical secrets management",
            "tier": "org-internal",
            "mode": "adopt",
            "id": "infisical",
            "requires_secret": [{"name": "INFISICAL_CLIENT_ID", "from": "any"}],
            "store_scope": None,
        },
    ]
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=services, secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config",
        lambda: _CONNECTED_STORE_CFG,
    )
    # WP-395 G-1: INFISICAL_CLIENT_ID is a `_NEVER_FROM_STORE` bootstrap
    # name, so it is now keychain-checked, not store-checked -- pin the
    # keychain outcome rather than let the test depend on this machine's
    # real keychain contents.
    monkeypatch.setattr("cc.commands.connections._check_keychain", lambda name: False)

    result = runner.invoke(app, ["connections", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["result"] == "ok"
    by_name = {c["name"]: c for c in payload["connections"]}
    assert by_name["git"]["secret_state"] == "ready"
    assert by_name["infisical"]["secret_state"] == "needs-connect"


def test_connections_cmd_exits_nonzero_when_copilot_unavailable(monkeypatch):
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _cp(args, 127, "", "copilot is not installed.")

    monkeypatch.setattr("cc.commands.connections._run", run)
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )

    result = runner.invoke(app, ["connections", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["result"] == "copilot-unavailable"


def test_connections_cmd_rich_output_has_two_groups(monkeypatch):
    services = [
        {"name": "git", "help": "Git ops", "tier": "org-internal", "mode": "adopt", "id": "git", "requires_secret": [], "store_scope": None},
        {
            "name": "infisical",
            "help": "Infisical secrets management",
            "tier": "org-internal",
            "mode": "adopt",
            "id": "infisical",
            "requires_secret": [{"name": "INFISICAL_CLIENT_ID", "from": "any"}],
            "store_scope": None,
        },
    ]
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=services, secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config",
        lambda: _CONNECTED_STORE_CFG,
    )
    monkeypatch.setattr("cc.commands.connections._check_keychain", lambda name: False)

    result = runner.invoke(app, ["connections"])
    assert result.exit_code == 0
    assert "Ready to use" in result.output
    assert "Available to connect" in result.output
    assert "git" in result.output
    assert "infisical" in result.output
