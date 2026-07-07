"""WS-A contract test: `cc deprovision --json` (the SECOND MUTATING WS-A
verb, after `update`).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/deprovision.schema.json (same
precedent as test_update_contract.py).

HARD SAFETY RULE: `cc deprovision` DELETES files. Every test here goes
through either the engine function directly or the Typer `CliRunner`
(in-process, no subprocess against the real machine) with EVERY root --
materialize root, mirror root, lockfile read path, and the advisory
`copilot.lock` mutex path -- injected/monkeypatched to `tmp_path`. The
`_no_real_home` autouse fixture below additionally asserts `Path.home()`
is never resolved as a fallback anywhere in the call graph. `cc
deprovision` is never run against real `~/.claude`/`~/.copilot` in this
file or anywhere else in this change.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands.deprovision import build_deprovision_report, compute_exit_code
from cc.core.ecosystem import deprovision as deprovision_engine
from cc.core.ecosystem.deprovision import SecretPathError, deprovision
from cc.core.locking import copilot_lock
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _deprovision_validator() -> Draft202012Validator:
    schema = _load_schema("deprovision.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (schema["$id"], Resource.from_contents(schema)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _deprovision_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "deprovision contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _patch_roots(
    monkeypatch,
    *,
    mirror_root: Path,
    materialize_root: Path,
    lockfile_path: Path,
    lock_mutex_path: Path,
) -> None:
    def _resolve_key(key: str, **_kwargs):
        return {
            "paths.mirrors_root": str(mirror_root),
            "paths.materialize_root": str(materialize_root),
        }.get(key)

    monkeypatch.setattr("cc.commands.deprovision.resolve_key", _resolve_key)
    monkeypatch.setattr("cc.commands.deprovision.default_lockfile_path", lambda: lockfile_path)
    monkeypatch.setattr("cc.commands.deprovision.lock_path", lambda: lock_mutex_path)


# ---------------------------------------------------------------------------
# noop: nothing recorded, nothing under mirror_root
# ---------------------------------------------------------------------------


def test_deprovision_json_noop_validates_against_contract_schema(monkeypatch, tmp_path):
    _patch_roots(
        monkeypatch,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=tmp_path / "copilot.lock.json",  # never written -- absent
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["deprovision", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["result"] == "noop"
    assert payload["removed"] == {"materialized": 0, "clones": []}
    assert payload["retained_dirty"] == []
    assert payload["secrets_touched"] == 0
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Disposable materialized content IS removed; count is correct; only
# engine-placed items are removed.
# ---------------------------------------------------------------------------


def test_deprovision_wipes_only_engine_placed_materialized_content(tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "knowledge").mkdir(parents=True)

    engine_owned_1 = materialize_root / "agents" / "qa.md"
    engine_owned_1.write_text("engine-placed", encoding="utf-8")
    engine_owned_2 = materialize_root / "knowledge" / "runbook.md"
    engine_owned_2.write_text("engine-placed too", encoding="utf-8")

    # NEVER lock-tracked -- must never be removed, regardless of location.
    unrelated_personal = materialize_root / "agents" / "personal-notes.md"
    unrelated_personal.write_text("Bob's own notes, not lock-tracked", encoding="utf-8")
    unrelated_hash_before = unrelated_personal.read_bytes()

    previous_lock = {
        "foundation": {
            "agents": {"qa": "sha-1"},
            "knowledge": {"runbook": "sha-2"},
        }
    }

    report = build_deprovision_report(
        _previous_lock=previous_lock,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
    )

    _validate(report)
    assert report["result"] == "wiped"
    assert report["removed"]["materialized"] == 2
    assert not engine_owned_1.exists()
    assert not engine_owned_2.exists()
    assert unrelated_personal.exists()  # never touched
    assert unrelated_personal.read_bytes() == unrelated_hash_before
    assert report["secrets_touched"] == 0


# ---------------------------------------------------------------------------
# NEVER-DESTROY: a dirty git working tree is retained, byte-identical
# ---------------------------------------------------------------------------


def test_deprovision_never_destroy_dirty_git_tree_retained_byte_identical(tmp_path):
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    _git_init(materialize_root)

    tracked = materialize_root / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed baseline", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=materialize_root, check=True)

    # Human edits it locally -- uncommitted, dirty.
    tracked.write_text("Bob's uncommitted personal edit", encoding="utf-8")
    hash_before = tracked.read_bytes()

    previous_lock = {"foundation": {"agents": {"qa": "sha-1"}}}

    report = build_deprovision_report(
        _previous_lock=previous_lock,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
    )

    hash_after = tracked.read_bytes()
    assert hash_after == hash_before  # BYTE-IDENTICAL -- never touched
    assert tracked.exists()
    assert str(tracked) in report["retained_dirty"]
    assert report["removed"]["materialized"] == 0
    assert report["secrets_touched"] == 0


# ---------------------------------------------------------------------------
# Mirrors: hard mode fully removes; soft mode (default) quarantines --
# nothing outside the injected roots is ever touched.
# ---------------------------------------------------------------------------


def test_deprovision_hard_mode_fully_removes_mirror_clones(tmp_path):
    mirror_root = tmp_path / "mirrors"
    tier_dir = mirror_root / "foundation"
    tier_dir.mkdir(parents=True)
    (tier_dir / "content.md").write_text("mirrored content", encoding="utf-8")

    outside = tmp_path / "untouched"
    outside.mkdir()
    (outside / "keep.txt").write_text("do not touch", encoding="utf-8")

    report = build_deprovision_report(
        _previous_lock={},
        _mirror_root=mirror_root,
        _materialize_root=tmp_path / "materialize",
        _mode="hard",
    )

    _validate(report)
    assert report["result"] == "wiped"
    assert not tier_dir.exists()
    assert report["removed"]["clones"] == ["foundation"]
    assert (outside / "keep.txt").exists()  # never touched


def test_deprovision_soft_mode_default_quarantines_mirror_clones_for_flip_back(tmp_path):
    mirror_root = tmp_path / "mirrors"
    tier_dir = mirror_root / "foundation"
    tier_dir.mkdir(parents=True)
    (tier_dir / "content.md").write_text("mirrored content", encoding="utf-8")

    report = build_deprovision_report(
        _previous_lock={},
        _mirror_root=mirror_root,
        _materialize_root=tmp_path / "materialize",
    )  # default mode == "soft"

    assert report["result"] == "wiped"
    assert not tier_dir.exists()  # removed from the ACTIVE mirror location
    assert report["removed"]["clones"] == ["foundation"]
    quarantined = mirror_root / ".quarantine" / "foundation" / "content.md"
    assert quarantined.exists()  # preserved, not deleted -- a flip-back restores it
    assert quarantined.read_text() == "mirrored content"


# ---------------------------------------------------------------------------
# secrets_touched is always 0; a secret-shaped path is refused, never wiped
# ---------------------------------------------------------------------------


def test_deprovision_secrets_touched_always_zero_on_success(tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("x", encoding="utf-8")

    report = build_deprovision_report(
        _previous_lock={"foundation": {"agents": {"qa": "sha"}}},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
    )
    assert report["secrets_touched"] == 0


def test_deprovision_refuses_secret_shaped_path_in_wipe_set(tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    secret_like = materialize_root / "agents" / "secrets.env"
    secret_like.write_text("SECRET=nope", encoding="utf-8")

    previous_lock = {"foundation": {"agents": {"secrets": "sha"}}}

    with pytest.raises(SecretPathError):
        deprovision(
            materialize_root=materialize_root,
            mirror_root=tmp_path / "mirrors",
            previous_lock=previous_lock,
        )
    assert secret_like.exists()  # refused before any removal was attempted


# ---------------------------------------------------------------------------
# partial: an attempted removal fails
# ---------------------------------------------------------------------------


def test_deprovision_partial_when_removal_fails(monkeypatch, tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(deprovision_engine, "_safe_remove", lambda _target: False)

    report = build_deprovision_report(
        _previous_lock={"foundation": {"agents": {"qa": "sha"}}},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
    )

    _validate(report)
    assert report["result"] == "partial"
    assert compute_exit_code(report) == 1


# ---------------------------------------------------------------------------
# flock: deprovision acquires the lock; concurrent deprovision sees contention
# ---------------------------------------------------------------------------


def test_deprovision_lock_contention_reported_honestly(monkeypatch, tmp_path):
    lock_mutex_path = tmp_path / "copilot.lock"

    _patch_roots(
        monkeypatch,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=tmp_path / "copilot.lock.json",
        lock_mutex_path=lock_mutex_path,
    )

    with copilot_lock(path=lock_mutex_path):
        result = runner.invoke(app, ["deprovision", "--json"])

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "lock-contention"
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# --dry-run removes nothing
# ---------------------------------------------------------------------------


def test_deprovision_dry_run_removes_nothing(monkeypatch, tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    target = materialize_root / "agents" / "qa.md"
    target.write_text("x", encoding="utf-8")

    mirror_root = tmp_path / "mirrors"
    tier_dir = mirror_root / "foundation"
    tier_dir.mkdir(parents=True)

    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text(
        json.dumps({"foundation": {"agents": {"qa": "sha"}}}), encoding="utf-8"
    )

    _patch_roots(
        monkeypatch,
        mirror_root=mirror_root,
        materialize_root=materialize_root,
        lockfile_path=lockfile_path,
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["deprovision", "--json", "--dry-run"])
    payload = json.loads(result.output)

    _validate(payload)
    assert target.exists()  # nothing removed
    assert tier_dir.exists()  # nothing quarantined/removed
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Sample CLI --json output (wiped + noop), for documentation purposes
# ---------------------------------------------------------------------------


def test_deprovision_cli_json_sample_wiped_case(monkeypatch, tmp_path):
    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("x", encoding="utf-8")

    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text(
        json.dumps({"foundation": {"agents": {"qa": "sha"}}}), encoding="utf-8"
    )

    _patch_roots(
        monkeypatch,
        mirror_root=tmp_path / "mirrors",
        materialize_root=materialize_root,
        lockfile_path=lockfile_path,
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["deprovision", "--json", "--hard"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["result"] == "wiped"
    assert payload["removed"]["materialized"] == 1
    assert result.exit_code == 0
