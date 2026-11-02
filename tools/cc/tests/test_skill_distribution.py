"""Org-tier skills reach BOTH Claude and Codex from one `cc update`.

Everything runs under tmp_path (isolated HOME stand-in); nothing resolves the
real home directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cc.commands.update import build_update_report
from cc.core.ecosystem import skill_distribution as sd
from cc.core.ecosystem.policy import permissive_policy


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("must not resolve Path.home()")

    monkeypatch.setattr(Path, "home", staticmethod(_boom))
    monkeypatch.delenv("CODEX_HOME", raising=False)


def _skill(root: Path, name: str, body: str = "v1") -> None:
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n", encoding="utf-8")


def _layers(org_root: Path, role: str = "organization") -> list[dict]:
    return [
        {
            "id": "claude-organization",
            "role": role,
            "rank": 30,
            "product": "claude",
            "source": {"repo": "https://example.invalid/x.git", "path": str(org_root)},
            "auth": "anon",
            "activation": "always",
        }
    ]


def _update(tmp: Path, org_root: Path, **kw):
    return build_update_report(
        _layers=kw.pop("layers", _layers(org_root)),
        _previous_lock=kw.pop("previous_lock", {}),
        _mirror_root=tmp / "mirrors",
        _materialize_roots={"claude": tmp / ".claude", "codex": tmp / "cx"},
        _codex_skills_dir=tmp / ".codex" / "skills",
        _lock_write_path=tmp / "cfg" / "copilot.lock.json",
        _policy=permissive_policy,
        _personal_roots=[],
        **kw,
    )


def test_org_skills_visible_to_both_harnesses(tmp_path):
    org = tmp_path / "org"
    _skill(org, "clean-mac-test")
    _skill(org, "infographics")
    report = _update(tmp_path, org)
    claude = tmp_path / ".claude" / "skills"
    codex = tmp_path / ".codex" / "skills"
    for name in ("clean-mac-test", "infographics"):
        assert (claude / name / "SKILL.md").is_file()
        assert (codex / name / "SKILL.md").is_file()
        assert codex.joinpath(name).resolve() == claude.joinpath(name).resolve()
    assert {r["action"] for r in report["skill_distribution"]} == {"linked"}
    state = tmp_path / "cfg" / sd.STATE_FILENAME
    assert (
        sd.verify_distribution(claude_dir=claude, codex_dir=codex, state_path=state)
        == []
    )


def test_second_update_is_a_noop(tmp_path):
    org = tmp_path / "org"
    _skill(org, "clean-mac-test")
    _update(tmp_path, org)
    lock = json.loads((tmp_path / "cfg" / "copilot.lock.json").read_text())
    again = _update(tmp_path, org, previous_lock=lock)
    assert "skill_distribution" not in again
    assert again["result"] == "up-to-date"


def test_foundation_and_personal_roles_are_not_projected(tmp_path):
    org = tmp_path / "org"
    _skill(org, "x")
    report = _update(tmp_path, org, layers=_layers(org, role="foundation"))
    assert "skill_distribution" not in report
    assert not (tmp_path / ".codex" / "skills").exists()


def test_conflicts_are_reported_never_replaced(tmp_path):
    org = tmp_path / "org"
    _skill(org, "stale")
    _skill(org, "elsewhere")
    codex = tmp_path / ".codex" / "skills"
    (codex / "stale").mkdir(parents=True)
    (codex / "stale" / "SKILL.md").write_text("mine")
    other = tmp_path / "other"
    other.mkdir()
    (codex / "elsewhere").symlink_to(other)
    report = _update(tmp_path, org)
    rows = {r["skill"]: r for r in report["skill_distribution"]}
    assert rows["stale"]["action"] == "conflict"
    assert rows["elsewhere"]["action"] == "conflict"
    assert (codex / "stale" / "SKILL.md").read_text() == "mine"
    assert os.readlink(codex / "elsewhere") == str(other)
    assert sd.read_state(tmp_path / "cfg" / sd.STATE_FILENAME) == {}


def test_removed_skill_removes_only_its_own_link(tmp_path):
    org = tmp_path / "org"
    _skill(org, "keep")
    _skill(org, "gone")
    _update(tmp_path, org)
    codex = tmp_path / ".codex" / "skills"
    (codex / "hand-made").symlink_to(tmp_path)
    import shutil

    shutil.rmtree(org / "skills" / "gone")
    lock = json.loads((tmp_path / "cfg" / "copilot.lock.json").read_text())
    report = _update(tmp_path, org, previous_lock=lock)
    assert [r["action"] for r in report["skill_distribution"]] == ["removed"]
    assert not (codex / "gone").is_symlink()
    assert (codex / "keep").is_symlink()
    assert (codex / "hand-made").is_symlink()


def test_doctor_verify_flags_a_harness_that_lost_the_skill(tmp_path):
    org = tmp_path / "org"
    _skill(org, "clean-mac-test")
    _update(tmp_path, org)
    codex = tmp_path / ".codex" / "skills"
    (codex / "clean-mac-test").unlink()
    problems = sd.verify_distribution(
        claude_dir=tmp_path / ".claude" / "skills",
        codex_dir=codex,
        state_path=tmp_path / "cfg" / sd.STATE_FILENAME,
    )
    assert len(problems) == 1 and "Codex" in problems[0]["problem"]


def test_dry_run_changes_nothing(tmp_path):
    org = tmp_path / "org"
    _skill(org, "clean-mac-test")
    report = _update(tmp_path, org, _dry_run=True)
    assert report["skill_distribution"][0]["action"] == "linked"
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / "cfg").exists()


def test_doctor_checker_reports_both_harnesses(tmp_path, monkeypatch):
    from cc.commands import doctor

    org = tmp_path / "org"
    _skill(org, "clean-mac-test")
    _update(tmp_path, org)
    lock = tmp_path / "cfg" / "copilot.lock.json"
    values = {
        "paths.claude_materialize_root": str(tmp_path / ".claude"),
        "paths.codex_skills_dir": str(tmp_path / ".codex" / "skills"),
    }
    monkeypatch.setattr(doctor, "resolve_key", lambda key, **_k: values.get(key))
    [ok] = doctor._skill_distribution_checkers(lock)
    assert (ok.id, ok.severity) == ("org-skill-distribution", "pass")
    (tmp_path / ".codex" / "skills" / "clean-mac-test").unlink()
    [bad] = doctor._skill_distribution_checkers(lock)
    assert bad.severity == "warn" and "Codex" in bad.detail
    assert doctor._skill_distribution_checkers(tmp_path / "none" / "x.json") == []
