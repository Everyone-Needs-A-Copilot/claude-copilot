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
    assert written["foundation"]["_meta"]["product"] == "claude"
    assert written["foundation"]["_meta"]["role"] == "foundation"
    assert written["foundation"]["_meta"]["source_sha"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    changed_ops = {c["item"]: c["op"] for c in report["changed"]}
    assert changed_ops["sec"] == "added"


def _two_local_layers(org_root: Path, foundation_root: Path) -> list[dict]:
    # `source.repo` is required by validate_layers() even for a visible
    # local checkout (`source.path` set directly, no `subpath`) -- see
    # manifest.py's own "must be an object with at least a `repo` key"
    # check. It is never dereferenced here because neither of
    # build_update_report()'s mirror-sync (`repo and not local_path`) nor
    # subpath-join (`local_path and subpath`) branches fires when `path`
    # is already given with no `subpath` -- `source["path"]` passes
    # through unchanged, exactly matching materialize.py's own test
    # helper `_layer()` (tests/test_ecosystem_materialize.py).
    return [
        {
            "id": "claude-organization",
            "role": "organization",
            "rank": 20,
            "product": "claude",
            "source": {"repo": "https://example.invalid/claude-organization.git", "path": str(org_root)},
            "auth": "anon",
            "activation": "always",
        },
        {
            "id": "claude-foundation",
            "role": "foundation",
            "rank": 40,
            "product": "claude",
            "source": {"repo": "https://example.invalid/claude-foundation.git", "path": str(foundation_root)},
            "auth": "anon",
            "activation": "always",
        },
    ]


def test_update_json_fold_fallback_reports_blocked_winner_and_validates_against_schema(
    tmp_path,
):
    """task 220 Fix 1, end to end through `cc update`'s own JSON builder --
    the live WP-384 regression: org's `commands/protocol.md` wins the
    OVERRIDE fold but is policy-blocked (unverified, by design -- no wired
    org signer). The foundation's own verified copy underneath it
    materializes in its place, un-freezing the slot, and the substitution
    is reported honestly on the `changed[]` entry -- never silently as if
    org's content had applied -- while the payload still validates against
    update.schema.json's additive `blocked_winner`/`reason` fields."""
    org_root = tmp_path / "org-src"
    (org_root / "commands").mkdir(parents=True)
    (org_root / "commands" / "protocol.md").write_text("org protocol", encoding="utf-8")

    foundation_root = tmp_path / "foundation-src"
    (foundation_root / "commands").mkdir(parents=True)
    (foundation_root / "commands" / "protocol.md").write_text(
        "foundation protocol", encoding="utf-8"
    )

    layers = _two_local_layers(org_root, foundation_root)

    def org_blocked_policy(item):
        return "block" if item["layer"] == "claude-organization" else "allow"

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=org_blocked_policy,
    )

    _validate(report)
    assert report["result"] == "applied"
    assert (
        tmp_path / "materialize" / "commands" / "protocol.md"
    ).read_text(encoding="utf-8") == "foundation protocol"

    change = next(c for c in report["changed"] if c["item"] == "protocol")
    assert change["layer"] == "claude-foundation"
    assert change["blocked_winner"] == "claude-organization"
    assert change["reason"] is not None and "unverified" in change["reason"]
    assert not report["blocked"]  # un-frozen -- no longer stuck reporting blocked


def test_update_threads_each_layers_resolved_ref_into_the_policy_gate(tmp_path):
    """G-9 (task 215 blocker fix): `build_update_report` computes
    `layer_source_refs` from each effective layer's OWN `source.ref` (the
    manifest's resolved/pinned revision) and threads it all the way into
    the policy gate's item dict -- proven end-to-end here through the real
    mirror-sync -> materialize wiring, not just materialize()'s own unit
    tests."""
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)
    seen_refs = []

    def capture_ref_policy(item):
        seen_refs.append(item.get("ref"))
        return "allow"

    build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=capture_ref_policy,
    )

    assert seen_refs == ["main"]  # `_one_layer`'s declared `source.ref`


# ---------------------------------------------------------------------------
# WP-372 P1.3(a): ecosystem.yml delivery, end-to-end through cc update
# ---------------------------------------------------------------------------


def test_update_delivers_org_ecosystem_yml_and_validates_against_schema(tmp_path):
    """The org layer's ecosystem.yml lands at
    <materialize_root>/ecosystem.yml through the real mirror-sync ->
    materialize pipeline, and the op it produces still validates against
    update.schema.json (dimension is a free string in that schema, so this
    is a purely additive widening -- no schema change required)."""
    org_repo = _make_source_repo(
        tmp_path,
        {"ecosystem.yml": "org: acme\ndepartments:\n  - unit: accounting\n    topology: separate\n"},
        name="org-repo",
    )
    layers = [
        {
            "id": "claude-organization",
            "role": "organization",
            "rank": 30,
            "product": "claude",
            "source": {"repo": str(org_repo), "ref": "main"},
            "auth": "anon",
            "activation": "always",
        }
    ]

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
    )

    _validate(report)
    ecosystem_changes = [c for c in report["changed"] if c["dimension"] == "ecosystem"]
    assert len(ecosystem_changes) == 1
    assert ecosystem_changes[0]["op"] == "added"
    assert ecosystem_changes[0]["layer"] == "claude-organization"
    dest = tmp_path / "materialize" / "ecosystem.yml"
    assert dest.exists()
    assert "accounting" in dest.read_text(encoding="utf-8")


