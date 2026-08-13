from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
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


class _FakeCodexRunner:
    def __init__(self) -> None:
        self.marketplaces: dict[str, Path] = {}
        self.plugins: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, ...]] = []
        self.fail_mutation: int | None = None
        self._mutations = 0

    @staticmethod
    def _marketplace(root: Path) -> dict[str, object]:
        return json.loads((root / ".agents/plugins/marketplace.json").read_text())

    def seed(self, root: Path, *, installed: bool = True) -> str:
        marketplace = self._marketplace(root)
        name = marketplace["name"]
        assert isinstance(name, str)
        self.marketplaces[name] = root.resolve()
        if installed:
            self._install_plugin(name, Path("/not-used"), copy_cache=False)
        return name

    def _mutate(self) -> None:
        self._mutations += 1
        if self.fail_mutation == self._mutations:
            raise installer.FrameworkInstallError("injected Codex plugin failure")

    def _install_plugin(
        self, marketplace_name: str, home: Path, *, copy_cache: bool = True
    ) -> dict[str, object]:
        root = self.marketplaces[marketplace_name]
        marketplace = self._marketplace(root)
        plugin = marketplace["plugins"][0]
        source = (root / plugin["source"]["path"]).resolve()
        manifest = json.loads(
            (source / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        version = manifest["version"]
        plugin_id = f"codex-copilot@{marketplace_name}"
        installed_path = (
            home / ".codex/plugins/cache" / marketplace_name / "codex-copilot" / version
        )
        if copy_cache and plugin_id not in self.plugins:
            if installed_path.exists():
                shutil.rmtree(installed_path)
            installed_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, installed_path, symlinks=True)
            for directory, subdirectories, files in os.walk(installed_path):
                Path(directory).chmod(0o755)
                for name in subdirectories:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(0o755)
                for name in files:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
        self.plugins[plugin_id] = {
            "pluginId": plugin_id,
            "name": "codex-copilot",
            "marketplaceName": marketplace_name,
            "version": version,
            "installed": True,
            "enabled": True,
            "source": {"source": "local", "path": str(source)},
        }
        return {
            "pluginId": plugin_id,
            "name": "codex-copilot",
            "marketplaceName": marketplace_name,
            "version": version,
            "installedPath": str(installed_path.resolve()),
        }

    def __call__(
        self, arguments: tuple[str, ...] | list[str], home: Path
    ) -> dict[str, object]:
        args = tuple(arguments)
        self.calls.append(args)
        if args == ("marketplace", "list", "--json"):
            return {
                "marketplaces": [
                    {
                        "name": name,
                        "root": str(root),
                        "marketplaceSource": {
                            "sourceType": "local",
                            "source": str(root),
                        },
                    }
                    for name, root in sorted(self.marketplaces.items())
                ]
            }
        if args == ("list", "--json"):
            return {"installed": list(self.plugins.values()), "available": []}
        if args[:2] == ("marketplace", "add"):
            self._mutate()
            root = Path(args[2]).resolve()
            marketplace = self._marketplace(root)
            name = marketplace["name"]
            assert isinstance(name, str)
            current = self.marketplaces.get(name)
            if current is not None and current != root:
                raise installer.FrameworkInstallError(
                    f"marketplace {name} already has a different source"
                )
            self.marketplaces[name] = root
            return {
                "marketplaceName": name,
                "installedRoot": str(root),
                "alreadyAdded": current == root,
            }
        if args[:2] == ("marketplace", "remove"):
            self._mutate()
            self.marketplaces.pop(args[2])
            return {"marketplaceName": args[2], "installedRoot": None}
        if args[0] == "add":
            self._mutate()
            marketplace_name = args[1].split("@", 1)[1]
            return self._install_plugin(marketplace_name, home)
        if args[0] == "remove":
            self._mutate()
            plugin_id = args[1]
            item = self.plugins.pop(plugin_id)
            cache = (
                home
                / ".codex/plugins/cache"
                / item["marketplaceName"]
                / "codex-copilot"
                / item["version"]
            )
            if cache.exists():
                shutil.rmtree(cache)
            return {"pluginId": plugin_id, "removed": True}
        raise AssertionError(f"unexpected Codex command: {args}")


_FAKE_CODEX_RUNNERS: dict[Path, _FakeCodexRunner] = {}


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
    (repo / "tracked-link").symlink_to("tracked-outside-runtime.txt")
    _write(
        repo / ".agents/plugins/marketplace.json",
        json.dumps(
            {
                "name": "codex-copilot-project",
                "plugins": [
                    {
                        "name": "codex-copilot",
                        "source": {
                            "source": "local",
                            "path": "./plugins/codex-copilot",
                        },
                    }
                ],
            }
        )
        + "\n",
    )
    _write(
        repo / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}) + "\n",
    )
    _write(
        repo / "plugins/codex-copilot/skills/me/SKILL.md",
        "# committed engineer skill\n",
    )
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
    runner = kwargs.pop("codex_runner", None)
    if runner is None:
        runner = _FAKE_CODEX_RUNNERS.setdefault(home, _FakeCodexRunner())
    return installer.install_framework_snapshot(
        source_root=repo,
        source_commit=commit,
        source_tree=tree,
        home=home,
        cc_installer=_fake_cc_installer,
        codex_runner=runner,
        **kwargs,
    )


