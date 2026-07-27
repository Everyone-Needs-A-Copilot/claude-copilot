"""WS-A contract test: `cc update --json` (the FIRST MUTATING WS-A verb).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/update.schema.json (see the
`$comment` header, same precedent as test_doctor_contract.py /
test_freshness_contract.py).

HARD SAFETY RULE: `cc update` MATERIALIZES and DELETES files. Every test
here goes through the Typer `CliRunner` (in-process, no subprocess against
the real machine) with EVERY root -- manifest, mirror root, materialize
root, lockfile read/write path, and the advisory `copilot.lock` mutex path
-- monkeypatched to `tmp_path`. The `_no_real_home` autouse fixture below
additionally asserts `Path.home()` is never resolved as a fallback
anywhere in the call graph. `cc update` is never run against real `~/.claude`
in this file or anywhere else in this change.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands.update import build_update_report
from cc.core.ecosystem.policy import permissive_policy
from cc.core.locking import copilot_lock
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _update_validator() -> Draft202012Validator:
    update_schema = _load_schema("update.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (update_schema["$id"], Resource.from_contents(update_schema)),
        ]
    )
    return Draft202012Validator(update_schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _update_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "update contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


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


def _one_layer(source_repo: Path) -> list[dict]:
    return [
        {
            "id": "foundation",
            "role": "foundation",
            "rank": 40,
            "product": "claude",
            "source": {"repo": str(source_repo), "ref": "main"},
            "auth": "anon",
            "activation": "always",
        }
    ]


def _patch_roots(
    monkeypatch,
    *,
    manifest_path: Path | None,
    mirror_root: Path,
    materialize_root: Path,
    lockfile_path: Path,
    lock_mutex_path: Path,
) -> None:
    def _resolve_key(key: str, **_kwargs):
        return {
            "layers.manifest": str(manifest_path) if manifest_path else None,
            "paths.mirrors_root": str(mirror_root),
            "paths.materialize_root": str(materialize_root),
        }.get(key)

    monkeypatch.setattr("cc.commands.update.resolve_key", _resolve_key)
    monkeypatch.setattr("cc.commands.update.default_lockfile_path", lambda: lockfile_path)
    monkeypatch.setattr("cc.commands.update.lock_path", lambda: lock_mutex_path)


def _write_manifest(tmp_path: Path, layers: list[dict]) -> Path:
    import yaml

    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text(
        yaml.safe_dump({"version": 1, "layers": layers}), encoding="utf-8"
    )
    return manifest_path


# ---------------------------------------------------------------------------
# Schema contract test
# ---------------------------------------------------------------------------


def test_update_json_fail_closed_blocked_validates_against_contract_schema(
    monkeypatch, tmp_path
):
    """PRODUCTION DEFAULT path (no policy injected -- fail-closed): an
    unverified item is blocked, never applied, and the payload still
    validates against update.schema.json."""
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    manifest_path = _write_manifest(tmp_path, _one_layer(source_repo))

    _patch_roots(
        monkeypatch,
        manifest_path=manifest_path,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=tmp_path / "copilot.lock.json",
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["update", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["result"] == "blocked"
    assert result.exit_code == 1
    assert payload["blocked"][0]["reason"] == "unverified"
    assert not (tmp_path / "materialize" / "agents" / "sec.md").exists()


def test_update_json_applied_validates_against_contract_schema(tmp_path):
    """With a permissive (test-injected) policy, the full mirror-sync ->
    resolve -> materialize -> lock-write pipeline actually applies, and the
    payload still validates against update.schema.json."""
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)
    lock_write_path = tmp_path / "copilot.lock.json"

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=lock_write_path,
        _policy=permissive_policy,
    )

    _validate(report)
    assert report["result"] == "applied"
    assert (tmp_path / "materialize" / "agents" / "sec.md").read_text() == "v1"
    assert lock_write_path.exists()
    written = json.loads(lock_write_path.read_text())
    assert written["foundation"]["agents"]["sec"]

    changed_ops = {c["item"]: c["op"] for c in report["changed"]}
    assert changed_ops["sec"] == "added"


def test_update_json_second_run_up_to_date(tmp_path):
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)

    first = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
    )
    assert first["result"] == "applied"

    previous_lock = json.loads((tmp_path / "copilot.lock.json").read_text())

    second = build_update_report(
        _layers=layers,
        _previous_lock=previous_lock,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
    )

    assert second["result"] == "up-to-date"
    assert second["lock_before"] == second["lock_after"]


# ---------------------------------------------------------------------------
# Offline honesty
# ---------------------------------------------------------------------------


def test_update_json_offline_no_cache_is_honest_never_partial(monkeypatch, tmp_path):
    unreachable = tmp_path / "does-not-exist-at-all"
    layers = _one_layer(unreachable)
    manifest_path = _write_manifest(tmp_path, layers)
    lockfile_path = tmp_path / "copilot.lock.json"

    _patch_roots(
        monkeypatch,
        manifest_path=manifest_path,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=lockfile_path,
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["update", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["result"] == "offline"
    assert payload["changed"] == []
    assert result.exit_code == 0
    assert not lockfile_path.exists()  # no partial write


# ---------------------------------------------------------------------------
# flock: update acquires the lock; concurrent update sees contention
# ---------------------------------------------------------------------------


def test_update_lock_contention_reported_honestly(monkeypatch, tmp_path):
    lock_mutex_path = tmp_path / "copilot.lock"
    manifest_path = _write_manifest(tmp_path, [])

    _patch_roots(
        monkeypatch,
        manifest_path=manifest_path,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=tmp_path / "copilot.lock.json",
        lock_mutex_path=lock_mutex_path,
    )

    with copilot_lock(path=lock_mutex_path):
        result = runner.invoke(app, ["update", "--json"])

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "lock-contention"
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# No manifest configured -- honest no-op, not an error
# ---------------------------------------------------------------------------


def test_update_json_no_manifest_configured_is_honest_up_to_date(monkeypatch, tmp_path):
    _patch_roots(
        monkeypatch,
        manifest_path=None,
        mirror_root=tmp_path / "mirrors",
        materialize_root=tmp_path / "materialize",
        lockfile_path=tmp_path / "copilot.lock.json",
        lock_mutex_path=tmp_path / "copilot.lock",
    )

    result = runner.invoke(app, ["update", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["result"] == "up-to-date"
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_update_dry_run_computes_plan_without_writing(tmp_path):
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)
    lock_write_path = tmp_path / "copilot.lock.json"
    materialize_root = tmp_path / "materialize"

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
        _lock_write_path=lock_write_path,
        _policy=permissive_policy,
        _dry_run=True,
    )

    assert report["result"] == "applied"
    assert not (materialize_root / "agents" / "sec.md").exists()
    assert not lock_write_path.exists()
