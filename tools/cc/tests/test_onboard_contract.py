import base64
import json
import shutil
import subprocess
from pathlib import Path

import cc.commands.onboard as onboard_module
import pytest
import yaml
from cc.commands.onboard import (
    build_ecosystem_onboard_report,
    build_personal_onboard_report,
)
from jsonschema import Draft202012Validator

# WS-A contract: every report this module emits must validate against the
# vendored copilot-control-tower onboard.schema.json (same vendoring
# precedent as test_doctor_contract.py -- see the `$comment` header on the
# vendored file). The schema's top-level `oneOf` already discriminates
# between the personal `repositoryReport` shape and the `ecosystemReport`
# shape, so one validator call handles both report families.
_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _onboard_validator() -> Draft202012Validator:
    schema = json.loads(
        (_SCHEMA_DIR / "onboard.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def _assert_valid_onboard_report(report: dict) -> None:
    validator = _onboard_validator()
    errors = sorted(validator.iter_errors(report), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


class FakeGitHub:
    def __init__(self, repos=None, errors=None):
        self.repos = {
            name: (
                value if isinstance(value, dict) else {"private": value, "files": {}}
            )
            for name, value in (repos or {}).items()
        }
        self.errors = set(errors or ())
        self.calls = []

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args[:4] == ("gh", "api", "user", "--jq"):
            return subprocess.CompletedProcess(args, 0, "pablo\n", "")
        if "POST" in args and "user/repos" in args:
            name = args[args.index("-f") + 1].removeprefix("name=")
            self.repos[name] = {"private": True, "files": {}}
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if "PUT" in args:
            endpoint = args[args.index("PUT") + 1]
            parts = endpoint.split("/")
            name = parts[2]
            encoded = next(
                value.removeprefix("content=")
                for value in args
                if value.startswith("content=")
            )
            self.repos[name]["files"]["copilot.layer.yml"] = base64.b64decode(
                encoded
            ).decode()
            return subprocess.CompletedProcess(args, 0, "{}", "")

        endpoint = args[2]
        parts = endpoint.split("/")
        name = parts[2]
        if name in self.errors:
            return subprocess.CompletedProcess(args, 1, "", "network unavailable")
        if name not in self.repos:
            return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
        repo = self.repos[name]
        if len(parts) == 3:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"private": repo["private"]}), ""
            )
        files = repo["files"]
        if len(parts) == 4:  # root contents
            if not files:
                return subprocess.CompletedProcess(
                    args, 1, "", "gh: Not Found (HTTP 404)"
                )
            return subprocess.CompletedProcess(
                args, 0, json.dumps([{"name": path} for path in files]), ""
            )
        path = "/".join(parts[4:])
        if path not in files:
            return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
        encoded = base64.b64encode(files[path].encode()).decode()
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"content": encoded}), ""
        )


def test_default_github_runner_uses_authorized_keychain_token_without_argv_leak(
    monkeypatch,
):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = tuple(args)
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(
        onboard_module, "resolve_executable", lambda _: Path("/usr/local/bin/gh")
    )
    monkeypatch.setattr(
        onboard_module.authstore, "read_identity", lambda: {"login": "pablo"}
    )
    monkeypatch.setattr(onboard_module, "resolve_key", lambda _: "github-service")
    monkeypatch.setattr(
        onboard_module.keychain,
        "get_secret",
        lambda account, service: "synthetic-token",
    )
    monkeypatch.setattr(onboard_module.subprocess, "run", fake_run)

    result = onboard_module._run(("gh", "api", "user"))

    assert result.returncode == 0
    assert captured["args"] == ("/usr/local/bin/gh", "api", "user")
    assert "synthetic-token" not in captured["args"]
    assert captured["env"]["GH_TOKEN"] == "synthetic-token"


def test_default_github_runner_falls_back_to_supported_absolute_path(
    monkeypatch, tmp_path
):
    gh_path = tmp_path / "gh"
    gh_path.write_text("#!/bin/sh\n", encoding="utf-8")
    gh_path.chmod(0o755)
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = tuple(args)
        return subprocess.CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(
        onboard_module, "resolve_executable", lambda _: gh_path.resolve()
    )
    monkeypatch.setattr(onboard_module.authstore, "read_identity", lambda: {})
    monkeypatch.setattr(onboard_module.subprocess, "run", fake_run)

    result = onboard_module._run(("gh", "api", "user/orgs", "--paginate"))

    assert result.returncode == 0
    assert captured["args"] == (
        str(gh_path.resolve()),
        "api",
        "user/orgs",
        "--paginate",
    )


def test_default_github_runner_stays_fail_closed_without_supported_binary(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(onboard_module, "resolve_executable", lambda _: None)

    result = onboard_module._run(("gh", "api", "user/orgs", "--paginate"))

    assert result.returncode == 127
    assert result.stdout == ""
    assert result.stderr == "gh is not installed."


def test_default_codex_runner_resolves_env_node_runtime_outside_shell_path(
    monkeypatch, tmp_path
):
    codex = tmp_path / "lib" / "codex.js"
    codex.parent.mkdir(parents=True)
    codex.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    codex.chmod(0o755)
    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"marketplaceName\":\"enac-materialized\"}'\n",
        encoding="utf-8",
    )
    node.chmod(0o755)

    def resolve(command):
        return {"codex": codex, "node": node}.get(command)

    monkeypatch.setattr(onboard_module, "resolve_executable", resolve)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    result = onboard_module._run(
        ("codex", "plugin", "marketplace", "add", "/tmp/catalog", "--json")
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["marketplaceName"] == "enac-materialized"


def test_default_codex_runner_fails_closed_when_env_runtime_is_missing(
    monkeypatch, tmp_path
):
    codex = tmp_path / "codex.js"
    codex.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    codex.chmod(0o755)
    monkeypatch.setattr(
        onboard_module,
        "resolve_executable",
        lambda command: codex if command == "codex" else None,
    )

    result = onboard_module._run(("codex", "plugin", "list", "--json"))

    assert result.returncode == 127
    assert result.stdout == ""
    assert result.stderr == "node runtime required by codex is not installed."


def test_codex_plugin_install_is_idempotent_and_uses_supported_commands(
    monkeypatch, tmp_path
):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )
    calls = []

    def run(args):
        calls.append(tuple(args))
        if args[2] == "marketplace":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"marketplaceName":"enac-materialized","alreadyAdded":true}',
                "",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            '{"pluginId":"codex-copilot@enac-materialized"}',
            "",
        )

    first = onboard_module._install_codex_plugin(apply=True, run=run)
    second = onboard_module._install_codex_plugin(apply=True, run=run)

    assert first == {"result": "ready"}
    assert second == {"result": "ready"}
    assert (
        calls
        == [
            (
                "codex",
                "plugin",
                "marketplace",
                "add",
                str(root),
                "--json",
            ),
            (
                "codex",
                "plugin",
                "add",
                "codex-copilot@enac-materialized",
                "--json",
            ),
        ]
        * 2
    )
    marketplace = json.loads(
        (root / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace["name"] == "enac-materialized"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugins/codex-copilot"


def test_codex_plugin_plan_uses_read_only_codex_inventory(monkeypatch, tmp_path):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"enac-materialized"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )
    calls = []

    def run(args):
        calls.append(tuple(args))
        if args[2] == "marketplace":
            payload = {
                "marketplaces": [{"name": "enac-materialized", "root": str(root)}]
            }
        else:
            payload = {
                "installed": [
                    {
                        "pluginId": "codex-copilot@enac-materialized",
                        "installed": True,
                        "enabled": True,
                    }
                ]
            }
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    report = onboard_module._install_codex_plugin(apply=False, run=run)

    assert report == {"result": "ready"}
    assert calls == [
        ("codex", "plugin", "marketplace", "list", "--json"),
        ("codex", "plugin", "list", "--json"),
    ]


def test_codex_plugin_plan_reports_unregistered_marketplace_as_change(
    monkeypatch, tmp_path
):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"enac-materialized"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )

    report = onboard_module._install_codex_plugin(
        apply=False,
        run=lambda args: subprocess.CompletedProcess(
            args, 0, '{"marketplaces":[]}', ""
        ),
    )

    assert report == {"result": "changes-required"}


