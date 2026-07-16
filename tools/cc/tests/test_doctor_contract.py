"""WS-A contract test: `cc doctor --json` must validate against the vendored
copilot-control-tower `doctor.schema.json`, and must never emit a false
`healthy` verdict.

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copies live in tests/fixtures/schemas/ (see the `$comment` header in
each vendored file) so this test does not depend on a sibling checkout being
present on disk.

WS-A doctor-completion (Stream-B) additions below: the status-ladder cases
and the field-set parity assertion against the vendored corpus fixture
(tests/fixtures/corpus/ -- same vendoring precedent as tests/fixtures/schemas/)
exercise `build_doctor_report()` directly (rather than through the CLI) so
every I/O root can be injected and no test here ever touches a real
`~/.claude`/`~/.copilot`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands.doctor import build_doctor_report
from cc.core.locking import copilot_lock
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"
_CORPUS_DIR = Path(__file__).parent / "fixtures" / "corpus"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _doctor_validator() -> Draft202012Validator:
    doctor_schema = _load_schema("doctor.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (doctor_schema["$id"], Resource.from_contents(doctor_schema)),
        ]
    )
    return Draft202012Validator(doctor_schema, registry=registry)


def _invoke_doctor_json() -> tuple[dict, int]:
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.output)
    return payload, result.exit_code


def test_doctor_json_validates_against_contract_schema():
    """`cc doctor --json` output must be a valid doctor.schema.json instance."""
    payload, exit_code = _invoke_doctor_json()

    validator = _doctor_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)

    # Exit code must be one of the WS-A contract's 0 (clean) / 1 (any fail
    # checker) / 2 (environment error) values -- never the legacy 3.
    assert exit_code in (0, 1, 2)


def test_doctor_json_false_healthy_is_impossible():
    """A `healthy` status must never coexist with a fail checker or offline=True.

    This mirrors the schema's own `allOf` invariant but is asserted directly
    against the real CLI output (not just a hand-built fixture) so a
    regression in build_doctor_report()'s status computation fails loudly
    here, independent of the schema check above.
    """
    payload, _ = _invoke_doctor_json()

    if payload["status"] == "healthy":
        assert payload["offline"] is False
        assert not any(c["severity"] == "fail" for c in payload["checkers"])
        assert not any(
            a.get("state") in ("expired", "revoked") for a in payload.get("auth", [])
        )


@pytest.mark.parametrize(
    "checkers,expect_healthy_allowed",
    [
        ([{"id": "x", "severity": "pass", "destructive": False}], True),
        ([{"id": "x", "severity": "fail", "destructive": False}], False),
    ],
)
def test_schema_rejects_healthy_with_fail_checker(checkers, expect_healthy_allowed):
    """Directly exercise the vendored schema's false-Healthy guard."""
    validator = _doctor_validator()
    instance = {
        "schema_version": "1.0",
        "host": "test-host",
        "score": 100,
        "status": "healthy",
        "offline": False,
        "checkers": checkers,
        "auth": [],
    }
    errors = list(validator.iter_errors(instance))
    if expect_healthy_allowed:
        assert not errors
    else:
        assert errors


# ---------------------------------------------------------------------------
# Test helpers -- real tmp git repos for the manifest/lock-pointer engine
# (mirrors tests/test_update_contract.py's _make_source_repo /
# tests/test_ecosystem_mirror.py's _make_fixture_repo precedent).
# ---------------------------------------------------------------------------