def _codex_plugin(home: Path, *arguments: str) -> dict[str, object]:
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ("codex", "plugin", *arguments),
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home), "CODEX_HOME": str(codex_home)},
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


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


def test_normalization_removes_duplicate_copilot_and_preserves_unrelated_state(
    tmp_path: Path,
):
    repo, commit, tree = _source_repository(tmp_path)
    legacy = tmp_path / "legacy"
    shutil.copytree(repo, legacy, ignore=shutil.ignore_patterns(".git"))
    descriptor = legacy / ".agents/plugins/marketplace.json"
    marketplace = json.loads(descriptor.read_text())
    marketplace["name"] = "legacy-copilot"
    descriptor.write_text(json.dumps(marketplace) + "\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    runner = _FakeCodexRunner()
    runner.seed(repo)
    runner.seed(legacy)
    runner.marketplaces["unrelated"] = unrelated
    runner.plugins["other@unrelated"] = {
        "pluginId": "other@unrelated",
        "name": "other",
        "marketplaceName": "unrelated",
        "version": "1.0.0",
        "installed": True,
        "enabled": True,
        "source": {"source": "local", "path": str(unrelated)},
    }

    report = _install(repo, commit, tree, tmp_path / "home", codex_runner=runner)

    matching = [
        item for item in runner.plugins.values() if item["name"] == "codex-copilot"
    ]
    assert [item["pluginId"] for item in matching] == [
        "codex-copilot@codex-copilot-project"
    ]
    assert (
        runner.marketplaces["codex-copilot-project"]
        == Path(report["snapshot"]).resolve()
    )
    assert runner.marketplaces["legacy-copilot"] == legacy.resolve()
    assert runner.marketplaces["unrelated"] == unrelated
    assert "other@unrelated" in runner.plugins


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI unavailable")
def test_real_codex_plugin_moves_old_registration_to_exact_snapshot(tmp_path: Path):
    repo, _old_commit, _old_tree = _source_repository(tmp_path)
    old_root = tmp_path / "old-framework"
    shutil.copytree(repo, old_root, ignore=shutil.ignore_patterns(".git"))
    plugin_skill = repo / "plugins/codex-copilot/skills/me/SKILL.md"
    plugin_skill.write_text("# new committed engineer skill\n", encoding="utf-8")
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
            "new plugin bytes",
        ),
        check=True,
    )
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    home = tmp_path / "home"
    _codex_plugin(home, "marketplace", "add", str(old_root), "--json")
    _codex_plugin(home, "add", "codex-copilot@codex-copilot-project", "--json")

    report = _install(repo, commit, tree, home, codex_runner=installer.run_codex_plugin)

    snapshot = Path(report["snapshot"])
    marketplaces = _codex_plugin(home, "marketplace", "list", "--json")
    plugins = _codex_plugin(home, "list", "--json")
    matching = [
        item for item in plugins["installed"] if item["name"] == "codex-copilot"
    ]
    active = json.loads((home / ".copilot/framework-runtime.json").read_text())
    assert [(item["name"], item["root"]) for item in marketplaces["marketplaces"]] == [
        ("codex-copilot-project", str(snapshot))
    ]
    assert len(matching) == 1
    assert matching[0]["source"]["path"] == str(snapshot / "plugins/codex-copilot")
    installed_path = Path(active["codex_plugin"]["installed_path"])
    assert installer._plugin_helper._tree_identity(installed_path) == (
        installer._plugin_helper._tree_identity(snapshot / "plugins/codex-copilot")
    )
    assert active["codex_plugin"]["tree_sha256"] == (
        installer._plugin_helper._tree_sha256(
            installer._plugin_helper._tree_identity(snapshot / "plugins/codex-copilot")
        )
    )


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI unavailable")
def test_real_codex_plugin_rolls_back_old_registration_on_publish_failure(
    tmp_path: Path,
):
    repo, commit, tree = _source_repository(tmp_path)
    old_root = tmp_path / "old-framework"
    shutil.copytree(repo, old_root, ignore=shutil.ignore_patterns(".git"))
    home = tmp_path / "home"
    _codex_plugin(home, "marketplace", "add", str(old_root), "--json")
    _codex_plugin(home, "add", "codex-copilot@codex-copilot-project", "--json")

    with pytest.raises(installer.FrameworkInstallError, match="publish failure"):
        _install(
            repo,
            commit,
            tree,
            home,
            codex_runner=installer.run_codex_plugin,
            _fail_after_publish=1,
        )

    marketplaces = _codex_plugin(home, "marketplace", "list", "--json")
    plugins = _codex_plugin(home, "list", "--json")
    assert [(item["name"], item["root"]) for item in marketplaces["marketplaces"]] == [
        ("codex-copilot-project", str(old_root))
    ]
    matching = [
        item for item in plugins["installed"] if item["name"] == "codex-copilot"
    ]
    assert len(matching) == 1
    assert matching[0]["source"]["path"] == str(old_root / "plugins/codex-copilot")
    assert not (home / ".copilot/framework-runtime.json").exists()