def test_codex_plugin_plan_fails_closed_when_codex_cannot_start(monkeypatch, tmp_path):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"enac-materialized"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )

    report = onboard_module._install_codex_plugin(
        apply=False,
        run=lambda args: subprocess.CompletedProcess(
            args, 127, "", "node runtime required by codex is not installed."
        ),
    )

    assert report == {
        "result": "blocked",
        "detail": (
            "Codex is installed, but its required command-line runtime "
            "could not be started outside the terminal."
        ),
    }


@pytest.mark.parametrize(
    ("marketplace_stdout", "plugin_stdout", "detail"),
    (
        (
            "not-json",
            None,
            "Codex returned an unreadable marketplace inventory.",
        ),
        (
            '{"marketplaces":[{"name":"enac-materialized","root":"ROOT"}]}',
            "not-json",
            "Codex returned an unreadable plugin inventory.",
        ),
    ),
)
def test_codex_plugin_plan_fails_closed_on_unreadable_inventory(
    monkeypatch, tmp_path, marketplace_stdout, plugin_stdout, detail
):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"enac-materialized"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )
    marketplace_stdout = marketplace_stdout.replace("ROOT", str(root))
    responses = iter(
        response
        for response in (marketplace_stdout, plugin_stdout)
        if response is not None
    )

    report = onboard_module._install_codex_plugin(
        apply=False,
        run=lambda args: subprocess.CompletedProcess(args, 0, next(responses), ""),
    )

    assert report == {"result": "blocked", "detail": detail}


@pytest.mark.parametrize(
    ("result", "detail"),
    (
        (
            subprocess.CompletedProcess(
                (),
                127,
                "",
                "codex is not installed.",
            ),
            "Codex is not installed in a supported location on this Mac.",
        ),
        (
            subprocess.CompletedProcess(
                (),
                127,
                "",
                "node runtime required by codex is not installed.",
            ),
            (
                "Codex is installed, but its required command-line runtime "
                "could not be started outside the terminal."
            ),
        ),
        (
            subprocess.CompletedProcess((), 1, "", "policy rejected"),
            "Codex rejected the verified local marketplace.",
        ),
    ),
)
def test_codex_marketplace_failures_are_distinct_and_do_not_leak_stderr(
    monkeypatch, tmp_path, result, detail
):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )

    report = onboard_module._install_codex_plugin(apply=True, run=lambda _args: result)

    assert report == {"result": "blocked", "detail": detail}
    assert result.stderr not in report["detail"]


def test_codex_plugin_install_failure_is_distinct_from_marketplace_failure(
    monkeypatch, tmp_path
):
    root = tmp_path / "materialized" / "codex"
    manifest = root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"codex-copilot"}\n', encoding="utf-8")
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: root if key == "paths.codex_materialize_root" else None,
    )
    calls = 0

    def run(args):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            args,
            0 if calls == 1 else 1,
            "{}",
            "" if calls == 1 else "install policy rejected",
        )

    report = onboard_module._install_codex_plugin(apply=True, run=run)

    assert report == {
        "result": "blocked",
        "detail": "Codex rejected the Codex Copilot plugin installation.",
    }


def test_copilot_probe_uses_resolved_absolute_executable(monkeypatch, tmp_path):
    copilot = tmp_path / "copilot"
    copilot.write_text("#!/bin/sh\n", encoding="utf-8")
    copilot.chmod(0o755)
    manifest = tmp_path / "copilot.layers.yml"
    manifest.write_text("version: 1\nlayers: []\n", encoding="utf-8")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = tuple(args)
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, '{"chain": [], "services": []}', "")

    monkeypatch.setattr(
        onboard_module, "resolve_executable", lambda _: copilot.resolve()
    )
    monkeypatch.setattr(onboard_module.subprocess, "run", fake_run)

    payload, detail = onboard_module._copilot_layers_payload(manifest)

    assert detail == ""
    assert payload == {"chain": [], "services": []}
    assert captured["args"] == (str(copilot.resolve()), "--json", "layers")
    assert captured["env"]["COPILOT_LAYERS_FILE"] == str(manifest)


