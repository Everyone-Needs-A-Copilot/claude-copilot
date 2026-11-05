"""Tests for .claude/hooks/coordinator-guard.sh (Coordinator rule, 2026-11-05)."""
import json, os, subprocess
from pathlib import Path
import pytest

GUARD = Path(__file__).resolve().parents[2] / '.claude/hooks/coordinator-guard.sh'


@pytest.fixture
def run(tmp_path):
    cfg = tmp_path / 'cfg'
    (cfg / 'projects/p/memory').mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != 'COPILOT_COORDINATOR'}
    env.update(CLAUDE_CONFIG_DIR=str(cfg), COPILOT_COORDINATOR_LOG=str(tmp_path / 'off.log'))

    def invoke(tool, tool_input, agent=False, **over):
        payload = {'session_id': 's', 'tool_name': tool, 'tool_input': tool_input}
        if agent:
            payload.update(agent_id='abc', agent_type='general-purpose')
        r = subprocess.run([str(GUARD)], input=json.dumps(payload), text=True,
                           capture_output=True, env={**env, **over}, timeout=30)
        return r
    invoke.cfg, invoke.log = cfg, tmp_path / 'off.log'
    return invoke


def bash(run, cmd, **kw):
    return run('Bash', {'command': cmd}, **kw).returncode


def test_main_edit_write_read_blocked(run):
    for tool, ti in [('Edit', {'file_path': '/Volumes/x/a.py'}), ('Write', {'file_path': '/tmp/a'}),
                     ('NotebookEdit', {'notebook_path': '/x.ipynb'}), ('Read', {'file_path': '/x/a'}),
                     ('Grep', {'pattern': 'a', 'path': '/x'}), ('Glob', {'pattern': '*', 'path': '/x'})]:
        r = run(tool, ti)
        assert r.returncode == 2, tool
        assert 'Coordinator rule' in r.stderr and 'Agent tool' in r.stderr


def test_memory_plans_scratchpad_allowed(run):
    mem = run.cfg / 'projects/p/memory/n.md'
    assert run('Write', {'file_path': str(mem)}).returncode == 0
    assert run('Read', {'file_path': str(mem)}).returncode == 0
    assert run('Read', {'file_path': str(run.cfg / 'plans/x.md')}).returncode == 0
    assert run('Write', {'file_path': '/private/tmp/claude-501/-P/sess/scratchpad/n.txt'}).returncode == 0
    # agent task output and traversal are not allowed
    assert run('Read', {'file_path': '/private/tmp/claude-501/-P/sess/tasks/a.output'}).returncode == 2
    assert run('Read', {'file_path': str(run.cfg / 'projects/p/memory/../secret')}).returncode == 2


def test_bash_allowlist(run):
    for ok in ['tc task list --json', 'cc status', 'cc skill get x --scope machine --json', 'git status --short',
               'git -C /a/b log --oneline -5', 'git branch --show-current', 'git worktree list', 'git rev-parse HEAD',
               'pwd', 'date', 'readlink -f x', 'tc task list 2>&1 | tc x', 'git status && git log']:
        assert bash(run, ok) == 0, ok
    for bad in ['ls', 'cat a', 'npm test', 'git commit -m x', 'git branch -D x', 'git worktree remove x',
                'git status; rm -rf x', 'tc x && rm y', 'tc x | sh', 'echo $(cat a)', 'tc x > out', 'git log `id`',
                'cc resources run -- ls', 'tc x\nrm y', '']:
        assert bash(run, bad) == 2, bad


def test_subagent_unaffected(run):
    assert run('Edit', {'file_path': '/Volumes/x/a.py'}, agent=True).returncode == 0
    assert run('Read', {'file_path': '/x'}, agent=True).returncode == 0
    assert bash(run, 'npm test', agent=True) == 0


def test_other_tools_pass(run):
    assert run('Agent', {'prompt': 'x'}).returncode == 0
    assert run('TodoWrite', {}).returncode == 0


def test_off_switch_logged(run):
    r = run('Edit', {'file_path': '/x'}, COPILOT_COORDINATOR='off')
    assert r.returncode == 0
    assert 'COPILOT_COORDINATOR=off' in run.log.read_text()
