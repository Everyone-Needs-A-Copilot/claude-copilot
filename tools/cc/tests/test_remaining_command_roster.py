"""All declared commands participate in missing-file discovery and recovery."""
from pathlib import Path
from cc.core.ecosystem.project_integration import _missing_action_targets, _existing_component_paths
from cc.core.ecosystem.reconciliation_recipes import _validate_relative_target
from cc.core.ecosystem.reconciliation_diagnostics import _allowed_target


def test_declared_future_command_is_visible_to_all_consumers(tmp_path):
    for command in ('reflect', 'a-future-command'):
        relative = f'.claude/commands/{command}.md'
        source = tmp_path / 'reference.md'
        source.write_text('Declared command\n')
        (tmp_path / '.claude/commands').mkdir(parents=True, exist_ok=True)
        assert relative in _missing_action_targets(tmp_path, 'claude', {relative: source})
        assert _allowed_target(relative)
        _validate_relative_target("claude", relative)
        existing, readable = _existing_component_paths(tmp_path, 'claude')
        assert readable and '.claude/commands' in existing
        (tmp_path / relative).write_text('Installed command\n')
        assert relative not in _missing_action_targets(tmp_path, 'claude', {relative: source})


def test_shell_validator_uses_authoritative_reader():
    script = Path(__file__).resolve().parents[3] / 'scripts/install/validate-installation.sh'
    body = script.read_text()
    assert body.count('from cc.core.ecosystem.canonical_transaction import claude_reference_roster') == 2
    assert '"protocol.md"' not in body
    assert '"me.md"' not in body


def test_workspace_finish_installs_only_missing_reflect(tmp_path):
    from .test_workspaces_contract import _git_init, _repo_roots
    from cc.core.ecosystem.workspaces import activate_components, workspace_status, finish_project_integration
    import hashlib
    project = tmp_path / 'consumer'
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(project, ('claude', 'codex'), claude_root=claude_root, codex_root=codex_root)
    missing = project / '.claude/commands/reflect.md'
    expected = missing.read_bytes()
    missing.unlink()
    preserved = {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in project.rglob('*') if p.is_file() and '.git' not in p.parts}
    assert not (project / 'copilot.lock.json').exists()
    before = workspace_status(project, personal_registry=tmp_path / 'personal.json', claude_root=claude_root, codex_root=codex_root)
    assert before['classification'] == 'safe-finish'
    # Claude repairs reflect while the complete, unlocked Codex install is adopted.
    assert before['safe_action']['kind'] == 'composite'
    finish_project_integration(project, before['safe_action']['id'], claude_root=claude_root, codex_root=codex_root)
    assert missing.read_bytes() == expected
    assert (project / 'copilot.lock.json').is_file()
    for name, sha in preserved.items():
        assert hashlib.sha256((project / name).read_bytes()).hexdigest() == sha
    after = workspace_status(project, personal_registry=tmp_path / 'personal.json', claude_root=claude_root, codex_root=codex_root)
    assert after['classification'] == 'ready'
