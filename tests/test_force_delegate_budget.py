"""ADR-005 measured byte meter: charges what the transcript shows entered the main session."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / '.claude/force-delegate-budget-baseline-v1.1.0.json').read_text())['thresholds']


@pytest.fixture
def budget(tmp_path):
    hooks = tmp_path / '.claude/hooks'
    hooks.mkdir(parents=True)
    for name in ('pretool-check.sh', 'copilot-hook.sh', 'session-start.sh', 'protocol-injection.md'):
        shutil.copy2(ROOT / '.claude/hooks' / name, hooks)
    for baseline in (ROOT / '.claude').glob('force-delegate-budget-baseline-v*.json'):
        shutil.copy2(baseline, hooks.parent)
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('')
    env = {k: v for k, v in os.environ.items() if k not in (
        'CI', 'COPILOT_FORCE_DELEGATE', 'COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE',
        'COPILOT_HOOK_STATE_DIR', 'COPILOT_SESSION_START')}
    env.update(COPILOT_HOOKS_ROOT=str(hooks), CLAUDE_PROJECT_DIR=str(tmp_path))

    def invoke(tool='Bash', data=None, *, through_shim=False, **overrides):
        payload = {'session_id': 'budget-test', 'tool_name': tool,
                   'transcript_path': str(transcript),
                   'tool_input': data or {'command': 'echo small'}}
        script = 'copilot-hook.sh' if through_shim else 'pretool-check.sh'
        return subprocess.run(
            ['bash', str(hooks / script), 'pretool-check'], cwd=tmp_path,
            input=json.dumps(payload), text=True, capture_output=True, timeout=10,
            env={**env, **overrides})

    def session_start(source):
        payload = {'session_id': 'budget-test', 'source': source,
                   'transcript_path': str(transcript)}
        return subprocess.run(
            ['bash', str(hooks / 'session-start.sh')], cwd=tmp_path, input=json.dumps(payload),
            text=True, capture_output=True, timeout=30, env={**env, 'COPILOT_SESSION_START': 'off'})

    return tmp_path, hooks / 'state/budget-budget-test.json', transcript, invoke, session_start


def tool_result(content, sidechain=False):
    return {'type': 'user', 'isSidechain': sidechain, 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't', 'content': content}]}}


def tool_use(name, data):
    return {'type': 'assistant', 'isSidechain': False, 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't', 'name': name, 'input': data}]}}


def append(transcript, *entries, partial=''):
    with transcript.open('a') as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + '\n')
        fh.write(partial)


def spent(state):
    return json.loads(state.read_text())['bytesCharged']


def test_command_text_costs_nothing_only_measured_output_counts(budget):
    _, state, transcript, invoke, _ = budget
    # The shapes the retired estimator priced at a flat 8000 bytes.
    for command in ('grep -rn "x" src/*.py | grep -i y', 'cat big.log', 'find / -name z'):
        assert invoke(data={'command': command}).returncode == 0
    assert spent(state) == 0
    append(transcript, tool_result('three\nshort\nlines\n'))
    assert invoke().returncode == 0
    assert spent(state) == len('three\nshort\nlines\n')


def test_reads_incrementally_and_waits_for_a_partial_line(budget):
    _, state, transcript, invoke, _ = budget
    append(transcript, tool_result('a' * 100), partial='{"type":"user","message":{"content":[{"type":"tool_')
    assert invoke().returncode == 0
    assert spent(state) == 100
    with transcript.open('a') as fh:
        fh.write('result","content":"' + 'b' * 50 + '"}]}}\n')
    assert invoke().returncode == 0
    assert spent(state) == 150
    assert invoke().returncode == 0
    assert spent(state) == 150
    assert json.loads(state.read_text())['transcriptOffset'] == transcript.stat().st_size


def test_charges_utf8_bytes_edits_and_images_but_not_sidechain(budget):
    _, state, transcript, invoke, _ = budget
    append(transcript,
           tool_result('π'),
           tool_result([{'type': 'text', 'text': 'abc'}, {'type': 'image', 'source': {'data': 'x' * 90000}}]),
           tool_result('z' * 5000, sidechain=True),
           tool_use('Edit', {'file_path': 'f', 'old_string': 'ignored', 'new_string': 'new'}),
           tool_use('Write', {'file_path': 'f', 'content': 'body'}),
           tool_use('MultiEdit', {'file_path': 'f', 'edits': [{'new_string': 'ab'}, {'new_string': 'c'}]}),
           tool_use('Bash', {'command': 'x' * 5000}),
           {'type': 'system', 'subtype': 'turn_duration'})
    assert invoke().returncode == 0
    assert spent(state) == 2 + 3 + POLICY['image_block_bytes'] + 3 + 4 + 3


def test_over_budget_denies_with_plain_agent_names_and_keeps_measurement(budget):
    root, state, transcript, invoke, _ = budget
    append(transcript, tool_result('x' * (POLICY['byte_budget_bytes'] + 1)))
    result = invoke('Read', {'file_path': str(root / 'a')}, through_shim=True)
    assert result.returncode == 2
    assert f"{POLICY['byte_budget_bytes'] + 1}/{POLICY['byte_budget_bytes']} bytes" in result.stdout
    assert '/compact' in result.stdout and '@agent-' not in result.stdout
    saved = json.loads(state.read_text())
    assert saved['bytesCharged'] == POLICY['byte_budget_bytes'] + 1
    assert saved['transcriptOffset'] == transcript.stat().st_size
    assert saved['filesTouched'] == []
    bypass = invoke(data={'command': 'COPILOT_FORCE_DELEGATE=off git status'})
    assert bypass.returncode == 0


def test_compaction_resets_both_meters_without_remeasuring_history(budget):
    root, state, transcript, invoke, session_start = budget
    append(transcript, tool_result('x' * (POLICY['byte_budget_bytes'] + 1)))
    assert invoke('Read', {'file_path': str(root / 'a')}).returncode == 2
    assert session_start('startup').returncode == 0
    assert invoke().returncode == 2
    result = session_start('compact')
    assert result.returncode == 0, result.stderr
    assert spent(state) == 0
    assert invoke('Read', {'file_path': str(root / 'a')}).returncode == 0
    append(transcript, tool_result('after'))
    assert invoke().returncode == 0
    assert spent(state) == len('after')
    assert json.loads(state.read_text())['filesTouched'] == [str(root / 'a')]


def test_estimator_state_is_remeasured_but_its_file_targets_are_kept(budget):
    root, state, transcript, invoke, _ = budget
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({
        'session_id': 'budget-test', 'bytesCharged': 43912, 'filesTouched': [str(root / 'old')],
        'updatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}))
    append(transcript, tool_result('real'))
    assert invoke().returncode == 0
    saved = json.loads(state.read_text())
    assert saved['bytesCharged'] == len('real')
    assert saved['filesTouched'] == [str(root / 'old')]


def test_missing_transcript_fails_open_without_advancing(budget):
    _, state, transcript, invoke, _ = budget
    transcript.unlink()
    result = invoke()
    assert result.returncode == 0
    assert 'transcript not found' in result.stderr
    assert spent(state) == 0


def test_file_meter_counts_distinct_targets_and_denied_target_is_not_kept(budget):
    root, state, _, invoke, _ = budget
    limit = POLICY['files_budget_count']
    for i in range(limit):
        assert invoke('Read', {'file_path': str(root / f'f{i}')}).returncode == 0
    assert invoke('Read', {'file_path': str(root / 'f0')}).returncode == 0
    denied = invoke('Read', {'file_path': str(root / 'extra')})
    assert denied.returncode == 2 and 'files' in denied.stdout
    assert len(json.loads(state.read_text())['filesTouched']) == limit


def test_same_session_concurrent_calls_all_record_their_targets(budget):
    root, state, _, invoke, _ = budget
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda i: invoke('Read', {'file_path': str(root / f'c{i}')}), range(4)))
    assert all(r.returncode == 0 and 'timed out' not in r.stderr for r in results)
    assert len(json.loads(state.read_text())['filesTouched']) == 4


def test_ci_requires_committed_exact_override_and_ignores_environment(budget):
    root, state, transcript, invoke, _ = budget
    append(transcript, tool_result('x' * (POLICY['byte_budget_bytes'] + 1)))
    override = {'COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE': 'bytes:reviewed boundary'}
    assert invoke(CI='true', **override).returncode == 2
    assert invoke(**override).returncode == 0
    assert invoke(CI='true').returncode == 2
    for args in (
        ['init', '-q'], ['add', '.claude/force-delegate-budget-overrides.jsonl'],
        ['-c', 'user.name=Budget Test', '-c', 'user.email=budget@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'review exact overage'],
    ):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    assert invoke(CI='true').returncode == 0
    append(transcript, tool_result('x'))
    assert invoke(CI='true').returncode == 2


def test_highest_baseline_version_wins(budget):
    root, _, transcript, invoke, _ = budget
    (root / '.claude/force-delegate-budget-baseline-v1.10.0.json').write_text(json.dumps({
        'byte_to_token_ratio': 4.0, 'thresholds': {
            'byte_budget_bytes': 10, 'files_budget_count': 5, 'warning_ratio': 0.8,
            'image_block_bytes': 6000}}))
    append(transcript, tool_result('x' * 11))
    result = invoke()
    assert result.returncode == 2 and '11/10 bytes' in result.stdout
