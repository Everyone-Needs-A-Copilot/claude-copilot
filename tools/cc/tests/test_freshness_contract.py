"""WS-A contract test: `cc freshness --json` must validate against the
vendored copilot-control-tower `freshness.schema.json`, and must never
report `stale: false` ("up to date") when it could not actually check
(offline, or no local lock yet) -- the honesty rule this schema was
amended to support (see cc/commands/freshness.py's module docstring).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copies live in tests/fixtures/schemas/ (see test_doctor_contract.py
for the identical precedent this mirrors).

Uses local `file://`-style (plain-path) fixture git repos for the
mirror-side lock-pointer ref -- never a real remote, ~/.claude, or
~/.copilot.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands.freshness import build_freshness_report
from cc.core.ecosystem.freshness import current_lock_sha as _real_current_lock_sha
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _freshness_validator() -> Draft202012Validator:
    freshness_schema = _load_schema("freshness.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (freshness_schema["$id"], Resource.from_contents(freshness_schema)),
        ]
    )
    return Draft202012Validator(freshness_schema, registry=registry)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "freshness contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _canonical_lock_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _make_fixture_repo(tmp_path: Path, lock_data: dict) -> tuple[Path, str]:
    repo = tmp_path / "tier-source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    lock_file = repo / "copilot.lock.json"
    lock_file.write_bytes(_canonical_lock_bytes(lock_data))

    blob_sha = subprocess.run(
        ["git", "hash-object", "-w", "copilot.lock.json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(
        ["git", "update-ref", "refs/copilot/lock", blob_sha], cwd=repo, check=True
    )
    return repo, blob_sha


def _invoke_freshness_json(monkeypatch, *, source: str | None, lockfile_path: Path):
    monkeypatch.setattr(
        "cc.commands.freshness.resolve_key",
        lambda key, **_: {
            "layers.lock_source": source,
            "layers.lock_ref": "refs/copilot/lock",
        }.get(key),
    )
    monkeypatch.setattr(
        "cc.commands.freshness.current_lock_sha",
        lambda **_: _real_current_lock_sha(_lockfile_path=lockfile_path),
    )

    result = runner.invoke(app, ["freshness", "--json"])
    payload = json.loads(result.output)
    return payload, result.exit_code


def _validate(payload: dict) -> None:
    validator = _freshness_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_freshness_json_fresh_validates_and_reports_not_stale(monkeypatch, tmp_path):
    lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    repo, blob_sha = _make_fixture_repo(tmp_path, lock_data)

    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_bytes(_canonical_lock_bytes(lock_data))

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=str(repo), lockfile_path=lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert payload["current_lock_sha"] == blob_sha
    assert payload["latest_lock_sha"] == blob_sha
    assert payload["stale"] is False
    assert payload["offline"] is False


def test_freshness_json_stale_validates_and_reports_stale(monkeypatch, tmp_path):
    remote_lock_data = {"foundation": {"agents": {"sec": "newnewnew"}}}
    repo, remote_sha = _make_fixture_repo(tmp_path, remote_lock_data)

    # Local machine is behind: it still has the OLD resolved state.
    local_lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_bytes(_canonical_lock_bytes(local_lock_data))

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=str(repo), lockfile_path=lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert payload["latest_lock_sha"] == remote_sha
    assert payload["current_lock_sha"] != remote_sha
    assert payload["stale"] is True
    assert payload["offline"] is False


def test_freshness_json_offline_is_honest_never_reports_up_to_date(
    monkeypatch, tmp_path
):
    """Remote is unreachable -- must NEVER coerce `stale` to False."""
    local_lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_bytes(_canonical_lock_bytes(local_lock_data))

    unreachable_source = str(tmp_path / "does-not-exist-at-all")

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=unreachable_source, lockfile_path=lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert payload["latest_lock_sha"] is None
    assert payload["stale"] is None
    assert payload["offline"] is True
    # The honesty rule, asserted directly (never fabricate "fresh"):
    assert payload["stale"] is not False


def test_freshness_json_no_local_lock_yet_is_honest(monkeypatch, tmp_path):
    """First-run machine: no local copilot.lock.json yet."""
    lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    repo, blob_sha = _make_fixture_repo(tmp_path, lock_data)

    missing_lockfile_path = tmp_path / "copilot.lock.json"  # never written

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=str(repo), lockfile_path=missing_lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert payload["current_lock_sha"] is None
    assert payload["latest_lock_sha"] == blob_sha
    assert payload["stale"] is None
    assert payload["offline"] is False
    assert payload["stale"] is not False


def test_freshness_json_no_source_configured_is_honest_empty(monkeypatch, tmp_path):
    """No `layers.lock_source` configured yet -- nothing to check."""
    missing_lockfile_path = tmp_path / "copilot.lock.json"

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=None, lockfile_path=missing_lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert payload["current_lock_sha"] is None
    assert payload["latest_lock_sha"] is None
    assert payload["stale"] is None
    assert payload["offline"] is False


def test_freshness_schema_rejects_legacy_non_nullable_up_to_date_fabrication():
    """Directly exercise the amended schema: a `stale: false` payload with
    a null current_lock_sha (i.e. a fabricated "fresh" while unable to
    check) is exactly the shape the schema widening forbids being the
    ONLY honest option -- it must still be schema-*parseable* (nullable
    fields don't forbid false), but the CLI itself (asserted above) never
    emits it. This test only pins the schema's structural allowances:
    both SHAs null + stale null is valid; both null + stale false is also
    schema-valid (JSON Schema cannot enforce the cross-field honesty
    invariant -- invariant #1, CLI computes/app parses) but the CLI-level
    tests above are what actually pin honesty."""
    validator = _freshness_validator()

    honest_unknown = {
        "schema_version": "1.0",
        "current_lock_sha": None,
        "latest_lock_sha": None,
        "stale": None,
        "offline": True,
        "checked_at": "2026-07-07T00:00:00Z",
    }
    assert not list(validator.iter_errors(honest_unknown))

    legacy_shape_missing_offline = {
        "schema_version": "1.0",
        "current_lock_sha": "abc1234",
        "latest_lock_sha": "abc1234",
        "stale": False,
        "checked_at": "2026-07-07T00:00:00Z",
    }
    errors = list(validator.iter_errors(legacy_shape_missing_offline))
    assert errors, "offline is now required -- the legacy shape must fail validation"


# ---------------------------------------------------------------------------
# Per-layer freshness (update-slice gap #2) -- opt-in, additive `layers` array
# ---------------------------------------------------------------------------


def test_default_cli_payload_byte_shape_unchanged_regression_guard(monkeypatch, tmp_path):
    """REGRESSION GUARD: the CLI's own `freshness_cmd()` (cc/main.py) calls
    `build_freshness_report()` with NO arguments -- `per_layer` must
    default to `False`, and the emitted payload's key set must be
    byte-shape-identical to the pre-per-layer contract (no `layers` key at
    all, not even an empty list)."""
    lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    repo, blob_sha = _make_fixture_repo(tmp_path, lock_data)

    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_bytes(_canonical_lock_bytes(lock_data))

    payload, exit_code = _invoke_freshness_json(
        monkeypatch, source=str(repo), lockfile_path=lockfile_path
    )

    assert exit_code == 0
    _validate(payload)
    assert set(payload.keys()) == {
        "schema_version",
        "current_lock_sha",
        "latest_lock_sha",
        "stale",
        "offline",
        "checked_at",
    }
    assert "layers" not in payload


def test_build_freshness_report_per_layer_opt_in_adds_layers_and_validates(tmp_path):
    lock_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_bytes(_canonical_lock_bytes(lock_data))

    mirror_root = tmp_path / "mirrors"
    foundation_lock_data = {"a": "1"}
    (mirror_root / "foundation").mkdir(parents=True)
    (mirror_root / "foundation" / "copilot.lock.json").write_bytes(
        _canonical_lock_bytes(foundation_lock_data)
    )

    layers = [
        {"id": "foundation", "source": {"repo": "https://example.invalid/foundation.git"}},
        {"id": "personal", "source": {"path": str(tmp_path / "personal-vault")}},
    ]

    payload = build_freshness_report(
        _source=None,
        _ref="refs/copilot/lock",
        per_layer=True,
        _layers=layers,
        _mirror_root=mirror_root,
        _lockfile_path=lockfile_path,
        _latest_sha=None,
        _layer_latest_lookup={"foundation": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
    )

    _validate(payload)
    assert "layers" in payload
    assert len(payload["layers"]) == 2

    by_id = {entry["id"]: entry for entry in payload["layers"]}
    assert by_id["foundation"]["latest"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert by_id["foundation"]["current"] is not None
    assert by_id["foundation"]["stale"] is True
    assert by_id["foundation"]["offline"] is False

    assert by_id["personal"]["current"] is None
    assert by_id["personal"]["latest"] is None
    assert by_id["personal"]["stale"] is None
    assert by_id["personal"]["offline"] is False


def test_build_freshness_report_per_layer_unreachable_layer_validates_offline_true(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"  # never written -- no local lock yet.
    mirror_root = tmp_path / "mirrors"

    layers = [{"id": "org", "source": {"repo": "https://example.invalid/unreachable.git"}}]

    payload = build_freshness_report(
        _source=None,
        _ref="refs/copilot/lock",
        per_layer=True,
        _layers=layers,
        _mirror_root=mirror_root,
        _lockfile_path=lockfile_path,
        _latest_sha=None,
        _layer_latest_lookup={"org": None},
    )

    _validate(payload)
    entry = payload["layers"][0]
    assert entry["id"] == "org"
    assert entry["current"] is None
    assert entry["latest"] is None
    assert entry["stale"] is None
    assert entry["offline"] is True


def test_build_freshness_report_per_layer_empty_layers_is_empty_array_and_validates(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    mirror_root = tmp_path / "mirrors"

    payload = build_freshness_report(
        _source=None,
        _ref="refs/copilot/lock",
        per_layer=True,
        _layers=[],
        _mirror_root=mirror_root,
        _lockfile_path=lockfile_path,
        _latest_sha=None,
    )

    _validate(payload)
    assert payload["layers"] == []


def test_build_freshness_report_per_layer_false_default_never_calls_per_layer_build(
    monkeypatch, tmp_path
):
    """The existing (non-per-layer) call path must never even import/touch
    `build_per_layer_freshness()` -- asserted by monkeypatching it to raise
    if invoked."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("per_layer=False must never call build_per_layer_freshness()")

    monkeypatch.setattr("cc.commands.freshness.build_per_layer_freshness", _boom)

    lockfile_path = tmp_path / "copilot.lock.json"
    payload = build_freshness_report(
        _source=None, _ref="refs/copilot/lock", _lockfile_path=lockfile_path, _latest_sha=None
    )

    _validate(payload)
    assert "layers" not in payload