def test_plan_reuses_private_and_marks_only_404_missing():
    gh = FakeGitHub({"claude-copilot-private": True})
    report = build_personal_onboard_report(components=("claude", "codex"), run=gh)
    assert report["result"] == "changes-required"
    assert [row["state"] for row in report["repositories"]] == [
        "existing-private",
        "missing",
    ]
    assert not any("POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_apply_creates_missing_private_repository():
    gh = FakeGitHub()
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["state"] == "created"
    assert report["repositories"][0]["package_state"] == "seeded"
    post = next(call for call in gh.calls if "POST" in call)
    assert "private=true" in post
    assert "auto_init=false" in post
    assert any("PUT" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_unknown_read_blocks_all_creation():
    gh = FakeGitHub(errors={"codex-copilot-private"})
    report = build_personal_onboard_report(
        components=("claude", "codex"), apply=True, run=gh
    )
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "unknown"
    assert not any("POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_public_collision_blocks_all_creation():
    gh = FakeGitHub({"codex-copilot-private": False})
    report = build_personal_onboard_report(
        components=("claude", "codex"), apply=True, run=gh
    )
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "conflict-public"
    assert not any("POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_existing_empty_private_repository_is_seeded_without_recreation():
    gh = FakeGitHub({"codex-copilot-private": True})
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["state"] == "existing-private"
    assert report["repositories"][0]["package_state"] == "seeded"
    assert not any("POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_existing_valid_rank_ten_manifest_is_reused():
    manifest = """schema_version: '1.0'\npackage:\n  role: personal\n  rank: 10\n  product: codex\n  owner: authenticated-user\ndimensions: []\n"""
    gh = FakeGitHub(
        {
            "codex-copilot-private": {
                "private": True,
                "files": {"copilot.layer.yml": manifest},
            }
        }
    )
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["package_state"] == "ready"
    assert not any("PUT" in call or "POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


# ---------------------------------------------------------------------------
# B1: the personal-content refusal becomes an offer (`adoptable`)
# ---------------------------------------------------------------------------


def test_adoptable_state_is_not_blocked():
    """A private, non-empty repo with no root marker is an offer, not a
    refusal: plan result is `changes-required`, never `blocked`."""
    gh = FakeGitHub(
        {"claude-copilot-private": {"private": True, "files": {"notes.md": "mine"}}}
    )
    report = build_personal_onboard_report(components=("claude", "codex"), run=gh)
    assert report["result"] == "changes-required"
    claude_row = report["repositories"][0]
    assert claude_row["package_state"] == "adoptable"
    assert claude_row["package_action"] == "adopt"
    assert claude_row["action"] == "none"
    # The cost of declining is component-specific, plain-language, and
    # CLI-authored -- the app never invents this sentence (invariant #1).
    assert claude_row["decline_detail"] == (
        "Without this, Claude Copilot can't be set up on this Mac. "
        "You can include it later."
    )
    codex_row = report["repositories"][1]
    assert codex_row["package_state"] == "missing"
    assert codex_row["decline_detail"] == ""
    assert not any("PUT" in call or "POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_invalid_marker_still_blocks():
    """A present-but-unrecognized marker MUST stay hard-blocking `held`: the
    write would not be purely additive, unlike the no-marker-at-all case."""
    gh = FakeGitHub(
        {
            "claude-copilot-private": {
                "private": True,
                "files": {"copilot.layer.yml": "not: a-recognized-manifest\n"},
            }
        }
    )
    report = build_personal_onboard_report(
        components=("claude", "codex"), apply=True, run=gh
    )
    assert report["result"] == "blocked"
    assert report["repositories"][0]["package_state"] == "held"
    assert not any("PUT" in call or "POST" in call for call in gh.calls)
    _assert_valid_onboard_report(report)


def test_adopt_writes_marker_only_with_consent():
    """Consenting to adopt writes exactly the marker file -- additive only,
    the person's own pre-existing content is left untouched."""
    gh = FakeGitHub(
        {"claude-copilot-private": {"private": True, "files": {"notes.md": "mine"}}}
    )
    report = build_personal_onboard_report(
        components=("claude",), apply=True, adopt_existing=("claude",), run=gh
    )
    assert report["result"] == "applied"
    row = report["repositories"][0]
    assert row["package_state"] == "adopted"
    assert row["package_action"] == "none"
    assert not any("POST" in call for call in gh.calls)
    assert sum("PUT" in call for call in gh.calls) == 1
    files = gh.repos["claude-copilot-private"]["files"]
    assert files["notes.md"] == "mine"
    assert "copilot.layer.yml" in files
    _assert_valid_onboard_report(report)


def test_no_consent_is_a_noop():
    """An adoptable component left out of `--adopt-existing` is a no-op:
    nothing is written, and the offer stays open for next time."""
    gh = FakeGitHub(
        {"claude-copilot-private": {"private": True, "files": {"notes.md": "mine"}}}
    )
    report = build_personal_onboard_report(components=("claude",), apply=True, run=gh)
    assert report["result"] == "applied"
    row = report["repositories"][0]
    assert row["package_state"] == "adoptable"
    assert row["package_action"] == "adopt"
    assert not any("PUT" in call or "POST" in call for call in gh.calls)
    assert gh.repos["claude-copilot-private"]["files"] == {"notes.md": "mine"}
    _assert_valid_onboard_report(report)


def test_mixed_two_of_four_component_consent():
    """Claude, Codex, Knowledge, and CLI never share a fate: each adoptable
    component is decided on its own, never all-or-nothing."""
    gh = FakeGitHub(
        {
            f"{component}-copilot-private": {
                "private": True,
                "files": {"notes.md": "mine"},
            }
            for component in ("claude", "codex", "knowledge", "cli")
        }
    )
    report = build_personal_onboard_report(
        components=("claude", "codex", "knowledge", "cli"),
        apply=True,
        adopt_existing=("claude", "knowledge"),
        run=gh,
    )
    assert report["result"] == "applied"
    by_component = {row["component"]: row for row in report["repositories"]}
    assert by_component["claude"]["package_state"] == "adopted"
    assert by_component["knowledge"]["package_state"] == "adopted"
    assert by_component["codex"]["package_state"] == "adoptable"
    assert by_component["cli"]["package_state"] == "adoptable"
    # Consenting clears the cost of declining; a still-adoptable component
    # keeps its own component-specific sentence, never a shared one.
    assert by_component["claude"]["decline_detail"] == ""
    assert by_component["knowledge"]["decline_detail"] == ""
    assert by_component["codex"]["decline_detail"] == (
        "Without this, Codex Copilot can't be set up on this Mac. "
        "You can include it later."
    )
    assert by_component["cli"]["decline_detail"] == (
        "Without this, CLI Copilot can't be set up on this Mac. "
        "You can include it later."
    )
    written = {
        name for name, repo in gh.repos.items() if "copilot.layer.yml" in repo["files"]
    }
    assert written == {"claude-copilot-private", "knowledge-copilot-private"}
    _assert_valid_onboard_report(report)


def test_personal_inventory_carries_decline_detail_only_for_adoptable_rows():
    """The wizard's question-screen items get the same `decline_detail` the
    repository rows carry -- present (non-empty) only where the CLI marked
    the component `adoptable`, empty everywhere else."""
    personal = {
        "repositories": [
            {
                "component": "claude",
                "state": "existing-private",
                "package_state": "adoptable",
                "package_detail": "Your own content is already in here.",
                "decline_detail": (
                    "Without this, Claude Copilot can't be set up on this "
                    "Mac. You can include it later."
                ),
            },
            {
                "component": "codex",
                "state": "existing-private",
                "package_state": "ready",
                "package_detail": "Already set up. Everything in here will be kept.",
                "decline_detail": "",
            },
        ]
    }
    items = onboard_module._personal_inventory(personal)
    by_id = {item["id"]: item for item in items}
    assert by_id["personal-claude"]["decline_detail"] == (
        "Without this, Claude Copilot can't be set up on this Mac. "
        "You can include it later."
    )
    assert by_id["personal-codex"]["decline_detail"] == ""


def _aggregate_run(args):
    endpoint = args[2]
    if endpoint.endswith("/contents/ecosystem.yml"):
        handoff = """schema_version: '2.0'
org: Acme
harness: [claude, codex]
components: [knowledge, cli, claude, codex]
store:
  status: deferred
foundation:
  refs:
    knowledge: '^0.1.0'
    cli: '^0.3.0'
    claude: '^5.8.0'
    codex: '^0.6.0'
"""
        encoded = base64.b64encode(handoff.encode()).decode()
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"content": encoded}), ""
        )
    if endpoint.endswith("claude-copilot/tags"):
        return subprocess.CompletedProcess(
            args, 0, '[{"name":"v5.9.0"},{"name":"v6.0.0"}]', ""
        )
    if endpoint.endswith("codex-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.6.2"}]', "")
    if endpoint.endswith("knowledge-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.1.0"}]', "")
    if endpoint.endswith("cli-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.3.1"}]', "")
    raise AssertionError(args)


def _personal(**_kwargs):
    return {
        "result": "ready",
        "owner": "pablo",
        "summary": {
            "existing": 2,
            "missing": 0,
            "created": 0,
            "seeded": 0,
            "held": 0,
            "blocked": 0,
        },
    }


def _ssh(**_kwargs):
    return {
        "result": "ready",
        "key": "existing",
        "registration": "registered",
        "config": "ready",
        "detail": "ready",
    }


def _ssh_adoptable(**_kwargs):
    """B1 for the SSH gate, shaped exactly like a real `changes-required`
    adoption report: an already-working alias offered instead of refused."""
    return {
        "result": "changes-required",
        "key": "existing",
        "registration": "registered",
        "config": "adoptable",
        "detail": (
            "Your existing github-work alias already works and signs in as "
            "pablo. I'll leave it exactly as it is."
        ),
        "decline_detail": (
            "Without this, the github-personal alias won't be set up, and "
            "this device won't have everything it needs. Your existing "
            "github-work alias is never touched either way."
        ),
        "adopted_alias": "github-work",
        "missing_alias": "github-personal",
    }


def _codex(*, apply, **_kwargs):
    return {"result": "ready" if apply else "changes-required"}


def _cli(_manifest_path):
    return {"result": "ready"}


def _consumer_ready(*_args):
    return {"result": "ready"}


def test_ecosystem_plan_fails_closed_when_codex_inventory_is_blocked(tmp_path):
    def blocked_codex(**_kwargs):
        return {
            "result": "blocked",
            "detail": "Codex could not inspect installed plugins.",
        }

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=False,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=blocked_codex,
        consumer_probe_fn=_consumer_ready,
    )

    assert report["result"] == "blocked"
    assert report["stages"][-1] == {
        "stage": "codex-plugin",
        "result": "blocked",
        "detail": "Codex could not inspect installed plugins.",
    }
    _assert_valid_onboard_report(report)


