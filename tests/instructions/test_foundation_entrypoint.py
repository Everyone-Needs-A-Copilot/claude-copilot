"""Discoverable disposable canonical setup and shared verification boundary."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_entry_guide_names_existing_operations_and_explicit_limits():
    guide = (ROOT / 'docs/30-operations/16-foundation-entrypoint.md').read_text()
    for term in ('/setup-project', '/protocol', 'cc reconcile plan', 'cc reconcile verify',
                 'cc verify plan', 'cc verify run', 'cc verify status', 'tc',
                 'partial profile is retired', 'does **not** invent', 'source-bound QA'):
        assert term in guide


def test_canonical_consumer_setup_then_shared_verification(tmp_path, monkeypatch):
    # Reuse existing safe source/assessment fixtures; production transaction is real.
    spec = importlib.util.spec_from_file_location(
        'entrypoint_canonical_fixture', ROOT / 'tools/cc/tests/test_canonical_project_transaction.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    claude, codex, _ = fixture._reference_sources(tmp_path)
    native = Path(os.environ.get('CODEX_COPILOT_TEST_ROOT', ROOT.parent / 'codex-copilot'))
    if not (native / 'plugins/codex-copilot/skills/specialist-agents/references/verification-policy.md').is_file():
        pytest.skip('current native Codex source unavailable; set CODEX_COPILOT_TEST_ROOT explicitly')
    # Stage actual reviewed adapters in disposable public-source roots. This does
    # not use Claude's vendored plugin or claim a signed/global installation.
    for directory in ('.claude/agents', '.claude/commands'):
        shutil.copytree(ROOT / directory, claude / directory, dirs_exist_ok=True)
    for relative in ('VERSION.json', '.claude/fitness-check.sh', '.claude/hooks/copilot-hook.sh'):
        shutil.copy2(ROOT / relative, claude / relative)
    shutil.copytree(native / 'plugins/codex-copilot', codex / 'plugins/codex-copilot', dirs_exist_ok=True)
    shutil.copy2(native / 'scripts/copilot-gate.sh', codex / 'scripts/copilot-gate.sh')
    fixture._configure_sources(monkeypatch, claude, codex)
    # No optional signed-layer manifest in this local native-source fixture;
    # otherwise a developer's configured mirror can override the staged source.
    monkeypatch.setattr(fixture.codex_plugin_source, 'resolve_key', lambda _key: None)
    authority = tmp_path / 'projects'
    project = fixture._git_project(authority)
    owner = project / 'owner.txt'
    owner.write_text('project-owned content\n')
    subprocess.run(['git', 'add', 'owner.txt'], cwd=project, check=True)
    subprocess.run(['git', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture owner'],
                   cwd=project, check=True)
    request = fixture.build_canonical_project_request(project, approved_roots=(authority,))
    state = tmp_path / 'state'
    options = dict(machine_builder=lambda: fixture._machine(authority.resolve()),
                   census_builder=fixture._census(project, authority.resolve()))
    plan = fixture.build_plan_report(request, **options,
                                    plan_issuer=lambda **kw: fixture.issue_plan(**kw, root=state))
    assert plan['result'] == 'action-required'
    assert fixture.build_apply_report(request, plan['plan_id'], **options,
                                      state_root=state)['result'] == 'applied'
    assert fixture.build_verify_report(request, **options)['result'] == 'ready'
    assert owner.read_text() == 'project-owned content\n'
    for relative in ('CLAUDE.md', 'AGENTS.md', '.claude/hooks/copilot-hook.sh',
                     'plugins/codex-copilot/.codex-plugin/plugin.json', 'scripts/copilot-gate.sh'):
        assert (project / relative).is_file(), relative
    for role in ('me', 'qa'):
        assert (project / f'.claude/agents/{role}.md').read_bytes() == (ROOT / f'.claude/agents/{role}.md').read_bytes()
    policy = 'plugins/codex-copilot/skills/specialist-agents/references/verification-policy.md'
    assert (project / policy).read_bytes() == (native / policy).read_bytes()
    assert '### Fixed finish line' in (project / policy).read_text()

    # Project-authored check and manifest, never an installer-generated fake test.
    (project / 'check.py').write_text(
        'from pathlib import Path\n'
        'assert Path("owner.txt").read_text() == "project-owned content\\n"\n'
        'assert Path("CLAUDE.md").is_file() and Path("AGENTS.md").is_file()\n')
    manifest = {'schemaVersion': 1, 'inputs': ['owner.txt', 'check.py', 'CLAUDE.md', 'AGENTS.md'],
                'fallbackLanes': ['entry'], 'lanes': [{'id': 'entry', 'description': 'Owned entry check',
                'paths': ['owner.txt'], 'argv': ['{python}', 'check.py'], 'cwd': '.',
                'timeoutSeconds': 5, 'hermetic': False}]}
    (project / 'verification.json').write_text(json.dumps(manifest))

    def cc(*args):
        result = subprocess.run([sys.executable, '-m', 'cc.main', 'verify', *args, '--root', str(project), '--json'],
                                cwd=project, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    selected = cc('plan', '--changed', 'owner.txt', '--task', 'fixture-68')
    plan_path = tmp_path / 'verify-plan.json'
    plan_path.write_text(json.dumps(selected))
    run = cc('run', '--plan', str(plan_path))
    assert run['status'] == 'passed'
    assert run['approval'] == 'none; tc alone grants task approval'
    assert cc('status', '--run', run['runId'])['status'] == 'passed'
    overview = subprocess.run([sys.executable, '-m', 'cc.main', 'status', '--project', str(project), '--json'],
                              cwd=project, capture_output=True, text=True, timeout=15)
    assert overview.returncode == 0, overview.stdout + overview.stderr
    observed = json.loads(overview.stdout)
    assert observed['readOnly'] is True
    assert observed['verification']['run']['id'] == run['runId']
    assert all(r['running'] == 'unknown' for r in observed['foundation']['runtimes'])
    assert not (project / '.copilot/tasks.db').exists()  # Runner never creates task authority.
