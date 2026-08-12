"""WS-A-style contract test for `cc connect <service-id> --json` (WP-395's
D-6 manual keychain floor, WP-396/398 pragmatic connect design, Task
Copilot task 222): must validate against the vendored copilot-control-tower
`connect.schema.json`, must accept secret VALUES only via stdin (never
argv/env/a file), must never let a value reach any output/log/error, and
must leave an accurate per-credential report on a partial failure.

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/connect.schema.json (mirrors
test_connections_contract.py's identical precedent).

Every `run`/`ecosystem_cfg`/`check_keychain`/`stdin_reader`/`write_keychain`
fake below is a pure Python function or object -- no real `copilot`,
Infisical, or `security` subprocess is invoked by the unit-level tests.
`TestFakeSecurityBinaryEndToEnd` at the bottom is the one exception: it
PATH-shims a real fake `security` executable and lets the real
`core/keychain.py` writer shell out to it for real, to prove the
stdin-only mechanism at the OS-process level, not just at the injected-
callable level.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from cc.commands.connect import _connect_exit_code, build_connect_report
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _connect_validator() -> Draft202012Validator:
    connect_schema = _load_schema("connect.schema.json")
    connections_schema = _load_schema("connections.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            ("connections.schema.json", Resource.from_contents(connections_schema)),
            (connect_schema["$id"], Resource.from_contents(connect_schema)),
        ]
    )
    return Draft202012Validator(connect_schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _connect_validator()
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
    *, layers_services: list[dict[str, Any]], secret_keys: Optional[list[str]] = None
) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if tuple(args[:3]) == ("copilot", "--json", "layers"):
            return _cp(args, 0, json.dumps(_layers_payload(layers_services)))
        if tuple(args[:4]) == ("copilot", "infisical", "--json", "secret"):
            payload = [{"secretKey": key} for key in (secret_keys or [])]
            return _cp(args, 0, json.dumps(payload))
        raise AssertionError(f"unexpected run() call: {args}")

    return run


_INFISICAL_SERVICE = {
    "name": "infisical",
    "help": "Infisical secrets management",
    "tier": "org-internal",
    "mode": "adopt",
    "id": "infisical",
    "requires_secret": [
        {"name": "INFISICAL_CLIENT_ID", "from": "keychain"},
        {"name": "INFISICAL_CLIENT_SECRET", "from": "keychain"},
    ],
    "store_scope": None,
}

_GIT_SERVICE = {
    "name": "git",
    "help": "Git ops",
    "tier": "org-internal",
    "mode": "adopt",
    "id": "git",
    "requires_secret": [],
    "store_scope": None,
}


class _FakeKeychainStore:
    """In-memory stand-in for the OS keychain -- `check` feeds
    `check_keychain`, `write` feeds `write_keychain`. Shared across a single
    `build_connect_report()` call's two internal `build_connections_report()`
    evaluations, so a successful write is genuinely visible to the
    "re-run the presence checks" second pass, exactly like the real
    `security` CLI would make it visible."""

    def __init__(self, present: Optional[dict[str, str]] = None) -> None:
        self.present: dict[str, str] = dict(present or {})
        self.write_calls: list[tuple[str, str]] = []

    def check(self, name: str) -> bool:
        return name in self.present

    def write(self, name: str, value: str) -> bool:
        self.write_calls.append((name, value))
        self.present[name] = value
        return True


def _build(
    service_id: str,
    *,
    check_only: bool = False,
    stdin: str = "",
    services: Optional[list[dict[str, Any]]] = None,
    store: Optional[_FakeKeychainStore] = None,
    write_keychain: Optional[Callable[[str, str], bool]] = None,
    ecosystem_cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    services = services if services is not None else [_INFISICAL_SERVICE, _GIT_SERVICE]
    store = store if store is not None else _FakeKeychainStore()
    return build_connect_report(
        service_id,
        check_only=check_only,
        stdin_reader=lambda: stdin,
        run=_fake_run(layers_services=services, secret_keys=[]),
        ecosystem_cfg=ecosystem_cfg if ecosystem_cfg is not None else _CONNECTED_STORE_CFG,
        check_keychain=store.check,
        write_keychain=write_keychain if write_keychain is not None else store.write,
    )


# ---------------------------------------------------------------------------
# Unknown service / no missing credentials -- honest structured results
# ---------------------------------------------------------------------------


def test_unknown_service_is_an_honest_structured_result():
    report = _build("not-a-real-service", stdin="{}")
    _validate(report)
    assert report["result"] == "unknown-service"
    assert report["service"] is None
    assert report["credentials"] is None
    assert "not-a-real-service" in report["detail"]


def test_service_matches_by_id_first_then_by_name():
    services = [{**_INFISICAL_SERVICE, "id": "infisical-slug"}]
    by_id = _build("infisical-slug", services=services, stdin="{}")
    by_name = _build("infisical", services=services, stdin="{}")
    assert by_id["service"]["id"] == "infisical-slug"
    assert by_name["service"]["id"] == "infisical-slug"


def test_service_with_no_missing_credentials_never_reads_stdin():
    def boom() -> str:
        raise AssertionError("stdin must not be read when nothing is missing")

    report = build_connect_report(
        "git",
        stdin_reader=boom,
        run=_fake_run(layers_services=[_GIT_SERVICE], secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: False,
        write_keychain=lambda name, value: (_ for _ in ()).throw(AssertionError("no writes")),
    )
    _validate(report)
    assert report["result"] == "ok"
    assert report["credentials"] == []
    assert report["service"]["secret_state"] == "ready"


def test_already_satisfied_names_are_never_overwritten_even_if_supplied():
    store = _FakeKeychainStore(present={"INFISICAL_CLIENT_ID": "old-value", "INFISICAL_CLIENT_SECRET": "old2"})
    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "new-value"}),
        store=store,
    )
    _validate(report)
    assert report["credentials"] == [
        {"name": "INFISICAL_CLIENT_ID", "outcome": "already-present", "detail": None},
        {"name": "INFISICAL_CLIENT_SECRET", "outcome": "already-present", "detail": None},
    ]
    assert store.write_calls == []
    assert store.present["INFISICAL_CLIENT_ID"] == "old-value"


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------


def test_missing_credentials_are_stored_and_the_row_flips_to_ready():
    store = _FakeKeychainStore()
    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "secret-value"}),
        store=store,
    )
    _validate(report)
    assert report["result"] == "ok"
    assert report["mode"] == "connect"
    assert report["credentials"] == [
        {"name": "INFISICAL_CLIENT_ID", "outcome": "stored", "detail": None},
        {"name": "INFISICAL_CLIENT_SECRET", "outcome": "stored", "detail": None},
    ]
    assert store.write_calls == [
        ("INFISICAL_CLIENT_ID", "id-value"),
        ("INFISICAL_CLIENT_SECRET", "secret-value"),
    ]
    assert report["service"]["secret_state"] == "ready"
    assert report["service"]["missing"] == []


def test_partial_success_leaves_an_accurate_per_credential_report():
    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "id-value"}),  # secret omitted
    )
    _validate(report)
    assert report["credentials"] == [
        {"name": "INFISICAL_CLIENT_ID", "outcome": "stored", "detail": None},
        {
            "name": "INFISICAL_CLIENT_SECRET",
            "outcome": "failed",
            "detail": "no value was provided for this credential.",
        },
    ]
    # The row still honestly reports the still-missing name.
    assert report["service"]["missing"] == ["INFISICAL_CLIENT_SECRET"]


def test_keychain_write_failure_reports_failed_outcome():
    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "s"}),
        write_keychain=lambda name, value: False,
    )
    assert report["credentials"] == [
        {"name": "INFISICAL_CLIENT_ID", "outcome": "failed", "detail": "the keychain write failed."},
        {"name": "INFISICAL_CLIENT_SECRET", "outcome": "failed", "detail": "the keychain write failed."},
    ]
    assert report["service"]["secret_state"] == "needs-connect"


def test_keychain_unavailable_exception_is_a_structured_failure_not_a_crash():
    from cc.core.keychain import KeychainUnavailable

    def raises(name: str, value: str) -> bool:
        raise KeychainUnavailable("macOS Keychain is unavailable on this platform ('linux')")

    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "s"}),
        write_keychain=raises,
    )
    assert all(c["outcome"] == "failed" for c in report["credentials"])
    assert "linux" in report["credentials"][0]["detail"]


# ---------------------------------------------------------------------------
# Value validation -- empty, non-string, line breaks -- structured, no crash
# ---------------------------------------------------------------------------


def test_empty_value_is_a_structured_error_and_never_reaches_the_writer():
    def boom(name: str, value: str) -> bool:
        if name == "INFISICAL_CLIENT_ID":
            raise AssertionError("must never write an empty value")
        return True

    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "", "INFISICAL_CLIENT_SECRET": "s"}),
        write_keychain=boom,
    )
    by_name = {c["name"]: c for c in report["credentials"]}
    assert by_name["INFISICAL_CLIENT_ID"] == {
        "name": "INFISICAL_CLIENT_ID",
        "outcome": "failed",
        "detail": "value must not be empty.",
    }
    assert by_name["INFISICAL_CLIENT_SECRET"]["outcome"] == "stored"


def test_non_string_value_is_a_structured_error():
    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": 12345, "INFISICAL_CLIENT_SECRET": "s"}),
    )
    by_name = {c["name"]: c for c in report["credentials"]}
    assert by_name["INFISICAL_CLIENT_ID"]["outcome"] == "failed"
    assert by_name["INFISICAL_CLIENT_ID"]["detail"] == "value must be a string."


def test_value_with_line_break_is_rejected_before_the_writer_is_ever_called():
    def boom(name: str, value: str) -> bool:
        if name == "INFISICAL_CLIENT_ID":
            raise AssertionError("must never write a value containing a line break")
        return True

    report = _build(
        "infisical",
        stdin=json.dumps({"INFISICAL_CLIENT_ID": "line1\nline2", "INFISICAL_CLIENT_SECRET": "s"}),
        write_keychain=boom,
    )
    by_name = {c["name"]: c for c in report["credentials"]}
    assert by_name["INFISICAL_CLIENT_ID"]["outcome"] == "failed"
    assert by_name["INFISICAL_CLIENT_ID"]["detail"] == "value must not contain a line break."


# ---------------------------------------------------------------------------
# stdin parsing -- invalid JSON never leaks into any output
# ---------------------------------------------------------------------------


def test_malformed_json_stdin_is_invalid_input_and_never_echoed():
    report = _build("infisical", stdin='{"INFISICAL_CLIENT_ID": "top-secret-should-never-leak"')
    _validate(report)
    assert report["result"] == "invalid-input"
    serialized = json.dumps(report)
    assert "top-secret-should-never-leak" not in serialized
    assert all(c["outcome"] == "failed" for c in report["credentials"])
    assert report["detail"] == "stdin was not valid JSON."


def test_stdin_json_array_instead_of_object_is_invalid_input():
    report = _build("infisical", stdin=json.dumps(["INFISICAL_CLIENT_ID", "value"]))
    assert report["result"] == "invalid-input"
    assert all(c["outcome"] == "failed" for c in report["credentials"])


def test_oversized_stdin_is_rejected_without_reading_it_as_credentials():
    huge = json.dumps({"INFISICAL_CLIENT_ID": "x" * 200_000})
    report = _build("infisical", stdin=huge)
    assert report["result"] == "invalid-input"


# ---------------------------------------------------------------------------
# --check mode -- no stdin, no writes, just the row
# ---------------------------------------------------------------------------


def test_check_mode_never_reads_stdin_or_writes():
    def boom_stdin() -> str:
        raise AssertionError("--check must never read stdin")

    def boom_write(name: str, value: str) -> bool:
        raise AssertionError("--check must never write")

    report = build_connect_report(
        "infisical",
        check_only=True,
        stdin_reader=boom_stdin,
        run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: True,
        write_keychain=boom_write,
    )
    _validate(report)
    assert report["mode"] == "check"
    assert report["credentials"] is None
    assert report["service"]["secret_state"] == "ready"


def test_check_mode_on_unknown_service_is_still_honest():
    report = build_connect_report(
        "not-real",
        check_only=True,
        stdin_reader=lambda: (_ for _ in ()).throw(AssertionError()),
        run=_fake_run(layers_services=[_GIT_SERVICE], secret_keys=[]),
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: False,
        write_keychain=lambda n, v: True,
    )
    assert report["result"] == "unknown-service"
    assert report["mode"] == "check"
    assert report["service"] is None
    assert report["credentials"] is None


# ---------------------------------------------------------------------------
# Envelope passthrough -- copilot-unavailable / org-config-unavailable
# ---------------------------------------------------------------------------


def test_copilot_unavailable_is_passed_through_honestly():
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _cp(args, 127, "", "copilot is not installed.")

    report = build_connect_report(
        "infisical",
        stdin_reader=lambda: "{}",
        run=run,
        ecosystem_cfg=_CONNECTED_STORE_CFG,
        check_keychain=lambda name: False,
        write_keychain=lambda n, v: True,
    )
    _validate(report)
    assert report["result"] == "copilot-unavailable"
    assert report["service"] is None
    assert report["credentials"] is None


def test_org_config_unavailable_still_lets_keychain_hinted_names_connect():
    """A keychain-hinted/never-store-able name doesn't need the org's
    ecosystem.yml at all -- connect should still be able to write it even
    when `org-config-unavailable` is the envelope-level result."""
    store = _FakeKeychainStore()
    report = build_connect_report(
        "infisical",
        stdin_reader=lambda: json.dumps(
            {"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "secret-value"}
        ),
        run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
        ecosystem_cfg={},  # no materialized org config
        check_keychain=store.check,
        write_keychain=store.write,
    )
    _validate(report)
    assert report["result"] == "org-config-unavailable"
    assert report["credentials"] == [
        {"name": "INFISICAL_CLIENT_ID", "outcome": "stored", "detail": None},
        {"name": "INFISICAL_CLIENT_SECRET", "outcome": "stored", "detail": None},
    ]
    assert report["service"]["secret_state"] == "ready"


# ---------------------------------------------------------------------------
# _connect_exit_code()
# ---------------------------------------------------------------------------


def test_exit_code_zero_when_ok_and_nothing_failed():
    assert _connect_exit_code({"result": "ok", "credentials": [{"outcome": "stored"}]}) == 0
    assert _connect_exit_code({"result": "ok", "credentials": []}) == 0
    assert _connect_exit_code({"result": "ok", "credentials": None}) == 0


def test_exit_code_one_when_any_credential_failed():
    assert (
        _connect_exit_code(
            {"result": "ok", "credentials": [{"outcome": "stored"}, {"outcome": "failed"}]}
        )
        == 1
    )


def test_exit_code_one_when_result_not_ok():
    assert _connect_exit_code({"result": "unknown-service", "credentials": None}) == 1
    assert _connect_exit_code({"result": "invalid-input", "credentials": [{"outcome": "failed"}]}) == 1


# ---------------------------------------------------------------------------
# CLI wiring (`cc connect ...`)
# ---------------------------------------------------------------------------


def test_connect_cmd_json_matches_schema_and_stores_via_stdin(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )
    store = _FakeKeychainStore()
    monkeypatch.setattr("cc.commands.connections._check_keychain", store.check)
    monkeypatch.setattr("cc.commands.connect._default_write_keychain", lambda n, v: store.write(n, v))

    result = runner.invoke(
        app,
        ["connect", "infisical", "--json"],
        input=json.dumps({"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "secret-value"}),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["result"] == "ok"
    assert payload["service"]["secret_state"] == "ready"
    assert "id-value" not in result.output
    assert "secret-value" not in result.output


def test_connect_cmd_exits_nonzero_on_unknown_service(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.connections._run", _fake_run(layers_services=[_GIT_SERVICE], secret_keys=[])
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )

    result = runner.invoke(app, ["connect", "not-real", "--json"], input="{}")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["result"] == "unknown-service"


def test_connect_cmd_exits_nonzero_on_partial_failure(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )
    monkeypatch.setattr("cc.commands.connections._check_keychain", lambda n: False)

    result = runner.invoke(
        app, ["connect", "infisical", "--json"], input=json.dumps({"INFISICAL_CLIENT_ID": "id-value"})
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["result"] == "ok"  # envelope is fine; the per-credential report carries the failure
    assert any(c["outcome"] == "failed" for c in payload["credentials"])


def test_connect_cmd_check_flag_never_prompts_for_stdin(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )
    monkeypatch.setattr("cc.commands.connections._check_keychain", lambda n: True)

    result = runner.invoke(app, ["connect", "infisical", "--check", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["mode"] == "check"
    assert payload["credentials"] is None
    assert payload["service"]["secret_state"] == "ready"


def test_connect_cmd_rich_output_never_prints_a_value(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.connections._run",
        _fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
    )
    monkeypatch.setattr(
        "cc.commands.connections.load_ecosystem_config", lambda: _CONNECTED_STORE_CFG
    )
    store = _FakeKeychainStore()
    monkeypatch.setattr("cc.commands.connections._check_keychain", store.check)
    monkeypatch.setattr("cc.commands.connect._default_write_keychain", lambda n, v: store.write(n, v))

    result = runner.invoke(
        app,
        ["connect", "infisical"],
        input=json.dumps({"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "secret-value"}),
    )
    assert result.exit_code == 0, result.output
    assert "stored" in result.output
    assert "id-value" not in result.output
    assert "secret-value" not in result.output


# ---------------------------------------------------------------------------
# Fake-`security`-binary end-to-end proof (PATH-shimmed, real subprocess)
# ---------------------------------------------------------------------------

_FAKE_SECURITY_SCRIPT = r'''#!/usr/bin/env python3
"""Fake `security` for tests: a tiny stand-in that supports exactly the two
invocations cc's keychain code makes (`find-generic-password` presence-only,
and `-i` interactive/batch mode for writes), backed by a JSON state file, and
logs every argv list it was invoked with so a test can assert a secret value
never appeared there.
"""
import json
import os
import shlex
import sys

STATE_PATH = os.environ["FAKE_KEYCHAIN_STATE"]
ARGV_LOG = os.environ["FAKE_SECURITY_ARGV_LOG"]


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)


def log_argv(argv):
    with open(ARGV_LOG, "a") as f:
        f.write(json.dumps(argv) + "\n")


def key_for(service, account):
    return f"{service}::{account}"


def handle_add(tokens):
    account = service = password = None
    saw_update = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-a":
            account = tokens[i + 1]
            i += 2
        elif tok == "-s":
            service = tokens[i + 1]
            i += 2
        elif tok == "-w":
            password = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2
        elif tok == "-U":
            saw_update = True
            i += 1
        else:
            i += 1
    if account is None or service is None or password is None:
        sys.stderr.write("fake security: missing -a/-s/-w\n")
        return 1
    del saw_update  # accepted, not required to branch on for this fake
    state = load_state()
    state[key_for(service, account)] = password
    save_state(state)
    return 0


def handle_find(argv):
    account = service = None
    want_value = "-w" in argv
    i = 0
    while i < len(argv):
        if argv[i] == "-a":
            account = argv[i + 1]
            i += 2
        elif argv[i] == "-s":
            service = argv[i + 1]
            i += 2
        else:
            i += 1
    state = load_state()
    key = key_for(service, account)
    if key not in state:
        sys.stderr.write(
            "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.\n"
        )
        return 44
    if want_value:
        sys.stdout.write(state[key] + "\n")
    return 0


def main():
    argv = sys.argv[1:]
    log_argv(argv)
    if argv[:1] == ["-i"]:
        rc = 0
        for line in sys.stdin.read().splitlines():
            line = line.strip()
            if not line:
                continue
            tokens = shlex.split(line)
            if not tokens:
                continue
            cmd, rest = tokens[0], tokens[1:]
            if cmd == "add-generic-password":
                rc = handle_add(rest)
            else:
                sys.stderr.write(f"fake security: unknown command {cmd!r}\n")
                rc = 1
        return rc
    if argv[:1] == ["find-generic-password"]:
        return handle_find(argv[1:])
    sys.stderr.write(f"fake security: unsupported invocation {argv!r}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


class TestFakeSecurityBinaryEndToEnd:
    """PATH-shims a real `security` executable (a fake) and lets the REAL
    `core/keychain.py` writer and `connections.py`'s default `_check_keychain`
    shell out to it as a genuine subprocess -- the strongest available proof
    that a value never reaches argv: the fake records the exact argv IT was
    invoked with (as the OS delivered it), and a test asserts the value is
    absent from every logged call.
    """

    def _install_fake_security(self, tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
        # The production Keychain boundary is intentionally Darwin-only.
        # This fixture supplies a real subprocess fake, so make the platform
        # precondition explicit instead of depending on the host running the
        # test suite.
        monkeypatch.setattr("cc.core.keychain.sys.platform", "darwin")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_security = bin_dir / "security"
        fake_security.write_text(_FAKE_SECURITY_SCRIPT, encoding="utf-8")
        fake_security.chmod(fake_security.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        state_path = tmp_path / "keychain_state.json"
        argv_log = tmp_path / "argv_log.jsonl"
        monkeypatch.setenv("FAKE_KEYCHAIN_STATE", str(state_path))
        monkeypatch.setenv("FAKE_SECURITY_ARGV_LOG", str(argv_log))
        # Prepend (not replace) so `python3`/other tools the fake's shebang
        # needs remain resolvable; our fake is first, so it wins the lookup.
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        return state_path, argv_log

    def _read_argv_log(self, argv_log: Path) -> list[list[str]]:
        if not argv_log.exists():
            return []
        return [json.loads(line) for line in argv_log.read_text().splitlines() if line]

    def test_stored_value_never_appears_in_any_logged_argv(self, tmp_path, monkeypatch):
        _state_path, argv_log = self._install_fake_security(tmp_path, monkeypatch)
        secret_value = "sekrit-42-do-not-leak"

        report = build_connect_report(
            "infisical",
            stdin_reader=lambda: json.dumps(
                {"INFISICAL_CLIENT_ID": secret_value, "INFISICAL_CLIENT_SECRET": "other-value"}
            ),
            run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
            # check_keychain/write_keychain left at their real defaults --
            # both shell to "security" and must resolve our PATH-shimmed fake.
        )

        assert report["credentials"] == [
            {"name": "INFISICAL_CLIENT_ID", "outcome": "stored", "detail": None},
            {"name": "INFISICAL_CLIENT_SECRET", "outcome": "stored", "detail": None},
        ]

        calls = self._read_argv_log(argv_log)
        assert calls, "the fake security binary was never invoked"
        for call in calls:
            assert secret_value not in call
            assert all(secret_value not in token for token in call)
            # The write path must be `-i` (batch/stdin), never argv `-w VALUE`.
            if call and call[0] != "-i":
                assert "-w" not in call, f"a non-interactive call carried -w: {call}"

    def test_value_travelled_via_stdin_not_argv(self, tmp_path, monkeypatch):
        _state_path, argv_log = self._install_fake_security(tmp_path, monkeypatch)
        secret_value = "another-sekrit-value"

        build_connect_report(
            "infisical",
            stdin_reader=lambda: json.dumps(
                {"INFISICAL_CLIENT_ID": secret_value, "INFISICAL_CLIENT_SECRET": "x"}
            ),
            run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
        )

        # The fake only ever *sees* the value by persisting it from stdin
        # inside its own `-i` handling -- prove the value actually landed in
        # the fake's state (i.e. it WAS received, just never via argv).
        state = json.loads(_state_path.read_text())
        assert state.get("copilot-cli::INFISICAL_CLIENT_ID") == secret_value

    def test_round_trips_through_check_after_connect(self, tmp_path, monkeypatch):
        self._install_fake_security(tmp_path, monkeypatch)

        connect_report = build_connect_report(
            "infisical",
            stdin_reader=lambda: json.dumps(
                {"INFISICAL_CLIENT_ID": "id-value", "INFISICAL_CLIENT_SECRET": "secret-value"}
            ),
            run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
        )
        assert connect_report["service"]["secret_state"] == "ready"

        check_report = build_connect_report(
            "infisical",
            check_only=True,
            run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
        )
        _validate(check_report)
        assert check_report["service"]["secret_state"] == "ready"
        assert check_report["service"]["missing"] == []

    def test_already_present_outcome_does_not_invoke_the_writer(self, tmp_path, monkeypatch):
        state_path, argv_log = self._install_fake_security(tmp_path, monkeypatch)
        state_path.write_text(
            json.dumps(
                {
                    "copilot-cli::INFISICAL_CLIENT_ID": "existing-id",
                    "copilot-cli::INFISICAL_CLIENT_SECRET": "existing-secret",
                }
            )
        )

        report = build_connect_report(
            "infisical",
            check_only=True,
            run=_fake_run(layers_services=[_INFISICAL_SERVICE], secret_keys=[]),
            ecosystem_cfg=_CONNECTED_STORE_CFG,
        )
        assert report["service"]["secret_state"] == "ready"
        calls = self._read_argv_log(argv_log)
        # Every logged call must be a presence check (find-generic-password),
        # never a write (`-i`), since nothing was missing to write.
        assert all(call[:1] == ["find-generic-password"] for call in calls)
