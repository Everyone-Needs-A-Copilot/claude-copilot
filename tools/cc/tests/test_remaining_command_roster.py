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


def test_roundtrip_uses_declared_roster_and_detects_membership_errors(tmp_path):
    import json
    from cc.core.conformance import roundtrip as rt
    from cc.core.conformance.types import Verdict

    source = tmp_path / 'source'
    source.mkdir()
    declaration = {'components': {'commands': {'projectCommands': ['reflect.md']},
                                  'agents': {'frameworkAgents': ['me']}}}
    manifest = source / 'VERSION.json'
    manifest.write_text(json.dumps(declaration))
    project = tmp_path / 'consumer'
    commands = project / '.claude/commands'
    commands.mkdir(parents=True)
    (commands / 'reflect.md').write_text('reflect')

    def verdict():
        return rt.check_closes_command_gap(
            project=project, subject='roster', framework_repo_root=source
        ).verdict

    assert verdict() is Verdict.PASS
    # Mutate the declaration after the first call: no import-time snapshot.
    declaration['components']['commands']['projectCommands'].append('future-command.md')
    manifest.write_text(json.dumps(declaration))
    assert verdict() is Verdict.FAIL  # required file absent
    (commands / 'future-command.md').write_text('new command')
    assert verdict() is Verdict.PASS
    (commands / 'extra.md').write_text('not declared')
    assert verdict() is Verdict.FAIL  # extra file
    (commands / 'reflect.md').unlink()
    assert verdict() is Verdict.FAIL  # right count, wrong membership


def test_roundtrip_source_reference_detects_equal_count_codex_substitution(tmp_path):
    import json
    import shutil
    from cc.core.conformance import roundtrip as rt
    from cc.core.conformance.types import Verdict

    source = tmp_path / 'source'
    plugin = source / 'plugins/codex-copilot'
    (plugin / '.codex-plugin').mkdir(parents=True)
    (plugin / '.codex-plugin/plugin.json').write_text('{"name":"codex-copilot"}')
    (plugin / 'hook.sh').write_text('echo hook')
    (source / 'VERSION.json').write_text(json.dumps({'components': {
        'commands': {'projectCommands': ['reflect.md']},
        'agents': {'frameworkAgents': ['me']}}}))
    historical = rt.load_reference_manifest(
        Path(__file__).parent / 'conformance/fixtures/reference-install/manifest.json'
    )
    reference = rt.reference_for_sources(historical, claude_source=source, codex_source=source)
    assert historical['claude']['commands']['names'] != ['reflect']
    assert reference['claude']['commands']['names'] == ['reflect']
    project = tmp_path / 'consumer'
    installed = project / 'plugins/codex-copilot'
    shutil.copytree(plugin, installed)
    bridge = project / '.claude/skills/codex-copilot'
    bridge.parent.mkdir(parents=True)
    bridge.symlink_to('../../plugins/codex-copilot/skills')

    def verdict():
        return next(r.verdict for r in rt.check_produces_reference_install(
            project=project, reference=reference, subject_prefix='install'
        ) if r.subject.endswith('::codex'))

    assert verdict() is Verdict.PASS
    (installed / 'hook.sh').rename(installed / 'wrong.sh')
    assert verdict() is Verdict.FAIL