def test_update_second_run_reports_ecosystem_yml_unchanged(tmp_path):
    org_repo = _make_source_repo(
        tmp_path, {"ecosystem.yml": "org: acme\n"}, name="org-repo",
    )
    layers = [
        {
            "id": "claude-organization",
            "role": "organization",
            "rank": 30,
            "product": "claude",
            "source": {"repo": str(org_repo), "ref": "main"},
            "auth": "anon",
            "activation": "always",
        }
    ]
    common_kwargs = dict(
        _layers=layers,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialize",
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
    )

    first = build_update_report(_previous_lock={}, **common_kwargs)
    second = build_update_report(_previous_lock={}, **common_kwargs)

    _validate(first)
    _validate(second)
    first_eco = [c for c in first["changed"] if c["dimension"] == "ecosystem"][0]
    second_eco = [c for c in second["changed"] if c["dimension"] == "ecosystem"][0]
    assert first_eco["op"] == "added"
    assert second_eco["op"] == "unchanged"


# ---------------------------------------------------------------------------
# WP-372 P0.3: personal_roots_from_config() production feeder wiring
# ---------------------------------------------------------------------------


def test_update_default_personal_roots_feeder_protects_configured_root(monkeypatch, tmp_path):
    """When `_personal_roots` is NOT injected (the real production path),
    `build_update_report()` must consult `personal_roots_from_config()`
    and pass the result through to `materialize()` -- proving the
    production feeder is actually wired, not merely present as a function
    (the P0 incident's exact defect: the parameter existed, nothing fed
    it)."""
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)
    materialize_root = tmp_path / "materialize"

    # Register the agents/ dimension directory itself as a "personal root"
    # -- simulating a configured paths.knowledge_repo/projects.roots entry
    # that happens to coincide with a materialize target.
    monkeypatch.setattr(
        "cc.commands.update.personal_roots_from_config",
        lambda: [str(materialize_root / "agents")],
    )

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
        # _personal_roots deliberately NOT passed -- exercising the default.
    )

    assert not (materialize_root / "agents" / "sec.md").exists()
    held = report["held_for_approval"]
    assert held, "expected the configured personal root to hold the item"
    assert "personal root" in held[0]["reason"]


def test_update_explicit_personal_roots_override_skips_config_feeder(monkeypatch, tmp_path):
    """An explicitly injected `_personal_roots=[]` must NOT be replaced by
    `personal_roots_from_config()` -- tests (and any future caller wanting
    to opt out) can still pass an explicit list."""
    source_repo = _make_source_repo(tmp_path, {"agents/sec.md": "v1"})
    layers = _one_layer(source_repo)
    materialize_root = tmp_path / "materialize"

    monkeypatch.setattr(
        "cc.commands.update.personal_roots_from_config",
        lambda: [str(materialize_root / "agents")],  # would protect if consulted
    )

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialize_root,
        _lock_write_path=tmp_path / "copilot.lock.json",
        _policy=permissive_policy,
        _personal_roots=[],  # explicit override -- config feeder must be skipped
    )

    assert (materialize_root / "agents" / "sec.md").read_text() == "v1"
    assert report["held_for_approval"] == []


def test_update_syncs_external_product_mirrors_without_materializing_authored_shapes(
    tmp_path,
):
    knowledge = _make_source_repo(
        tmp_path,
        {"00-best-practices/README.md": "knowledge"},
        name="knowledge-source",
    )
    cli = _make_source_repo(
        tmp_path,
        {"cli.overlay.yml": "version: 1\nadopt: []\n"},
        name="cli-source",
    )
    layers = [
        {
            "id": "knowledge-foundation",
            "role": "foundation",
            "rank": 40,
            "product": "knowledge",
            "source": {"repo": str(knowledge), "ref": "main"},
            "auth": "anon",
            "activation": "always",
        },
        {
            "id": "foundation",
            "role": "foundation",
            "rank": 40,
            "product": "cli",
            "source": {"repo": str(cli), "ref": "main"},
            "auth": "anon",
            "activation": "always",
        },
    ]
    lock_path = tmp_path / "copilot.lock.json"
    materialized = tmp_path / "materialized"

    report = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=materialized,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
    )

    assert report["result"] == "up-to-date"
    assert report["changed"] == []
    assert (tmp_path / "mirrors/knowledge/knowledge-foundation/00-best-practices/README.md").is_file()
    assert (tmp_path / "mirrors/cli/foundation/cli.overlay.yml").is_file()
    assert not materialized.exists()
    lock = json.loads(lock_path.read_text())
    assert lock["knowledge-foundation"]["_meta"]["product"] == "knowledge"
    assert lock["foundation"]["_meta"]["product"] == "cli"


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
