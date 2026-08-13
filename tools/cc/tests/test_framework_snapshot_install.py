from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER_PATH = REPO_ROOT / "scripts" / "install-framework-snapshot.py"
SPEC = importlib.util.spec_from_file_location(
    "framework_snapshot_installer", INSTALLER_PATH
)
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


MACHINE_COMMANDS = (
    "setup.md",
    "setup-project.md",
    "update-project.md",
    "update-copilot.md",
    "setup-copilot.md",
    "knowledge-copilot.md",
)


@pytest.fixture(autouse=True)
def _make_immutable_test_snapshots_removable(tmp_path: Path):
    """Leave pytest able to remove intentionally read-only snapshot fixtures."""

    yield
    for snapshots_root in tmp_path.glob("**/framework-snapshots"):
        if not snapshots_root.is_dir():
            continue
        for snapshot in snapshots_root.glob("claude-copilot-*"):
            if not snapshot.is_dir() or snapshot.is_symlink():
                continue
            for directory, subdirectories, files in os.walk(
                snapshot, topdown=True, followlinks=False
            ):
                Path(directory).chmod(
                    stat.S_IMODE(Path(directory).stat().st_mode) | 0o700
                )
                for name in files:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o600)
                for name in subdirectories:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o700)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ("git", "-C", str(repo), *arguments), text=True
    ).strip()


