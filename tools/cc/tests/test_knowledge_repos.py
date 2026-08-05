"""Tests for layered knowledge repos: paths.knowledge_repo as an ordered list.

Covers the normalizer (resolve_knowledge_repos), env var comma-split,
`cc config add`/`remove` idempotency, `cc config set` comma parsing, and
`cc env` comma-joined output + first-element back-compat alias.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cc.commands.env import _is_personal_knowledge_path
from cc.core.config import (
    add_to_list_config,
    get_resolved_config,
    personal_roots_from_config,
    remove_from_list_config,
    resolve_key,
    resolve_knowledge_repos,
)
from cc.main import app

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# resolve_knowledge_repos: normalizer for all three shapes
# ---------------------------------------------------------------------------


def test_normalize_string_value_is_one_element_list():
    assert resolve_knowledge_repos("/shared/knowledge") == ["/shared/knowledge"]


def test_normalize_list_value_preserves_order():
    assert resolve_knowledge_repos(["/shared", "/personal"]) == ["/shared", "/personal"]


def test_normalize_none_is_empty_list():
    assert resolve_knowledge_repos(None) == []


def test_normalize_empty_string_is_empty_list():
    assert resolve_knowledge_repos("") == []


def test_normalize_list_drops_falsy_entries():
    assert resolve_knowledge_repos(["/shared", "", None]) == ["/shared"]


def test_normalize_uses_resolve_key_when_no_arg(monkeypatch):
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key, **_: ["/a", "/b"] if key == "paths.knowledge_repo" else None,
    )
    assert resolve_knowledge_repos() == ["/a", "/b"]


# ---------------------------------------------------------------------------
# Env override: comma-separated string -> ordered list
# ---------------------------------------------------------------------------


def test_env_override_comma_separated_becomes_list(monkeypatch):
    monkeypatch.setenv("CC_PATHS_KNOWLEDGE_REPO", "/shared/kc, /personal/kc")
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["paths.knowledge_repo"] == ["/shared/kc", "/personal/kc"]


def test_env_override_single_value_still_one_element_list(monkeypatch):
    monkeypatch.setenv("CC_PATHS_KNOWLEDGE_REPO", "/only/one")
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["paths.knowledge_repo"] == ["/only/one"]


def test_resolve_key_env_override_comma_separated(monkeypatch):
    monkeypatch.setenv("CC_PATHS_KNOWLEDGE_REPO", "/a,/b,/c")
    value = resolve_key("paths.knowledge_repo", _machine={}, _project={})
    assert value == ["/a", "/b", "/c"]


def test_env_override_drops_empty_segments(monkeypatch):
    monkeypatch.setenv("CC_PATHS_KNOWLEDGE_REPO", "/a,,/b, ,")
    value = resolve_key("paths.knowledge_repo", _machine={}, _project={})
    assert value == ["/a", "/b"]


# ---------------------------------------------------------------------------
# Layer precedence unchanged: highest-precedence source provides the WHOLE list
# ---------------------------------------------------------------------------


def test_project_list_wins_over_machine_string():
    """Project sets its own list; machine's string is NOT concatenated in."""
    cfg = get_resolved_config(
        _machine={"paths": {"knowledge_repo": "/machine/kc"}},
        _project={"paths": {"knowledge_repo": ["/proj/a", "/proj/b"]}},
    )
    assert cfg["paths.knowledge_repo"] == ["/proj/a", "/proj/b"]


def test_machine_list_used_when_project_absent():
    cfg = get_resolved_config(
        _machine={"paths": {"knowledge_repo": ["/machine/a", "/machine/b"]}},
        _project={},
    )
    assert cfg["paths.knowledge_repo"] == ["/machine/a", "/machine/b"]


# ---------------------------------------------------------------------------
# cc config add: idempotent append (core function)
# ---------------------------------------------------------------------------


def test_config_add_creates_list_from_unset(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    add_to_list_config("paths.knowledge_repo", "/shared/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc"]


def test_config_add_appends_to_existing_list(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"knowledge_repo": ["/shared/kc"]}}))
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    add_to_list_config("paths.knowledge_repo", "/personal/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc", "/personal/kc"]


def test_config_add_upgrades_legacy_string_to_list(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"knowledge_repo": "/shared/kc"}}))
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    add_to_list_config("paths.knowledge_repo", "/personal/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc", "/personal/kc"]


