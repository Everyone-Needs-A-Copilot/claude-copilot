"""Tests for the extension resolver (Gap 1): `knowledge-manifest.json`
discovery, agent-id matching, personal-over-org precedence, override vs.
extension typing, requiredSkills verification, fallbackBehavior, and the
deterministic `compose_agent_content` seam.

Fixtures under tests/fixtures/extensions/{org-repo,personal-repo}/ are
byte-for-byte COPIES of the real, currently-unreachable content in
knowledge-copilot-internal and knowledge-copilot-private (never modified by
these tests or by the resolver -- see the module docstring in
core/extensions_resolver.py for why the documented two-hardcoded-path
algorithm never found them).

Covers:
- Personal-over-org precedence (cw declared in both fixtures -- personal
  wins because it is listed first, not via a separate rank comparison).
- All 5 real knowledge-copilot-internal extensions resolve (sd override;
  uxd, cw, do, ind extensions) with correct type/file/source.
- requiredSkills verification + fallbackBehavior branches: use_base,
  use_base_with_warning, fail.
- Malformed / absent manifest is skipped silently -- resolution for other
  repos/agents still proceeds, never raises.
- compose_agent_content: override substitutes; extension appends
  (deterministic, labeled, never a silent section-merge); skills/no-match
  leave the base agent untouched.
- CLI wiring: `cc extensions resolve --agent <id> --json`.
- The updated schema enum (16 agents) validates the real org manifest,
  including its `ind` extension entry the old 11-agent enum rejected.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import cc.core.ecosystem.knowledge_skill_source as knowledge_skill_source
import cc.core.extensions_resolver as extensions_resolver
import pytest
from cc.core.extensions_resolver import (
    ACTION_APPLY,
    ACTION_FALLBACK_FAIL,
    ACTION_FALLBACK_USE_BASE,
    ACTION_FALLBACK_WARNING,
    ACTION_NO_EXTENSION,
    ExtensionSkillBindings,
    compose_agent_content,
    resolve_extension,
)
from cc.core.skill_store import SkillMeta
from cc.main import app
from typer.testing import CliRunner

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "extensions"
ORG_REPO = str(FIXTURES / "org-repo")
PERSONAL_REPO = str(FIXTURES / "personal-repo")


def _no_missing(_required: list[str]) -> list[str]:
    """Injected skills checker: everything is available."""
    return []


def _all_missing(required: list[str]) -> list[str]:
    """Injected skills checker: nothing is available."""
    return list(required)


# ---------------------------------------------------------------------------
# Precedence: personal-over-org
# ---------------------------------------------------------------------------


def test_personal_wins_over_org_when_both_declare_same_agent():
    # Both fixtures declare a `cw` extension. Personal-over-org precedence
    # is list order -- personal listed first.
    r = resolve_extension(
        "cw",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        missing_skills_checker=_no_missing,
    )
    assert r.matched is True
    assert r.source_repo == PERSONAL_REPO
    assert r.file.endswith("personal-repo/.claude/extensions/cw.extension.md")
    assert r.action == ACTION_APPLY


def test_org_wins_when_listed_first():
    # Same two repos, reversed order -- proves precedence is genuinely
    # about iteration order, not a hardcoded "personal always wins" rule.
    r = resolve_extension(
        "cw",
        knowledge_repos=[ORG_REPO, PERSONAL_REPO],
        missing_skills_checker=_no_missing,
    )
    assert r.source_repo == ORG_REPO


def test_org_only_match_when_personal_has_no_entry():
    # sd is only declared in the org manifest.
    r = resolve_extension(
        "sd",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        missing_skills_checker=_no_missing,
    )
    assert r.matched is True
    assert r.source_repo == ORG_REPO
    assert r.type == "override"


# ---------------------------------------------------------------------------
# The 5 real knowledge-copilot-internal extensions resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent,expected_type,expected_file",
    [
        ("sd", "override", "sd.override.md"),
        ("uxd", "extension", "uxd.extension.md"),
        ("cw", "extension", "cw.extension.md"),
        ("do", "extension", "do.extension.md"),
        ("ind", "extension", "ind.extension.md"),
    ],
)
def test_real_org_extensions_resolve(agent, expected_type, expected_file):
    r = resolve_extension(
        agent,
        knowledge_repos=[ORG_REPO],
        missing_skills_checker=_no_missing,
    )
    assert r.matched is True
    assert r.action == ACTION_APPLY
    assert r.type == expected_type
    assert r.file.endswith(f".claude/extensions/{expected_file}")
    assert r.source_repo == ORG_REPO
    assert Path(r.file).is_file()


def test_ta_has_no_org_extension():
    # ta is not among the 5 declared extensions -- proves the resolver
    # doesn't hallucinate a match.
    r = resolve_extension("ta", knowledge_repos=[ORG_REPO])
    assert r.matched is False
    assert r.action == ACTION_NO_EXTENSION
    assert r.file is None
    assert r.source_repo is None


def test_sd_declares_its_real_required_skills():
    r = resolve_extension(
        "sd", knowledge_repos=[ORG_REPO], missing_skills_checker=_no_missing
    )
    assert r.required_skills == ["moments-mapping", "cocreate-sprint"]


# ---------------------------------------------------------------------------
# requiredSkills + fallbackBehavior
# ---------------------------------------------------------------------------


def test_missing_skills_use_base_with_warning_falls_back_with_warning():
    # uxd's fixture entry declares fallbackBehavior=use_base_with_warning.
    r = resolve_extension(
        "uxd", knowledge_repos=[ORG_REPO], missing_skills_checker=_all_missing
    )
    assert r.action == ACTION_FALLBACK_WARNING
    assert r.use_extension is False
    assert r.fallback_applied is True
    assert r.skills_ok is False
    assert "moments-mapping" in r.missing_skills
    assert r.warning is not None and "uxd" in r.warning


def test_do_extension_declares_use_base_fallback():
    # do's real fixture entry has no requiredSkills and fallbackBehavior
    # use_base -- confirms the fixture data itself, independent of the
    # synthetic use_base branch test below.
    from cc.core.extensions_resolver import _find_agent_extension, _load_manifest

    manifest = _load_manifest(ORG_REPO)
    entry = _find_agent_extension(manifest, "do")
    assert entry["fallbackBehavior"] == "use_base"

    r = resolve_extension(
        "do", knowledge_repos=[ORG_REPO], missing_skills_checker=_all_missing
    )
    assert r.action == ACTION_APPLY  # no requiredSkills declared -- nothing to miss


def test_missing_skills_use_base_behavior(tmp_path):
    _write_manifest(
        tmp_path,
        agent="qa",
        ext_type="extension",
        required_skills=["nonexistent-skill"],
        fallback="use_base",
    )
    r = resolve_extension(
        "qa", knowledge_repos=[str(tmp_path)], missing_skills_checker=_all_missing
    )
    assert r.action == ACTION_FALLBACK_USE_BASE
    assert r.use_extension is False
    assert r.warning is None  # silent -- use_base never warns


def test_missing_skills_fail_behavior_blocks(tmp_path):
    _write_manifest(
        tmp_path,
        agent="qa",
        ext_type="override",
        required_skills=["nonexistent-skill"],
        fallback="fail",
    )
    r = resolve_extension(
        "qa", knowledge_repos=[str(tmp_path)], missing_skills_checker=_all_missing
    )
    assert r.action == ACTION_FALLBACK_FAIL
    assert r.use_extension is False
    assert "nonexistent-skill" in r.warning


def test_default_fallback_behavior_is_use_base_with_warning_when_unspecified(tmp_path):
    _write_manifest(
        tmp_path,
        agent="qa",
        ext_type="extension",
        required_skills=["nonexistent-skill"],
        fallback=None,
    )
    r = resolve_extension(
        "qa", knowledge_repos=[str(tmp_path)], missing_skills_checker=_all_missing
    )
    assert r.fallback_behavior == "use_base_with_warning"
    assert r.action == ACTION_FALLBACK_WARNING


# ---------------------------------------------------------------------------
# Malformed / absent manifest -- skipped silently, never blocks
# ---------------------------------------------------------------------------


def test_absent_manifest_is_skipped_silently(tmp_path, caplog):
    empty_repo = tmp_path / "no-manifest-here"
    empty_repo.mkdir()
    with caplog.at_level(logging.WARNING):
        r = resolve_extension("sd", knowledge_repos=[str(empty_repo), ORG_REPO])
    assert r.matched is True  # fell through to the next (valid) repo
    assert r.source_repo == ORG_REPO


def test_malformed_manifest_is_skipped_silently(tmp_path, caplog):
    bad_repo = tmp_path / "bad-repo"
    bad_repo.mkdir()
    (bad_repo / "knowledge-manifest.json").write_text("{ not valid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        r = resolve_extension("sd", knowledge_repos=[str(bad_repo), ORG_REPO])
    assert r.matched is True
    assert r.source_repo == ORG_REPO
    assert any("malformed manifest" in rec.message for rec in caplog.records)


def test_malformed_manifest_alone_never_raises_and_returns_no_match(tmp_path):
    bad_repo = tmp_path / "bad-repo"
    bad_repo.mkdir()
    (bad_repo / "knowledge-manifest.json").write_text("{ not valid json", encoding="utf-8")
    r = resolve_extension("sd", knowledge_repos=[str(bad_repo)])
    assert r.matched is False
    assert r.action == ACTION_NO_EXTENSION


def test_non_object_manifest_is_skipped_silently(tmp_path):
    weird_repo = tmp_path / "weird-repo"
    weird_repo.mkdir()
    (weird_repo / "knowledge-manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
    r = resolve_extension("sd", knowledge_repos=[str(weird_repo), ORG_REPO])
    assert r.source_repo == ORG_REPO


def test_entry_with_missing_file_on_disk_is_skipped(tmp_path):
    _write_manifest(
        tmp_path,
        agent="qa",
        ext_type="override",
        file_rel=".claude/extensions/does-not-exist.md",
    )
    r = resolve_extension("qa", knowledge_repos=[str(tmp_path)])
    assert r.matched is False


def test_entry_with_unknown_type_is_skipped(tmp_path):
    _write_manifest(tmp_path, agent="qa", ext_type="bogus-type")
    r = resolve_extension("qa", knowledge_repos=[str(tmp_path)])
    assert r.matched is False


def test_empty_knowledge_repos_list_returns_no_match():
    r = resolve_extension("sd", knowledge_repos=[])
    assert r.matched is False
    assert r.action == ACTION_NO_EXTENSION


def test_prepare_source_bindings_verifies_protected_ladder_once(
    monkeypatch, tmp_path
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    calls = 0

    monkeypatch.setattr(
        knowledge_skill_source,
        "knowledge_repository_requires_authenticated_source",
        lambda _repo: True,
    )

    def resolve_sources():
        nonlocal calls
        calls += 1
        return [
            (first, SimpleNamespace(repository_root=first)),
            (second, SimpleNamespace(repository_root=second)),
        ]

    monkeypatch.setattr(
        knowledge_skill_source, "resolve_knowledge_skill_sources", resolve_sources
    )

    bindings = extensions_resolver.prepare_extension_source_bindings(
        [str(first), str(second)]
    )

    assert calls == 1
    assert bindings[str(first.absolute())][0] is True
    assert bindings[str(first.absolute())][1].repository_root == first
    assert bindings[str(second.absolute())][0] is True
    assert bindings[str(second.absolute())][1].repository_root == second


def test_prepare_source_bindings_fails_closed_for_entire_protected_batch(
    monkeypatch, tmp_path
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.setattr(
        knowledge_skill_source,
        "knowledge_repository_requires_authenticated_source",
        lambda _repo: True,
    )

    def unavailable_sources():
        raise RuntimeError("signed ladder unavailable")

    monkeypatch.setattr(
        knowledge_skill_source,
        "resolve_knowledge_skill_sources",
        unavailable_sources,
    )

    bindings = extensions_resolver.prepare_extension_source_bindings(
        [str(first), str(second)]
    )

    assert bindings == {
        str(first.absolute()): (True, None),
        str(second.absolute()): (True, None),
    }


def test_resolve_extension_prepares_one_batch_for_multiple_repositories(monkeypatch):
    calls = 0

    def prepare(repos):
        nonlocal calls
        calls += 1
        return {str(Path(repo).absolute()): (False, None) for repo in repos}

    monkeypatch.setattr(
        extensions_resolver, "prepare_extension_source_bindings", prepare
    )

    result = resolve_extension(
        "cw",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        missing_skills_checker=_no_missing,
    )

    assert calls == 1
    assert result.source_repo == PERSONAL_REPO


def test_resolve_extension_uses_caller_batch_without_reverification(monkeypatch):
    def unexpected_prepare(_repos):
        raise AssertionError("caller-scoped bindings must be reused")

    monkeypatch.setattr(
        extensions_resolver,
        "prepare_extension_source_bindings",
        unexpected_prepare,
    )
    bindings = {
        str(Path(PERSONAL_REPO).absolute()): (False, None),
        str(Path(ORG_REPO).absolute()): (False, None),
    }

    result = resolve_extension(
        "cw",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        missing_skills_checker=_no_missing,
        source_bindings=bindings,
    )

    assert result.source_repo == PERSONAL_REPO


def test_shared_skill_bindings_discover_required_skills_once(monkeypatch, tmp_path):
    calls = 0
    skills = [
        SkillMeta(
            name=name,
            description="test skill",
            path=tmp_path / name / "SKILL.md",
        )
        for name in ("moments-mapping", "cocreate-sprint", "accessibility")
    ]

    monkeypatch.setattr(
        "cc.core.skill_store.default_skill_paths", lambda **_kwargs: []
    )

    def discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return skills

    monkeypatch.setattr("cc.core.skill_store.discover_skills_with_sources", discover)
    source_bindings = {
        str(Path(PERSONAL_REPO).absolute()): (False, None),
        str(Path(ORG_REPO).absolute()): (False, None),
    }
    skill_bindings = ExtensionSkillBindings(
        (PERSONAL_REPO, ORG_REPO), source_bindings
    )

    sd = resolve_extension(
        "sd",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        source_bindings=source_bindings,
        skill_bindings=skill_bindings,
    )
    uxd = resolve_extension(
        "uxd",
        knowledge_repos=[PERSONAL_REPO, ORG_REPO],
        source_bindings=source_bindings,
        skill_bindings=skill_bindings,
    )

    assert sd.action == ACTION_APPLY
    assert uxd.action == ACTION_APPLY
    assert calls == 1


def test_skill_binding_receipt_failure_marks_authenticated_skill_missing(
    monkeypatch, tmp_path
):
    source = object()
    skill = SkillMeta(
        name="secure-skill",
        description="test skill",
        path=tmp_path / "secure-skill" / "SKILL.md",
        _knowledge_source=source,
    )
    bindings = ExtensionSkillBindings((), {})
    bindings._skills = [skill]

    def unavailable_receipt(*_args, **_kwargs):
        raise RuntimeError("entitlement changed")

    monkeypatch.setattr(
        "cc.core.skill_store.get_skill_content_with_receipt_from_verified_batch",
        unavailable_receipt,
    )

    missing, receipts = bindings.evaluate(["secure-skill"])

    assert missing == ["secure-skill"]
    assert receipts == ()


def test_resolve_extension_missing_caller_binding_fails_closed(monkeypatch):
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("missing batch keys must not trigger live lookup")

    monkeypatch.setattr(
        knowledge_skill_source,
        "knowledge_repository_requires_authenticated_source",
        unexpected_lookup,
    )
    monkeypatch.setattr(
        knowledge_skill_source,
        "resolve_knowledge_skill_sources",
        unexpected_lookup,
    )

    result = resolve_extension(
        "cw",
        knowledge_repos=[PERSONAL_REPO],
        missing_skills_checker=_no_missing,
        source_bindings={},
    )

    assert result.matched is False
    assert result.action == ACTION_NO_EXTENSION


# ---------------------------------------------------------------------------
# compose_agent_content: the honest, defined "extension" limit
# ---------------------------------------------------------------------------


def test_compose_override_is_pure_substitution():
    r = resolve_extension("sd", knowledge_repos=[ORG_REPO], missing_skills_checker=_no_missing)
    composed = compose_agent_content(r, base_agent_content="# base sd agent\n")
    extension_text = Path(r.file).read_text(encoding="utf-8")
    assert composed == extension_text
    assert "base sd agent" not in composed


def test_compose_extension_appends_and_labels_it_explicitly():
    r = resolve_extension("cw", knowledge_repos=[ORG_REPO], missing_skills_checker=_no_missing)
    base = "# base cw agent\nBase instructions.\n"
    composed = compose_agent_content(r, base_agent_content=base)
    extension_text = Path(r.file).read_text(encoding="utf-8")

    assert composed.startswith(base)
    assert extension_text in composed
    # Must be honest about what happened -- never claim "merged".
    assert "APPENDED" in composed
    assert "NOT section-merged" in composed


def test_compose_no_match_leaves_base_untouched():
    r = resolve_extension("ta", knowledge_repos=[ORG_REPO])
    base = "# base ta agent\n"
    assert compose_agent_content(r, base_agent_content=base) == base


def test_compose_fallback_leaves_base_untouched():
    r = resolve_extension("uxd", knowledge_repos=[ORG_REPO], missing_skills_checker=_all_missing)
    base = "# base uxd agent\n"
    assert compose_agent_content(r, base_agent_content=base) == base


def test_compose_skills_type_leaves_base_untouched(tmp_path):
    _write_manifest(tmp_path, agent="qa", ext_type="skills")
    r = resolve_extension("qa", knowledge_repos=[str(tmp_path)], missing_skills_checker=_no_missing)
    base = "# base qa agent\n"
    assert compose_agent_content(r, base_agent_content=base) == base


# ---------------------------------------------------------------------------
# CLI wiring: cc extensions resolve
# ---------------------------------------------------------------------------


def test_cli_resolve_agent_json(monkeypatch):
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos",
        lambda *a, **k: [ORG_REPO],
    )
    result = runner.invoke(app, ["extensions", "resolve", "--agent", "sd", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["agent"] == "sd"
    assert payload["type"] == "override"
    assert payload["source_repo"] == ORG_REPO


def test_cli_resolve_no_match_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos",
        lambda *a, **k: [ORG_REPO],
    )
    result = runner.invoke(app, ["extensions", "resolve", "--agent", "ta", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["matched"] is False


def test_cli_resolve_requires_agent_or_all():
    result = runner.invoke(app, ["extensions", "resolve"])
    assert result.exit_code == 2


def test_cli_resolve_fail_fallback_exits_nonzero(monkeypatch, tmp_path):
    _write_manifest(
        tmp_path, agent="qa", ext_type="override",
        required_skills=["nonexistent-skill"], fallback="fail",
    )
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos",
        lambda *a, **k: [str(tmp_path)],
    )
    result = runner.invoke(app, ["extensions", "resolve", "--agent", "qa", "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["action"] == ACTION_FALLBACK_FAIL


# ---------------------------------------------------------------------------
# Schema drift (Gap 1's other defect): the enum must accept the real roster
# ---------------------------------------------------------------------------


def test_schema_accepts_real_org_manifest_including_ind():
    jsonschema = pytest.importorskip("jsonschema")

    repo_root = Path(__file__).resolve().parents[3]
    schema_path = repo_root / "docs" / "schemas" / "knowledge-manifest-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    manifest = json.loads((FIXTURES / "org-repo" / "knowledge-manifest.json").read_text(encoding="utf-8"))
    agent_enum = schema["properties"]["extensions"]["items"]["properties"]["agent"]["enum"]
    assert "ind" in agent_enum  # the real manifest's extension the old enum rejected

    for entry in manifest["extensions"]:
        jsonschema.validate(instance=entry, schema=schema["properties"]["extensions"]["items"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(
    repo_dir: Path,
    *,
    agent: str,
    ext_type: str = "extension",
    required_skills=None,
    fallback=None,
    file_rel: str | None = None,
) -> None:
    ext_dir = repo_dir / ".claude" / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    rel = file_rel or f".claude/extensions/{agent}.{ext_type if ext_type in ('override', 'skills') else 'extension'}.md"
    if file_rel is None:
        (repo_dir / rel).write_text(f"# {agent} synthetic extension\n", encoding="utf-8")

    entry: dict = {"agent": agent, "type": ext_type, "file": rel}
    if required_skills is not None:
        entry["requiredSkills"] = required_skills
    if fallback is not None:
        entry["fallbackBehavior"] = fallback

    manifest = {
        "version": "1.0",
        "name": "synthetic-test-repo",
        "extensions": [entry],
    }
    (repo_dir / "knowledge-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
