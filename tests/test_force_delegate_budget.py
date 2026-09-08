"""ADR-005 boundaries missing from the preserved owner-authored shell suite."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def budget(tmp_path):
    hooks = tmp_path / '.claude/hooks'
    hooks.mkdir(parents=True)
    shutil.copy2(ROOT / '.claude/hooks/pretool-check.sh', hooks)
    baseline = ROOT / '.claude/force-delegate-budget-baseline-v1.0.0.json'
    shutil.copy2(baseline, hooks.parent)
    thresholds = json.loads(baseline.read_text())['thresholds']
    env = {k: v for k, v in os.environ.items() if k not in (
        'CI', 'COPILOT_FORCE_DELEGATE', 'COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE',
        'COPILOT_HOOK_STATE_DIR')}

    def invoke(tool='Bash', data=None, **overrides):
        return subprocess.run(
            ['bash', str(hooks / 'pretool-check.sh')], cwd=tmp_path,
            input=json.dumps({'session_id': 'budget-test', 'tool_name': tool,
                              'tool_input': data or {'command': 'echo small'}}),
            text=True, capture_output=True, timeout=5, env={**env, **overrides},
        )

    return tmp_path, hooks / 'state/budget-budget-test.json', thresholds, invoke


def test_utf8_edit_bytes_and_denied_retry_do_not_inflate_spend(budget):
    root, state, policy, invoke = budget
    result = invoke('Edit', {'file_path': str(root / 'a'), 'new_string': 'π\n'})
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['bytesCharged'] == 3
    oversized = {'file_path': str(root / 'a'), 'content': 'x' * policy['byte_budget_bytes']}
    for _ in range(2):
        assert invoke('Write', oversized).returncode == 2
        assert json.loads(state.read_text())['bytesCharged'] == 3


def test_same_session_concurrent_calls_are_all_charged(budget):
    _, state, policy, invoke = budget
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: invoke(), range(4)))
    assert all(r.returncode == 0 and 'timed out' not in r.stderr for r in results)
    assert json.loads(state.read_text())['bytesCharged'] == 4 * policy['bash_bounded_charge_bytes']


def test_ci_requires_committed_exact_override_and_ignores_environment(budget):
    root, state, policy, invoke = budget
    payload = {'file_path': str(root / 'a'), 'content': 'x' * (policy['byte_budget_bytes'] + 1)}
    override = {'COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE': 'bytes:reviewed boundary'}
    assert invoke('Write', payload, CI='true', **override).returncode == 2
    assert invoke('Write', payload, **override).returncode == 0
    state.unlink()
    assert invoke('Write', payload, CI='true').returncode == 2
    for args in (
        ['init', '-q'], ['add', '.claude/force-delegate-budget-overrides.jsonl'],
        ['-c', 'user.name=Budget Test', '-c', 'user.email=budget@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'review exact overage'],
    ):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    assert invoke('Write', payload, CI='true').returncode == 0
    state.unlink()
    payload['content'] += 'x'
    assert invoke('Write', payload, CI='true').returncode == 2
