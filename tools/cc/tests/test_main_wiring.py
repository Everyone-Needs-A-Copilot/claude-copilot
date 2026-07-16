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

import json

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


def test_auth_login_no_client_id_returns_error_envelope(cli):
    """`cc auth login --json` with no GitHub App client id configured
    anywhere (no local override, no inherited ecosystem.yml) -- the
    `no-company-app` error envelope, exit 2."""
    result = cli(["auth", "login", "--json"])

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
