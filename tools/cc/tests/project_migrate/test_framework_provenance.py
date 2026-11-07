"""A historical product file is not evidence of a distributed Copilot capability."""

from __future__ import annotations

from pathlib import Path

from cc.core.project_migrate import build_known, plan_migration, scan_project
from cc.core.project_migrate.framework_index import build_index
from tests.project_migrate.test_framework_copies import _commit, _git


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_history_provenance_excludes_products_but_keeps_retired_capabilities(tmp_path: Path):
    framework = tmp_path / "knowledge-copilot-internal"
    framework.mkdir()
    _git(framework, "init", "-q", "-b", "main")
    product = {
        "www/hermes/CaseRole.xml": "product xml\n",
        "scripts/create_database_schema.py": "application schema\n",
        ".claude/plans/expand-article-patterns.md": "product plan\n",
        ".claude/hooks/state/session-turns.json": '{"turn": 7}\n',
        "templates/03-requirements/10-user-stories.md": "intentional product artifact\n",
    }
    capabilities = {
        ".claude/fitness-check.sh": "framework fitness\n",
        ".claude/skills/old/SKILL.md": "framework skill\n",
        ".claude/evals/qa/qa.yaml": "framework evaluation\n",
        "plugins/old-plugin/agents/openai.yaml": "framework agent\n",
        ".codex/hooks/retired.py": "legacy Codex hook\n",
        "templates/hooks/template-hook.sh": "distributed hook template\n",
        "templates/commands/template-command.md": "distributed command template\n",
        "scripts/initiatives/retired.sh": "shared retired tool\n",
        "scripts/check-freshness.py": "shared retired check\n",
        "00-best-practices/03-templates/07-initiative-package/bin/lib-initiatives.sh": "distributed initiative helper\n",
    }
    for rel, data in (product | capabilities).items():
        _write(framework, rel, data)
    _commit(framework, "historical products and distributed capabilities")
    # A later commit retires both product and framework files. The index must
    # distinguish their historical roles without relying on current file existence.
    for rel in product | capabilities:
        (framework / rel).rename(framework / (Path(rel).name + ".retired"))
    _commit(framework, "retire historical sources")
    index = build_index([framework])
    project = tmp_path / "project"
    project.mkdir()
    for rel, data in product.items():
        path = _write(project, "scripts/product/" + Path(rel).name, data)
        assert index.matches(path) is None, rel
    for rel, data in capabilities.items():
        path = _write(project, "plugins/copied/" + Path(rel).name, data)
        assert index.matches(path), rel


def test_release_snapshot_has_same_provenance_boundary(tmp_path: Path):
    snapshot = tmp_path / "knowledge-copilot-internal"
    snapshot.mkdir()
    _write(snapshot, "www/hermes/CaseRole.xml", "product xml\n")
    _write(snapshot, "plugins/org/skills/cco/SKILL.md", "framework skill\n")
    _write(snapshot, "scripts/check-current.py", "current shared tool\n")
    index = build_index(trees=[snapshot])
    assert index.matches(snapshot / "www/hermes/CaseRole.xml") is None
    assert index.matches(snapshot / "plugins/org/skills/cco/SKILL.md")
    assert index.matches(snapshot / "scripts/check-current.py")


def test_declared_project_plugin_is_kept_without_hiding_real_copies(tmp_path: Path):
    import json

    framework = tmp_path / "framework"
    framework.mkdir()
    _git(framework, "init", "-q", "-b", "main")
    _write(framework, "plugins/org/skills/cw/SKILL.md", "shared skill\n")
    _commit(framework, "distributed plugin")
    project = tmp_path / "project"
    project.mkdir()
    _write(project, "plugins/owned/skills/cw/SKILL.md", "shared skill\n")
    _write(project, "plugins/stale/skills/cw/SKILL.md", "shared skill\n")
    _write(project, "copilot.project.json", json.dumps({"protectedPaths": ["plugins/owned"]}))
    known = build_known(claude_root=tmp_path / "none", codex_root=tmp_path / "none", framework_repos=[framework])
    plan = plan_migration(project, known=known, allow_missing_codex=True)
    copied = [a.path for a in plan.actions if a.detail.get("copy")]
    assert copied == ["plugins/stale/skills/cw/SKILL.md"]
    assert any(k.path == "plugins/owned/skills/cw/SKILL.md" and "protectedPaths" in k.reason for k in plan.keeps)
    assert scan_project(project, known)["copied_paths"] == copied
