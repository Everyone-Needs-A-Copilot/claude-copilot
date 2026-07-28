"""WS-A contract test: `cc layers [join] --json` (Stream-C, D7.1 -- proposed
contract addition, not yet in upstream WS-A scope).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/layers.schema.json (same precedent as
test_update_contract.py / test_deprovision_contract.py).

HARD SAFETY RULE: `cc layers join` MATERIALIZES files and never makes a
real network call. Every test here goes through either the build/execute
functions directly or the Typer `CliRunner` (in-process, no subprocess
against the real machine) with EVERY root -- identity root, ecosystem
config, manifest path, mirror root, materialize root, lockfile path, and
the advisory `copilot.lock` mutex path -- injected/monkeypatched to
`tmp_path`, and a fake `get_json`/`get_secret` transport standing in for
GitHub/Keychain. The `_no_real_home` autouse fixture below additionally
asserts `Path.home()` is never resolved as a fallback anywhere in the call
graph. `cc layers`/`cc layers join` is never run against a real machine or
a real network in this file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml
from cc.commands.layers import (
    GITHUB_KEYCHAIN_SERVICE,
    build_layers_report,
    compute_layers_join_exit_code,
    execute_layers_join,
    layers_app,
)
from cc.core.ecosystem import entitlement
from cc.core.ecosystem.policy import permissive_policy
from cc.core.locking import copilot_lock
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _layers_validator() -> Draft202012Validator:
    schema = _load_schema("layers.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (schema["$id"], Resource.from_contents(schema)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _layers_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "layers contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _make_source_repo(tmp_path: Path, files: dict[str, str], *, name: str = "source-repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, check=True)
    for relpath, content in files.items():
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _write_ecosystem_yaml(tmp_path: Path, depts: list[dict[str, Any]]) -> Path:
    path = tmp_path / "ecosystem.yml"
    path.write_text(yaml.safe_dump({"departments": depts}), encoding="utf-8")
    return path


def _fake_get_secret_factory(tokens: dict[str, str]):
    def _fake(account: str, *, service: str, **_kwargs) -> Optional[str]:
        assert service == GITHUB_KEYCHAIN_SERVICE
        return tokens.get(account)

    return _fake


def _get_json_status(status: Optional[int]):
    def _fake(url: str, token: str) -> Optional[int]:
        return status

    return _fake


IDENTITY = {"login": "octocat", "scopes": "repo", "obtained_at": "2026-07-16T00:00:00Z"}
TOKENS = {"octocat": "s3cr3t-token"}


# ---------------------------------------------------------------------------
# entitlement.repo_accessible() -- 200/404/network-fail -> True/False/None
# ---------------------------------------------------------------------------


def test_repo_accessible_200_is_entitled():
    assert entitlement.repo_accessible("org/repo", "tok", get_json=_get_json_status(200)) is True


def test_repo_accessible_404_is_not_entitled():
    assert entitlement.repo_accessible("org/repo", "tok", get_json=_get_json_status(404)) is False


def test_repo_accessible_403_is_not_entitled():
    assert entitlement.repo_accessible("org/repo", "tok", get_json=_get_json_status(403)) is False


def test_repo_accessible_network_failure_is_none():
    assert entitlement.repo_accessible("org/repo", "tok", get_json=_get_json_status(None)) is None


def test_repo_accessible_no_token_is_none_without_calling_transport():
    def _boom(*_a, **_k):
        raise AssertionError("should never call transport without a token")

    assert entitlement.repo_accessible("org/repo", None, get_json=_boom) is None


# ---------------------------------------------------------------------------
# build_layers_report() -- list
# ---------------------------------------------------------------------------


def test_list_report_entitled_true_and_joined_false_validates_against_schema():
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _layers=[],
        _get_json=_get_json_status(200),
    )
    _validate(report)
    assert report["layers"] == [
        {
            "tier": "department",
            "id": "finance",
            "name": "Finance",
            "repo": "org/dept-finance",
            "entitled": True,
            "joined": False,
        }
    ]


def test_list_report_not_entitled():
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _layers=[],
        _get_json=_get_json_status(404),
    )
    _validate(report)
    assert report["layers"][0]["entitled"] is False
    assert "reason" not in report["layers"][0]


def test_list_report_joined_true_when_present_in_local_manifest():
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _layers=[
            {
                "id": "finance",
                "role": "department",
                "rank": 100,
                "product": "cli",
                "source": {"repo": "org/dept-finance"},
                "auth": "anon",
                "activation": "always",
            }
        ],
        _get_json=_get_json_status(200),
    )
    _validate(report)
    assert report["layers"][0]["joined"] is True


def test_list_report_signed_out_is_entitled_null_reason_signed_out():
    report = build_layers_report(
        _identity={},
        _get_secret=_fake_get_secret_factory({}),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _layers=[],
        _get_json=_get_json_status(200),
    )
    _validate(report)
    assert report["layers"][0]["entitled"] is None
    assert report["layers"][0]["reason"] == "signed-out"


def test_list_report_offline_is_entitled_null_reason_offline():
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _layers=[],
        _get_json=_get_json_status(None),
    )
    _validate(report)
    assert report["layers"][0]["entitled"] is None
    assert report["layers"][0]["reason"] == "offline"


def test_list_report_empty_catalog_is_valid_never_crashes():
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[],
        _layers=[],
    )
    _validate(report)
    assert report["layers"] == []


def test_list_report_missing_local_manifest_file_is_empty_not_a_crash(tmp_path):
    """A `layers.manifest` path that has never been written yet (no join
    has ever happened on this machine) must degrade to `joined: False`
    everywhere, never raise."""
    missing_manifest = tmp_path / "does-not-exist" / "copilot.layers.yml"
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=missing_manifest,
        _get_json=_get_json_status(200),
    )
    _validate(report)
    assert report["layers"][0]["joined"] is False


def test_list_report_end_to_end_tmp_ecosystem_yaml(tmp_path):
    ecosystem_path = _write_ecosystem_yaml(
        tmp_path,
        [{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
    )
    report = build_layers_report(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _ecosystem_cfg_path=ecosystem_path,
        _layers=[],
        _get_json=_get_json_status(200),
    )
    _validate(report)
    assert report["layers"][0]["id"] == "finance"


# ---------------------------------------------------------------------------
# build_layers_join_report() / execute_layers_join() -- join happy path
# ---------------------------------------------------------------------------


def test_join_happy_path_materializes_and_validates_against_schema(tmp_path):
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"}, name="dept-finance")
    ecosystem_path = _write_ecosystem_yaml(
        tmp_path, [{"id": "finance", "name": "Finance", "repo": str(source_repo)}]
    )
    manifest_path = tmp_path / "copilot.layers.yml"
    lockfile_path = tmp_path / "copilot.lock.json"
    mirror_root = tmp_path / "mirrors"
    materialize_root = tmp_path / "materialize"
    lock_mutex_path = tmp_path / "copilot.lock"

    report, exit_code = execute_layers_join(
        "finance",
        _lock_path=lock_mutex_path,
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _ecosystem_cfg_path=ecosystem_path,
        _manifest_path=manifest_path,
        _get_json=_get_json_status(200),
        _mirror_root=mirror_root,
        _materialize_root=materialize_root,
        _lockfile_path=lockfile_path,
        _lock_write_path=lockfile_path,
        _policy=permissive_policy,
    )

    _validate(report)
    assert report["result"] == "joined"
    assert report["tier"] == "department"
    assert report["id"] == "finance"
    assert report["synced_lock_sha"]
    assert exit_code == 0

    # The layer was actually added to the local manifest...
    written_manifest = yaml.safe_load(manifest_path.read_text())
    assert written_manifest["layers"][0]["id"] == "finance"

    # ...and its content was actually materialized into materialize_root.
    materialized = materialize_root / "agents" / "sec.md"
    assert materialized.exists()
    assert materialized.read_text() == "v1"

    # ...and the lockfile was actually written.
    assert lockfile_path.exists()
    written_lock = json.loads(lockfile_path.read_text())
    assert written_lock["finance"]["agents"]["sec"]


def test_join_second_call_is_already_joined(tmp_path):
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"}, name="dept-finance")
    ecosystem_path = _write_ecosystem_yaml(
        tmp_path, [{"id": "finance", "name": "Finance", "repo": str(source_repo)}]
    )
    manifest_path = tmp_path / "copilot.layers.yml"
    lockfile_path = tmp_path / "copilot.lock.json"
    mirror_root = tmp_path / "mirrors"
    materialize_root = tmp_path / "materialize"

    common_kwargs = dict(
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _ecosystem_cfg_path=ecosystem_path,
        _manifest_path=manifest_path,
        _get_json=_get_json_status(200),
        _mirror_root=mirror_root,
        _materialize_root=materialize_root,
        _lockfile_path=lockfile_path,
        _lock_write_path=lockfile_path,
        _policy=permissive_policy,
    )

    first, first_exit = execute_layers_join(
        "finance", _lock_path=tmp_path / "copilot.lock.1", **common_kwargs
    )
    assert first["result"] == "joined"
    assert first_exit == 0

    second, second_exit = execute_layers_join(
        "finance", _lock_path=tmp_path / "copilot.lock.2", **common_kwargs
    )
    _validate(second)
    assert second["result"] == "already-joined"
    assert second_exit == 0


def test_join_not_entitled_is_exit_zero_and_never_writes_manifest(tmp_path):
    manifest_path = tmp_path / "copilot.layers.yml"

    report, exit_code = execute_layers_join(
        "finance",
        _lock_path=tmp_path / "copilot.lock",
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=manifest_path,
        _get_json=_get_json_status(404),
    )

    _validate(report)
    assert report["result"] == "not-entitled"
    assert exit_code == 0
    assert not manifest_path.exists()


def test_join_unknown_layer_id_is_error_exit_one(tmp_path):
    report, exit_code = execute_layers_join(
        "does-not-exist",
        _lock_path=tmp_path / "copilot.lock",
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=tmp_path / "copilot.layers.yml",
        _get_json=_get_json_status(200),
    )

    _validate(report)
    assert report["result"] == "error"
    assert exit_code == 1


def test_join_offline_entitlement_check_is_exit_zero(tmp_path):
    report, exit_code = execute_layers_join(
        "finance",
        _lock_path=tmp_path / "copilot.lock",
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=tmp_path / "copilot.layers.yml",
        _get_json=_get_json_status(None),
    )

    _validate(report)
    assert report["result"] == "offline"
    assert exit_code == 0


def test_join_signed_out_is_error_envelope_exit_two(tmp_path):
    report, exit_code = execute_layers_join(
        "finance",
        _lock_path=tmp_path / "copilot.lock",
        _identity={},
        _get_secret=_fake_get_secret_factory({}),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=tmp_path / "copilot.layers.yml",
    )

    assert report["error"]["code"] == "signed-out"
    assert exit_code == 2


# ---------------------------------------------------------------------------
# flock: join acquires the lock; concurrent join sees contention
# ---------------------------------------------------------------------------


def test_join_lock_contention_reported_honestly(tmp_path):
    lock_mutex_path = tmp_path / "copilot.lock"

    with copilot_lock(path=lock_mutex_path):
        report, exit_code = execute_layers_join(
            "finance",
            _lock_path=lock_mutex_path,
            _identity=IDENTITY,
            _get_secret=_fake_get_secret_factory(TOKENS),
            _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
            _manifest_path=tmp_path / "copilot.layers.yml",
            _get_json=_get_json_status(200),
        )

    assert report["error"]["code"] == "lock-contention"
    assert exit_code == 2


def test_join_invalid_local_manifest_maps_to_invalid_manifest_exit_two(tmp_path):
    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text("not: [valid", encoding="utf-8")

    report, exit_code = execute_layers_join(
        "finance",
        _lock_path=tmp_path / "copilot.lock",
        _identity=IDENTITY,
        _get_secret=_fake_get_secret_factory(TOKENS),
        _departments=[{"id": "finance", "name": "Finance", "repo": "org/dept-finance"}],
        _manifest_path=manifest_path,
        _get_json=_get_json_status(200),
    )

    assert report["error"]["code"] == "invalid-manifest"
    assert exit_code == 2


# ---------------------------------------------------------------------------
# CLI wiring: `layers_app` (bare == list, `list`, `join`) via CliRunner
# ---------------------------------------------------------------------------


def test_cli_bare_invocation_defaults_to_list(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cc.commands.layers.build_layers_report",
        lambda: {"schema_version": "1.0", "layers": []},
    )
    result = runner.invoke(layers_app, ["--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["layers"] == []


def test_cli_list_subcommand_matches_bare_default(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.layers.build_layers_report",
        lambda: {"schema_version": "1.0", "layers": []},
    )
    result = runner.invoke(layers_app, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    _validate(payload)


def test_cli_join_not_entitled_via_runner(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.layers.execute_layers_join",
        lambda layer_id: (
            {"schema_version": "1.0", "result": "not-entitled", "tier": "department", "id": layer_id},
            0,
        ),
    )
    result = runner.invoke(layers_app, ["join", "finance", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["result"] == "not-entitled"


def test_cli_join_lock_contention_via_runner_exit_two(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.layers.execute_layers_join",
        lambda layer_id: (
            {"schema_version": "1.0", "error": {"code": "lock-contention", "message": "held"}},
            2,
        ),
    )
    result = runner.invoke(layers_app, ["join", "finance", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "lock-contention"


# ---------------------------------------------------------------------------
# compute_layers_join_exit_code()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result,expected_exit",
    [
        ("joined", 0),
        ("already-joined", 0),
        ("not-entitled", 0),
        ("offline", 0),
        ("error", 1),
    ],
)
def test_compute_layers_join_exit_code(result, expected_exit):
    assert compute_layers_join_exit_code({"result": result}) == expected_exit
