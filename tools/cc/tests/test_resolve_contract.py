"""WS-A contract test: `cc resolve --explain --json` must validate against
the vendored copilot-control-tower `resolve.schema.json`, and every item
must carry the fail-closed security fields (never a fabricated
"signed"/"matches" verdict).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copies live in tests/fixtures/schemas/ (see test_doctor_contract.py
for the identical precedent this mirrors).

Everything here is tmp_path-fixtured -- no real ~/.claude, no network, no
real `copilot.lock`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.commands.resolve import build_resolve_report
from cc.core.ecosystem.discovery import discover_contributions
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _resolve_validator() -> Draft202012Validator:
    resolve_schema = _load_schema("resolve.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (resolve_schema["$id"], Resource.from_contents(resolve_schema)),
        ]
    )
    return Draft202012Validator(resolve_schema, registry=registry)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "resolve contract test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _write_fixture_layer(tmp_path: Path) -> Path:
    """A single-layer local fixture with one `agents/` item -- enough to
    produce a non-empty, schema-valid --explain report without a real
    remote clone (materialize hasn't landed yet -- see discovery.py)."""
    layer_root = tmp_path / "foundation-layer"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "sec.md").write_text("security agent body")
    return layer_root


def _write_manifest(tmp_path: Path, layer_root: Path) -> Path:
    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text(
        f"""
version: 1
layers:
  - id: foundation
    role: foundation
    rank: 40
    product: claude
    source:
      repo: https://example.invalid/foundation.git
      path: {layer_root}
    auth: anon
    activation: always
"""
    )
    return manifest_path


def _invoke_resolve_json(monkeypatch, tmp_path: Path) -> tuple[dict, int]:
    layer_root = _write_fixture_layer(tmp_path)
    manifest_path = _write_manifest(tmp_path, layer_root)

    layers = [
        {
            "id": "foundation",
            "role": "foundation",
            "rank": 40,
            "product": "claude",
            "source": {
                "repo": "https://example.invalid/foundation.git",
                "path": str(layer_root),
            },
            "auth": "anon",
            "activation": "always",
        }
    ]
    # Compute the same content sha discovery will compute, so the lockfile
    # we write "recorded" the current content -- winning_sha must be
    # non-null (a real string) for a fully schema-valid instance; a null
    # winning_sha is exercised directly against the pure resolver in
    # test_ecosystem_resolver.py instead (see that file's docstring and
    # this repo's WS-A slice notes on the schema's non-nullable git_sha).
    contributions = discover_contributions(layers)
    sha = contributions["foundation"]["agents"]["sec"]

    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text(
        json.dumps({"foundation": {"agents": {"sec": sha}}}), encoding="utf-8"
    )

    monkeypatch.setattr(
        "cc.commands.resolve.resolve_key",
        lambda key, **_: str(manifest_path) if key == "layers.manifest" else None,
    )
    monkeypatch.setattr(
        "cc.commands.resolve.default_lockfile_path", lambda: lockfile_path
    )

    result = runner.invoke(app, ["resolve", "--explain", "--json"])
    payload = json.loads(result.output)
    return payload, result.exit_code


def test_resolve_explain_json_validates_against_contract_schema(monkeypatch, tmp_path):
    payload, exit_code = _invoke_resolve_json(monkeypatch, tmp_path)

    assert exit_code == 0
    assert payload["items"], (
        "expected the fixture manifest to produce at least one resolved item"
    )

    validator = _resolve_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_resolve_explain_json_fail_closed_security_fields(monkeypatch, tmp_path):
    """Missing signed/materialized evidence remains null/false."""
    payload, _ = _invoke_resolve_json(monkeypatch, tmp_path)

    assert payload["items"]
    for entry in payload["items"]:
        assert entry["signer_of_introducing_commit"] is None
        assert entry["live_hash_matches"] is False


