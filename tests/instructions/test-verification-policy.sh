#!/usr/bin/env bash
# Static instruction contract; does not claim model effectiveness or runtime dispatch.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
python3 - <<'PY'
from pathlib import Path

policy_path = Path('.claude/agents/_shared/verification-policy.md')
policy = policy_path.read_text()
agents = {name: Path(f'.claude/agents/{name}.md').read_text() for name in ('me', 'qa')}

def verify_policy(content):
    rows = {line.split('|')[1].strip(): line for line in content.splitlines()
            if line.startswith('| ') and len(line.split('|')) == 5}
    cases = {
        'Instructions/routing': ('Parse', 'dispatch/hook wiring', 'wording alone does not require live model'),
        'Logic/transformation': ('Reproducer', 'affected callers', 'Shared API'),
        'Storage/installation': ('Disposable real persistence', 'rollback', 'preservation', 'platform/snapshot'),
        'UI behavior': ('Playwright', 'semantic assertions', 'before/after trace and video', 'affected journeys'),
        'Machine/model effectiveness': ('Separate', 'frozen paired', 'never an unrelated code edit'),
    }
    for lane, terms in cases.items():
        assert lane in rows and all(t in rows[lane] for t in terms), lane
    for required in (
        'Unknown impact selects a broader named lane, never an empty selection',
        'New tests\nare required for missing behavior coverage',
        'first divergent state', 'IDs/membership', 'two falsified root-cause\nhypotheses',
        'cite file:line', 'focused 60 seconds', 'affected 180\nseconds', '900 seconds',
        'at least\nevery 30 seconds', 'Timeout is incomplete', 'never a pass or silent restart',
        "never another task's approval", 'tc remains the sole\nsource-bound QA authority',
        'explicit authority', 'old/new expectations and rationale', 'exact changed\nassertions/diff',
        'negative control', 'Never weaken, skip or delete assertions',
    ):
        assert required in content, required

verify_policy(policy)
for name, text in agents.items():
    embedded = text.split('<!-- cse-verification-policy:start -->\n')[1].split('<!-- cse-verification-policy:end -->')[0]
    assert embedded == policy, f'{name}: policy embed differs from canonical source'
    verify_policy(embedded)  # named-file deployment works without shipping _shared
    assert 'Read `.claude/agents/_shared/verification-policy.md`' not in text
    assert 'tests_written' not in text, f'{name}: unconditional test generation'
    assert 'maxIterations is a ceiling, not a required run count' in text
    assert 'tc task evidence-identity <id>' in text
    assert 'Do not downgrade requiresQa' in text
for obsolete in ('Files Changed | Required Tests', 'Write NEW tests for changed code',
                 'After 3 consecutive rejections the gate auto-unblocks',
                 'the design command validates a task reference, not database membership'):
    assert obsolete not in agents['qa'], obsolete
for mutant in (
    policy.replace('broader named lane', 'empty lane'),
    policy.replace('negative control', 'optional observation'),
    policy.replace('wording alone does not require live model', 'always run live model'),
    policy.replace('tc remains the sole\nsource-bound QA authority', 'runner grants approval'),
):
    try:
        verify_policy(mutant)
    except AssertionError:
        continue
    raise AssertionError('policy negative control unexpectedly passed')
print('PASS: 5 lane contracts, shared me/qa loading, evidence authority, 4 negative controls')
print('UNTESTED: live model compliance; this check validates instruction structure only')
PY
