"""Integration smoke tests: WS-A verb wiring in `cc/main.py`.

Stream-Z (final integration pass): `auth`/`layers` are `app.add_typer()`
subgroups, `freshness --all-projects`/`--per-layer` and `update
--project`/`--fanout` are new opt-in flags dispatching to
`commands.projects`/`commands.freshness`. Every other stream's own
contract test (`test_auth_contract.py`, `test_layers_contract.py`,
`test_freshness_contract.py`, `test_projects_contract.py`,
`test_update_contract.py`) already exercises `build_*`/`execute_*`
directly with fully injected roots; THIS file only asserts the thin
`cc/main.py` dispatch itself is wired -- exit codes + `schema_version`
through the real Typer CLI surface (`CliRunner`), the one thing those
module-level contract tests cannot cover.

Every test here redirects `HOME` to an empty `tmp_path` sandbox
(`monkeypatch.setenv("HOME", ...)`) so none of these commands' un-injectable
default roots (`Path.home()`/`os.path.expanduser("~")`-based: authstore's
identity pointer, the ecosystem.yml default location, the advisory
copilot.lock, `projects.roots`/`projects.registry` defaults) ever touch this
machine's real `~/.claude`/`~/.copilot` state -- mirrors every other
contract test file's `_no_real_home` precedent, just via env-var redirection
since the CLI surface itself exposes no `_root`-style injection points.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

import cc.commands.onboard as onboard_module
import pytest


@pytest.fixture(autouse=True)
def _sandboxed_home(tmp_path, monkeypatch):
    """Redirect every `~`-based default (Path.home() and
    os.path.expanduser("~") both resolve off the HOME env var) at an empty,
    per-test tmp directory -- see module docstring."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_auth_login_no_org_known_returns_org_required(cli):
    """`cc auth login --json` with no client id AND no org configured
    anywhere (a completely fresh sandbox, no `--org`) -- there is nothing
    to bootstrap a client id from yet, so `org-required` fires."""
    result = cli(["auth", "login", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == "org-required"


def test_auth_login_org_known_but_no_company_app_returns_error_envelope(cli, monkeypatch):
    """`cc auth login --org <org> --json` when the org's public bootstrap
    artifact carries no client id -- the org genuinely has no company app
    set up yet (the case the OLD `ecosystem.yml`-fallback contract used to
    cover, before that branch was replaced by the public-bootstrap fetch --
    see commands/auth.py's `_resolve_client_id()`)."""
    monkeypatch.setattr(
        "cc.commands.auth.bootstrap_config.fetch_org_client_id",
        lambda *_a, **_k: (None, "invalid-artifact"),
    )
    monkeypatch.setattr(
        "cc.commands.auth.bootstrap_config.org_exists_on_github", lambda *_a, **_k: True
    )

    result = cli(["auth", "login", "--org", "acme-co", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == "no-company-app"


def test_auth_status_signed_out(cli):
    """`cc auth status --json` on a fresh sandbox (no identity pointer on
    disk) -- offline-safe, `signed-out`, exit 0."""
    result = cli(["auth", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["kind"] == "status"
    assert payload["status"] == "signed-out"


def test_layers_list_empty_catalog(cli):
    """`cc layers --json` with no inherited ecosystem.yml on this machine
    -- an honest empty catalog, never a crash, exit 0."""
    result = cli(["layers", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["layers"] == []


def test_freshness_all_projects_no_roots_is_empty(cli):
    """`cc freshness --all-projects --json` with no `projects.roots`
    configured on this machine -- an honest empty sweep, exit 0."""
    result = cli(["freshness", "--all-projects", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["total"] == 0
    assert payload["projects"] == []
    assert payload["global"] == []


def test_freshness_all_projects_and_per_layer_mutually_exclusive(cli):
    """Combining the two new opt-in flags is refused (different report
    shapes) rather than silently picking one, exit 2."""
    result = cli(["freshness", "--all-projects", "--per-layer", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == "invalid-argument"


def test_update_project_on_tmp_project_up_to_date(cli, tmp_path):
    """`cc update --project <path> --component claude --json` against a
    fresh project with no lock manifest yet -- an honest `up-to-date`
    no-op (nothing to materialize), exit 0."""
    project = tmp_path / "a-project"
    project.mkdir()

    result = cli(["update", "--project", str(project), "--component", "claude", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["result"] == "up-to-date"
    assert payload["path"] == str(project)


def test_update_project_requires_component(cli, tmp_path):
    """`cc update --project <path>` without `--component` is refused,
    exit 2, rather than crashing on `execute_materialize_project()`'s
    required keyword argument."""
    project = tmp_path / "a-project"
    project.mkdir()

    result = cli(["update", "--project", str(project), "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == "invalid-argument"


def test_update_project_and_fanout_mutually_exclusive(cli, tmp_path):
    project = tmp_path / "a-project"
    project.mkdir()

    result = cli(
        [
            "update",
            "--project",
            str(project),
            "--component",
            "claude",
            "--fanout",
            "--json",
        ]
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == "invalid-argument"


def test_update_fanout_no_projects_is_clean(cli):
    """`cc update --fanout --json` with no discovered projects -- an
    honest empty roll-up, exit 0 (no held/failed counts)."""
    result = cli(["update", "--fanout", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["summary"]["total"] == 0
    assert payload["summary"]["held"] == 0
    assert payload["summary"]["failed"] == 0


def test_update_fanout_wires_source_roots_and_reports_real_count(cli, tmp_path, monkeypatch):
    """The reported defect, end-to-end: before this fix, `cc update
    --fanout --json` always reported `summary.total == 0` because
    `cc/main.py`'s call site wired neither `_source_roots` nor
    `_latest_by_product` into `execute_fanout()` -- every project folded to
    `stale: None` and was dropped with a bare `continue`, never landing in
    `results[]`. With a real stale project under a configured root and a
    real claude source root carrying a `VERSION.json`, the fan-out must now
    report it, with the actual materialize outcome visible."""
    projects_root = tmp_path / "projects-root"
    projects_root.mkdir()
    project = projects_root / "some-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=project, check=True)
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "commands" / "x.md").write_text("v1", encoding="utf-8")
    (project / "copilot.lock.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "components": [
                    {
                        "component": "claude",
                        "version": "1.0.0",
                        "release_tag": "v1.0.0",
                        "files": [
                            {
                                "path": ".claude/commands/x.md",
                                "ownership": "framework",
                                "checksum": "sha256:" + hashlib.sha256(b"v1").hexdigest(),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)

    claude_source = tmp_path / "claude-source"
    (claude_source / ".claude" / "commands").mkdir(parents=True)
    (claude_source / "VERSION.json").write_text(json.dumps({"framework": "2.0.0"}), encoding="utf-8")
    (claude_source / ".claude" / "commands" / "x.md").write_text("v2", encoding="utf-8")

    monkeypatch.setenv("CC_PROJECTS_ROOTS", str(projects_root))
    monkeypatch.setenv("CC_PATHS_CLAUDE_COPILOT_ROOT", str(claude_source))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(tmp_path / "no-codex-here"))

    result = cli(["update", "--fanout", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["updated"] == 1
    assert payload["summary"]["failed"] == 0
    entry = payload["results"][0]
    assert entry["path"] == str(project)
    assert entry["component"] == "claude"
    assert entry["report"]["result"] == "applied"

    # --dry-run: the project's own file must be untouched.
    assert (project / ".claude" / "commands" / "x.md").read_text(encoding="utf-8") == "v1"


def _fake_onboard_run(args):
    """Minimal fake `run` transport covering exactly the GitHub reads
    `_load_handoff`/`_layer_manifest` make for org="Acme", products
    claude+codex -- same shape as test_onboard_contract.py's
    `_aggregate_run`, duplicated locally so this file's wiring-only tests
    don't take on a cross-test-file import."""
    endpoint = args[2]
    if endpoint.endswith("/contents/ecosystem.yml"):
        handoff = (
            "schema_version: '2.0'\n"
            "org: Acme\n"
            "harness: [claude, codex]\n"
            "components: [knowledge, cli, claude, codex]\n"
            "store:\n"
            "  status: deferred\n"
            "foundation:\n"
            "  refs:\n"
            "    knowledge: '^0.1.0'\n"
            "    cli: '^0.3.0'\n"
            "    claude: '^5.8.0'\n"
            "    codex: '^0.6.0'\n"
        )
        encoded = base64.b64encode(handoff.encode()).decode()
        return subprocess.CompletedProcess(args, 0, json.dumps({"content": encoded}), "")
    if endpoint.endswith("claude-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v5.9.0"}]', "")
    if endpoint.endswith("codex-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.6.2"}]', "")
    if endpoint.endswith("knowledge-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.1.0"}]', "")
    if endpoint.endswith("cli-copilot/tags"):
        return subprocess.CompletedProcess(args, 0, '[{"name":"v0.3.1"}]', "")
    raise AssertionError(args)


def _fake_onboard_personal(**_kwargs):
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


def _fake_onboard_codex(*, apply, **_kwargs):
    return {"result": "ready" if apply else "changes-required"}


def test_onboard_ecosystem_resolves_collaborators_at_call_time(cli, monkeypatch):
    """Regression for D3: `onboard_cmd` (commands/onboard.py) calls
    `build_ecosystem_onboard_report()` passing none of its injectable
    `run`/`personal_fn`/`ssh_fn`/`codex_fn` keywords, so this CLI path is the
    one place those collaborators are exercised entirely through their
    call-time-resolved defaults. Before the fix, `ssh_fn: ... =
    ensure_machine_ssh_identity` was a definition-time-bound default --
    Python captures it once, at module import, so monkeypatching the module
    attribute below (this codebase's usual test-substitution idiom, used
    throughout every other contract test file) would have been silently
    ineffective, and the real `ensure_machine_ssh_identity` -- which writes
    `~/.ssh/config` and `~/.ssh/id_ed25519_copilot` for real -- would have run
    instead of `fake_ssh`. This test proves the seam now holds, and that the
    real `~/.ssh/config` on the machine running the suite is untouched
    either way (belt-and-suspenders, on top of `_sandboxed_home`'s HOME
    redirection)."""
    ssh_calls: list[dict] = []

    def fake_ssh(**kwargs):
        ssh_calls.append(kwargs)
        return {
            "result": "ready",
            "key": "existing",
            "registration": "registered",
            "config": "ready",
            "detail": "ready",
        }

    monkeypatch.setattr(onboard_module, "_run", _fake_onboard_run)
    monkeypatch.setattr(
        onboard_module, "build_personal_onboard_report", _fake_onboard_personal
    )
    monkeypatch.setattr(onboard_module, "ensure_machine_ssh_identity", fake_ssh)
    monkeypatch.setattr(onboard_module, "_install_codex_plugin", _fake_onboard_codex)

    real_ssh_config = Path.home() / ".ssh" / "config"
    real_ssh_config_before = (
        real_ssh_config.read_bytes() if real_ssh_config.exists() else None
    )

    result = cli(["onboard", "--org", "Acme", "--json"])

    real_ssh_config_after = (
        real_ssh_config.read_bytes() if real_ssh_config.exists() else None
    )
    assert real_ssh_config_after == real_ssh_config_before, (
        "onboard touched the real ~/.ssh/config -- the call-time collaborator "
        "resolution seam did not hold"
    )
    assert ssh_calls, (
        "onboard_cmd never reached the patched ssh_fn -- either the "
        "call-time resolution seam is broken again, or the plan was blocked "
        "before the device-ssh stage"
    )

    payload = json.loads(result.output)
    # G-5 (task 208): breaking bump -- onboard's `schema_version` moved
    # 1.0 -> 2.0 alongside the tightened `ecosystemLayer` contract.
    assert payload["schema_version"] == "2.0"
    assert payload["result"] in {"ready", "changes-required"}
    assert result.exit_code in (0, 1)
