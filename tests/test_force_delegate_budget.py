"""ADR-005 boundaries missing from the preserved owner-authored shell suite."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def budget(tmp_path):
    hooks = tmp_path / '.claude/hooks'
    hooks.mkdir(parents=True)
    shutil.copy2(ROOT / '.claude/hooks/pretool-check.sh', hooks)
    shutil.copy2(ROOT / '.claude/hooks/copilot-hook.sh', hooks)
    shutil.copytree(ROOT / '.claude/hooks/lib', hooks / 'lib')
    baseline = ROOT / '.claude/force-delegate-budget-baseline-v1.0.0.json'
    shutil.copy2(baseline, hooks.parent)
    thresholds = json.loads(baseline.read_text())['thresholds']
    env = {k: v for k, v in os.environ.items() if k not in (
        'CI', 'COPILOT_FORCE_DELEGATE', 'COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE',
        'COPILOT_HOOK_STATE_DIR', 'COPILOT_FORCE_DELEGATE_FLOOR_BYTES')}

    def invoke(tool='Bash', data=None, *, payload_cwd=None, through_shim=False, **overrides):
        payload = {'session_id': 'budget-test', 'tool_name': tool,
                   'tool_input': data or {'command': 'echo small'}}
        if payload_cwd is not None:
            payload['cwd'] = str(payload_cwd)
        script = 'copilot-hook.sh' if through_shim else 'pretool-check.sh'
        return subprocess.run(
            ['bash', str(hooks / script), 'pretool-check'], cwd=tmp_path,
            input=json.dumps(payload), text=True, capture_output=True, timeout=5,
            env={**env, 'COPILOT_HOOKS_ROOT': str(hooks),
                 'CLAUDE_PROJECT_DIR': str(tmp_path), **overrides},
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


def seed_spend(state, amount):
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({
        'session_id': 'budget-test', 'bytesCharged': amount, 'filesTouched': [],
        'updatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }))


@pytest.mark.parametrize('spent', [35912, 40000])
def test_reported_head_pipeline_recovers_through_shim(budget, spent):
    root, state, _, invoke = budget
    seed_spend(state, spent)
    # Exact command shape from the 43912/40000 failure. No shell command is
    # executed: the real shim/dispatcher only receives a PreToolUse payload.
    command = (f'cd {root} && grep -rn "bridge" pipeline_copilot/cli/*.py '
               '2>/dev/null | grep -i "def \\|command\\|add_parser\\|help=" | head -20')
    result = invoke(data={'command': command}, payload_cwd=root / 'initiative',
                    through_shim=True)
    assert result.returncode == 0, result.stderr
    charged = json.loads(state.read_text())
    assert charged['bytesCharged'] == spent + 20 * 128
    assert charged['filesTouched'] == []


@pytest.mark.parametrize('limiter,charge', [
    ('head', 1280), ('head -20', 2560), ('head -n 20', 2560),
    ('head -n20', 2560), ('head --lines=20', 2560), ('head --lines 20', 2560),
    ('/usr/bin/head -n 20', 2560), ('head -c 4096', 4096),
    ('head -c4096', 4096), ('head --bytes=4096', 4096),
    ('head --bytes 4096', 4096), ('head -n 0', 0),
])
def test_terminal_head_limit_is_charged_and_floor_stays_usable(budget, limiter, charge):
    root, state, policy, invoke = budget
    seed_spend(state, policy['byte_budget_bytes'])
    result = invoke(data={'command': f'cd "{root}/quoted directory" && rg x . | {limiter}'})
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['bytesCharged'] == policy['byte_budget_bytes'] + charge


@pytest.mark.parametrize('command', [
    'rg x . | head -n -20', 'rg x . | head -c -20',
    'rg x . | head -n nope', 'rg x . | head -n',
    'rg x . | head -20 extra-file', 'rg x . | head -n 20 -n 100000',
    'rg x . | head -20 | cat huge', 'rg x . | head -20; cat huge',
    'cat huge; rg x . | head -20', 'rg x . | head -20 && cat huge',
    'cat huge && rg x . | head -20', 'rg x . | head -20 || cat huge',
    'rg x . | head -20 & cat huge', 'cat huge\nrg x . | head -20',
    'rg x . | head -20 > result', 'rg x . > result | head -20',
    'rg x . | head -20 < huge', 'rg x . | head $(echo 20)',
    'rg x . | head -n "$LIMIT"', 'rg x . | head `echo -20`',
    'rg x . | echo "head -20"', 'rg x . # | head -20',
    'rg x . | head -n "20', 'rg x . | head -20 |',
    r'rg x . \| head -20', 'rg x . "|" head -20', "rg x . '|' head -20",
])
def test_head_text_does_not_hide_unbounded_output(budget, command):
    _, state, policy, invoke = budget
    seed_spend(state, policy['byte_budget_bytes'])
    before = state.read_bytes()
    for _ in range(2):
        result = invoke(data={'command': command})
        assert result.returncode == 2, (command, result.stderr)
        assert state.read_bytes() == before


@pytest.mark.parametrize('limiter', ['head -n 100000', 'head -c 40001'])
@pytest.mark.parametrize('producer', ['rg x .', 'rg -m 1 x .'])
def test_large_head_limit_is_not_a_small_output_exemption(budget, limiter, producer):
    _, state, _, invoke = budget
    result = invoke(data={'command': f'{producer} | {limiter}'})
    assert result.returncode == 2, result.stderr
    assert not state.exists()


def test_pipeline_estimation_never_executes_substitutions(budget):
    root, state, policy, invoke = budget
    seed_spend(state, policy['byte_budget_bytes'])
    marker = root / 'must-not-exist'
    result = invoke(data={'command': f'rg "$(touch {marker})" . | head -20'})
    assert result.returncode == 2, result.stderr
    assert not marker.exists()


@pytest.mark.parametrize('prefix', ['', 'cd data && '])
def test_small_glob_targets_resolve_and_sum_actual_sizes(budget, prefix):
    root, state, policy, invoke = budget
    data = root / 'data'
    data.mkdir()
    (data / 'one.py').write_bytes(b'x' * 41)
    (data / 'two.py').write_bytes(b'x' * 59)
    seed_spend(state, policy['byte_budget_bytes'])
    result = invoke(data={'command': prefix + 'grep -rn "bridge" *.py'},
                    payload_cwd=root if prefix else data, through_shim=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['bytesCharged'] == policy['byte_budget_bytes'] + 100


@pytest.mark.parametrize('pattern', ['missing/*.py', '*.py', "'*.py'"])
def test_unmatched_large_and_quoted_globs_do_not_get_a_small_charge(budget, pattern):
    root, state, policy, invoke = budget
    (root / 'huge.py').write_bytes(b'x' * (policy['byte_budget_bytes'] + 1))
    seed_spend(state, policy['byte_budget_bytes'])
    before = state.read_bytes()
    result = invoke(data={'command': f'grep -rn "bridge" {pattern}'}, payload_cwd=root)
    assert result.returncode == 2, result.stderr
    assert state.read_bytes() == before


@pytest.mark.parametrize('command', [
    'pcopilot bridge --help 2>&1 | grep -i config',
    'pcopilot --version | grep 1',
    'cd "some directory" && pcopilot bridge --help 2>/dev/null | rg config | grep -v path',
])
def test_help_output_filtered_from_stdin_retains_bounded_charge(budget, command):
    _, state, policy, invoke = budget
    seed_spend(state, policy['byte_budget_bytes'])
    result = invoke(data={'command': command}, through_shim=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['bytesCharged'] == (
        policy['byte_budget_bytes'] + policy['bash_bounded_charge_bytes'])


@pytest.mark.parametrize('command', [
    'pcopilot bridge --help | grep -i config huge',
    'pcopilot bridge --help | grep -f patterns',
    'pcopilot bridge --help | cat huge',
    'pcopilot bridge --help; grep config huge',
    'pcopilot bridge --help | grep config; cat huge',
    'sh -c "cat huge" --help | grep config',
    'pcopilot bridge --help | grep config < huge',
])
def test_help_flag_does_not_exempt_independent_file_output(budget, command):
    _, state, policy, invoke = budget
    seed_spend(state, policy['byte_budget_bytes'])
    before = state.read_bytes()
    result = invoke(data={'command': command})
    assert result.returncode == 2, result.stderr
    assert state.read_bytes() == before


def test_missing_pipeline_helper_keeps_conservative_estimate(budget):
    root, state, policy, invoke = budget
    (root / '.claude/hooks/lib/bash_pipeline_cost.py').unlink()
    seed_spend(state, policy['byte_budget_bytes'])
    result = invoke(data={'command': 'grep x . | head -20'})
    assert result.returncode == 2, result.stderr
    assert 'This call: 8000 estimated bytes' in result.stderr
