"""Discoverable disposable canonical setup and shared verification boundary."""
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_entry_guide_names_existing_operations_and_explicit_limits():
    guide = (ROOT / 'docs/30-operations/16-foundation-entrypoint.md').read_text()
    for term in ('/setup-project', '/protocol', 'cc project init', 'cc doctor', 'is retired',
                 'cc verify plan', 'cc verify run', 'cc verify status', 'tc',
                 'partial profile is retired', 'does **not** invent', 'source-bound QA'):
        assert term in guide


def test_shared_verification_on_a_project_authored_manifest(tmp_path):
    """Old expectation: the test first ran the plan/apply/verify copy transaction (`cc reconcile`),
    asserted the framework files, shared verification policy and agents were copied into the project,
    then ran `cc verify`. New expectation: nothing is copied into a project (central resolution), so
    the setup half is gone and `cc verify` runs against a plain project with its own authored check."""
    project = tmp_path / 'projects' / 'fixture'
    project.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q'], cwd=project, check=True)
    owner = project / 'owner.txt'
    owner.write_text('project-owned content\n')
    (project / 'CLAUDE.md').write_text('# project\n')
    (project / 'AGENTS.md').write_text('# project\n')

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
