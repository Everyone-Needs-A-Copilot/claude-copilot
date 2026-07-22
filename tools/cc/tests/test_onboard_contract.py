import json
import base64
import subprocess
from pathlib import Path

import yaml

from cc.commands.onboard import build_ecosystem_onboard_report, build_personal_onboard_report


class FakeGitHub:
    def __init__(self, repos=None, errors=None):
        self.repos = {
            name: (value if isinstance(value, dict) else {"private": value, "files": {}})
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
            encoded = next(value.removeprefix("content=") for value in args if value.startswith("content="))
            self.repos[name]["files"]["copilot.layer.yml"] = base64.b64decode(encoded).decode()
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
            return subprocess.CompletedProcess(args, 0, json.dumps({"private": repo["private"]}), "")
        files = repo["files"]
        if len(parts) == 4:  # root contents
            if not files:
                return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
            return subprocess.CompletedProcess(
                args, 0, json.dumps([{"name": path} for path in files]), ""
            )
        path = "/".join(parts[4:])
        if path not in files:
            return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
        encoded = base64.b64encode(files[path].encode()).decode()
        return subprocess.CompletedProcess(args, 0, json.dumps({"content": encoded}), "")


def test_plan_reuses_private_and_marks_only_404_missing():
    gh = FakeGitHub({"claude-copilot-private": True})
    report = build_personal_onboard_report(components=("claude", "codex"), run=gh)
    assert report["result"] == "changes-required"
    assert [row["state"] for row in report["repositories"]] == ["existing-private", "missing"]
    assert not any("POST" in call for call in gh.calls)


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


def test_unknown_read_blocks_all_creation():
    gh = FakeGitHub(errors={"codex-copilot-private"})
    report = build_personal_onboard_report(components=("claude", "codex"), apply=True, run=gh)
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "unknown"
    assert not any("POST" in call for call in gh.calls)


def test_public_collision_blocks_all_creation():
    gh = FakeGitHub({"codex-copilot-private": False})
    report = build_personal_onboard_report(components=("claude", "codex"), apply=True, run=gh)
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "conflict-public"
    assert not any("POST" in call for call in gh.calls)


def test_existing_empty_private_repository_is_seeded_without_recreation():
    gh = FakeGitHub({"codex-copilot-private": True})
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["state"] == "existing-private"
    assert report["repositories"][0]["package_state"] == "seeded"
    assert not any("POST" in call for call in gh.calls)


def test_existing_unfamiliar_content_blocks_before_other_creation():
    gh = FakeGitHub(
        {"claude-copilot-private": {"private": True, "files": {"notes.md": "mine"}}}
    )
    report = build_personal_onboard_report(
        components=("claude", "codex"), apply=True, run=gh
    )
    assert report["result"] == "blocked"
    assert report["repositories"][0]["package_state"] == "held"
    assert not any("POST" in call for call in gh.calls)


def test_existing_valid_rank_ten_manifest_is_reused():
    manifest = """schema_version: '1.0'\npackage:\n  role: personal\n  rank: 10\n  product: codex\n  owner: authenticated-user\ndimensions: []\n"""
    gh = FakeGitHub(
        {"codex-copilot-private": {"private": True, "files": {"copilot.layer.yml": manifest}}}
    )
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["package_state"] == "ready"
    assert not any("PUT" in call or "POST" in call for call in gh.calls)


def _aggregate_run(args):
    endpoint = args[2]
    if endpoint.endswith("/contents/ecosystem.yml"):
        handoff = """schema_version: '2.0'
org: Acme
harness: [claude, codex]
store:
  status: deferred
foundation:
  refs:
    claude: '^5.8.0'
    codex: '^0.6.0'
"""
        encoded = base64.b64encode(handoff.encode()).decode()
        return subprocess.CompletedProcess(args, 0, json.dumps({"content": encoded}), "")
    if endpoint.endswith("claude-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v5.9.0"},{"name":"v6.0.0"}]', "")
    if endpoint.endswith("codex-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.6.2"}]', "")
    raise AssertionError(args)


