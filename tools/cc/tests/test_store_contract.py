from __future__ import annotations

import json
import subprocess

from cc.commands.store import build_store_verify_report


def _config():
    return {
        "org": "Example-Org",
        "store": {
            "status": "connected",
            "type": "infisical",
            "endpoint": "https://secrets.example.test",
            "workspace_id": "workspace-1",
            "environment": "prod",
            "secret_path": "/shared",
            "broker_url": "https://access.example.test",
            "broker_issuer": "https://access.example.test",
            "broker_audience": "https://secrets.example.test",
            "team_scopes": [
                {
                    "team": "everyone",
                    "scope": "shared",
                    "environment": "prod",
                    "secret_path": "/shared",
                    "access": "read",
                    "identity_id": "identity-shared",
                }
            ],
        },
    }


def test_store_verify_requires_positive_and_negative_live_evidence():
    observed = []

    def run(args):
        observed.append(tuple(args))
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "schema_version": "1.0",
                    "result": "ready",
                    "detail": "ready",
                    "auth_mode": "github-broker",
                    "positive_read": True,
                    "negative_denied": True,
                    "secret_count": 8,
                    "read_only": True,
                }
            ),
            "",
        )

    report = build_store_verify_report(run=run, ecosystem_cfg=_config())

    assert report["result"] == "ready"
    assert all(report["checks"].values())
    assert report["evidence"] == {
        "auth_mode": "github-broker",
        "secret_count": 8,
        "exit_code": 0,
    }
    command = observed[0]
    assert command[:5] == ("copilot", "infisical", "--json", "access", "verify")
    assert "--negative-path" in command
    assert "--scope" in command


def test_store_verify_fails_closed_when_negative_scope_is_readable():
    def run(args):
        return subprocess.CompletedProcess(
            args,
            1,
            json.dumps(
                {
                    "result": "unsafe",
                    "detail": "Shared access reached a path that should have been denied.",
                    "auth_mode": "github-broker",
                    "positive_read": True,
                    "negative_denied": False,
                    "secret_count": 8,
                    "read_only": False,
                }
            ),
            "",
        )

    report = build_store_verify_report(run=run, ecosystem_cfg=_config())

    assert report["result"] == "unsafe"
    assert report["checks"]["positive_read"] is True
    assert report["checks"]["negative_denied"] is False


def test_store_verify_never_runs_with_unbounded_or_writable_policy():
    cfg = _config()
    cfg["store"]["team_scopes"][0]["access"] = "write"

    def run(_args):
        raise AssertionError("verification must not run")

    report = build_store_verify_report(run=run, ecosystem_cfg=cfg)

    assert report["result"] == "not-configured"
    assert report["checks"]["policy_valid"] is False


def test_store_verify_never_copies_underlying_stderr_into_report():
    marker = "secret-value-that-must-not-leak"

    def run(args):
        return subprocess.CompletedProcess(args, 1, "not-json", marker)

    report = build_store_verify_report(run=run, ecosystem_cfg=_config())

    assert report["result"] == "unavailable"
    assert marker not in json.dumps(report)