def test_resolve_enriches_verified_signer_and_live_destination_hash(
    monkeypatch, tmp_path
):
    source_root = _write_fixture_layer(tmp_path)
    materialize_root = tmp_path / "materialized-claude"
    destination = materialize_root / "agents" / "sec.md"
    destination.parent.mkdir(parents=True)
    destination.write_bytes((source_root / "agents" / "sec.md").read_bytes())
    layer = {
        "id": "foundation",
        "role": "foundation",
        "rank": 40,
        "product": "claude",
        "source": {
            "repo": "https://example.invalid/foundation.git",
            "ref": "v1.0.0",
            "path": str(source_root),
        },
        "auth": "anon",
        "activation": "always",
        "policy": {"allowed_signers": ["SHA256:test-signer"]},
    }
    contributions = discover_contributions([layer])
    locked_sha = contributions["foundation"]["agents"]["sec"]
    monkeypatch.setattr(
        "cc.commands.resolve.verify_git_item",
        lambda *args, **kwargs: (True, "SHA256:test-signer"),
    )

    report = build_resolve_report(
        _layers=[layer],
        _contributions=contributions,
        _lockfile={"foundation": {"agents": {"sec": locked_sha}}},
        _mirror_root=tmp_path / "mirrors",
        _materialize_roots={"claude": materialize_root},
        _knowledge_cache_root=tmp_path / "knowledge-cache",
    )

    assert report["items"][0]["signer_of_introducing_commit"] == (
        "SHA256:test-signer"
    )
    assert report["items"][0]["live_hash_matches"] is True


def test_resolve_reports_modified_destination_without_losing_source_signer(
    monkeypatch, tmp_path
):
    source_root = _write_fixture_layer(tmp_path)
    materialize_root = tmp_path / "materialized-claude"
    destination = materialize_root / "agents" / "sec.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("tampered destination\n", encoding="utf-8")
    layer = {
        "id": "foundation",
        "role": "foundation",
        "rank": 40,
        "product": "claude",
        "source": {
            "repo": "https://example.invalid/foundation.git",
            "ref": "v1.0.0",
            "path": str(source_root),
        },
        "auth": "anon",
        "activation": "always",
        "policy": {"allowed_signers": ["SHA256:test-signer"]},
    }
    contributions = discover_contributions([layer])
    locked_sha = contributions["foundation"]["agents"]["sec"]
    monkeypatch.setattr(
        "cc.commands.resolve.verify_git_item",
        lambda *args, **kwargs: (True, "SHA256:test-signer"),
    )

    report = build_resolve_report(
        _layers=[layer],
        _contributions=contributions,
        _lockfile={"foundation": {"agents": {"sec": locked_sha}}},
        _mirror_root=tmp_path / "mirrors",
        _materialize_roots={"claude": materialize_root},
        _knowledge_cache_root=tmp_path / "knowledge-cache",
    )

    assert report["items"][0]["signer_of_introducing_commit"] == (
        "SHA256:test-signer"
    )
    assert report["items"][0]["live_hash_matches"] is False


