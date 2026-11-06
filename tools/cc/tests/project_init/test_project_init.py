"""cc project init: marker, thin sections, Codex trust, packs, timing. Temp dirs only."""

from __future__ import annotations

import json
import subprocess
import time
import tomllib

import pytest
from typer.testing import CliRunner

from cc.commands.project import project_app
from cc.core.project_init import SECTION_BEGIN, InitError, init_project
from cc.core.project_init.marker import MARKER_FILENAME


@pytest.fixture
def env(tmp_path):
    return {
        "codex_config": tmp_path / "codex" / "config.toml",
        "registry": tmp_path / "home" / "registered.json",
        "packs_root": tmp_path / "packs",
    }


def _git(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_fresh_repo_writes_everything_and_is_fast(tmp_path, env):
    repo = tmp_path / "fresh"
    _git(repo)
    start = time.monotonic()
    report = init_project(repo, **env)
    elapsed = time.monotonic() - start
    print(f"TIMING fresh={elapsed:.3f}s")
    assert elapsed < 10
    marker = json.loads((repo / MARKER_FILENAME).read_text())
    assert marker["runtimes"] == ["claude", "codex"]
    assert marker["components"] == ["claude", "codex"]
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert SECTION_BEGIN in (repo / name).read_text()
    assert set(report["changed"]) >= {MARKER_FILENAME, "CLAUDE.md", "AGENTS.md", "codex-trust", "registry"}


def test_foreign_repo_not_clobbered_and_fast(tmp_path, env):
    repo = tmp_path / "foreign"
    _git(repo)
    claude = b"# Foreign\n\nTheir rules, no trailing newline"
    agents = b"# Agents\n\nTheir agents.\n"
    (repo / "CLAUDE.md").write_bytes(claude)
    (repo / "AGENTS.md").write_bytes(agents)
    start = time.monotonic()
    init_project(repo, **env)
    elapsed = time.monotonic() - start
    print(f"TIMING foreign={elapsed:.3f}s")
    assert elapsed < 10
    assert (repo / "CLAUDE.md").read_bytes().startswith(claude)
    assert (repo / "AGENTS.md").read_bytes().startswith(agents)
    assert (repo / "CLAUDE.md").read_text().count(SECTION_BEGIN) == 1


def test_second_run_changes_nothing(tmp_path, env):
    repo = tmp_path / "again"
    _git(repo)
    (repo / "CLAUDE.md").write_text("# Mine\n")
    init_project(repo, **env)
    snap = {p.name: p.read_bytes() for p in repo.iterdir() if p.is_file()}
    cfg = env["codex_config"].read_bytes()
    reg = env["registry"].read_bytes()
    second = init_project(repo, **env)
    assert second["result"] == "unchanged" and second["changed"] == []
    assert snap == {p.name: p.read_bytes() for p in repo.iterdir() if p.is_file()}
    assert env["codex_config"].read_bytes() == cfg
    assert env["registry"].read_bytes() == reg


def test_codex_trust_single_entry_with_backup_preserving_existing(tmp_path, env):
    cfg = env["codex_config"]
    cfg.parent.mkdir(parents=True)
    original = '[projects."/other"]\ntrust_level = "trusted"\n'
    cfg.write_text(original)
    repo = tmp_path / "r"
    _git(repo)
    init_project(repo, **env)
    init_project(repo, **env)
    data = tomllib.loads(cfg.read_text())
    assert data["projects"][str(repo.resolve())]["trust_level"] == "trusted"
    assert "/other" in data["projects"]
    assert cfg.read_text().count(str(repo.resolve())) == 1
    assert cfg.with_name("config.toml.bak").read_text() == original


def test_invalid_codex_config_is_clean_error_and_untouched(tmp_path, env):
    cfg = env["codex_config"]
    cfg.parent.mkdir(parents=True)
    cfg.write_text("not = [valid\n")
    repo = tmp_path / "r"
    _git(repo)
    with pytest.raises(InitError) as exc:
        init_project(repo, **env)
    assert exc.value.code == "codex-config-invalid"
    assert cfg.read_text() == "not = [valid\n"


def test_outside_configured_roots_registers_path(tmp_path, env):
    repo = tmp_path / "anywhere"
    repo.mkdir()
    init_project(repo, **env)
    assert str(repo.resolve()) in json.loads(env["registry"].read_text())["projects"]


def test_non_git_folder_succeeds(tmp_path, env):
    folder = tmp_path / "plain"
    folder.mkdir()
    assert init_project(folder, **env)["result"] == "changed"


def test_non_git_missing_path_is_clean_json_error(tmp_path, env):
    result = CliRunner().invoke(project_app, ["init", str(tmp_path / "missing"), "--json"])
    assert result.exit_code == 1
    body = json.loads(result.output)
    assert body["error"]["code"] == "not-found"


def test_cli_json_success(tmp_path, env):
    folder = tmp_path / "p"
    folder.mkdir()
    result = CliRunner().invoke(
        project_app, ["init", str(folder), "--json", "--codex-config", str(env["codex_config"])],
        env={"HOME": str(tmp_path / "home")},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["runtimes"] == ["claude", "codex"]


def test_marker_cannot_be_claude_only_and_preserves_extras(tmp_path, env):
    repo = tmp_path / "m"
    repo.mkdir()
    (repo / MARKER_FILENAME).write_text(json.dumps({"schema_version": "1.0", "components": ["claude"], "runtimes": ["claude"], "custom": 1}))
    init_project(repo, **env)
    marker = json.loads((repo / MARKER_FILENAME).read_text())
    assert marker["runtimes"] == ["claude", "codex"] and marker["components"] == ["claude", "codex"]
    assert marker["custom"] == 1


def test_active_packs_become_gitignored_links(tmp_path, env):
    skills = env["packs_root"] / "writing-legal" / "skills"
    (skills / "cw").mkdir(parents=True)
    (skills / "cs").mkdir()
    repo = tmp_path / "packs"
    _git(repo)
    (repo / MARKER_FILENAME).write_text(json.dumps({"activePacks": [{"name": "writing-legal", "activatedBy": "plugins/mine"}]}))
    report = init_project(repo, **env)
    link = repo / "plugins/mine/skills/cw"
    assert link.is_symlink() and link.resolve() == (skills / "cw").resolve()
    ignored = subprocess.run(["git", "check-ignore", "plugins/mine/skills/cw"], cwd=repo, capture_output=True, text=True)
    assert ignored.returncode == 0
    assert sorted(report["pack_links"]) == ["plugins/mine/skills/cs", "plugins/mine/skills/cw"]
    assert init_project(repo, **env)["changed"] == []


def test_missing_pack_is_warning_not_failure(tmp_path, env):
    repo = tmp_path / "np"
    repo.mkdir()
    (repo / MARKER_FILENAME).write_text(json.dumps({"activePacks": [{"name": "nope"}]}))
    report = init_project(repo, **env)
    assert report["warnings"]
