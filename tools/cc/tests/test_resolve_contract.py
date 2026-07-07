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
    """Every item must emit signer_of_introducing_commit: null and
    live_hash_matches: false until signature-verify + materialize land --
    never a fabricated 'signed'/'matches' verdict."""
    payload, _ = _invoke_resolve_json(monkeypatch, tmp_path)

    assert payload["items"]
    for entry in payload["items"]:
        assert entry["signer_of_introducing_commit"] is None
        assert entry["live_hash_matches"] is False


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
    source:
      repo: https://example.invalid/a.git
    auth: anon
    activation: always
  - id: dept-b
    role: department
    rank: 20
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