def test_resolve_no_manifest_configured_returns_schema_valid_empty_report(monkeypatch):
    """No `layers.manifest` set -- an honest empty result, not an error,
    and still schema-valid."""
    monkeypatch.setattr("cc.commands.resolve.resolve_key", lambda key, **_: None)

    result = runner.invoke(app, ["resolve", "--explain", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload == {"schema_version": "1.0", "items": []}

    validator = _resolve_validator()
    assert not list(validator.iter_errors(payload))


def test_resolve_invalid_manifest_reports_plain_language_error_not_traceback(
    monkeypatch, tmp_path
):
    bad_manifest = tmp_path / "copilot.layers.yml"
    bad_manifest.write_text(
        """
version: 1
layers:
  - id: dept-a
    role: department
    rank: 20
    product: claude
    source:
      repo: https://example.invalid/a.git
    auth: anon
    activation: always
  - id: dept-b
    role: department
    rank: 20
    product: claude
    source:
      repo: https://example.invalid/b.git
    auth: anon
    activation: always
"""
    )
    monkeypatch.setattr(
        "cc.commands.resolve.resolve_key",
        lambda key, **_: str(bad_manifest) if key == "layers.manifest" else None,
    )

    result = runner.invoke(app, ["resolve", "--explain", "--json"])
    assert result.exit_code == 2

    payload = json.loads(result.output)
    assert payload["error"]["code"] == "invalid-manifest"
    assert "rank 20" in payload["error"]["message"]
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# WP-372 P5.1: `cc resolve` was blind to every pathless (remote-sourced)
# layer -- discover_contributions() requires a static local source.path,
# and the live manifest never carries one. resolve.py now synthesizes the
# same mirror-based path update.py already does (mirror.synthesize_
# source_path()), read-only.
# ---------------------------------------------------------------------------


def _pathless_layer(layer_id: str = "foundation", *, product: str = "claude") -> dict:
    """A layer with NO static `source.path` -- the exact shape of the live
    manifest (only `source.repo`, nothing local)."""
    return {
        "id": layer_id,
        "role": "foundation",
        "rank": 40,
        "product": product,
        "source": {"repo": f"https://example.invalid/{layer_id}.git", "ref": "main"},
        "auth": "anon",
        "activation": "always",
    }


def test_resolve_synthesizes_mirror_path_for_pathless_layer_and_folds_items(tmp_path):
    """A manifest with a pathless layer + a mirror ALREADY on disk (as if
    `cc update` already ran) -- resolve must fold real items, not report
    0, and must never clone/fetch anything to do it."""
    from cc.commands.resolve import build_resolve_report

    mirror_root = tmp_path / "mirrors"
    (mirror_root / "foundation" / "agents").mkdir(parents=True)
    (mirror_root / "foundation" / "agents" / "sec.md").write_text(
        "security agent body", encoding="utf-8"
    )

    report = build_resolve_report(
        _layers=[_pathless_layer("foundation")],
        _lockfile={},
        _mirror_root=mirror_root,
    )

    assert report["items"], "expected the already-mirrored content to resolve"
    item = report["items"][0]
    assert item["dimension"] == "agents"
    assert item["item"] == "sec"
    assert item["winning_layer"] == "foundation"


def test_resolve_synthesizes_product_scoped_mirror_path_for_externally_consumed_product(
    tmp_path,
):
    """knowledge/cli layers mirror one directory deeper
    (`<mirror_root>/<product>/<layer id>`) -- resolve must compute the
    SAME nested path `cc update` does (mirror.EXTERNALLY_CONSUMED_PRODUCTS),
    not the flat one."""
    from cc.commands.resolve import build_resolve_report

    mirror_root = tmp_path / "mirrors"
    (mirror_root / "knowledge" / "foundation" / "agents").mkdir(parents=True)
    (mirror_root / "knowledge" / "foundation" / "agents" / "kc.md").write_text(
        "knowledge agent body", encoding="utf-8"
    )

    report = build_resolve_report(
        _layers=[_pathless_layer("foundation", product="knowledge")],
        _lockfile={},
        _mirror_root=mirror_root,
    )

    assert report["items"]
    assert report["items"][0]["item"] == "kc"


def test_resolve_pathless_layer_with_no_mirror_on_disk_yet_is_honest_empty(tmp_path):
    """Read-only contract: if no `cc update` has run yet (no mirror on
    disk), resolve must NOT clone/fetch -- it degrades to an honest empty
    result via discover_contributions()'s own existing "path doesn't
    exist" fallback, never a crash."""
    from cc.commands.resolve import build_resolve_report

    report = build_resolve_report(
        _layers=[_pathless_layer("foundation")],
        _lockfile={},
        _mirror_root=tmp_path / "mirrors-that-do-not-exist",
    )

    assert report["items"] == []


def test_resolve_layer_with_explicit_local_path_is_unaffected_by_synthesis(monkeypatch, tmp_path):
    """A layer that ALREADY carries a static local source.path (the
    pre-P5.1 working case) must be completely unaffected -- synthesis is a
    no-op for it (mirror.synthesize_source_path() returns None whenever
    local_path is already set)."""
    payload, exit_code = _invoke_resolve_json(monkeypatch, tmp_path)
    assert exit_code == 0
    assert payload["items"]


def test_resolve_joins_subpath_onto_explicit_local_path(tmp_path):
    """A "visible checkout" layer (explicit `source.path`, the default
    since `feat(cc): place ecosystem repositories visibly`) that ALSO
    declares `source.subpath` (the live manifest's `claude-foundation`
    entry: checkout root + `.claude`) must resolve against
    `<path>/<subpath>`, exactly like `update.py`'s `elif local_path and
    subpath:` branch -- not the bare checkout root, which has no
    `commands/`/`agents/`/`skills/` of its own. Regression for the gap
    where `mirror.synthesize_source_path()` is a documented no-op for any
    layer with an explicit local path, so subpath was silently dropped and
    `cc resolve --explain` disagreed with what `cc update` actually
    materializes."""
    from cc.commands.resolve import build_resolve_report

    checkout_root = tmp_path / "claude-copilot"
    (checkout_root / ".claude" / "commands").mkdir(parents=True)
    (checkout_root / ".claude" / "commands" / "protocol.md").write_text(
        "foundation protocol body", encoding="utf-8"
    )
    # A decoy at the checkout root (NOT under .claude/) proves the fix
    # resolves against the subpath-joined root, not the bare checkout.
    (checkout_root / "commands").mkdir(parents=True)
    (checkout_root / "commands" / "protocol.md").write_text(
        "should never be discovered", encoding="utf-8"
    )

    layer = {
        "id": "claude-foundation",
        "role": "foundation",
        "rank": 40,
        "product": "claude",
        "source": {
            "repo": "https://example.invalid/claude-copilot.git",
            "ref": "v1.0.0",
            "path": str(checkout_root),
            "subpath": ".claude",
        },
        "auth": "anon",
        "activation": "always",
    }

    report = build_resolve_report(
        _layers=[layer],
        _lockfile={},
        _mirror_root=tmp_path / "mirrors-unused",
    )

    assert report["items"], "expected the subpath-joined foundation content to resolve"
    item = next(i for i in report["items"] if i["dimension"] == "commands")
    assert item["item"] == "protocol"
    assert item["winning_layer"] == "claude-foundation"


def test_resolve_rejects_subpath_that_escapes_the_checkout(tmp_path):
    """Same fail-closed boundary `update.py` already enforces: a
    `source.subpath` of `..` (or absolute) must raise ManifestError, never
    silently resolve outside the checkout."""
    from cc.commands.resolve import build_resolve_report
    from cc.core.ecosystem.manifest import ManifestError

    checkout_root = tmp_path / "claude-copilot"
    checkout_root.mkdir(parents=True)

    layer = {
        "id": "claude-foundation",
        "role": "foundation",
        "rank": 40,
        "product": "claude",
        "source": {
            "repo": "https://example.invalid/claude-copilot.git",
            "path": str(checkout_root),
            "subpath": "../escape",
        },
        "auth": "anon",
        "activation": "always",
    }

    with pytest.raises(ManifestError):
        build_resolve_report(
            _layers=[layer],
            _lockfile={},
            _mirror_root=tmp_path / "mirrors-unused",
        )


# ---------------------------------------------------------------------------
# `cc resolve` verb collision: legacy single-key mode must be unaffected
# ---------------------------------------------------------------------------


def test_resolve_legacy_key_mode_still_works(monkeypatch):
    monkeypatch.setattr(
        "cc.main.resolve_key",
        lambda key, scope=None, **_: "/resolved/value",
    )
    result = runner.invoke(app, ["resolve", "paths.memory"])
    assert result.exit_code == 0
    assert result.output.strip() == "/resolved/value"


def test_resolve_without_key_or_explain_errors_cleanly():
    result = runner.invoke(app, ["resolve"])
    assert result.exit_code != 0
