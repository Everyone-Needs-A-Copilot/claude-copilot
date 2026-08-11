"""RC-4 fixes #1/#2/#4 -- `projects.generate_component_lock_entry()` is the
per-project lock GENERATOR: real per-path checksums of what is genuinely on
disk (never a value copied from a framework template or another project's
lock), ownership derived from each file's own frontmatter (never a blanket
`ownership: framework` claim that can contradict `owner: project`), and an
explicit `ownership_mode` on every entry it returns (never left for a
reader's implicit `"full"` default).

`write_project_lock`/`read_project_lock`/`serialize_project_lock` are
exercised elsewhere (`test_projects_contract.py`, `test_ecosystem_lockfile.py`
-shaped consumers); this file is scoped to the GENERATION half RC-4 named as
missing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from cc.core.ecosystem.projects import generate_component_lock_entry


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _sha256_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestGeneratedChecksumsReflectTheRealInstall:
    def test_checksum_is_read_from_this_project_not_a_template(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        _write(project / ".claude/commands/protocol.md", "this project's own bytes\n")

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )

        recorded = {item["path"]: item for item in entry["files"]}
        assert recorded[".claude/commands/protocol.md"]["checksum"] == _sha256_of(
            "this project's own bytes\n"
        )

    def test_two_projects_with_different_installs_never_collide(
        self, tmp_path: Path
    ) -> None:
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        _write(project_a / ".claude/commands/protocol.md", "install A\n")
        _write(project_b / ".claude/commands/protocol.md", "install B\n")

        entry_a = generate_component_lock_entry(
            project_a,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )
        entry_b = generate_component_lock_entry(
            project_b,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )

        assert entry_a["files"] != entry_b["files"]

    def test_two_projects_with_the_same_install_legitimately_agree(
        self, tmp_path: Path
    ) -> None:
        """A generator that reads real disk state is not required to
        produce a unique value for two GENUINELY identical installs --
        uniqueness comes from the install differing, not from the
        function injecting artificial noise."""

        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        _write(project_a / ".claude/commands/protocol.md", "identical bytes\n")
        _write(project_b / ".claude/commands/protocol.md", "identical bytes\n")

        entry_a = generate_component_lock_entry(
            project_a,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )
        entry_b = generate_component_lock_entry(
            project_b,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )

        assert entry_a["files"] == entry_b["files"]

    def test_a_candidate_path_absent_from_disk_is_silently_skipped(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/commands/protocol.md"],
        )

        assert entry["files"] == []


class TestOwnershipIsDerivedFromFrontmatter:
    def test_owner_project_frontmatter_is_never_recorded_framework_owned(
        self, tmp_path: Path
    ) -> None:
        """Reproduces, and closes, the `sproutworks` contradiction: an
        agent whose own frontmatter declares `owner: project` must never
        appear in `files[]` as `ownership: "framework"`."""

        project = tmp_path / "project"
        _write(
            project / ".claude/agents/elec.md",
            "---\nname: elec\nowner: project\n---\n\nBody.\n",
        )

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/agents/elec.md"],
        )

        assert entry["files"] == []

    def test_agent_with_no_owner_frontmatter_is_recorded_framework_owned(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        _write(project / ".claude/agents/cw.md", "---\nname: cw\n---\n\nBody.\n")

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[".claude/agents/cw.md"],
        )

        assert len(entry["files"]) == 1
        assert entry["files"][0]["path"] == ".claude/agents/cw.md"
        assert entry["files"][0]["ownership"] == "framework"

    def test_mixed_roster_records_only_the_framework_owned_files(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        _write(project / ".claude/agents/cw.md", "---\nname: cw\n---\n\nBody.\n")
        _write(
            project / ".claude/agents/elec.md",
            "---\nname: elec\nowner: project\n---\n\nBody.\n",
        )
        _write(
            project / ".claude/agents/emb.md",
            "---\nname: emb\nowner: project\n---\n\nBody.\n",
        )

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=[
                ".claude/agents/cw.md",
                ".claude/agents/elec.md",
                ".claude/agents/emb.md",
            ],
        )

        recorded_paths = {item["path"] for item in entry["files"]}
        assert recorded_paths == {".claude/agents/cw.md"}


class TestOwnershipModeIsAlwaysExplicit:
    def test_full_mode_is_named_on_the_returned_entry(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="full",
            candidate_paths=(),
        )

        assert entry["ownership_mode"] == "full"

    def test_customized_preserve_mode_is_named_on_the_returned_entry(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()

        entry = generate_component_lock_entry(
            project,
            "claude",
            version="1.0.0",
            release_tag="v1.0.0",
            ownership_mode="customized-preserve",
            candidate_paths=(),
        )

        assert entry["ownership_mode"] == "customized-preserve"

    def test_an_unsupported_mode_is_rejected_rather_than_silently_recorded(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()

        try:
            generate_component_lock_entry(
                project,
                "claude",
                version="1.0.0",
                release_tag="v1.0.0",
                ownership_mode="partial",
                candidate_paths=(),
            )
        except ValueError as exc:
            assert "partial" in str(exc)
        else:
            raise AssertionError("expected ValueError for an unsupported ownership_mode")