def test_ecosystem_plan_builds_four_isolated_three_layer_stacks(tmp_path):
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=False,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
    )
    assert report["result"] == "changes-required"
    assert report["components"] == ["knowledge", "cli", "claude", "codex"]
    assert [
        (layer["product"], layer["role"], layer["rank"]) for layer in report["layers"]
    ] == [
        ("knowledge", "personal", 10),
        ("knowledge", "organization", 30),
        ("knowledge", "foundation", 40),
        ("cli", "personal", 10),
        ("cli", "organization", 30),
        ("cli", "foundation", 40),
        ("claude", "personal", 10),
        ("claude", "organization", 30),
        ("claude", "foundation", 40),
        ("codex", "personal", 10),
        ("codex", "organization", 30),
        ("codex", "foundation", 40),
    ]
    assert [stage["stage"] for stage in report["stages"]] == [
        "organization-handoff",
        "personal-packages",
        "device-ssh",
        "layer-manifest",
        "secret-store",
        "codex-plugin",
    ]
    assert not (tmp_path / "layers.yml").exists()
    _assert_valid_onboard_report(report)


def test_ecosystem_plan_provisions_every_handoff_component(tmp_path):
    seen: list[tuple[str, ...]] = []

    def personal(**kwargs):
        seen.append(tuple(kwargs["components"]))
        return _personal(**kwargs)

    report = build_ecosystem_onboard_report(
        org="Acme",
        products=("claude",),
        apply=False,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
    )

    assert seen == [("knowledge", "cli", "claude", "codex")]
    assert report["products"] == ["claude"]
    assert report["components"] == ["knowledge", "cli", "claude", "codex"]
    _assert_valid_onboard_report(report)


def test_ecosystem_plan_offers_adoptable_ssh_alias_instead_of_blocking(tmp_path):
    """B1 for the SSH gate: a working-but-unmanaged alias downgrades the plan
    to `changes-required`, never `blocked`, and surfaces a machine-scope
    inventory row an app can render as a question -- the same shape an
    adoptable personal package already gets, and the same `--adopt-existing`
    plumbing carries the consent back in."""
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=False,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh_adoptable,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
    )
    assert report["result"] == "changes-required"
    ssh_stage = next(
        stage for stage in report["stages"] if stage["stage"] == "device-ssh"
    )
    assert ssh_stage["config"] == "adoptable"
    # The stage dict only ever carries the schema's whitelisted fields --
    # the richer adoption fields belong to the inventory row, not the stage.
    assert "adopted_alias" not in ssh_stage
    assert "decline_detail" not in ssh_stage
    ssh_item = next(item for item in report["inventory"] if item["id"] == "device-ssh")
    assert ssh_item["scope"] == "machine"
    assert ssh_item["action"] == "create"
    assert ssh_item["reversible"] is True
    assert ssh_item["decline_detail"]
    _assert_valid_onboard_report(report)


def test_manifest_plan_keeps_recognized_legacy_cli_layers(tmp_path):
    target = tmp_path / "copilot.layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    component: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: ssh-work
""",
        encoding="utf-8",
    )
    desired = {
        "version": 1,
        "org": "Acme",
        "layers": [
            {
                "id": "claude-personal",
                "role": "personal",
                "rank": 10,
                "product": "claude",
                "source": {
                    "repo": "git@github-personal:pablo/claude-copilot-private.git",
                    "ref": "main",
                },
                "auth": "personal",
                "activation": "always",
            }
        ],
    }

    plan = onboard_module._manifest_adoption_plan(
        desired, target, configured_path=target
    )

    assert plan.action == "repair"
    retained, managed = plan.payload["layers"]
    assert retained["id"] == "cli-organization"
    assert retained["component"] == "cli"
    assert "product" not in retained
    assert "activation" not in retained
    assert managed["product"] == "claude"


def test_manifest_plan_holds_managed_id_with_different_repository(tmp_path):
    target = tmp_path / "copilot.layers.yml"
    target.write_text(
        """version: 1
org: Acme
layers:
  - id: codex-personal
    role: personal
    rank: 10
    product: codex
    source: {repo: git@github-personal:pablo/my-custom-layer.git, ref: main}
    auth: personal
    activation: always
""",
        encoding="utf-8",
    )
    desired = {
        "version": 1,
        "org": "Acme",
        "layers": [
            {
                "id": "codex-personal",
                "role": "personal",
                "rank": 10,
                "product": "codex",
                "source": {
                    "repo": "git@github-personal:pablo/codex-copilot-private.git",
                    "ref": "main",
                },
                "auth": "personal",
                "activation": "always",
            }
        ],
    }

    plan = onboard_module._manifest_adoption_plan(
        desired, target, configured_path=target
    )

    assert plan.action == "review"
    assert "isn't one I recognize" in plan.detail


def test_existing_eight_layer_machine_repairs_to_all_twelve_layers(tmp_path):
    handoff = {
        "foundation": {
            "refs": {
                "knowledge": "v0.1.0",
                "cli": "v0.3.1",
                "claude": "v5.9.0",
                "codex": "v0.6.2",
            }
        }
    }
    desired = onboard_module._layer_manifest(
        "Acme", "pablo", ("knowledge", "cli", "claude", "codex"), handoff, run=_aggregate_run
    )
    existing_layers = [
        dict(layer)
        for layer in desired["layers"]
        if layer["product"] in {"cli", "claude", "codex"}
        and not (layer["product"] == "cli" and layer["role"] == "personal")
    ]
    for layer in existing_layers:
        if layer["product"] == "cli" and layer["role"] == "organization":
            layer["role"] = "org"
            layer["auth"] = "ssh-work"
        if layer["product"] == "cli" and layer["role"] == "foundation":
            layer["source"] = {
                "repo": "https://github.com/Everyone-Needs-A-Copilot/cli-copilot.git",
                "ref": "^0.3.0",
            }
            layer["auth"] = "anon"
    target = tmp_path / "copilot.layers.yml"
    target.write_text(
        yaml.safe_dump({"version": 1, "org": "Acme", "layers": existing_layers}),
        encoding="utf-8",
    )
    authoring = tmp_path / "knowledge-copilot-internal"
    authoring.mkdir()
    authored_file = authoring / "private.md"
    authored_file.write_text("keep me", encoding="utf-8")

    plan = onboard_module._manifest_adoption_plan(desired, target, configured_path=target)

    assert plan.action == "repair"
    assert plan.payload is not None
    assert len(plan.payload["layers"]) == 12
    assert {layer["product"] for layer in plan.payload["layers"]} == {
        "knowledge", "cli", "claude", "codex"
    }
    assert authored_file.read_text(encoding="utf-8") == "keep me"


def test_existing_eight_layer_machine_apply_commits_all_four_products_without_touching_authored_repos(
    tmp_path,
):
    handoff = {
        "foundation": {
            "refs": {
                "knowledge": "v0.1.0",
                "cli": "v0.3.1",
                "claude": "v5.9.0",
                "codex": "v0.6.2",
            }
        }
    }
    desired = onboard_module._layer_manifest(
        "Acme",
        "pablo",
        ("knowledge", "cli", "claude", "codex"),
        handoff,
        run=_aggregate_run,
    )
    existing_layers = [
        dict(layer)
        for layer in desired["layers"]
        if layer["product"] in {"cli", "claude", "codex"}
        and not (layer["product"] == "cli" and layer["role"] == "personal")
    ]
    for layer in existing_layers:
        if layer["product"] == "cli" and layer["role"] == "organization":
            layer["role"] = "org"
            layer["auth"] = "ssh-work"
        if layer["product"] == "cli" and layer["role"] == "foundation":
            layer["source"] = {
                "repo": "https://github.com/Everyone-Needs-A-Copilot/cli-copilot.git",
                "ref": "^0.3.0",
            }
            layer["auth"] = "anon"
    target = tmp_path / "copilot.layers.yml"
    target.write_text(
        yaml.safe_dump({"version": 1, "org": "Acme", "layers": existing_layers}),
        encoding="utf-8",
    )
    before = target.read_bytes()
    authoring = tmp_path / "knowledge-copilot-internal"
    authoring.mkdir()
    authored_file = authoring / "private.md"
    authored_file.write_text("keep me exactly", encoding="utf-8")
    committed = []

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=lambda **_: (
            {"result": "up-to-date", "blocked": [], "held_for_approval": []},
            0,
        ),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
        commit_config_fn=lambda path, knowledge: committed.append(
            (path, list(knowledge))
        ),
    )

    assert report["result"] == "ready"
    applied = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert len(applied["layers"]) == 12
    assert {
        (layer["product"], layer["role"])
        for layer in applied["layers"]
    } == {
        (product, role)
        for product in ("knowledge", "cli", "claude", "codex")
        for role in ("personal", "organization", "foundation")
    }
    rollback = Path(
        next(
            stage for stage in report["stages"] if stage["stage"] == "layer-manifest"
        )["rollback_path"]
    )
    assert rollback.read_bytes() == before
    assert authored_file.read_text(encoding="utf-8") == "keep me exactly"
    assert committed and committed[0][0] == target
    assert len(committed[0][1]) == 3
    _assert_valid_onboard_report(report)


def test_machine_pointer_commit_is_atomic_and_preserves_unrelated_config(tmp_path):
    config_path = onboard_module.machine_config_path()
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "$schema": "cc-config-v1",
                "version": 1,
                "github_app": {"org": "Acme"},
                "paths": {"projects": "/existing"},
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "copilot.layers.yml"
    knowledge_paths = ["/mirrors/knowledge/personal", "/mirrors/knowledge/org"]

    written = onboard_module._commit_machine_pointers(
        manifest_path, knowledge_paths
    )

    assert written == config_path
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["layers"]["manifest"] == str(manifest_path)
    assert payload["paths"]["knowledge_repo"] == knowledge_paths
    assert payload["paths"]["projects"] == "/existing"
    assert payload["github_app"]["org"] == "Acme"


def test_manifest_migration_is_reversible_and_removes_only_recognized_source(tmp_path):
    legacy = tmp_path / "old" / "copilot.layers.yml"
    legacy.parent.mkdir()
    legacy.write_text(
        """version: 1
