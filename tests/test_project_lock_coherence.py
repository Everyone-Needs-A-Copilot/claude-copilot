from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/verify-project-lock-coherence.py"
CLAUDE_PATHS = (
    ".claude/commands/protocol.md",
    ".claude/fitness-check.sh",
    ".claude/hooks/copilot-hook.sh",
    ".claude/agents/sd.md",
    ".claude/agents/kc.md",
)
CODEX_PATHS = (
    "plugins/codex-copilot/.codex-plugin/plugin.json",
    "scripts/copilot-gate.sh",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _prepare_release_tree(root: Path) -> None:
    version = {
        "framework": "5.14.11",
        "components": {
            "commands": {"projectCommands": ["protocol.md"]},
            "agents": {"frameworkAgents": ["sd"]},
        },
    }
    _write(root / "VERSION.json", json.dumps(version) + "\n")
    for relative_path in CLAUDE_PATHS:
        _write(root / relative_path, f"source bytes for {relative_path}\n")
    _write(
        root / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}) + "\n",
    )
    _write(root / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n")


def _component(root: Path, name: str, version: str, paths: tuple[str, ...]) -> dict:
    return {
        "component": name,
        "files": [
            {
                "checksum": f"sha256:{_sha256(root / relative_path)}",
                "ownership": "framework",
                "path": relative_path,
            }
            for relative_path in paths
        ],
        "ownership_mode": "full",
        "release_tag": f"v{version}",
        "version": version,
    }


def _write_lock(root: Path) -> dict:
    payload = {
        "components": [
            _component(root, "claude", "5.14.11", CLAUDE_PATHS),
            _component(root, "codex", "0.6.1", CODEX_PATHS),
        ],
        "mutations": [],
        "schema_version": "1.0",
    }
    (root / "copilot.lock.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "copilot.lock.json").chmod(0o644)
    return payload


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_exact_project_lock_tree_passes(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert (
        result.stdout.strip()
        == "project lock coherence: verified 2 components / 7 files"
    )


def test_project_lock_rejects_checksum_drift(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    payload = _write_lock(tmp_path)
    payload["components"][0]["files"][0]["checksum"] = "sha256:" + "0" * 64
    (tmp_path / "copilot.lock.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "checksum differs from release tree" in result.stderr


def test_project_lock_rejects_symlinked_lock_document(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    external = tmp_path.parent / f"{tmp_path.name}-external-lock.json"
    shutil.move(tmp_path / "copilot.lock.json", external)
    (tmp_path / "copilot.lock.json").symlink_to(external)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "cannot open path safely" in result.stderr


def test_project_lock_rejects_omitted_extra_agent(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    _write(tmp_path / ".claude/agents/ta.md", "unlocked framework agent\n")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "Claude agent source roster differs" in result.stderr


def test_project_lock_rejects_omitted_codex_source_file(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    _write(tmp_path / "plugins/codex-copilot/skills/new/SKILL.md", "new source\n")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "component codex roster differs" in result.stderr


def test_project_lock_rejects_project_owned_framework_row(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    payload = _write_lock(tmp_path)
    payload["components"][0]["files"][0]["ownership"] = "project"
    (tmp_path / "copilot.lock.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "duplicate or not framework-owned" in result.stderr


def test_project_lock_rejects_noncanonical_or_duplicate_json(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    raw = (tmp_path / "copilot.lock.json").read_text(encoding="utf-8")
    (tmp_path / "copilot.lock.json").write_text(
        raw.replace(
            '"schema_version": "1.0"',
            '"schema_version": "1.0", "schema_version": "1.0"',
        ),
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "duplicate key" in result.stderr


def test_project_lock_rejects_wrong_mode(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    (tmp_path / "copilot.lock.json").chmod(0o600)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "not an exact bounded owner file" in result.stderr


def test_project_lock_rejects_symlinked_source_parent(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    displaced = tmp_path / "displaced-claude"
    shutil.move(tmp_path / ".claude", displaced)
    (tmp_path / ".claude").symlink_to(displaced, target_is_directory=True)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "cannot" in result.stderr or "source tree" in result.stderr


def test_project_lock_rejects_hardlinked_leaf(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    alias = tmp_path / "alias.md"
    os.link(tmp_path / ".claude/agents/sd.md", alias)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "not an exact bounded owner file" in result.stderr


def test_project_lock_rejects_replaced_parent_tree(tmp_path: Path) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    shutil.rmtree(tmp_path / ".claude")
    for relative_path in CLAUDE_PATHS:
        _write(tmp_path / relative_path, f"replacement bytes for {relative_path}\n")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "checksum differs from release tree" in result.stderr


def test_project_lock_rejects_same_byte_named_leaf_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    spec = importlib.util.spec_from_file_location("lock_coherence_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module._named_identity
    swapped = False

    def swap_before_revalidation(root_descriptor: int, relative_path: str):
        nonlocal swapped
        if relative_path == ".claude/agents/sd.md" and not swapped:
            swapped = True
            target = tmp_path / relative_path
            displaced = target.with_name("sd.displaced")
            target.rename(displaced)
            target.write_bytes(displaced.read_bytes())
        return original(root_descriptor, relative_path)

    monkeypatch.setattr(module, "_named_identity", swap_before_revalidation)

    with pytest.raises(SystemExit, match="path changed while it was read"):
        module.verify(tmp_path)

    assert swapped is True


@pytest.mark.parametrize(
    ("relative_path", "message"),
    (
        ("plugins/codex-copilot/late.py", "release source roster changed"),
        (".claude/agents/ta.md", "Claude agent source roster differs"),
    ),
)
def test_project_lock_rejects_late_roster_insertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    message: str,
) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    spec = importlib.util.spec_from_file_location("lock_coherence_late_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module._read_exact_file_snapshot
    inserted = False

    def insert_after_roster(root_descriptor: int, path: str, **kwargs):
        nonlocal inserted
        if path == ".claude/commands/protocol.md" and not inserted:
            inserted = True
            _write(tmp_path / relative_path, "late source\n")
        return original(root_descriptor, path, **kwargs)

    monkeypatch.setattr(module, "_read_exact_file_snapshot", insert_after_roster)

    with pytest.raises(SystemExit, match=message):
        module.verify(tmp_path)

    assert inserted is True


def test_project_lock_rejects_transient_roster_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "lock_coherence_generation_module", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module._read_exact_file_snapshot
    mutated = False

    def mutate_after_roster(root_descriptor: int, path: str, **kwargs):
        nonlocal mutated
        if path == ".claude/commands/protocol.md" and not mutated:
            mutated = True
            transient = tmp_path / "plugins/codex-copilot/transient.py"
            _write(transient, "transient source\n")
            transient.unlink()
        return original(root_descriptor, path, **kwargs)

    monkeypatch.setattr(module, "_read_exact_file_snapshot", mutate_after_roster)

    with pytest.raises(SystemExit, match="directory generation changed"):
        module.verify(tmp_path)

    assert mutated is True


def test_project_lock_rejects_transient_locked_leaf_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_release_tree(tmp_path)
    _write_lock(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "lock_coherence_leaf_generation_module", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module._read_exact_file_snapshot
    mutated = False

    def mutate_and_restore(root_descriptor: int, path: str, **kwargs):
        nonlocal mutated
        if path == ".claude/fitness-check.sh" and not mutated:
            mutated = True
            target = tmp_path / ".claude/commands/protocol.md"
            original_bytes = target.read_bytes()
            target.write_bytes(b"transient source bytes\n")
            target.write_bytes(original_bytes)
        return original(root_descriptor, path, **kwargs)

    monkeypatch.setattr(module, "_read_exact_file_snapshot", mutate_and_restore)

    with pytest.raises(SystemExit, match="locked source leaf changed"):
        module.verify(tmp_path)

    assert mutated is True


@pytest.mark.parametrize(
    ("authority_path", "component_index", "forged_version"),
    (
        ("VERSION.json", 0, "9.9.9"),
        ("plugins/codex-copilot/.codex-plugin/plugin.json", 1, "8.8.8"),
    ),
)
def test_project_lock_rejects_transient_version_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_path: str,
    component_index: int,
    forged_version: str,
) -> None:
    _prepare_release_tree(tmp_path)
    payload = _write_lock(tmp_path)
    payload["components"][component_index]["version"] = forged_version
    payload["components"][component_index]["release_tag"] = f"v{forged_version}"
    (tmp_path / "copilot.lock.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location(
        "lock_coherence_authority_generation_module", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module._read_exact_file_snapshot
    forged = False

    def forge_during_authority_read(root_descriptor: int, path: str, **kwargs):
        nonlocal forged
        if path == authority_path and not forged:
            forged = True
            target = tmp_path / path
            original_bytes = target.read_bytes()
            document = json.loads(original_bytes)
            if path == "VERSION.json":
                document["framework"] = forged_version
            else:
                document["version"] = forged_version
            target.write_text(json.dumps(document) + "\n", encoding="utf-8")
            result = original(root_descriptor, path, **kwargs)
            target.write_bytes(original_bytes)
            return result
        return original(root_descriptor, path, **kwargs)

    monkeypatch.setattr(
        module,
        "_read_exact_file_snapshot",
        forge_during_authority_read,
    )

    with pytest.raises(SystemExit, match="release authority changed"):
        module.verify(tmp_path)

    assert forged is True