def test_failed_validation_preserves_error_and_removes_readonly_snapshot(
    tmp_path: Path,
):
    repo, commit, tree = _source_repository(tmp_path)
    home = tmp_path / "home"

    def install_with_forbidden_cache(snapshot: Path, staged_shim: Path) -> None:
        _fake_cc_installer(snapshot, staged_shim)
        cache = snapshot / "tools" / "cc" / "src" / "cc" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "main.cpython-314.pyc").write_bytes(b"untracked bytecode")

    with pytest.raises(
        installer.FrameworkInstallError,
        match=r"untracked extra entry: tools/cc/src/cc/__pycache__",
    ):
        installer.install_framework_snapshot(
            source_root=repo,
            source_commit=commit,
            source_tree=tree,
            home=home,
            cc_installer=install_with_forbidden_cache,
        )

    snapshot = home / ".copilot" / "framework-snapshots" / f"claude-copilot-{commit}"
    assert not snapshot.exists()
    assert not (home / ".local" / "bin" / "cc").exists()
    assert not (home / ".copilot" / "framework-runtime.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "machine-command-content",
        "non-runtime-content",
        "tracked-type",
        "tracked-mode",
        "symlink-target",
        "untracked-extra",
    ],
)
def test_reuse_rejects_snapshot_that_no_longer_matches_git(
    tmp_path: Path, mutation: str
):
    repo, commit, tree = _source_repository(tmp_path)
    home = tmp_path / "home"
    first = _install(repo, commit, tree, home)
    snapshot = Path(first["snapshot"])
    managed = [
        *(home / ".claude" / "commands" / name for name in MACHINE_COMMANDS),
        home / ".local" / "bin" / "cc",
        home / ".copilot" / "framework-runtime.json",
    ]
    before = {path: path.read_bytes() for path in managed}
    snapshot.chmod(0o755)

    if mutation == "machine-command-content":
        target = snapshot / ".claude/commands/setup-project.md"
        target.chmod(0o644)
        target.write_text("# altered command\n", encoding="utf-8")
    elif mutation == "non-runtime-content":
        target = snapshot / "tracked-outside-runtime.txt"
        target.chmod(0o644)
        target.write_text("altered tracked bytes\n", encoding="utf-8")
    elif mutation == "tracked-type":
        target = snapshot / "tracked-outside-runtime.txt"
        target.unlink()
        target.mkdir(mode=0o755)
    elif mutation == "tracked-mode":
        target = snapshot / "tracked-outside-runtime.txt"
        target.chmod(0o555)
    elif mutation == "symlink-target":
        target = snapshot / "tracked-link"
        target.unlink()
        target.symlink_to("VERSION.json")
    else:
        target = snapshot / "untracked-extra.txt"
        target.write_text("not in Git\n", encoding="utf-8")
    installer._make_tree_readonly(snapshot)

    with pytest.raises(installer.FrameworkInstallError, match="snapshot"):
        _install(repo, commit, tree, home)

    assert {path: path.read_bytes() for path in managed} == before


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


def test_full_repository_real_installer_succeeds_in_isolated_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    commit = _git(REPO_ROOT, "rev-parse", "HEAD")
    tree = _git(REPO_ROOT, "rev-parse", "HEAD^{tree}")
    home = tmp_path / "home"
    home.mkdir()
    for name in ("tmp", "cache", "pip-cache", "uv-cache"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("PIP_CACHE_DIR", str(tmp_path / "pip-cache"))
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))

    report = installer.install_framework_snapshot(
        source_root=REPO_ROOT,
        source_commit=commit,
        source_tree=tree,
        home=home,
    )

    snapshot = Path(report["snapshot"])
    shim = home / ".local" / "bin" / "cc"
    active = json.loads((home / ".copilot" / "framework-runtime.json").read_text())
    assert report["result"] == "installed"
    assert report["machine_commands"] == list(MACHINE_COMMANDS)
    assert not (snapshot / ".git").exists()
    assert not list((snapshot / "tools" / "cc" / "src").rglob("__pycache__"))
    assert not list((snapshot / "tools" / "cc" / "src").rglob("*.pyc"))
    assert (
        subprocess.check_output(
            (str(shim), "--version"),
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        .strip()
        .startswith("cc version ")
    )
    assert active["source_commit"] == commit
    assert active["source_tree"] == tree
    assert active["snapshot"] == str(snapshot)
    assert [item["name"] for item in active["machine_commands"]] == list(
        MACHINE_COMMANDS
    )
    for name in MACHINE_COMMANDS:
        assert (home / ".claude" / "commands" / name).read_bytes() == (
            snapshot / ".claude" / "commands" / name
        ).read_bytes()