def _canonical_lock_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _make_source_repo(tmp_path: Path, lock_slice: dict, *, name: str, ref: str) -> Path:
    """Init a local git repo and publish `ref` -> the blob sha of
    `lock_slice`'s canonical JSON bytes (the lock-pointer convention --
    core/ecosystem/mirror.py's module docstring)."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    lock_file = repo / "copilot.lock.json"
    lock_file.write_bytes(_canonical_lock_bytes(lock_slice))

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    blob_sha = subprocess.run(
        ["git", "hash-object", "-w", "copilot.lock.json"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "update-ref", ref, blob_sha], cwd=repo, check=True)
    return repo


def _layer(layer_id: str, product: str, repo: Path, *, rank: int = 40) -> dict:
    return {
        "id": layer_id,
        "role": layer_id,
        "rank": rank,
        "product": product,
        "source": {"repo": str(repo)},
        "auth": "anon",
        "activation": "always",
    }


def _base_kwargs(tmp_path: Path, **overrides) -> dict:
    """Every doctor I/O root injected at a tmp-path default, so no case here
    ever touches a real `~/.claude`/`~/.copilot`.

    Writes a CLEAN machine/project config pair by default (so `setup-needed`
    -- the highest-precedence lifecycle state -- doesn't swallow every other
    status-ladder case here); `test_setup_needed_outranks_every_other_signal`
    is the one case that deliberately overrides these back to missing paths.
    """
    machine_cfg = tmp_path / "machine.json"
    machine_cfg.write_text("{}", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("x\n", encoding="utf-8")
    project_cfg = tmp_path / "project.json"
    project_cfg.write_text("{}", encoding="utf-8")

    base = {
        "_machine_cfg_path": machine_cfg,
        "_project_cfg_path": project_cfg,
        "_resolved_cfg": {},
        "_layers": [],
        "_lockfile": {},
        "_mirror_root": tmp_path / "mirrors",
        "_auth_root": tmp_path / "auth",
        "_lock_probe_path": tmp_path / "copilot.lock",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Status ladder -- offline / update-available / signed-out / syncing / healthy
# ---------------------------------------------------------------------------


def test_status_healthy_with_matching_component_checker(tmp_path):
    repo = _make_source_repo(
        tmp_path, {"agents": {"sec": "abc1234"}}, name="org-source", ref="refs/copilot/lock"
    )
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _layers=[_layer("org", "knowledge", repo)],
            _lockfile=lock,
        )
    )

    assert report["status"] == "healthy"
    assert report["offline"] is False
    sync_checker = next(c for c in report["checkers"] if c["id"] == "knowledge-org-sync")
    assert sync_checker["severity"] == "pass"
    assert sync_checker["local_sha"] == sync_checker["remote_sha"]


def test_status_update_available_when_local_behind_remote(tmp_path):
    repo = _make_source_repo(
        tmp_path, {"agents": {"sec": "def5678"}}, name="org-source", ref="refs/copilot/lock"
    )
    lock = {"org": {"agents": {"sec": "abc1234"}}}  # local slice differs from remote's

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _layers=[_layer("org", "knowledge", repo)],
            _lockfile=lock,
        )
    )

    assert report["status"] == "update-available"
    assert report["offline"] is False
    sync_checker = next(c for c in report["checkers"] if c["id"] == "knowledge-org-sync")
    assert sync_checker["severity"] == "warn"
    assert sync_checker["repair"] == "cc update"


def test_status_offline_when_remote_unreachable(tmp_path):
    unreachable = tmp_path / "does-not-exist-at-all"
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _layers=[_layer("org", "knowledge", unreachable)],
            _lockfile=lock,
        )
    )

    assert report["status"] == "offline"
    assert report["offline"] is True
    sync_checker = next(c for c in report["checkers"] if c["id"] == "knowledge-org-sync")
    assert sync_checker["severity"] == "warn"
    assert "could not reach remote" in sync_checker["detail"]
    assert "remote_sha" not in sync_checker


def test_status_needs_attention_outranks_offline(tmp_path):
    """A config-checker warn (e.g. missing machine config) must win over an
    offline component-checker signal -- needs-attention > offline in the
    ladder."""
    unreachable = tmp_path / "does-not-exist-at-all"
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    kwargs = _base_kwargs(
        tmp_path,
        _layers=[_layer("org", "knowledge", unreachable)],
        _lockfile=lock,
        # A plain config-checker warn (path not found) -- must outrank the
        # offline component-checker signal below.
        _resolved_cfg={"paths.shared_docs": str(tmp_path / "missing-shared-docs")},
    )

    report = build_doctor_report(**kwargs)

    assert report["status"] == "needs-attention"
    # The offline signal is still honestly reported at the top level even
    # though a worse status won the ladder.
    assert report["offline"] is True


def test_status_signed_out_when_keychain_token_missing(tmp_path):
    auth_root = tmp_path / "auth"
    auth_root.mkdir()
    (auth_root / "active.json").write_text(
        json.dumps({"login": "octocat", "scopes": "read:org repo"}), encoding="utf-8"
    )

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _auth_root=auth_root,
            _keychain_get_secret=lambda account, *, service: None,  # no token stored
        )
    )

    assert report["status"] == "signed-out"
    assert report["auth"] == [{"identity": "octocat", "scope": "read:org repo", "state": "revoked"}]


def test_status_signed_out_expired_when_expires_at_in_past(tmp_path):
    auth_root = tmp_path / "auth"
    auth_root.mkdir()
    (auth_root / "active.json").write_text(
        json.dumps(
            {"login": "octocat", "scopes": "read:org", "expires_at": "2020-01-01T00:00:00Z"}
        ),
        encoding="utf-8",
    )

    report = build_doctor_report(**_base_kwargs(tmp_path, _auth_root=auth_root))

    assert report["status"] == "signed-out"
    entry = report["auth"][0]
    assert entry["state"] == "expired"
    assert entry["identity"] == "octocat"
    assert entry["expires_at"] == "2020-01-01T00:00:00Z"


def test_no_auth_entry_when_never_signed_in(tmp_path):
    """No identity pointer at all -- not a failure, just no entry."""
    report = build_doctor_report(**_base_kwargs(tmp_path, _auth_root=tmp_path / "no-such-auth-dir"))
    assert report["auth"] == []


def test_no_auth_entry_when_keychain_has_the_token(tmp_path):
    auth_root = tmp_path / "auth"
    auth_root.mkdir()
    (auth_root / "active.json").write_text(
        json.dumps({"login": "octocat", "scopes": "read:org"}), encoding="utf-8"
    )

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _auth_root=auth_root,
            _keychain_get_secret=lambda account, *, service: "a-real-token",
        )
    )

    assert report["auth"] == []
    assert report["status"] != "signed-out"


def test_status_syncing_when_lock_currently_held(tmp_path):
    lock_probe_path = tmp_path / "copilot.lock"

    with copilot_lock(path=lock_probe_path):
        report = build_doctor_report(**_base_kwargs(tmp_path, _lock_probe_path=lock_probe_path))

    assert report["status"] == "syncing"


def test_probe_never_creates_lock_file_when_absent(tmp_path):
    """cc doctor is read-only -- probing for contention must never itself
    create the lock file if it doesn't already exist."""
    lock_probe_path = tmp_path / "copilot.lock"
    assert not lock_probe_path.exists()

    report = build_doctor_report(**_base_kwargs(tmp_path, _lock_probe_path=lock_probe_path))

    assert report["status"] != "syncing"
    assert not lock_probe_path.exists()