layers:
  - id: cli-foundation
    role: foundation
    component: cli
    rank: 40
    source: {repo: https://example.test/cli.git, ref: v1.0.0}
    auth: anon
""",
        encoding="utf-8",
    )
    target = tmp_path / "new" / "copilot.layers.yml"
    desired = {
        "version": 1,
        "org": "Acme",
        "layers": [
            {
                "id": "codex-foundation",
                "role": "foundation",
                "rank": 40,
                "product": "codex",
                "source": {"repo": "https://example.test/codex.git", "ref": "v1.0.0"},
                "auth": "anon",
                "activation": "always",
            }
        ],
    }
    before = legacy.read_bytes()
    plan = onboard_module._manifest_adoption_plan(
        desired, target, configured_path=legacy
    )

    backup = onboard_module._apply_manifest_adoption(plan)

    assert plan.action == "migrate"
    assert backup is not None and backup.read_bytes() == before
    assert not legacy.exists()
    retained = yaml.safe_load(target.read_text())["layers"][0]
    assert retained["component"] == "cli"
    assert "product" not in retained


def test_manifest_repair_is_not_a_checkbox_and_applies_without_any_consent(tmp_path):
    """`layer-manifest` is infrastructure, not a B1 offer: a `repair` row
    must never be `reversible` (that would render an ask-row checkbox the
    person could clear), and the repair must complete on `apply=True` even
    when `adopt_existing` is empty -- nobody is ever asked. If this ever
    regresses to gating the write on a consent token, the file would stay
    unrepaired here and the assertions below would catch it."""
    target = tmp_path / "layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    component: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: ssh-work
""",
        encoding="utf-8",
    )
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        adopt_existing=(),  # explicit: nobody consented to anything
        update_fn=lambda **_: (
            {"result": "up-to-date", "blocked": [], "held_for_approval": []},
            0,
        ),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
    )
    manifest_stage = next(s for s in report["stages"] if s["stage"] == "layer-manifest")
    assert manifest_stage["action"] == "repair"
    assert manifest_stage["result"] == "applied"
    manifest_item = next(i for i in report["inventory"] if i["id"] == "layer-manifest")
    assert manifest_item["reversible"] is False
    written = yaml.safe_load(target.read_text())
    cli = next(layer for layer in written["layers"] if layer["id"] == "org-internal")
    assert cli["product"] == "cli"
    products = {layer["product"] for layer in written["layers"] if "product" in layer}
    assert products == {"knowledge", "cli", "claude", "codex"}
    assert report["result"] == "ready"
    _assert_valid_onboard_report(report)


def test_candidate_consumer_rejection_blocks_before_any_apply(tmp_path):
    target = tmp_path / "layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    component: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: ssh-work
""",
        encoding="utf-8",
    )
    before = target.read_bytes()
    apply_calls = []

    def personal(*, apply, **_kwargs):
        apply_calls.append(apply)
        return _personal()

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=lambda *_: {
            "result": "blocked",
            "detail": "The installed reader would lose Discord.",
        },
    )

    assert report["result"] == "blocked"
    assert apply_calls == [False]
    assert target.read_bytes() == before
    assert not (tmp_path / ".copilot-control-tower-backups").exists()
    manifest_stage = next(s for s in report["stages"] if s["stage"] == "layer-manifest")
    assert manifest_stage["result"] == "blocked"
    assert "lose Discord" in manifest_stage["detail"]
    _assert_valid_onboard_report(report)


def test_cli_candidate_probe_rejects_capability_loss(tmp_path, monkeypatch):
    baseline = tmp_path / "before.yml"
    baseline.write_text("version: 1\nlayers: []\n", encoding="utf-8")
    candidate = tmp_path / "candidate.yml"
    candidate.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    product: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: work
    activation: always
""",
        encoding="utf-8",
    )

    def payload(path):
        services = [
            {"name": "git", "tier": "foundation", "mode": "base"},
            {"name": "discord", "tier": "foundation", "mode": "base"},
        ]
        if path == baseline:
            services[-1] = {
                "name": "discord",
                "tier": "organization",
                "mode": "provides",
            }
        return (
            {
                "chain": [
                    {
                        "id": "cli-organization",
                        "role": "organization",
                        "rank": 30,
                        "repo": "git@github-work:Acme/cli-copilot-internal.git",
                        "ref": "main",
                        "auth": "work",
                        "unit": None,
                    }
                ],
                "services": services,
            },
            "",
        )

    monkeypatch.setattr(onboard_module, "_copilot_layers_payload", payload)

    result = onboard_module._probe_cli_candidate(candidate, baseline)

    assert result["result"] == "blocked"
    assert "discord" in result["detail"]


def test_materialize_failure_restores_exact_manifest_and_rematerializes_prior(
    tmp_path,
):
    target = tmp_path / "layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    component: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: ssh-work
""",
        encoding="utf-8",
    )
    before = target.read_bytes()
    updates = []

    def update(**kwargs):
        updates.append(Path(kwargs["_manifest_path"]).read_bytes())
        if len(updates) == 1:
            return {"result": "blocked", "blocked": [{}], "held_for_approval": []}, 2
        return {"result": "up-to-date", "blocked": [], "held_for_approval": []}, 0

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=update,
        doctor_fn=lambda **_: pytest.fail("doctor must not run after update failure"),
    )

    assert report["result"] == "blocked"
    assert len(updates) == 2
    assert updates[0] != before
    assert updates[1] == before
    assert target.read_bytes() == before
    manifest_stage = next(s for s in report["stages"] if s["stage"] == "layer-manifest")
    assert manifest_stage["result"] == "rolled-back"
    assert Path(manifest_stage["rollback_path"]).read_bytes() == before
    _assert_valid_onboard_report(report)


def test_unhealthy_post_apply_doctor_restores_exact_manifest(tmp_path):
    target = tmp_path / "layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-organization
    role: organization
    component: cli
    rank: 30
    source: {repo: git@github-work:Acme/cli-copilot-internal.git, ref: main}
    auth: ssh-work
""",
        encoding="utf-8",
    )
    before = target.read_bytes()
    updates = []

    def update(**kwargs):
        updates.append(Path(kwargs["_manifest_path"]).read_bytes())
        return {"result": "up-to-date", "blocked": [], "held_for_approval": []}, 0

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=update,
        doctor_fn=lambda **_: {"status": "unhealthy", "score": 20},
    )

    assert report["result"] == "blocked"
    assert len(updates) == 2
    assert updates[1] == before
    assert target.read_bytes() == before
    manifest_stage = next(s for s in report["stages"] if s["stage"] == "layer-manifest")
    assert manifest_stage["result"] == "rolled-back"
    _assert_valid_onboard_report(report)


