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
    for tool, ti in [('Edit', {'file_path': '/x/a.py'}), ('Write', {'file_path': '/tmp/a'}),
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
               'pwd', 'date', 'readlink x', 'tc task list 2>&1 | tc x', 'git status && git log']:
        assert bash(run, ok) == 0, ok
    for bad in ['ls', 'cat a', 'npm test', 'git commit -m x', 'git branch -D x', 'git worktree remove x', 'readlink -f x',
                'git status; rm -rf x', 'tc x && rm y', 'tc x | sh', 'echo $(cat a)', 'tc x > out', 'git log `id`',
                'cc resources run -- ls', 'tc x\nrm y', '']:
        assert bash(run, bad) == 2, bad


def test_subagent_unaffected(run):
    assert run('Edit', {'file_path': '/x/a.py'}, agent=True).returncode == 0
    assert run('Read', {'file_path': '/x'}, agent=True).returncode == 0
    assert bash(run, 'npm test', agent=True) == 0


def test_other_tools_pass(run):
    assert run('Agent', {'prompt': 'x'}).returncode == 0
    assert run('TodoWrite', {}).returncode == 0


def test_off_switch_logged(run):
    r = run('Edit', {'file_path': '/x'}, COPILOT_COORDINATOR='off')
    assert r.returncode == 0
    assert 'COPILOT_COORDINATOR=off' in run.log.read_text()


def test_git_read_forms_cannot_write_or_execute(run):
    for bad in ['git log --output=f', 'git log --out=f', 'git log --output f', 'git log --ext-diff', 'git log --textconv',
                'git log -p', 'git log --patch', 'git log -u', 'git log -pn1', 'git status --git-dir=/x',
                'git log --work-tree=/x', 'git rev-parse --exec-path', 'git log -c', 'git log --cc', 'git log -O/bin/sh',
                'git -c core.pager=sh log', 'git -c alias.x=y status', 'git log --show-signature', 'git log --open-files-in-pager=sh', 'git log --pager=sh']:
        assert bash(run, bad) == 2, bad
    for ok in ['git log --oneline -5', 'git log --stat -n 3', 'git status --short -b', 'git rev-parse --show-toplevel',
               'git log --format=%h -- src', 'git rev-parse --abbrev-ref HEAD', 'git rev-parse --git-dir']:
        assert bash(run, ok) == 0, ok


def test_git_branch_and_worktree_listing_only(run):
    for ok in ['git branch', 'git branch -a', 'git branch -r', 'git branch -v', 'git branch --list', 'git branch --show-current',
               'git worktree list', 'git worktree list --porcelain']:
        assert bash(run, ok) == 0, ok
    for bad in ['git branch -d x', 'git branch -D x', 'git branch -m x', 'git branch -M x', 'git branch -c x y',
                'git branch -C x y', 'git branch --set-upstream-to=o/x', 'git branch -u o/x', 'git branch newbranch',
                'git branch --delete x', 'git branch -f x', 'git branch --edit-description', 'git branch -a -D x',
                'git worktree add x', 'git worktree remove x', 'git worktree prune', 'git worktree list --expire=now',
                'git worktree', 'git worktree lock x']:
        assert bash(run, bad) == 2, bad


def test_git_allowlist_blocks_bypasses(run):
    for c in ["git log --outp=f", "git log --out=f", "git log --ou=f", "git log '--output=f'", 'git log "--outp=f"',
              "git log --ext", "git log --textc", "git log --cc", "git log --diff-merges=on", "git log --pa", "git log -u",
              "git log -O f", "git log --open-files-in-pager", "git log --show-signature", "git --git-dir=/x log",
              "git log --git-dir=/x", "git --work-tree=/x status", "git status --work-tree=/x", "git rev-parse --git-dir=/x",
              "git log --format=%h\\x", "git log $X", "git log 'a", "git status -uall", "git worktree list --foo",
              "pwd x", "date -s 12:00", "readlink", "readlink -f x", "git rev-parse --verify HEAD"]:
        assert bash(run, c) == 2, c


def test_git_allowlist_allows(run):
    for c in ["git status -s", "git status --short -b", "git status --branch", "git status --porcelain", "git status --porcelain=v2",
              "git log --oneline -n 5", "git log -5", "git log --max-count=3", "git log --format=%h", "git log --pretty='%h %s'",
              'git log --format="%h %an"', "git log --graph --decorate --all", "git log --since=2.days --until=yesterday --author=bob",
              "git log --stat", "git log --name-only", "git log --name-status", "git log --first-parent --no-merges",
              "git log main..HEAD", "git log origin/main...HEAD", "git log HEAD~3 -- src docs/a.md", "git log 'v1.0'",
              "git branch --list 'f*'", "git branch -vv", "git worktree list --porcelain", "git rev-parse --abbrev-ref HEAD",
              "git rev-parse --short HEAD", "git rev-parse --show-toplevel", "git rev-parse --git-dir", "git rev-parse --is-inside-work-tree",
              "pwd", "date", "date -u +%F", "readlink x", "git -C /x status -s"]:
        assert bash(run, c) == 0, c
