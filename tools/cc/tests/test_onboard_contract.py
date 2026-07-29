import base64
import json
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
        return subprocess.CompletedProcess(
            args, 0, '{"chain": [], "services": []}', ""
        )

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
store:
  status: deferred
foundation:
  refs:
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


def _consumer_ready(*_args):
    return {"result": "ready"}


def test_ecosystem_plan_builds_two_isolated_three_layer_stacks(tmp_path):
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
    assert [
        (layer["product"], layer["role"], layer["rank"]) for layer in report["layers"]
    ] == [
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
    cli = next(
        layer for layer in written["layers"] if layer["id"] == "cli-organization"
    )
    assert cli["component"] == "cli"
    assert "product" not in cli
    products = {layer["product"] for layer in written["layers"] if "product" in layer}
    assert products == {"claude", "codex"}
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
    monkeypatch.setattr(
        "cc.commands.onboard.write_config",
        lambda key, value: config_writes.append((key, value)),
    )
    monkeypatch.setattr(
        onboard_module,
        "FOUNDATION_ALLOWED_SIGNERS",
        {"claude": ("CLAUDE-FINGERPRINT",), "codex": ("CODEX-FINGERPRINT",)},
    )
    report = build_ecosystem_onboard_report(
        org="Acme",
        apply=True,
        run=_aggregate_run,
        manifest_path=tmp_path / "layers.yml",
        personal_fn=_personal,
        ssh_fn=_ssh,
        codex_fn=_codex,
        consumer_probe_fn=_consumer_ready,
        update_fn=lambda **_: (
            {"result": "up-to-date", "blocked": [], "held_for_approval": []},
            0,
        ),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
    )
    assert report["result"] == "ready"
    manifest = yaml.safe_load((tmp_path / "layers.yml").read_text())
    assert [(item["product"], item["rank"]) for item in manifest["layers"]] == [
        ("claude", 10),
        ("claude", 30),
        ("claude", 40),
        ("codex", 10),
        ("codex", 30),
        ("codex", 40),
    ]
    assert manifest["layers"][2]["source"]["ref"] == "v5.9.0"
    assert manifest["layers"][5]["source"]["ref"] == "v0.6.2"
    assert manifest["layers"][2]["policy"]["allowed_signers"] == ["CLAUDE-FINGERPRINT"]
    assert manifest["layers"][5]["policy"]["allowed_signers"] == ["CODEX-FINGERPRINT"]
    assert manifest["layers"][0]["policy"]["allowed_signers"] == []
    assert config_writes == [("layers.manifest", str(tmp_path / "layers.yml"))]
    _assert_valid_onboard_report(report)


def test_foundation_release_signer_is_compiled_for_both_products():
    approved = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"

    assert onboard_module.FOUNDATION_ALLOWED_SIGNERS == {
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
    assert len(report["layers"]) == 6
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
