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
        'UI behavior (T3': ('Playwright', 'semantic assertions', 'before/after trace and video', 'affected journeys'),
        'Machine/model effectiveness': ('Separate', 'frozen paired', 'never an unrelated code edit'),
    }
    for lane, terms in cases.items():
        row = [r for k, r in rows.items() if k.startswith(lane)]
        assert row and all(t in row[0] for t in terms), lane
    tiers = {
        'T1 copy': ('New text present, old text gone, one browser load', 'no QA agent'),
        'T2 structural': ('One or two renders', 'existing fast checks', 'no separate QA agent'),
        'T3 foundational': ('Full depth', 'independent @agent-qa'),
    }
    for tier, terms in tiers.items():
        row = [r for k, r in rows.items() if k.startswith(tier)]
        assert row and all(x in row[0] for x in terms), tier
    for required in (
        '## Verification Tiers', 'escalates upward only', 'Downgrades are owner-only',
        'Untiered tasks default to T3', 'light source check, not automatic T3',
        'Unknown impact selects a broader named lane, never an empty selection',
        'New tests\nare required for missing behavior coverage',
        'first divergent state', 'IDs/membership', 'two falsified root-cause\nhypotheses',
        'cite file:line', 'focused 60 seconds', 'affected 180\nseconds', '900 seconds',
        'at least\nevery 30 seconds', 'Timeout is incomplete', 'never a pass or silent restart',
        "never another task's approval", 'tc remains the sole\nsource-bound QA authority',
        'A failing check is fixed in the product, never by weakening the check',
        "The one exception is a check that the owner's requested change makes obsolete",
        'record old and new expectations in the work product',
        'report it, do not ask', 'Record the rationale and exact changed files',
        '### Fixed finish line', 'Freeze that boundary for the batch',
        'one planned batch acceptance pass', 'rerun affected checks only',
        'do not silently reopen completed work', 'still blocks that criterion',
        'then stop', 'incomplete, not complete',
    ):
        assert required in content, required

verify_policy(policy)
for name, text in agents.items():
    embedded = text.split('<!-- cse-verification-policy:start -->\n')[1].split('<!-- cse-verification-policy:end -->')[0]
    assert embedded == policy, f'{name}: policy embed differs from canonical source'
    assert 'Obsolete-contract migration' not in embedded and 'Escalate undecided' not in embedded
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
    policy.replace('report it, do not ask', 'ask first'),
    policy.replace('never by weakening the check', 'by editing the check'),
    policy.replace('A failing check is fixed in the product', 'Checks may change'),
    policy.replace('wording alone does not require live model', 'always run live model'),
    policy.replace('tc remains the sole\nsource-bound QA authority', 'runner grants approval'),
    policy.replace('then stop', 'then improve again'),
    policy.replace('no QA agent |', 'QA agent required |'),
    policy.replace('Untiered tasks default to T3', 'Untiered tasks default to T1'),
    policy.replace('escalates upward only', 'may move either way'),
    policy.replace('Downgrades are owner-only', 'Agents may downgrade'),
    policy.replace('light source check, not automatic T3', 'forced T3'),
    policy.replace('One or two renders', 'Full Playwright suite'),
    policy.replace('still blocks that criterion', 'never blocks completion'),
):
    try:
        verify_policy(mutant)
    except AssertionError:
        continue
    raise AssertionError('policy negative control unexpectedly passed')
# Forced-depth instructions are gone from the role and planning files
assert 'Finalize without @agent-qa' not in agents['me']
assert '**ALWAYS**: every implementation' not in agents['me']
assert 'T1/T2 finish with `tc task attest`' in agents['me'] and 'T3 and any escalation' in agents['me']
assert 'verify only that a valid tc attestation exists' in agents['qa']
ta = Path('.claude/agents/ta.md').read_text()
assert 'Frontend: "Playwright E2E tests required"\n' not in ta and 'name its verification tier' in ta
assert 'T3 foundational: Backend' in ta
for name, text in (('me', agents['me']), ('qa', agents['qa']), ('ta', ta), ('protocol', Path('.claude/commands/protocol.md').read_text())):
    assert 'untiered tasks are T3' in text.replace('\n', ' '), name
protocol = Path('.claude/commands/protocol.md').read_text()
assert '## Fixed Delivery Boundary' in protocol
assert 'close\nthe task' in protocol and 'then stop' in protocol
assert 'set the verification tier' in protocol and 'valid tc attestation (T1/T2)' in protocol
assert 'sixth `Tier:` line' in protocol and 'T1 copy work is not substantial' in protocol
print('PASS: 5 lane contracts, 3 tier rows, shared me/qa loading, fixed finish line, evidence authority, owner-requested obsolete-check rule, 14 negative controls')
print('UNTESTED: live model compliance; this check validates instruction structure only')
PY