def test_unfamiliar_manifest_blocks_before_personal_apply(tmp_path):
    target = tmp_path / "layers.yml"
    target.write_text("this: is-not-a-layer-manifest\n", encoding="utf-8")
    apply_calls = []

    def personal(*, apply, **_kwargs):
        apply_calls.append(apply)
        return {
            "result": "ready",
            "owner": "pablo",
            "repositories": [],
            "summary": {
                "existing": 2,
                "missing": 0,
                "created": 0,
                "seeded": 0,
                "held": 0,
                "blocked": 0,
            },
        }

    before = target.read_bytes()
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        personal_fn=personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
    )

    assert report["result"] == "blocked"
    assert report["inventory"][-1]["action"] == "review"
    assert apply_calls == [False]
    assert target.read_bytes() == before
    _assert_valid_onboard_report(report)


def test_symlinked_manifest_is_held_without_following_or_replacing_it(tmp_path):
    outside = tmp_path / "outside.yml"
    outside.write_text("version: 1\nlayers: []\n", encoding="utf-8")
    target = tmp_path / "home" / "copilot.layers.yml"
    target.parent.mkdir()
    target.symlink_to(outside)
    desired = {"version": 1, "org": "Acme", "layers": [{"id": "codex-foundation"}]}

    plan = onboard_module._manifest_adoption_plan(
        desired,
        target,
        configured_path=target,
        allowed_root=target.parent,
    )

    assert plan.action == "review"
    assert target.is_symlink()
    assert outside.read_text() == "version: 1\nlayers: []\n"


@pytest.mark.parametrize(
    "target",
    (
        Path.home() / ".config" / "copilot" / "copilot.layers.yml",
        Path.home() / ".copilot" / "copilot.layers.yml",
        Path.home() / ".copilot-cli" / "copilot.layers.yml",
    ),
)
def test_atomic_yaml_refuses_real_manifest_paths_during_pytest(target):
    """Prevention fires before mkdir/tempfile/replace at every real path."""
    from cc.core.write_guard import TestIsolationEscapeError

    before = target.read_bytes() if target.is_file() else None
    parent_existed = target.parent.exists()

    with pytest.raises(TestIsolationEscapeError, match="Refusing to write"):
        onboard_module._atomic_yaml(target, {"version": 1, "layers": []})

    assert (target.read_bytes() if target.is_file() else None) == before
    assert target.parent.exists() is parent_existed


def test_manifest_with_url_embedded_credential_is_held_and_not_copied(tmp_path):
    target = tmp_path / "copilot.layers.yml"
    target.write_text(
        """version: 1
layers:
  - id: cli-foundation
    role: foundation
    component: cli
    rank: 40
    source: {repo: "https://ghp_example@example.test/cli.git", ref: v1}
    auth: anon
""",
        encoding="utf-8",
    )

    plan = onboard_module._manifest_adoption_plan(
        {"version": 1, "org": "Acme", "layers": []},
        target,
        configured_path=target,
    )

    assert plan.action == "review"
    assert not (tmp_path / ".copilot-control-tower-backups").exists()


def test_ecosystem_apply_writes_exact_refs_and_runs_update_doctor(
    tmp_path, monkeypatch
):
    config_writes = []
    events = []

    def commit_config(path, knowledge):
        events.append("commit-config")
        config_writes.append((str(path), list(knowledge)))

    def update(**_kwargs):
        events.append("cc-update")
        return {"result": "up-to-date", "blocked": [], "held_for_approval": []}, 0

    def cli(_path):
        events.append("cli-update")
        return {"result": "ready"}

    def doctor(**_kwargs):
        events.append("doctor")
        return {"status": "healthy", "score": 100}
    monkeypatch.setattr(
        onboard_module,
        "FOUNDATION_ALLOWED_SIGNERS",
        {
            "knowledge": (),
            "cli": (),
            "claude": ("CLAUDE-FINGERPRINT",),
            "codex": ("CODEX-FINGERPRINT",),
        },
    )
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=update,
        doctor_fn=doctor,
        commit_config_fn=commit_config,
    )
    assert report["result"] == "ready"
    manifest = yaml.safe_load((tmp_path / "layers.yml").read_text())
    assert [(item["product"], item["rank"]) for item in manifest["layers"]] == [
        ("knowledge", 10),
        ("knowledge", 30),
        ("knowledge", 40),
        ("cli", 10),
        ("cli", 30),
        ("cli", 40),
        ("claude", 10),
        ("claude", 30),
        ("claude", 40),
        ("codex", 10),
        ("codex", 30),
        ("codex", 40),
    ]
    assert manifest["layers"][2]["source"]["ref"] == "v0.1.0"
    assert manifest["layers"][5]["source"]["ref"] == "v0.3.1"
    assert manifest["layers"][8]["source"]["ref"] == "v5.9.0"
    assert manifest["layers"][11]["source"]["ref"] == "v0.6.2"
    assert manifest["layers"][8]["policy"]["allowed_signers"] == ["CLAUDE-FINGERPRINT"]
    assert manifest["layers"][11]["policy"]["allowed_signers"] == ["CODEX-FINGERPRINT"]
    assert manifest["layers"][0]["policy"]["allowed_signers"] == []
    assert config_writes == [
        (
            str(tmp_path / "layers.yml"),
            [
                str(Path.home() / ".copilot/mirrors/knowledge/knowledge-personal"),
                str(Path.home() / ".copilot/mirrors/knowledge/knowledge-organization"),
                str(Path.home() / ".copilot/mirrors/knowledge/knowledge-foundation"),
            ],
        )
    ]
    assert events == ["cc-update", "cli-update", "doctor", "commit-config"]
    _assert_valid_onboard_report(report)


def test_foundation_release_signer_is_compiled_for_both_products():
    approved = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"

    assert onboard_module.FOUNDATION_ALLOWED_SIGNERS == {
        "knowledge": (),
        "cli": (),
        "claude": (approved,),
        "codex": (approved,),
    }


def test_connected_store_without_scope_identifiers_blocks_before_writes(tmp_path):
    def connected(args):
        result = _aggregate_run(args)
        if args[2].endswith("/contents/ecosystem.yml"):
            payload = json.loads(result.stdout)
            handoff = (
                base64.b64decode(payload["content"])
                .decode()
                .replace("status: deferred", "status: connected\n  type: infisical")
            )
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"content": base64.b64encode(handoff.encode()).decode()}),
                "",
            )
        return result

    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=connected,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
    )
    assert report["result"] == "blocked"
    assert report["stages"][-1]["stage"] == "secret-store"
    assert len(report["layers"]) == 12
    assert not (tmp_path / "layers.yml").exists()
    _assert_valid_onboard_report(report)


def test_valid_connected_store_identity_refusal_defers_without_overwriting_credentials():
    store = {
        "status": "connected",
        "type": "infisical",
        "workspace_id": "workspace-1",
        "environment": "prod",
        "secret_path": "/shared",
    }

    report = onboard_module._provision_store(
        store,
        apply=True,
        run=lambda args: subprocess.CompletedProcess(
            args,
            1,
            json.dumps(
                {
                    "schema_version": "1.0",
                    "result": "blocked",
                    "detail": (
                        "This device already has store credentials for another "
                        "identity; setup did not replace them."
                    ),
                }
            ),
            "",
        ),
    )

    assert report == {
        "result": "deferred",
        "type": "infisical",
        "detail": (
            "This device already has store credentials for another identity; "
            "setup did not replace them."
        ),
    }