def _personal(**_kwargs):
    return {"result": "ready", "owner": "pablo", "summary": {"existing": 2, "missing": 0, "created": 0, "seeded": 0, "held": 0, "blocked": 0}}


def _ssh(**_kwargs):
    return {"result": "ready", "key": "existing", "registration": "registered", "config": "ready", "detail": "ready"}


def _codex(*, apply, **_kwargs):
    return {"result": "ready" if apply else "changes-required"}


def test_ecosystem_plan_builds_two_isolated_three_layer_stacks(tmp_path):
    report = build_ecosystem_onboard_report(
        org="Acme", apply=False, run=_aggregate_run, manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal, ssh_fn=_ssh, codex_fn=_codex,
    )
    assert report["result"] == "changes-required"
    assert [(layer["product"], layer["role"], layer["rank"]) for layer in report["layers"]] == [
        ("claude", "personal", 10), ("claude", "organization", 30), ("claude", "foundation", 40),
        ("codex", "personal", 10), ("codex", "organization", 30), ("codex", "foundation", 40),
    ]
    assert [stage["stage"] for stage in report["stages"]] == [
        "organization-handoff", "personal-packages", "device-ssh", "layer-manifest", "secret-store", "codex-plugin"
    ]
    assert not (tmp_path / "layers.yml").exists()


def test_ecosystem_apply_writes_exact_refs_and_runs_update_doctor(tmp_path, monkeypatch):
    config_writes = []
    monkeypatch.setattr("cc.commands.onboard.write_config", lambda key, value: config_writes.append((key, value)))
    report = build_ecosystem_onboard_report(
        org="Acme", apply=True, run=_aggregate_run, manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal, ssh_fn=_ssh, codex_fn=_codex,
        update_fn=lambda **_: ({"result": "up-to-date", "blocked": [], "held_for_approval": []}, 0),
        doctor_fn=lambda: {"status": "healthy", "score": 100},
    )
    assert report["result"] == "ready"
    manifest = yaml.safe_load((tmp_path / "layers.yml").read_text())
    assert [(item["product"], item["rank"]) for item in manifest["layers"]] == [
        ("claude", 10), ("claude", 30), ("claude", 40),
        ("codex", 10), ("codex", 30), ("codex", 40),
    ]
    assert manifest["layers"][2]["source"]["ref"] == "v5.9.0"
    assert manifest["layers"][5]["source"]["ref"] == "v0.6.2"
    assert config_writes == [("layers.manifest", str(tmp_path / "layers.yml"))]


def test_connected_store_without_scope_identifiers_blocks_before_writes(tmp_path):
    def connected(args):
        result = _aggregate_run(args)
        if args[2].endswith("/contents/ecosystem.yml"):
            payload = json.loads(result.stdout)
            handoff = base64.b64decode(payload["content"]).decode().replace("status: deferred", "status: connected\n  type: infisical")
            return subprocess.CompletedProcess(args, 0, json.dumps({"content": base64.b64encode(handoff.encode()).decode()}), "")
        return result
    report = build_ecosystem_onboard_report(
        org="Acme", apply=True, run=connected, manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal, ssh_fn=_ssh, codex_fn=_codex,
    )
    assert report["result"] == "blocked"
    assert report["stages"][-1]["stage"] == "secret-store"
    assert len(report["layers"]) == 6
    assert not (tmp_path / "layers.yml").exists()


def test_aggregate_block_before_manifest_still_returns_layers_field(tmp_path):
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=lambda **_: {
            "result": "blocked",
            "summary": {"existing": 0, "missing": 0, "created": 0, "seeded": 0, "held": 1, "blocked": 1},
        },
        ssh_fn=_ssh,
        codex_fn=_codex,
    )
    assert report["result"] == "blocked"
    assert report["layers"] == []
    assert not (tmp_path / "layers.yml").exists()