def test_config_add_is_idempotent(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"knowledge_repo": ["/shared/kc"]}}))
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    add_to_list_config("paths.knowledge_repo", "/shared/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc"]


# ---------------------------------------------------------------------------
# cc config add / remove: CLI commands
# ---------------------------------------------------------------------------


def test_config_add_cli_command(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "add", "paths.knowledge_repo", "/shared/kc")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc"]

    # Second add of the same value is a no-op (idempotent)
    invoke("config", "add", "paths.knowledge_repo", "/shared/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc"]


def test_config_add_project_scope(monkeypatch, tmp_path):
    cfg_file = tmp_path / "project_config.json"
    monkeypatch.setattr("cc.core.config_paths.project_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.project_config_path", lambda: cfg_file)

    result = invoke("config", "add", "paths.knowledge_repo", "/proj/kc", "--project")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/proj/kc"]


def test_config_remove_deletes_value(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"paths": {"knowledge_repo": ["/shared/kc", "/personal/kc"]}})
    )
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    remove_from_list_config("paths.knowledge_repo", "/shared/kc")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/personal/kc"]


def test_config_remove_is_noop_when_absent(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"knowledge_repo": ["/shared/kc"]}}))
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    remove_from_list_config("paths.knowledge_repo", "/not/there")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc"]


def test_config_remove_cli_command(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"paths": {"knowledge_repo": ["/shared/kc", "/personal/kc"]}})
    )
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "remove", "paths.knowledge_repo", "/shared/kc")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/personal/kc"]


# ---------------------------------------------------------------------------
# cc config set: comma-separated value becomes a list for this key only
# ---------------------------------------------------------------------------


def test_config_set_comma_separated_parses_to_list(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "set", "paths.knowledge_repo", "/shared/kc,/personal/kc")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == ["/shared/kc", "/personal/kc"]


def test_config_set_single_value_stays_a_string(monkeypatch, tmp_path):
    """Back-compat: a single value (no comma) is stored as a plain string."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "set", "paths.knowledge_repo", "/shared/kc")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["knowledge_repo"] == "/shared/kc"


def test_config_set_other_keys_unaffected_by_comma_splitting(monkeypatch, tmp_path):
    """Comma-parsing is scoped to LIST_VALUED_KEYS; other keys keep commas literal."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "set", "docs.source_order", "local,fetch")
    assert result.exit_code == 0
    data = json.loads(cfg_file.read_text())
    assert data["docs"]["source_order"] == "local,fetch"


# ---------------------------------------------------------------------------
# cc env: comma-joined list + first-element back-compat alias
# ---------------------------------------------------------------------------