def test_store_without_bootstrap_authority_defers_on_unreadable_cli_failure():
    store = {
        "status": "connected",
        "type": "infisical",
        "workspace_id": "workspace-1",
        "environment": "prod",
        "secret_path": "/shared",
    }

    report = onboard_module._provision_store(
        store,
        apply=True,
        run=lambda args: subprocess.CompletedProcess(
            args, 1, "", "Infisical credentials not configured."
        ),
    )

    assert report["result"] == "deferred"
    assert report["type"] == "infisical"
    assert "existing credentials" in report["detail"]


def test_unavailable_optional_store_does_not_block_core_apply(tmp_path):
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        store_fn=lambda *_args, **_kwargs: {
            "result": "deferred",
            "type": "infisical",
            "detail": "Shared integrations were left for later.",
        },
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=lambda **_: (
            {"result": "up-to-date", "blocked": [], "held_for_approval": []},
            0,
        ),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
    )

    assert report["result"] == "ready"
    store_stage = next(
        stage for stage in report["stages"] if stage["stage"] == "secret-store"
    )
    assert store_stage["result"] == "deferred"
    assert (tmp_path / "layers.yml").is_file()
    _assert_valid_onboard_report(report)


def test_successful_store_scope_is_a_non_secret_schema_summary():
    store = {
        "status": "connected",
        "type": "infisical",
        "workspace_id": "workspace-1",
        "environment": "prod",
        "secret_path": "/shared",
    }

    report = onboard_module._provision_store(
        store,
        apply=False,
        run=lambda args: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "schema_version": "1.0",
                    "result": "ready",
                    "scope": {
                        "environment": "prod",
                        "secret_path": "/shared",
                        "access": "read",
                    },
                }
            ),
            "",
        ),
    )

    assert report == {
        "result": "ready",
        "type": "infisical",
        "scope": "prod:/shared:read",
    }


def test_aggregate_block_before_manifest_still_returns_layers_field(tmp_path):
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=lambda **_: {
            "result": "blocked",
            "summary": {
                "existing": 0,
                "missing": 0,
                "created": 0,
                "seeded": 0,
                "held": 1,
                "blocked": 1,
            },
        },
        ssh_fn=_ssh,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
    )
    assert report["result"] == "blocked"
    assert report["layers"] == []
    assert not (tmp_path / "layers.yml").exists()
    _assert_valid_onboard_report(report)


def test_department_membership_expands_visible_manifest_to_sixteen_layers(tmp_path):
    handoff = {
        "foundation": {
            "refs": {
                "knowledge": "v0.1.0",
                "cli": "v0.3.1",
                "claude": "v5.9.0",
                "codex": "v0.6.2",
            }
        }
    }

    manifest = onboard_module._layer_manifest(
        "Acme",
        "pablo",
        ("knowledge", "cli", "claude", "codex"),
        handoff,
        run=_aggregate_run,
        department_units=("accounting",),
        repository_root=tmp_path,
    )

    assert len(manifest["layers"]) == 16
    assert {
        (layer["product"], layer["role"], layer.get("unit"))
        for layer in manifest["layers"]
    } == {
        (product, role, "accounting" if role == "department" else None)
        for product in ("knowledge", "cli", "claude", "codex")
        for role in ("personal", "department", "organization", "foundation")
    }
    personal = next(
        layer
        for layer in manifest["layers"]
        if layer["product"] == "knowledge" and layer["role"] == "personal"
    )
    assert personal["source"]["path"] == str(tmp_path / "knowledge-copilot-private")
    assert ".copilot/mirrors" not in personal["source"]["path"]


def test_department_entitlement_requires_declared_active_membership():
    calls = []

    def run(args):
        calls.append(tuple(args))
        state = "active" if "/accounting/" in args[2] else "pending"
        return subprocess.CompletedProcess(args, 0, json.dumps({"state": state}), "")

    units = onboard_module._eligible_department_units(
        {
            "departments": [
                {"unit": "accounting", "topology": "separate"},
                {"unit": "legal", "topology": "separate"},
                {"unit": "../unsafe", "topology": "separate"},
            ]
        },
        "Acme",
        "pablo",
        run=run,
    )

    assert units == ("accounting",)
    assert len(calls) == 2


def test_repository_root_inference_finds_one_existing_component_cluster(
    tmp_path, monkeypatch
):
    sites = tmp_path / "Sites"
    cluster = sites / "COPILOT"
    cluster.mkdir(parents=True)
    (cluster / "knowledge-copilot").mkdir()
    (cluster / "cli-copilot-internal").mkdir()
    monkeypatch.setattr(
        onboard_module,
        "resolve_key",
        lambda key: [str(sites)] if key == "projects.roots" else None,
    )

    assert onboard_module._infer_repository_root(("accounting",)) == cluster


def test_topology_reports_connected_then_independently_verified(tmp_path):
    checkout = tmp_path / "codex-copilot-private"
    (checkout / ".git").mkdir(parents=True)
    manifest = {
        "version": 1,
        "layers": [
            {
                "id": "codex-personal",
                "product": "codex",
                "role": "personal",
                "rank": 10,
                "source": {
                    "repo": "git@github-personal:pablo/codex-copilot-private.git",
                    "ref": "main",
                    "path": str(checkout),
                },
            }
        ],
    }

    def run(args):
        args = tuple(args)
        if args[:3] == ("gh", "api", "repos/pablo/codex-copilot-private"):
            return subprocess.CompletedProcess(args, 0, json.dumps({"private": True}), "")
        if args[:3] == ("gh", "api", "repos/pablo/codex-copilot-private/contents"):
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[:4] == ("git", "-C", str(checkout), "remote"):
            return subprocess.CompletedProcess(
                args, 0, "git@github-personal:pablo/codex-copilot-private.git\n", ""
            )
        if args[:4] == ("git", "-C", str(checkout), "rev-parse"):
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        if args[:4] == ("git", "-C", str(checkout), "status"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:4] == ("git", "-C", str(checkout), "fetch"):
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    planned = onboard_module._topology_report_layers(manifest, run=run)
    verified = onboard_module._topology_report_layers(manifest, run=run, verified=True)

    assert planned[0]["connection_state"] == "connected"
    assert verified[0]["connection_state"] == "verified"
    assert verified[0]["sync_state"] == "current"


# ---------------------------------------------------------------------------
# _classify_repository_history() -- G-1 closed history classifier (task 204)
#
# Every fixture below is a real, disposable `git init` repo under `tmp_path`
# -- never a live working tree on this machine -- driven through the exact
# `run` signature `_classify_repository_history` expects, with real
# `git fetch` / `git merge-base --is-ancestor` doing the actual proving. The
# classifier never shells out to `gh`, so no GitHub stub is required here.
# ---------------------------------------------------------------------------


def _real_run(args):
    return subprocess.run(list(args), capture_output=True, text=True)


