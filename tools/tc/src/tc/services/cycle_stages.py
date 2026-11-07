"""Stage predicates and evidence journal; native dispatch belongs to the coordinator.

All native events are coordinator observations, not provider attestations. No
receipt executes code. The existing task QA and release trust gates still apply.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from tc.db.exceptions import ConflictError, ValidationError

PHASES = ('source-ready', 'package-ready', 'activate-ready', 'complete')
KINDS = {'discover', 'sweep', 'repair', 'integrate', 'package', 'activate', 'closeout'}
OUTCOMES = {'passed', 'failed', 'error', 'blocked'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _cy():
    from tc.services import cycles
    return cycles


def _dag(rows, label):
    ids = {r['id'] for r in rows}
    visiting, seen = set(), set()
    lookup = {r['id']: r for r in rows}
    def visit(key):
        if key in visiting:
            raise ValidationError(f'{label} dependency cycle')
        if key in seen:
            return
        visiting.add(key)
        for dep in lookup[key].get('dependsOn', []):
            if dep not in ids:
                raise ValidationError(f'Unknown {label} dependency: {dep}')
            visit(dep)
        visiting.remove(key)
        seen.add(key)
    for key in ids:
        visit(key)


def validate_plan(plan):
    c = _cy()
    data = json.loads(json.dumps(plan))
    if data.get('policyVersion') != 1 or data.get('generation') != 1:
        raise ValidationError('schema2 requires policyVersion1 and initial generation1')
    stages, checks = data.get('stages'), data.get('checks')
    if not isinstance(stages, list) or not stages or not isinstance(checks, list) or not checks:
        raise ValidationError('schema2 requires nonempty stages and checks')
    for rows, label in ((stages, 'stage'), (checks, 'check')):
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError(f'{label} must be an object')
            c._slug(row.get('id'), label)
        if len({r['id'] for r in rows}) != len(rows):
            raise ValidationError(f'Duplicate {label} id')
        _dag(rows, label)
    by_stage = {s['id']: s for s in stages}
    for stage in stages:
        if stage.get('kind') not in KINDS or stage.get('phase') not in PHASES:
            raise ValidationError('Invalid stage kind or phase')
        c._slug(stage.get('owner'), 'stage owner')
        stage.setdefault('dependsOn', [])
    candidate_inputs = data.get('candidateInputsSha256')
    if candidate_inputs is not None and (not isinstance(candidate_inputs, str) or not re.fullmatch(r'[a-f0-9]{64}', candidate_inputs)):
        raise ValidationError('candidateInputsSha256 must be a SHA256 digest')
    cap = data.get('runtimeCapability', {})
    c._positive(cap.get('workers'), 'observed workers')
    if data.get('capacity', 0) > cap['workers']:
        raise ValidationError('Capacity exceeds observed native worker ceiling')
    c._artifact(cap.get('evidence', ''), data.get('root', '.'))
    streams = data.get('streams', [])
    # Reuse the complete v1 validator, then validate writers by stage. The
    # temporary read-only projection changes validation only, never saved roles.
    base = json.loads(json.dumps(data))
    base['schemaVersion'] = 1
    for stream in base.get('streams', []):
        stream['readOnly'], stream['paths'] = True, []
    normalized = c.validate_plan(base)
    restored = []
    for stream, raw in zip(normalized['streams'], streams):
        stream.update(raw)
        if stream.get('stage') not in by_stage:
            raise ValidationError('Stream requires declared stage')
        restored.extend(c.validate_claims([stream], data['root']))
    for sid in by_stage:
        group = [s for s in restored if s['stage'] == sid]
        if group:
            c.validate_claims(group, data['root'])
    # Future overlapping writers must be ordered, not merely differently named.
    def ancestors(stage):
        result = set()
        for dep in by_stage[stage]['dependsOn']:
            result.add(dep)
            result.update(ancestors(dep))
        return result
    for i, a in enumerate(restored):
        if a.get('readOnly'):
            continue
        if not a.get('worktree') or not Path(a['worktree']).is_absolute():
            raise ValidationError('Writer needs absolute worktree')
        if a['kind'] == 'code' and not a.get('branch'):
            raise ValidationError('Code writer needs branch')
        for b in restored[:i]:
            if b.get('readOnly'):
                continue
            overlap = any(c.paths_overlap(x, y) for x in a['paths'] for y in b['paths'])
            if overlap and a['stage'] not in ancestors(b['stage']) and b['stage'] not in ancestors(a['stage']):
                raise ValidationError('Overlapping writers need ordered stages')
    by_stream = {s['id']: s for s in restored}
    for check in checks:
        if check.get('stage') not in by_stage or check.get('stream') not in by_stream:
            raise ValidationError('Check requires declared stage and stream')
        if by_stream[check['stream']]['stage'] != check['stage']:
            raise ValidationError('Check stream belongs to a different stage')
        for key in ('criterion', 'consumer'):
            if not isinstance(check.get(key), str) or not check[key].strip():
                raise ValidationError(f'Check requires {key}')
        if not isinstance(check.get('paths'), list) or not check['paths']:
            raise ValidationError('Check requires source paths')
        check['paths'] = sorted(set(c.normalize_path(p, Path(data['root']).resolve()) for p in check['paths']))
        if not isinstance(check.get('inputs', {}), dict):
            raise ValidationError('Check inputs must be an object')
        check.setdefault('inputs', {})
        check.setdefault('dependsOn', [])
        check.setdefault('required', True)
        if not isinstance(check['required'], bool) or (not check['required'] and not check.get('exclusionReason')):
            raise ValidationError('Excluded check needs an explicit reason')
    data.update(root=normalized['root'], streams=restored, resourceLimits=normalized['resourceLimits'])
    return data


def managed(data):
    return data['plan'].get('schemaVersion') == 2


def binding(data, check):
    c = _cy()
    by_id = {r['id']: r for r in data['plan']['checks']}
    return _digest({'source': c.fingerprint(data['plan']['root'], check['paths']),
                    'spec': check, 'inputs': check['inputs'],
                    'dependencies': {dep: binding(data, by_id[dep]) for dep in check['dependsOn']}})


def initialize(data, conn):
    if not managed(data):
        return
    data['generation'] = 1
    data['stageState'] = {s['id']: {'state': 'planned'} for s in data['plan']['stages']}
    data['checkResults'] = {}
    data['operations'] = {}
    data['inventoryFrozen'] = False
    data['bindings'] = {r['id']: binding(data, r) for r in data['plan']['checks']}
    enroll_tasks(data, conn)


def enroll_tasks(data, conn):
    for task in {data['task'], *(s['task'] for s in data['plan']['streams'])}:
        row = conn.execute('SELECT metadata FROM tasks WHERE id=?', (task,)).fetchone()
        if not row:
            raise ValidationError('Unknown managed task')
        meta = json.loads(row[0] or '{}')
        stages = {s['stage'] for s in data['plan']['streams'] if s['task'] == task}
        req = {'cycle': data['id'], 'stage': next(iter(stages)) if len(stages) == 1 and task != data['task'] else None, 'policyVersion': 1}
        if meta.get('stageRequirement') and meta['stageRequirement'] != req:
            raise ConflictError('Task already enrolled in another stage authority')
        meta['stageRequirement'] = req
        conn.execute('UPDATE tasks SET metadata=? WHERE id=?', (json.dumps(meta), task))


def eligibility(data, stream):
    if not managed(data):
        return []
    if not inventory_current(data):
        return ['inventory-not-frozen-or-stale']
    own_checks = [r for r in data['plan']['checks'] if r['stream'] == stream['id'] and r['required']]
    if own_checks and all(result_current(data, r) and data['checkResults'][r['id']]['outcome'] == 'passed' for r in own_checks):
        return ['unchanged-evidence-retained']
    # Results are immutable within a generation. Do not spend another worker
    # permit on a failed/stale result that result-recorded must reject later.
    # Current retained passes may coexist with still-missing checks.
    if any(r['id'] in data['checkResults'] and not (
            result_current(data, r) and data['checkResults'][r['id']]['outcome'] == 'passed'
    ) for r in data['plan']['checks'] if r['stream'] == stream['id']):
        return ['result-requires-generation-transition']
    stage = next(s for s in data['plan']['stages'] if s['id'] == stream['stage'])
    state = data['stageState'][stage['id']]
    if state['state'] in {'held', 'accepted'}:
        return [f"stage-{state['state']}"]
    missing = []
    for dep in stage['dependsOn']:
        predecessor = data['stageState'][dep]
        need = 'collected' if stage['kind'] == 'repair' else 'accepted'
        if need == 'collected' and not predecessor.get('collected'):
            missing.append(f'{dep}.collected')
        elif need == 'accepted' and _stage_reasons(data, dep):
            missing.append(f'{dep}.accepted')
    if stage['kind'] == 'repair' and not state.get('repairPlan'):
        missing.append('repair-plan-not-frozen')
    return missing


def _artifact_current(receipt):
    a = receipt.get('artifactIdentity', {})
    p = Path(a.get('path', ''))
    return p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == a.get('sha256')


def inventory_current(data):
    return bool(data.get('inventoryFrozen') and data.get('inventoryDigest') == _digest(data['plan']) and _artifact_current(data.get('inventoryApproval', {})))


def result_current(data, check):
    row = data['checkResults'].get(check['id'])
    return bool(row and row['binding'] == binding(data, check) and _artifact_current(row))


def _stage_reasons(data, sid, *, accepted=True):
    c = _cy()
    state = data['stageState'][sid]
    reasons = []
    if accepted and (state['state'] != 'accepted' or not _artifact_current(state.get('approval', {}))):
        reasons.append(f'{sid}: stage not accepted')
    for check in data['plan']['checks']:
        if check['stage'] == sid and check['required']:
            if not result_current(data, check) or data['checkResults'][check['id']]['outcome'] != 'passed':
                reasons.append(f"{check['id']}: missing, failing or stale result")
    for stream in data['plan']['streams']:
        if stream['stage'] != sid:
            continue
        if c.worker_is_active(data, stream['id']):
            reasons.append(f"{stream['id']}: native scope not observed stopped")
        own_checks = [r for r in data['plan']['checks'] if r['stream'] == stream['id'] and r['required']]
        if not data['streams'][stream['id']].get('nativeStart') and not (own_checks and all(result_current(data, r) for r in own_checks)):
            reasons.append(f"{stream['id']}: no observed native work or retained results")
        if not stream.get('readOnly') and stream['kind'] == 'code' and not c._current(data, stream['id'], 'integrated'):
            reasons.append(f"{stream['id']}: code contribution not integrated")
    return reasons


def _check(data, phase='complete', stage=None):
    if not managed(data):
        return {'approved': False, 'reasons': ['schema2 governed cycle required']}
    if phase not in PHASES:
        raise ValidationError('Unknown phase')
    selected = [s['id'] for s in data['plan']['stages'] if (s['id'] == stage if stage else PHASES.index(s['phase']) <= PHASES.index(phase))]
    reasons = [] if inventory_current(data) else ['inventory not frozen or stale']
    if not selected:
        reasons.append('No stages cover requested phase')
    for sid in selected:
        reasons.extend(_stage_reasons(data, sid))
    paths = sorted({p for r in data['plan']['checks'] for p in r['paths']})
    return {'approved': not reasons, 'reasons': reasons, 'cycle': data['id'], 'generation': data['generation'], 'phase': phase,
            'sourceFingerprint': _cy().fingerprint(data['plan']['root'], paths)}


def check_cycle(*, cycle, phase='complete', db_path, candidate=None):
    c = _cy()
    conn = c._connection(db_path)
    try:
        result = _check(c._load(conn, cycle), phase)
        if candidate is not None and candidate != result.get('sourceFingerprint'):
            result['approved'] = False
            result['reasons'].append('Candidate identity differs')
        return result
    finally:
        conn.close()


def task_gate(*, task_id, conn, metadata=None):
    if metadata is None:
        row = conn.execute('SELECT metadata FROM tasks WHERE id=?', (task_id,)).fetchone()
        metadata = json.loads(row[0] or '{}') if row else {}
    req = metadata.get('stageRequirement')
    if not req:
        return {'approved': True, 'reasons': []}
    if not isinstance(req, dict) or req.get('policyVersion') != 1:
        return {'approved': False, 'reasons': ['Unsupported stage requirement']}
    try:
        data = _cy()._load(conn, req['cycle'])
        return _check(data, stage=req.get('stage'))
    except (KeyError, ValidationError) as exc:
        return {'approved': False, 'reasons': [str(exc)]}


def advance_cycle(*, cycle, event, receipt, db_path, expect_revision=None):
    c = _cy()
    if not isinstance(receipt, dict):
        raise ValidationError('Stage receipt must be an object')
    op = c._slug(receipt.get('operationId'), 'operationId')
    conn = c._connection(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        data = c._load(conn, cycle)
        if not managed(data):
            raise ValidationError('Stage operations require schema2')
        original = data['operations'].get(op)
        body_hash = _digest({'event': event, 'receipt': receipt})
        if original:
            if original['digest'] != body_hash:
                raise ConflictError('operationId reused with different input')
            return original['result']
        if expect_revision is not None and expect_revision != data['revision']:
            raise ConflictError('Cycle revision changed')
        if receipt.get('generation') != data['generation']:
            raise ConflictError('Stale stage generation')
        artifact = c._artifact(receipt.get('artifact', ''), data['plan']['root'])
        body = {**receipt, 'artifactIdentity': artifact, 'observedAt': time.time()}
        sid = receipt.get('stage')
        if event == 'inventory-frozen':
            if data['inventoryFrozen']:
                raise ConflictError('Inventory already frozen')
            if not receipt.get('actor') or not receipt.get('reviewer') or receipt['actor'] == receipt['reviewer']:
                raise ValidationError('Inventory needs independent review')
            data['inventoryFrozen'] = True
            data['inventoryApproval'] = body
            data['inventoryDigest'] = _digest(data['plan'])
        elif event in {'native-started', 'result-recorded'}:
            stream_id = receipt.get('stream')
            state = data['streams'].get(stream_id)
            claim = state.get('claim') if state else None
            if not claim or claim['token'] != receipt.get('leaseToken') or not claim.get('dispatchAuthorized'):
                raise ValidationError('Native event needs current authorized lease')
            if c._current(data, stream_id, 'stopped'):
                raise ConflictError('Native scope already stopped')
            if event == 'native-started':
                if not isinstance(receipt.get('nativeId'), str) or not receipt['nativeId']:
                    raise ValidationError('Actual returned nativeId required')
                if state.get('nativeStart'):
                    raise ConflictError('Native start already recorded')
                for row in conn.execute('SELECT data FROM protocol_cycles'):
                    peer_cycle = json.loads(row[0])
                    for peer_id, peer in peer_cycle['streams'].items():
                        if peer_cycle['id'] == cycle and peer_id == stream_id:
                            continue
                        if peer.get('nativeStart', {}).get('nativeId') == receipt['nativeId'] and c.worker_is_active(peer_cycle, peer_id):
                            raise ConflictError('Native identity already owns an active lease')
                state['nativeStart'] = body
            else:
                if not state.get('nativeStart'):
                    raise ValidationError('Permit does not establish native start')
                check = next((r for r in data['plan']['checks'] if r['id'] == receipt.get('check')), None)
                if not check or check['stream'] != stream_id:
                    raise ValidationError('Case is outside this stream')
                if receipt.get('outcome') not in OUTCOMES:
                    raise ValidationError('Invalid check outcome')
                if receipt['outcome'] in {'failed', 'error'} and not receipt.get('defect'):
                    raise ValidationError('Failed check needs defect identity')
                if check['id'] in data['checkResults']:
                    raise ConflictError('Case result already exists; integrate new generation')
                now = binding(data, check)
                if now != data['bindings'][check['id']]:
                    raise ConflictError('Source changed during frozen sweep')
                data['checkResults'][check['id']] = {**body, 'binding': now, 'agent': claim['agent']}
        elif event in {'candidate-integrated', 'inventory-revised'}:
            if any(c.worker_is_active(data, s) for s in data['streams']):
                raise ConflictError('Cannot integrate with unresolved native workers')
            if event == 'inventory-revised':
                if not receipt.get('actor') or not receipt.get('reviewer') or receipt['actor'] == receipt['reviewer']:
                    raise ValidationError('Inventory revision requires independent review')
                proposed = validate_plan(receipt.get('plan', {}))
                old = data['plan']
                for key in set(old) | set(proposed):
                    if key not in {'streams', 'checks', 'stages'} and old.get(key) != proposed.get(key):
                        raise ValidationError('Additive inventory cannot change cycle authority or candidate inputs')
                for key in ('streams', 'checks', 'stages'):
                    new = {r['id']: r for r in proposed[key]}
                    if any(new.get(r['id']) != r for r in old[key]):
                        raise ValidationError('Additive inventory cannot remove or alter prior obligations')
                if proposed == old and inventory_current(data):
                    raise ValidationError('Inventory revision must add an obligation or renew stale independent review')
                body['previousInventoryDigest'] = data.get('inventoryDigest')
                data['plan'] = proposed
                for spec in proposed['streams']:
                    data['streams'].setdefault(spec['id'], {'state': 'planned', 'events': {}, 'claim': None})
                for stage in proposed['stages']:
                    data['stageState'].setdefault(stage['id'], {'state': 'planned'})
                enroll_tasks(data, conn)
                data['inventoryApproval'] = body
                data['inventoryDigest'] = _digest(proposed)
                data['inventoryFrozen'] = True
            elif not inventory_current(data):
                raise ConflictError('Inventory approval is stale; independently revise it before integrating')
            bindings = {r['id']: binding(data, r) for r in data['plan']['checks']}
            retained = {key: row for key, row in data['checkResults'].items() if row['outcome'] == 'passed' and row['binding'] == bindings[key] and _artifact_current(row)}
            data['generation'] += 1
            data['checkResults'] = retained
            data['bindings'] = bindings
            for stage in data['stageState'].values():
                stage.clear()
                stage['state'] = 'planned'
            for key, state in data['streams'].items():
                spec = next(s for s in data['plan']['streams'] if s['id'] == key)
                own = [r['id'] for r in data['plan']['checks'] if r['stream'] == key and r['required']]
                keep = bool(own and all(cid in retained for cid in own) and c._current(data, key, 'stopped'))
                if not spec.get('readOnly') and spec['kind'] == 'code':
                    keep = bool((not own or all(cid in retained for cid in own)) and c._current(data, key, 'stopped') and c._current(data, key, 'integrated'))
                if not keep:
                    state.update(state='planned', claim=None, events={})
                    state.pop('nativeStart', None)
            body['retained'] = sorted(retained)
        else:
            stages = {s['id']: s for s in data['plan']['stages']}
            if sid not in stages:
                raise ValidationError('Unknown stage')
            stage, state = stages[sid], data['stageState'][sid]
            checks = [r for r in data['plan']['checks'] if r['stage'] == sid and r['required']]
            if event == 'sweep-collected':
                missing = [r['id'] for r in checks if not result_current(data, r)]
                if missing:
                    raise ConflictError('Sweep incomplete: ' + ','.join(missing))
                state.update(collected=body, state='collected')
            elif event == 'repair-plan-frozen':
                if stage['kind'] != 'repair' or any(not data['stageState'][d].get('collected') for d in stage['dependsOn']):
                    raise ConflictError('Repair needs complete predecessor sweep')
                failures = {r['id'] for r in data['plan']['checks'] if r['stage'] in stage['dependsOn'] and r['required'] and data['checkResults'].get(r['id'], {}).get('outcome') != 'passed'}
                defects = receipt.get('defects', [])
                if not isinstance(defects, list) or any(not isinstance(d, dict) or not d.get('id') or not d.get('owner') or not isinstance(d.get('cases'), list) for d in defects):
                    raise ValidationError('Defect catalogue needs ids, owners and cases')
                if {case for d in defects for case in d['cases']} != failures:
                    raise ValidationError('Repair catalogue must cover every failed/blocked case')
                state['repairPlan'] = body
            elif event == 'stage-accepted':
                if not receipt.get('actor') or not receipt.get('reviewer') or receipt['actor'] == receipt['reviewer']:
                    raise ValidationError('Independent reviewer required')
                builders = {s['claim']['agent'] for key, s in data['streams'].items() if s.get('claim') and next(x for x in data['plan']['streams'] if x['id'] == key)['stage'] == sid}
                if receipt['reviewer'] in builders:
                    raise ValidationError('Builder cannot approve its stage')
                reasons = _stage_reasons(data, sid, accepted=False)
                if not inventory_current(data):
                    reasons.append('Inventory approval stale')
                if checks and not state.get('collected'):
                    reasons.append('Sweep not collected')
                for dep in stage['dependsOn']:
                    if stage['kind'] != 'repair' and data['stageState'][dep]['state'] != 'accepted':
                        reasons.append('Predecessor not accepted')
                if stage['kind'] == 'repair' and not state.get('repairPlan'):
                    reasons.append('Repair plan not frozen')
                if reasons:
                    raise ConflictError('; '.join(reasons))
                state.update(state='accepted', approval=body)
            elif event == 'held':
                if not receipt.get('reason'):
                    raise ValidationError('Hold needs reason')
                state.update(state='held', hold=body)
            elif event == 'resume-reconciled':
                if any(c.worker_is_active(data, s['id']) for s in data['plan']['streams'] if s['stage'] == sid):
                    raise ConflictError('Native workers must be reconciled before resume')
                if state['state'] != 'held':
                    raise ConflictError('Stage is not held')
                state['state'] = 'planned'
            else:
                raise ValidationError('Unknown stage event')
        result = {'cycle': cycle, 'generation': data['generation'], 'event': event, 'revision': data['revision'] + 1}
        data['operations'][op] = {'digest': body_hash, 'result': result}
        c._save(conn, data, receipt.get('stream'), event, body)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit_cycle(*, cycle, db_path):
    c = _cy()
    conn = c._connection(db_path)
    try:
        data = c._load(conn, cycle)
        events = [dict(r) for r in conn.execute('SELECT id,stream_id,event,payload,created FROM protocol_cycle_events WHERE cycle_id=? ORDER BY id', (cycle,))]
        intervals, starts = [], {}
        queue_intervals, queue_starts = [], {}
        for row in events:
            body = json.loads(row.pop('payload'))
            row['generation'] = body.get('generation')
            row['reason'] = body.get('reason')
            sid = row['stream_id']
            if row['event'] == 'queue-observed':
                prior = queue_starts.pop(sid, None)
                if prior:
                    queue_intervals.append({**prior, 'stream': sid, 'ended': row['created'], 'seconds': max(0, row['created'] - prior['started'])})
                queue_starts[sid] = {'started': row['created'], 'state': body['state'], 'reason': body.get('reason')}
            if row['event'] == 'native-started':
                starts[sid] = (row['created'], body['nativeId'])
            if row['event'] in {'stopped', 'released'} and sid in starts:
                started, native = starts.pop(sid)
                intervals.append({'stream': sid, 'nativeId': native, 'started': started, 'stopped': row['created'], 'seconds': row['created'] - started})
        clock_regressed = any(b['created'] < a['created'] for a, b in zip(events, events[1:]))
        if clock_regressed:
            for interval in intervals + queue_intervals:
                interval['seconds'] = None
        pending = {sid for sid, state in data['streams'].items() if (state.get('claim') or {}).get('dispatchAuthorized') and c.worker_is_active(data, sid)}
        return {'cycle': cycle, 'events': events, 'nativeIntervals': intervals, 'unresolvedNative': sorted(set(starts) | pending), 'queueIntervals': queue_intervals, 'openQueueIntervals': queue_starts,
                'elapsedSeconds': None if clock_regressed else (events[-1]['created'] - events[0]['created'] if events else 0),
                'assurance': 'coordinator-observed; not provider-attested', 'unknown': ['CPU productivity', 'unobserved host intervals'] + (['Clock moved backward; elapsed intervals unknown'] if clock_regressed else []),
                'generation': data.get('generation')}
    finally:
        conn.close()


def export_packet(*, cycle, phase, output, db_path):
    c = _cy()
    conn = c._connection(db_path)
    try:
        data = c._load(conn, cycle)
        result = _check(data, phase)
        if not result['approved']:
            raise ValidationError('; '.join(result['reasons']))
        root = data['plan']['root']
        try:
            commit = c._git(root, 'rev-parse', 'HEAD')
        except ValidationError:
            commit = None
        selected = {s['id'] for s in data['plan']['stages'] if PHASES.index(s['phase']) <= PHASES.index(phase)}
        checks = [r for r in data['plan']['checks'] if r['stage'] in selected]
        packet = {'schemaVersion': 2, 'kind': 'tc-stage-release', 'policyVersion': 1, 'cycle': cycle, 'generation': data['generation'], 'phase': phase,
                  'candidateInputsSha256': data['plan'].get('candidateInputsSha256'),
                  'sourceCommit': commit, 'sourcePaths': sorted({p for r in data['plan']['checks'] for p in r['paths']}),
                  'sourceFingerprint': result['sourceFingerprint'],
                  'checks': [{**{key: value for key, value in r.items() if key != 'inputs'}, 'inputsSha256': _digest(r['inputs']), 'outcome': data['checkResults'].get(r['id'], {}).get('outcome', 'excluded'),
                              'binding': data['checkResults'].get(r['id'], {}).get('binding'),
                              'artifactSha256': data['checkResults'].get(r['id'], {}).get('artifactIdentity', {}).get('sha256')} for r in checks],
                  'stages': [{'id': sid, 'state': data['stageState'][sid]['state'], 'reviewer': data['stageState'][sid]['approval']['reviewer'],
                              'artifactSha256': data['stageState'][sid]['approval']['artifactIdentity']['sha256']} for sid in sorted(selected)],
                  'assurance': 'source-bound local workflow evidence; native observations are not provider attestation'}
        target = Path(output)
        with target.open('x') as handle:
            json.dump(packet, handle, sort_keys=True, indent=2)
            handle.write('\n')
        return {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'sourceCommit': commit, 'phase': phase}
    finally:
        conn.close()


def verify_packet(*, file, sha256, root, phase, source_commit=None, candidate_inputs_sha256=None):
    c = _cy()
    raw = Path(file).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValidationError('Packet digest differs from approved release input')
    try:
        packet = json.loads(raw)
    except ValueError as exc:
        raise ValidationError('Malformed stage packet') from exc
    if not isinstance(packet, dict):
        raise ValidationError('Stage packet must be an object')
    if (type(packet.get('schemaVersion')) is not int or packet['schemaVersion'] != 2
            or packet.get('kind') != 'tc-stage-release'
            or type(packet.get('policyVersion')) is not int or packet['policyVersion'] != 1):
        raise ValidationError('Unsupported stage packet')
    if phase not in PHASES or packet.get('phase') != phase:
        raise ValidationError('Packet purpose/phase mismatch')
    if type(packet.get('generation')) is not int or packet['generation'] < 1:
        raise ValidationError('Packet generation must be a positive integer')
    c._slug(packet.get('cycle'), 'packet cycle')

    def digest(value, label, *, optional=False):
        if optional and value is None:
            return
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
            raise ValidationError(f'{label} must be a SHA256 digest')

    digest(packet.get('candidateInputsSha256'), 'Packet component identity', optional=True)
    digest(candidate_inputs_sha256, 'Expected component identity', optional=True)
    if packet.get('candidateInputsSha256') != candidate_inputs_sha256:
        raise ValidationError('Selected component inputs differ from accepted candidate')
    for key in ('checks', 'stages', 'sourcePaths'):
        if not isinstance(packet.get(key), list) or not packet[key]:
            raise ValidationError(f'Packet {key} must be a nonempty list')
    if any(not isinstance(path, str) or not path for path in packet['sourcePaths']):
        raise ValidationError('Packet source paths must be nonempty strings')
    digest(packet.get('sourceFingerprint'), 'Source fingerprint')
    stage_ids = set()
    for row in packet['stages']:
        if not isinstance(row, dict):
            raise ValidationError('Stage approval must be an object')
        sid = c._slug(row.get('id'), 'packet stage')
        if sid in stage_ids:
            raise ValidationError('Duplicate stage approval')
        stage_ids.add(sid)
        if row.get('state') != 'accepted' or not isinstance(row.get('reviewer'), str) or not row['reviewer'].strip():
            raise ValidationError('Missing independent stage acceptance')
        digest(row.get('artifactSha256'), 'Stage approval artifact')
    ids = set()
    for row in packet['checks']:
        if not isinstance(row, dict):
            raise ValidationError('Case result must be an object')
        cid = c._slug(row.get('id'), 'packet case')
        if cid in ids:
            raise ValidationError('Duplicate case result')
        ids.add(cid)
        if not isinstance(row.get('stage'), str) or row['stage'] not in stage_ids:
            raise ValidationError('Case has no accepted stage')
        if type(row.get('required')) is not bool:
            raise ValidationError('Case required field must be boolean')
        if row['required']:
            if row.get('outcome') != 'passed':
                raise ValidationError('Required case is not accepted')
            digest(row.get('binding'), 'Case binding')
            digest(row.get('artifactSha256'), 'Case artifact')
        elif not isinstance(row.get('exclusionReason'), str) or not row['exclusionReason'].strip():
            raise ValidationError('Excluded case has no reviewed reason')
        for key in ('criterion', 'consumer'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValidationError(f'Case {key} must be a nonempty string')
        digest(row.get('inputsSha256'), 'Case inputs')
        if not isinstance(row.get('paths'), list) or not row['paths']:
            raise ValidationError('Case source paths must be a nonempty list')
        if any(not isinstance(path, str) or path not in packet['sourcePaths'] for path in row['paths']):
            raise ValidationError('Case source paths are not covered by the packet')
    if c.fingerprint(root, packet['sourcePaths']) != packet.get('sourceFingerprint'):
        raise ValidationError('Source fingerprint mismatch')
    expected = source_commit or packet.get('sourceCommit')
    for commit in (packet.get('sourceCommit'), source_commit):
        if commit is not None and (not isinstance(commit, str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', commit)):
            raise ValidationError('Source commit must be a full Git object identity')
    if expected and packet.get('sourceCommit') != expected:
        raise ValidationError('Source commit mismatch')
    if (Path(root) / '.git').exists():
        if expected and c._git(root, 'rev-parse', 'HEAD') != expected:
            raise ValidationError('Source commit mismatch')
    elif packet.get('sourceCommit') and not source_commit:
        raise ValidationError('Snapshot needs explicit independently verified source commit')
    return {'approved': True, 'phase': phase, 'generation': packet['generation'], 'cycle': packet['cycle'], 'sha256': sha256}

def dispatch_context(*, cwd, db_path):
    c = _cy()
    conn = c._connection(db_path)
    try:
        identity = c._repository_identity(cwd)
        found = []
        for row in conn.execute('SELECT data FROM protocol_cycles'):
            data = json.loads(row[0])
            if managed(data) and c._repository_identity(data['plan']['root']) == identity:
                task = conn.execute('SELECT status FROM tasks WHERE id=?', (data['task'],)).fetchone()
                if task and task[0] not in {'completed', 'cancelled'}:
                    found.append({'cycle': data['id'], 'task': data['task'], 'generation': data['generation']})
        return {'managed': bool(found), 'cycles': found, 'nativeDispatch': False}
    finally:
        conn.close()


def record_queue(conn, data):
    """Persist observed queue changes at actual state transitions, without polling."""
    if not managed(data):
        return
    ready = _cy().ready_state(data, conn)
    current = {sid: {'state': 'ready', 'reason': None} for sid in ready['ready']}
    current.update({r['id']: {'state': 'queued', 'reason': r['reason'], 'details': r.get('details', [])} for r in ready['queued']})
    current.update({sid: {'state': 'running', 'reason': None} for sid in ready['running']})
    previous = data.get('queueSnapshot', {})
    for sid in set(previous) | set(current):
        value = current.get(sid, {'state': 'settled', 'reason': None})
        if previous.get(sid) != value:
            payload = {**value, 'generation': data['generation']}
            conn.execute('INSERT INTO protocol_cycle_events(cycle_id,stream_id,event,payload,created) VALUES(?,?,?,?,?)',
                         (data['id'], sid, 'queue-observed', json.dumps(payload, sort_keys=True), time.time()))
    data['queueSnapshot'] = current


def governing_task(conn, task_id):
    """Resolve the existing direct execution association, without creating one."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_scope_members'").fetchone():
        return task_id
    member = conn.execute('SELECT root_task_id FROM execution_scope_members WHERE task_id=?', (task_id,)).fetchone()
    return member[0] if member else task_id


def validate_task_scope(conn, task_id, root_task_id=None):
    row = conn.execute('SELECT metadata FROM tasks WHERE id=?', (task_id,)).fetchone()
    metadata = json.loads(row[0] or '{}') if row else {}
    from tc.services.qa_contract import validate_contract
    contract = metadata.get('acceptanceContract')
    if not isinstance(contract, dict) or not contract.get('criteria') or (metadata.get('requiresQa') and not (contract.get('sources') or contract.get('externalSources'))):
        raise ValidationError('Managed QA task needs observable criteria and declared source scope before dispatch')
    validate_contract(contract)
    from tc.services.execution import has_limits
    if not has_limits(task_id=task_id, conn=conn):
        raise ValidationError('Managed task needs registered execution limits')
    if root_task_id is not None and task_id != root_task_id:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_scope_members'").fetchone():
            raise ValidationError('Bind child to governing execution scope before dispatch')
        member = conn.execute('SELECT root_task_id FROM execution_scope_members WHERE task_id=?', (task_id,)).fetchone()
        # A separately enrolled cycle may itself be a child of the governing
        # task. Its workers retain direct associations to that same authority.
        if not member or member[0] != governing_task(conn, root_task_id):
            raise ValidationError('Bind child to governing execution scope before dispatch')