def test_env_emits_comma_joined_list_for_knowledge_repo(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.knowledge_repo": ["/shared/kc", "/personal/kc"]},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert 'export CC_PATHS_KNOWLEDGE_REPO="/shared/kc,/personal/kc"' in result.output


def test_env_knowledge_repo_alias_is_first_element_only(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.knowledge_repo": ["/shared/kc", "/personal/kc"]},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert 'export CC_KNOWLEDGE_REPO="/shared/kc"' in result.output
    # Full ordered list still available under the long-form key
    assert 'export CC_PATHS_KNOWLEDGE_REPO="/shared/kc,/personal/kc"' in result.output


def test_env_knowledge_repo_alias_still_works_for_single_string(monkeypatch):
    """Back-compat: unchanged behavior when value is still a plain string."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.knowledge_repo": "/only/one"},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert 'export CC_KNOWLEDGE_REPO="/only/one"' in result.output


def test_env_empty_list_is_skipped(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.knowledge_repo": []},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "CC_PATHS_KNOWLEDGE_REPO" not in result.output
    assert "CC_KNOWLEDGE_REPO" not in result.output


# ---------------------------------------------------------------------------
# _is_personal_knowledge_path(): the <product>-copilot-private convention
# ---------------------------------------------------------------------------


def test_is_personal_knowledge_path_matches_ancestor_segment():
    assert _is_personal_knowledge_path(
        "/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"
    )


def test_is_personal_knowledge_path_matches_leaf_segment():
    assert _is_personal_knowledge_path("/Volumes/Dev/Sites/COPILOT/codex-copilot-private")


def test_is_personal_knowledge_path_false_for_org_repo():
    assert not _is_personal_knowledge_path(
        "/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal"
    )


def test_is_personal_knowledge_path_false_for_org_private_naming():
    """`<org>-org-private` is a DIFFERENT (org-tier) naming convention --
    must not false-positive as personal."""
    assert not _is_personal_knowledge_path("/Volumes/Dev/Sites/COPILOT/enac-org-private")


# ---------------------------------------------------------------------------
# WP-372 P3.1: CC_KNOWLEDGE_REPOS (full list) + CC_PERSONAL_KNOWLEDGE_REPO
# (personal entry, if any) -- CC_KNOWLEDGE_REPO stays first-element only.
# ---------------------------------------------------------------------------


def test_env_emits_full_ordered_list_under_short_form_knowledge_repos(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": [
                "/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal",
                "/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge",
            ]
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert (
        'export CC_KNOWLEDGE_REPOS='
        '"/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal,'
        '/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"' in result.output
    )
    # CC_KNOWLEDGE_REPO is UNCHANGED -- still first-element only.
    assert (
        'export CC_KNOWLEDGE_REPO="/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal"'
        in result.output
    )


def test_env_emits_personal_knowledge_repo_when_a_private_entry_is_present(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": [
                "/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal",
                "/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge",
            ]
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert (
        'export CC_PERSONAL_KNOWLEDGE_REPO='
        '"/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"' in result.output
    )


def test_env_personal_knowledge_repo_absent_when_no_private_entry_matches(monkeypatch):
    """Honest omission -- never a fabricated guess when nothing in the
    ordered list matches the `<product>-copilot-private` naming
    convention."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": [
                "/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal",
            ]
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "CC_PERSONAL_KNOWLEDGE_REPO" not in result.output


def test_env_knowledge_repos_and_personal_repo_absent_when_key_unset(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "CC_KNOWLEDGE_REPOS" not in result.output
    assert "CC_PERSONAL_KNOWLEDGE_REPO" not in result.output


def test_env_personal_knowledge_repo_works_for_single_string_value(monkeypatch):
    """Back-compat shape: a plain (non-list) personal-only knowledge_repo
    string still resolves to a personal entry."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": "/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert (
        'export CC_PERSONAL_KNOWLEDGE_REPO='
        '"/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"' in result.output
    )
    assert (
        'export CC_KNOWLEDGE_REPOS='
        '"/Volumes/Dev/Sites/COPILOT/claude-copilot-private/knowledge"' in result.output
    )


# ---------------------------------------------------------------------------
# personal_roots_from_config() -- WP-372 P0.3 production feeder for
# guard_personal()'s personal_roots
# ---------------------------------------------------------------------------


def test_personal_roots_includes_every_knowledge_repo_entry(monkeypatch):
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos",
        lambda: ["/shared/kc", "/personal/kc"],
    )
    monkeypatch.setattr("cc.core.config.resolve_key", lambda key, **_: None)

    assert personal_roots_from_config() == ["/shared/kc", "/personal/kc"]


def test_personal_roots_includes_every_projects_root_entry(monkeypatch):
    monkeypatch.setattr("cc.core.config.resolve_knowledge_repos", lambda: [])
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key, **_: ["/Users/example/projects", "/Volumes/Dev/Sites"]
        if key == "projects.roots"
        else None,
    )

    assert personal_roots_from_config() == [
        "/Users/example/projects",
        "/Volumes/Dev/Sites",
    ]


def test_personal_roots_concatenates_knowledge_repos_and_projects_roots(monkeypatch):
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos",
        lambda: ["/shared/kc"],
    )
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key, **_: ["/Volumes/Dev/Sites"] if key == "projects.roots" else None,
    )

    assert personal_roots_from_config() == ["/shared/kc", "/Volumes/Dev/Sites"]


def test_personal_roots_projects_roots_legacy_string_becomes_one_element(monkeypatch):
    monkeypatch.setattr("cc.core.config.resolve_knowledge_repos", lambda: [])
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key, **_: "/Volumes/Dev/Sites" if key == "projects.roots" else None,
    )

    assert personal_roots_from_config() == ["/Volumes/Dev/Sites"]


def test_personal_roots_empty_when_nothing_configured(monkeypatch):
    monkeypatch.setattr("cc.core.config.resolve_knowledge_repos", lambda: [])
    monkeypatch.setattr("cc.core.config.resolve_key", lambda key, **_: None)

    assert personal_roots_from_config() == []