def _init_content_repo(path: Path, filename: str, content: str, *, message: str = "init") -> None:
    """A real, disposable one-commit repo -- the G-1 fixture rule (never a
    live tree)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    _commit(path, filename, content, message)


def _commit(path: Path, filename: str, content: str, message: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=path, check=True)


def _set_fake_origin(path: Path, owner: str, name: str) -> None:
    """`_classify_repository_history` fetches `source["repo"]` directly --
    exactly like `_apply_visible_topology`'s `repair` branch -- never
    `origin`. `origin` only feeds the wrong-origin identity check, so a
    syntactically valid, never-dereferenced GitHub SSH URL is sufficient and
    keeps every fixture fully offline."""
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", f"git@github.com:{owner}/{name}.git"],
        check=True,
    )


def _clone_with_fake_origin(remote: Path, local: Path, owner: str, name: str) -> None:
    subprocess.run(["git", "clone", "-q", str(remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "remote", "remove", "origin"], check=True)
    _set_fake_origin(local, owner, name)


def test_classify_repository_history_exact(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "widget")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "exact"
    assert classification.sync_state == "current"
    assert classification.action == "reuse"


def test_classify_repository_history_fast_forwardable_is_proven_by_merge_base(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "widget")
    _commit(remote, "note.txt", "v2", "advance")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "fast-forwardable"
    assert classification.sync_state == "behind"
    assert classification.action == "repair"
    assert "clean fast-forward is available" in classification.detail


def test_classify_repository_history_dirty_working_tree_is_never_touched(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "widget")
    (local / "note.txt").write_text("uncommitted edit", encoding="utf-8")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "dirty"
    assert classification.sync_state == "local-changes"
    assert classification.action == "review"


def test_classify_repository_history_ahead_only_is_never_auto_repaired(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "widget")
    _commit(local, "note.txt", "v2 (unpublished)", "local-only work")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "ahead-only"
    assert classification.action == "review"
    assert classification.action != "repair"


def test_classify_repository_history_divergent_identical_tree(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "same content")
    _init_content_repo(local, "note.txt", "same content", message="independent history")
    _set_fake_origin(local, "pablo", "widget")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "divergent-identical-tree"
    assert classification.action == "review"
    assert classification.action != "repair"
    assert "content is identical" in classification.detail


def test_classify_repository_history_divergent_different_content(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "remote content")
    _init_content_repo(local, "note.txt", "local content", message="independent history")
    _set_fake_origin(local, "pablo", "widget")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "divergent-different-content"
    assert classification.action == "review"


def test_classify_repository_history_wrong_origin(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "someone-else", "unrelated")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "wrong-origin"
    assert classification.action == "review"


def test_classify_repository_history_unreadable_not_a_git_repository(tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    (local / ".git").write_text("not a real gitdir", encoding="utf-8")

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(tmp_path / "remote"), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "unreadable"
    assert classification.action == "review"


def test_classify_repository_history_unreadable_when_fetch_fails(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "widget")
    shutil.rmtree(remote)

    classification = onboard_module._classify_repository_history(
        local,
        owner="pablo",
        name="widget",
        source={"repo": str(remote), "ref": "main"},
        run=_real_run,
    )

    assert classification.state == "unreadable"
    assert classification.action == "review"


# ---------------------------------------------------------------------------
# _topology_report_layers() -- the read-only plan path must never promise a
# fast-forward it can't prove. `_repo_identity_from_layer`/
# `_remote_repository_state` are stubbed here only because they talk to
# `gh`/GitHub identity parsing, which is orthogonal to G-1; the Git history
# classification itself runs for real against disposable fixture repos.
# ---------------------------------------------------------------------------


def _topology_manifest(layer_id: str, local: Path, repo: Path, ref: str = "main") -> dict:
    return {
        "version": 1,
        "layers": [
            {
                "id": layer_id,
                "product": "codex",
                "role": "personal",
                "rank": 10,
                "source": {"repo": str(repo), "ref": ref, "path": str(local)},
            }
        ],
    }


def test_topology_report_never_promises_a_fast_forward_for_ahead_only(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    local = tmp_path / "codex-copilot-private"
    _init_content_repo(remote, "note.txt", "v1")
    _clone_with_fake_origin(remote, local, "pablo", "codex-copilot-private")
    _commit(local, "note.txt", "v2 (unpublished)", "local-only work")
    monkeypatch.setattr(
        onboard_module,
        "_repo_identity_from_layer",
        lambda layer: ("pablo", "codex-copilot-private"),
    )
    monkeypatch.setattr(
        onboard_module,
        "_remote_repository_state",
        lambda owner, name, *, run: ("ready", "private"),
    )

    rows = onboard_module._topology_report_layers(
        _topology_manifest("codex-personal", local, remote), run=_real_run
    )

    assert rows[0]["sync_state"] == "ahead"
    assert rows[0]["action"] == "review"
    assert rows[0]["action"] != "repair"


def test_topology_report_never_promises_a_fast_forward_for_divergent_identical_tree(
    tmp_path, monkeypatch
):
    remote = tmp_path / "remote"
    local = tmp_path / "codex-copilot-private"
    _init_content_repo(remote, "note.txt", "same content")
    _init_content_repo(local, "note.txt", "same content", message="independent history")
    _set_fake_origin(local, "pablo", "codex-copilot-private")
    monkeypatch.setattr(
        onboard_module,
        "_repo_identity_from_layer",
        lambda layer: ("pablo", "codex-copilot-private"),
    )
    monkeypatch.setattr(
        onboard_module,
        "_remote_repository_state",
        lambda owner, name, *, run: ("ready", "private"),
    )

    rows = onboard_module._topology_report_layers(
        _topology_manifest("codex-personal", local, remote), run=_real_run
    )

    assert rows[0]["sync_state"] == "diverged-identical"
    assert rows[0]["action"] == "review"
    assert rows[0]["action"] != "repair"


def test_legacy_personal_mirrors_move_out_of_active_tree(tmp_path):
    mirrors = tmp_path / ".copilot" / "mirrors"
    visible = tmp_path / "Sites" / "COPILOT"
    layers = []
    for product, layer_id in (
        ("knowledge", "knowledge-personal"),
        ("cli", "cli-personal"),
        ("claude", "claude-personal"),
        ("codex", "codex-personal"),
    ):
        (visible / f"{product}-copilot-private").mkdir(parents=True)
        legacy = mirrors / layer_id
        legacy.mkdir(parents=True)
        (legacy / "preserved.txt").write_text(product, encoding="utf-8")
        layers.append(
            {
                "id": layer_id,
                "product": product,
                "role": "personal",
                "source": {"path": str(visible / f"{product}-copilot-private")},
            }
        )

    moved = onboard_module._quarantine_legacy_personal_mirrors(
        {"layers": layers}, mirrors_root=mirrors
    )

    assert len(moved) == 4
    assert not any((mirrors / layer["id"]).exists() for layer in layers)
    quarantined = mirrors.parent / "legacy-mirrors"
    assert sorted(path.read_text(encoding="utf-8") for path in quarantined.glob("*/preserved.txt")) == [
        "claude", "cli", "codex", "knowledge"
    ]


def test_visible_apply_cannot_report_ready_when_resolution_is_empty(
    tmp_path, monkeypatch
):
    def topology(manifest, **_kwargs):
        return [
            {
                "id": layer["id"],
                "product": layer["product"],
                "role": layer["role"],
                "rank": layer["rank"],
                "unit": layer.get("unit"),
                "local_state": "visible",
                "connection_state": "connected",
                "sync_state": "current",
                "action": "reuse",
                "detail": "Visible and current.",
            }
            for layer in manifest["layers"]
        ]

    monkeypatch.setattr(onboard_module, "_topology_report_layers", topology)
    monkeypatch.setattr(
        onboard_module, "_apply_visible_topology", lambda *_args, **_kwargs: (True, None)
    )
    target = tmp_path / "config" / "layers.yml"
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=target,
        repository_root=tmp_path / "Sites" / "COPILOT",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        cli_fn=_cli,
        consumer_probe_fn=_consumer_ready,
        update_fn=lambda **_: (
            {"result": "up-to-date", "blocked": [], "held_for_approval": []},
            0,
        ),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
        resolve_fn=lambda **_: {"schema_version": "1.0", "items": []},
        commit_config_fn=lambda *_args: pytest.fail("empty resolution must not commit"),
        personal_mirror_cleanup_fn=lambda *_args: pytest.fail(
            "empty resolution must not move legacy repositories"
        ),
    )

    assert report["result"] == "blocked"
    assert next(stage for stage in report["stages"] if stage["stage"] == "resolve")[
        "result"
    ] == "blocked"
    assert not target.exists()
    _assert_valid_onboard_report(report)