def test_setup_needed_outranks_every_other_signal(tmp_path):
    kwargs = _base_kwargs(
        tmp_path,
        _machine_cfg_path=tmp_path / "missing-machine-config.json",
        _project_cfg_path=tmp_path / "missing-project-config.json",
    )
    report = build_doctor_report(**kwargs)
    assert report["status"] == "setup-needed"


# ---------------------------------------------------------------------------
# Full schema validation with a rich checkers[]/auth[] payload
# ---------------------------------------------------------------------------


def test_doctor_json_with_component_and_auth_checkers_validates_against_schema(tmp_path):
    repo = _make_source_repo(
        tmp_path, {"agents": {"sec": "abc1234"}}, name="org-source", ref="refs/copilot/lock"
    )
    auth_root = tmp_path / "auth"
    auth_root.mkdir()
    (auth_root / "active.json").write_text(
        json.dumps({"login": "octocat", "scopes": "read:org"}), encoding="utf-8"
    )

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _layers=[_layer("org", "knowledge", repo)],
            _lockfile={"org": {"agents": {"sec": "abc1234"}}},
            _auth_root=auth_root,
            _keychain_get_secret=lambda account, *, service: None,
        )
    )

    validator = _doctor_validator()
    errors = sorted(validator.iter_errors(report), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)
    assert report["status"] == "signed-out"


# ---------------------------------------------------------------------------
# Field-set parity against the vendored Control Tower corpus fixture
# ---------------------------------------------------------------------------


def test_field_set_parity_with_healthy_clean_fleet_corpus(tmp_path):
    """The real `doctor --json` payload must use the SAME set of top-level
    keys, and the SAME set of possible per-checker keys, as Control Tower's
    own `healthy-clean-fleet.json` fixture corpus -- proving this slice's
    emission shape (not just the schema, which is deliberately permissive
    via `additionalProperties: true` on checkers) matches what the app
    actually expects to render."""
    corpus = json.loads((_CORPUS_DIR / "healthy-clean-fleet.json").read_text(encoding="utf-8"))

    repo = _make_source_repo(
        tmp_path, {"agents": {"sec": "abc1234"}}, name="org-source", ref="refs/copilot/lock"
    )
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    report = build_doctor_report(
        **_base_kwargs(
            tmp_path,
            _layers=[_layer("org", "knowledge", repo)],
            _lockfile=lock,
        )
    )

    assert set(report.keys()) == set(corpus.keys())

    corpus_checker_keys = {key for checker in corpus["checkers"] for key in checker}
    report_checker_keys = {key for checker in report["checkers"] for key in checker}
    # Every key this slice's sync checker emits must be one the corpus
    # already documents (never a novel, undocumented field); the corpus
    # may use additional keys (e.g. "repair") this particular scenario
    # doesn't happen to exercise.
    assert report_checker_keys <= corpus_checker_keys

    sync_checker = next(c for c in report["checkers"] if c["id"] == "knowledge-org-sync")
    corpus_sync_checker = next(
        c for c in corpus["checkers"] if c["id"] == "knowledge-org-sync"
    )
    assert set(sync_checker.keys()) == set(corpus_sync_checker.keys())
