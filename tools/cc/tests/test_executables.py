from pathlib import Path

import pytest
from cc.core.executables import STANDARD_EXECUTABLE_PATHS, resolve_executable


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_path_resolution_wins_and_returns_canonical_absolute_path(tmp_path):
    target = _executable(tmp_path / "real" / "copilot")
    linked = tmp_path / "bin" / "copilot"
    linked.parent.mkdir()
    linked.symlink_to(target)

    resolved = resolve_executable(
        "copilot",
        which=lambda _command: str(linked),
        standard_paths=(tmp_path / "fallback",),
    )

    assert resolved == target.resolve()


def test_standard_location_fallback_works_without_shell_path(tmp_path):
    target = _executable(tmp_path / "standard" / "copilot")

    resolved = resolve_executable(
        "copilot",
        which=lambda _command: None,
        standard_paths=(tmp_path / "missing", target),
    )

    assert resolved == target.resolve()


def test_non_executable_candidates_are_rejected(tmp_path):
    candidate = tmp_path / "copilot"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o644)

    assert (
        resolve_executable(
            "copilot",
            which=lambda _command: str(candidate),
            standard_paths=(candidate,),
        )
        is None
    )


def test_user_local_fallback_expands_the_current_home(monkeypatch, tmp_path):
    target = _executable(tmp_path / ".local" / "bin" / "claude")
    monkeypatch.setenv("HOME", str(tmp_path))

    resolved = resolve_executable("claude", which=lambda _command: None)

    assert resolved == target.resolve()


@pytest.mark.parametrize("command", ("gh", "copilot", "claude", "codex"))
def test_gui_sensitive_direct_dependencies_have_bounded_fallbacks(command):
    candidates = STANDARD_EXECUTABLE_PATHS[command]

    assert candidates
    assert all(
        candidate.startswith("~/") or candidate.startswith("/")
        for candidate in candidates
    )


def test_unknown_command_remains_path_only():
    assert resolve_executable("unknown-command", which=lambda _command: None) is None