def _write(path: Path, content: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _source_repository(
    tmp_path: Path,
    *,
    roster: tuple[str, ...] = MACHINE_COMMANDS,
    omit_source: str | None = None,
) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(("git", "init", "--quiet", str(repo)), check=True)
    _write(
        repo / "VERSION.json",
        json.dumps({"components": {"commands": {"machineCommands": list(roster)}}})
        + "\n",
    )
    for name in MACHINE_COMMANDS:
        if name != omit_source:
            _write(repo / ".claude" / "commands" / name, f"# committed {name}\n")
    _write(repo / "tools" / "cc" / "install.sh", "#!/bin/sh\n", mode=0o755)
    _write(repo / "tools" / "cc" / "pyproject.toml", "[project]\nname='cc-test'\n")
    _write(
        repo / "tools" / "cc" / "src" / "cc" / "core" / "conformance" / "roundtrip.py",
        "# committed roundtrip\n",
    )
    _write(repo / "tracked-outside-runtime.txt", "full archive sentinel\n")
    subprocess.run(("git", "-C", str(repo), "add", "."), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Snapshot Test",
            "-c",
            "user.email=snapshot@test.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ),
        check=True,
    )
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return repo, commit, tree


def _fake_cc_installer(snapshot: Path, staged_shim: Path) -> None:
    payload = b"#!/bin/sh\nprintf 'cc 2.12.8\\n'\n"
    runtime = snapshot / "tools" / "cc" / ".venv" / "bin" / "cc"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(payload)
    runtime.chmod(0o755)
    staged_shim.parent.mkdir(parents=True, exist_ok=True)
    staged_shim.write_bytes(payload)
    staged_shim.chmod(0o755)


def _install(
    repo: Path,
    commit: str,
    tree: str,
    home: Path,
    **kwargs,
):
    return installer.install_framework_snapshot(
        source_root=repo,
        source_commit=commit,
        source_tree=tree,
        home=home,
        cc_installer=_fake_cc_installer,
        **kwargs,
    )


def test_exact_commit_archive_ignores_dirty_source_and_deploys_manifest_roster(
    tmp_path: Path,
):
    repo, commit, tree = _source_repository(tmp_path)
    (repo / ".claude" / "commands" / "setup-project.md").write_text(
        "# dirty worktree bytes\n", encoding="utf-8"
    )
    _write(repo / "untracked.txt", "must not be installed\n")
    home = tmp_path / "home"
    unrelated = home / ".claude" / "commands" / "my-command.md"
    _write(unrelated, "# person-owned\n")

    report = _install(repo, commit, tree, home)

    snapshot = Path(report["snapshot"])
    assert report["machine_commands"] == list(MACHINE_COMMANDS)
    assert not (snapshot / ".git").exists()
    assert (
        snapshot / "tracked-outside-runtime.txt"
    ).read_text() == "full archive sentinel\n"
    assert not (snapshot / "untracked.txt").exists()
    assert stat.S_IMODE(snapshot.stat().st_mode) & 0o222 == 0
    assert (snapshot / ".source-commit").read_text().strip() == commit
    assert (snapshot / ".source-tree").read_text().strip() == tree
    assert unrelated.read_text() == "# person-owned\n"

    active = json.loads((home / ".copilot" / "framework-runtime.json").read_text())
    recorded = {item["name"]: item["sha256"] for item in active["machine_commands"]}
    assert tuple(recorded) == MACHINE_COMMANDS
    for name in MACHINE_COMMANDS:
        committed = subprocess.check_output(
            ("git", "-C", str(repo), "show", f"{commit}:.claude/commands/{name}")
        )
        installed = (home / ".claude" / "commands" / name).read_bytes()
        assert installed == committed
        assert recorded[name] == hashlib.sha256(committed).hexdigest()
    assert (
        b"dirty worktree"
        not in (home / ".claude" / "commands" / "setup-project.md").read_bytes()
    )


@pytest.mark.parametrize(
    ("commit_value", "tree_value", "message"),
    [
        ("not-an-object", "b" * 40, "source commit must be"),
        ("a" * 40, "not-an-object", "source tree must be"),
    ],
)
def test_invalid_object_ids_fail_before_machine_mutation(
    tmp_path: Path, commit_value: str, tree_value: str, message: str
):
    repo, _commit, _tree = _source_repository(tmp_path)
    home = tmp_path / "home"

    with pytest.raises(installer.FrameworkInstallError, match=message):
        _install(repo, commit_value, tree_value, home)

    assert not (home / ".local" / "bin" / "cc").exists()
    assert not (home / ".claude" / "commands" / "setup-project.md").exists()


def test_mismatched_tree_fails_before_machine_mutation(tmp_path: Path):
    repo, commit, _tree = _source_repository(tmp_path)
    home = tmp_path / "home"

    with pytest.raises(installer.FrameworkInstallError, match="source tree mismatch"):
        _install(repo, commit, "f" * 40, home)

    assert not (home / ".local" / "bin" / "cc").exists()


@pytest.mark.parametrize(
    ("roster", "omit_source", "message"),
    [
        (("setup-project.md",), None, "omits required operational"),
        (
            ("setup-project.md", "update-project.md", "../outside.md"),
            None,
            "unsafe machineCommands entry",
        ),
        (
            MACHINE_COMMANDS,
            "update-project.md",
            "required snapshot file is unavailable",
        ),
    ],
)
def test_invalid_machine_command_manifest_fails_closed(
    tmp_path: Path,
    roster: tuple[str, ...],
    omit_source: str | None,
    message: str,
):
    repo, commit, tree = _source_repository(
        tmp_path, roster=roster, omit_source=omit_source
    )
    home = tmp_path / "home"
    old_shim = home / ".local" / "bin" / "cc"
    _write(old_shim, "#!/bin/sh\necho old\n", mode=0o755)

    with pytest.raises(installer.FrameworkInstallError, match=message):
        _install(repo, commit, tree, home)

    assert old_shim.read_text() == "#!/bin/sh\necho old\n"
    assert not (home / ".copilot" / "framework-runtime.json").exists()


@pytest.mark.parametrize("failure_index", [1, 3, 7, 8])
def test_publish_failure_rolls_back_all_managed_targets(
    tmp_path: Path, failure_index: int
):
    repo, commit, tree = _source_repository(tmp_path)
    home = tmp_path / "home"
    expected: dict[Path, bytes] = {}
    for name in MACHINE_COMMANDS:
        path = home / ".claude" / "commands" / name
        _write(path, f"# old {name}\n")
        expected[path] = path.read_bytes()
    shim = home / ".local" / "bin" / "cc"
    _write(shim, "#!/bin/sh\necho old\n", mode=0o755)
    expected[shim] = shim.read_bytes()
    active = home / ".copilot" / "framework-runtime.json"
    _write(active, '{"old":true}\n', mode=0o600)
    expected[active] = active.read_bytes()
    unrelated = home / ".claude" / "commands" / "mine.md"
    _write(unrelated, "# untouched\n")

    with pytest.raises(
        installer.FrameworkInstallError, match="injected publish failure"
    ):
        _install(repo, commit, tree, home, _fail_after_publish=failure_index)

    assert {path: path.read_bytes() for path in expected} == expected
    assert unrelated.read_text() == "# untouched\n"


def test_reinstall_is_idempotent_and_reuses_valid_readonly_snapshot(tmp_path: Path):
    repo, commit, tree = _source_repository(tmp_path)
    home = tmp_path / "home"

    first = _install(repo, commit, tree, home)
    active = home / ".copilot" / "framework-runtime.json"
    before = active.read_bytes()
    second = _install(repo, commit, tree, home)

    assert first["result"] == "installed"
    assert second["result"] == "up-to-date"
    assert second["changed_targets"] == 0
    assert active.read_bytes() == before


def test_full_repository_snapshot_runs_real_roundtrip_without_cnr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from cc.commands import conformance
    from cc.core.conformance import roundtrip
    from cc.core.conformance.types import Verdict

    commit = _git(REPO_ROOT, "rev-parse", "HEAD")
    tree = _git(REPO_ROOT, "rev-parse", "HEAD^{tree}")
    home = tmp_path / "home"
    report = _install(REPO_ROOT, commit, tree, home)
    snapshot = Path(report["snapshot"])
    codex_fixture = (
        REPO_ROOT / "tools" / "cc" / "tests" / "fixtures" / "codex-installer"
    )
    monkeypatch.setenv("CC_PATHS_CLAUDE_COPILOT_ROOT", str(snapshot))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(codex_fixture))
    monkeypatch.setattr(
        roundtrip, "discover_framework_repo_root", lambda start=None: snapshot
    )

    conformance._ensure_registry_loaded()
    results = conformance._run_roundtrip_layer()

    assert results
    assert any(
        result.id == "roundtrip.transaction.plan_apply_verify" for result in results
    )
    assert all(result.verdict is not Verdict.COULD_NOT_RUN for result in results)
