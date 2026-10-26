"""Administrative metadata only; caller supplies an existing review connection.

No connection/file opening, schema changes, native imports or scientific writes.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re


CLOSE = 'correction_unresolvable_closed'
REOPEN = 'correction_unresolvable_reopened'
FORMAT = 'correction_admin_disposition_v1'
MARKER = '_admin_unresolvable_v1'


class DispositionError(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise DispositionError(message)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _bindings(value):
    _need(isinstance(value, dict), 'Bindings must be an object')
    for key in ('release_id', 'decision_revision', 'rules_hash'):
        _need(_text(value.get(key)), 'Missing binding: ' + key)
    for key in ('source_bindings', 'output_bindings'):
        _need(isinstance(value.get(key), dict) and value[key] and all(value[key].values()), 'Missing pins: ' + key)
    _json(value)
    return deepcopy(value)


def _authorization(value):
    _need(isinstance(value, dict) and _text(value.get('authorizer')), 'Explicit authorizer required')
    _need(_text(value.get('reference')) and _text(value.get('reason')), 'Authority reference/reason required')


def _case(value):
    _need(isinstance(value, dict), 'Case binding must be an object')
    keys = ('case_id', 'route', 'record_a', 'record_b', 'version_a', 'version_b', 'evidence_hash')
    _need(all(_text(value.get(k)) for k in keys), 'Incomplete case/version/evidence binding')
    _need(value['route'] == 'correction' and value['record_a'] != value['record_b'], 'Only concrete correction comparisons may close')
    _need(re.fullmatch('[0-9a-f]{64}', value['evidence_hash']) is not None, 'Full evidence hash required')
    reasons = value.get('reasons')
    _need(isinstance(reasons, list) and reasons and all(_text(r) for r in reasons), 'Current correction reasons required')
    return {**{k: value[k] for k in keys}, 'reasons': sorted(set(reasons))}


def _close_request(payload):
    _need(isinstance(payload, dict) and _text(payload.get('operation_id')), 'Stable operation_id required')
    _bindings(payload.get('bindings'))
    _authorization(payload.get('authorization'))
    questions, rows = payload.get('questions'), payload.get('cases')
    _need(isinstance(questions, list) and bool(questions), 'Explicit authorized questions required')
    _need(isinstance(rows, list) and bool(rows), 'Explicit authorized comparison bindings required')
    cases = {}
    for row in rows:
        case = _case(row)
        _need(case['case_id'] not in cases, 'Duplicate comparison binding')
        cases[case['case_id']] = case
    refs, union = [], set()
    for q in questions:
        _need(isinstance(q, dict), 'Question must be an object')
        ref = (q.get('case_index'), q.get('question_index'))
        _need(all(type(i) is int and i > 0 for i in ref), 'Positive question references required')
        refs.append(ref)
        _need(all(_text(q.get(k)) for k in ('record_id', 'version_id', 'field')), 'Question record/version/field required')
        ids = q.get('comparison_ids')
        _need(isinstance(ids, list) and len(ids) == 1 and ids[0] in cases, 'Question must bind one exact authorized comparison')
        case = cases[ids[0]]
        _need((q['record_id'], q['version_id']) in {(case['record_a'], case['version_a']),
                                                   (case['record_b'], case['version_b'])}, 'Question endpoint/version differs from its comparison')
        union.update(ids)
    _need(len(set(refs)) == len(questions), 'Question authorization scope differs')
    _need(union == set(cases), 'Question union must cover exactly the authorized comparisons')
    _json(payload)
    return cases


def _row(work, case_id):
    row = work.execute('SELECT case_id,task_id,state,payload FROM followups WHERE case_id=?', (case_id,)).fetchone()
    return dict(zip(('case_id', 'task_id', 'state', 'payload'), row)) if row is not None else None


def _write_row(work, row):
    work.execute('INSERT INTO followups(case_id,task_id,state,payload) VALUES(?,?,?,?) '
                 'ON CONFLICT(case_id) DO UPDATE SET task_id=excluded.task_id,state=excluded.state,payload=excluded.payload',
                 tuple(row[k] for k in ('case_id', 'task_id', 'state', 'payload')))


def _closed_row(before, case, request):
    content = json.loads(before['payload']) if before else {}
    _need(isinstance(content, dict), 'Existing followup payload is not an object; preserve and inspect it')
    _need(MARKER not in content and (not before or before['state'] != 'closed_unresolvable'), 'An existing administrative closure overlaps; reopen first')
    content[MARKER] = {'operation_id': request['operation_id'], 'bindings_digest': _digest(request['bindings']),
                       'case_binding': case, 'question_refs': sorted([
                           [q['case_index'], q['question_index']] for q in request['questions']
                           if case['case_id'] in q['comparison_ids']])}
    return {'case_id': case['case_id'], 'task_id': before['task_id'] if before else None,
            'state': 'closed_unresolvable', 'payload': _json(content)}


@contextmanager
def _transaction(work):
    _need(not work.in_transaction, 'Caller must supply an idle connection; helper owns its transaction')
    work.execute('BEGIN IMMEDIATE')
    try:
        yield
        work.commit()
    except BaseException:
        work.rollback()
        raise


def _event(work, kind, body):
    cursor = work.execute('INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)',
                          (datetime.now(timezone.utc).isoformat(), kind, body['request']['operation_id'], _json(body)))
    return cursor.lastrowid


def _decode(row):
    event_id, kind, target, payload = row
    body = json.loads(payload)
    _need(body.get('format') == FORMAT and body['request']['operation_id'] == target and
          body['request_digest'] == _digest(body['request']), 'Corrupt administrative event')
    if kind == CLOSE:
        cases = _close_request(body['request'])
        _need(set(body['before_rows']) == set(body['after_rows']) == set(cases), 'Event comparison scope differs')
        for cid, case in cases.items():
            before = body['before_rows'][cid]
            _need(before is None or before.get('case_id') == cid, 'Invalid before-row identity')
            _need(body['after_rows'][cid] == _closed_row(before, case, body['request']), 'Event mirror does not match its authorized request')
    else:
        _need(kind == REOPEN, 'Unexpected administrative event kind')
        _reopen_request(body['request'])
    return {'id': event_id, 'kind': kind, 'body': body}


def _existing(work, request, expected_kind):
    rows = list(work.execute('SELECT id,kind,target,payload FROM events WHERE target=? ORDER BY id', (request['operation_id'],)))
    if not rows:
        return None
    _need(len(rows) == 1 and rows[0][1] == expected_kind, 'Operation ID already used or duplicated')
    event = _decode(rows[0])
    _need(event['body']['request_digest'] == _digest(request), 'Conflicting reuse of operation ID')
    return event


def apply_closed_unresolvable(work_connection, payload):
    """Append one close event and update only explicitly authorized followups atomically."""
    request = json.loads(_json(payload));cases = _close_request(request)
    with _transaction(work_connection):
        previous = _existing(work_connection, request, CLOSE)
        if previous:
            return {'operation_id': request['operation_id'], 'event_id': previous['id'], 'already_recorded': True,
                    'currently_closed': all(_row(work_connection, cid) == row for cid, row in previous['body']['after_rows'].items())}
        _, heads, _ = _history(work_connection)
        _need(not any(cid in heads and heads[cid]['kind'] == CLOSE for cid in cases),
              'An authoritative closure already covers this scope; reopen/inspect it first')
        before = {cid: _row(work_connection, cid) for cid in sorted(cases)}
        after = {cid: _closed_row(before[cid], cases[cid], request) for cid in sorted(cases)}
        event_id = _event(work_connection, CLOSE, dict(format=FORMAT, request=request,
                          request_digest=_digest(request), before_rows=before, after_rows=after))
        for row in after.values():
            _write_row(work_connection, row)
    return {'operation_id': request['operation_id'], 'event_id': event_id, 'already_recorded': False,
            'closed_questions': len(request['questions']), 'closed_comparisons': len(cases)}


def _reopen_request(payload):
    _need(isinstance(payload, dict) and _text(payload.get('operation_id')) and
          _text(payload.get('closure_operation_id')), 'Reopen operation and closure IDs required')
    _need(payload['operation_id'] != payload['closure_operation_id'], 'Reopen needs a new operation ID')
    _bindings(payload.get('bindings'));_authorization(payload.get('authorization'));_json(payload)


def reopen_closed_unresolvable(work_connection, payload):
    """Append a reversible reopen event. Never delete a followup or history row."""
    request = json.loads(_json(payload));_reopen_request(request)
    with _transaction(work_connection):
        previous = _existing(work_connection, request, REOPEN)
        if previous:
            _history(work_connection)
            return {'operation_id': request['operation_id'], 'event_id': previous['id'], 'already_recorded': True}
        rows = list(work_connection.execute('SELECT id,kind,target,payload FROM events WHERE target=? ORDER BY id',
                                            (request['closure_operation_id'],)))
        _need(len(rows) == 1 and rows[0][1] == CLOSE, 'Exact closure event not found')
        closed = _decode(rows[0])['body']
        _need(request['bindings'] == closed['request']['bindings'], 'Reopen bindings differ from closure')
        before, after = {}, {}
        for cid, expected in closed['after_rows'].items():
            before[cid] = _row(work_connection, cid)
            _need(before[cid] == expected, 'Followup changed since closure; reopen compare-and-set failed')
            original = closed['before_rows'][cid]
            after[cid] = original if original is not None else dict(case_id=cid, task_id=None, state='pending',
                payload=_json({'administrative_reopen': {'operation_id': request['operation_id'],
                                                       'closure_operation_id': request['closure_operation_id']}}))
        event_id = _event(work_connection, REOPEN, dict(format=FORMAT, request=request,
                         request_digest=_digest(request), before_rows=before, after_rows=after))
        for row in after.values():
            _write_row(work_connection, row)
    return {'operation_id': request['operation_id'], 'event_id': event_id, 'already_recorded': False, 'reopened_comparisons': len(after)}


def _history_snapshot(work):
    rows = list(work.execute('SELECT id,kind,target,payload FROM events WHERE kind IN (?,?) ORDER BY id', (CLOSE, REOPEN)))
    events, by_id, heads = [], {}, {}
    for row in rows:
        event = _decode(row);body = event['body'];op = body['request']['operation_id']
        _need(op not in by_id, 'Duplicate administrative operation history')
        if event['kind'] == CLOSE:
            for cid in body['after_rows']:
                _need(cid not in heads or heads[cid]['kind'] == REOPEN, 'Overlapping active closure history')
                heads[cid] = event
        else:
            reference = by_id.get(body['request']['closure_operation_id'])
            _need(reference is not None and reference['kind'] == CLOSE, 'Reopen history lacks its earlier closure')
            previous = reference['body']
            _need(body['request']['bindings'] == previous['request']['bindings'] and
                  set(body['before_rows']) == set(body['after_rows']) == set(previous['after_rows']), 'Reopen history scope/bindings differ')
            for cid in previous['after_rows']:
                _need(heads.get(cid) is reference and body['before_rows'][cid] == previous['after_rows'][cid], 'Reopen history is out of order')
                original = previous['before_rows'][cid]
                _need(body['after_rows'][cid] == original if original is not None else
                      body['after_rows'][cid] == dict(case_id=cid, task_id=None, state='pending', payload=_json({
                          'administrative_reopen': {'operation_id': op, 'closure_operation_id': body['request']['closure_operation_id']}})),
                      'Reopen history has altered before-state')
                heads[cid] = event
        by_id[op] = event;events.append(event)
    mirrors = {cid: _row(work, cid) for cid in sorted(heads)}
    return events, heads, mirrors


def _history(work):
    owned = not work.in_transaction
    if owned:
        work.execute('BEGIN')
    try:
        return _history_snapshot(work)
    finally:
        if owned:
            work.rollback()  # End only our read snapshot; never commit caller work.


def administrative_revision(work_connection):
    events, _, mirrors = _history(work_connection)
    return _digest({'events': events, 'followups': mirrors})


def project_closures(work_connection, bindings, current_cases):
    """Pure durable queue projection; stale evidence never suppresses a case."""
    current_bindings = _bindings(bindings)
    rows = list(current_cases.values()) if isinstance(current_cases, dict) else list(current_cases)
    current = {}
    for row in rows:
        _need(isinstance(row, dict) and _text(row.get('case_id')) and row.get('route') == 'correction', 'Expected a concrete current correction dataset')
        _need(row['case_id'] not in current, 'Duplicate current comparison')
        current[row['case_id']] = deepcopy(row)
    events, heads, mirrors = _history(work_connection)
    closed, stale, expired, absent, question_refs = [], [], [], [], set()
    for cid, event in sorted(heads.items()):
        if event['kind'] != CLOSE:
            _need(mirrors[cid] == event['body']['after_rows'][cid], 'Reopened followup mirror changed; rebuild/inspect before projection')
            continue
        body = event['body'];request = body['request']
        if request['bindings'] != current_bindings:
            expired.append(cid);continue
        _need(mirrors[cid] == body['after_rows'][cid], 'Closed followup mirror differs from authoritative event')
        if cid not in current:
            absent.append(cid);continue
        case = {r['case_id']: _case(r) for r in request['cases']}[cid]
        try:
            matches = _case(current[cid]) == case
        except DispositionError:
            matches = False
        if not matches:
            stale.append(cid);continue
        closed.append(cid)
        question_refs.update((q['case_index'], q['question_index']) for q in request['questions'] if cid in q['comparison_ids'])
    if stale:
        closed, question_refs = [], set()  # No partial hiding from an inconsistent inventory.
    active = sorted(set(current) - set(closed))
    return dict(projection_ready=not stale, bindings=current_bindings,
                admin_revision=_digest({'events': events, 'followups': mirrors}),
                raw_correction_comparisons=len(current), closed_unresolvable_comparisons=len(closed),
                active_correction_comparisons=len(active), projected_closed_questions=len(question_refs),
                closed_case_ids=closed, active_case_ids=active, active_cases=[current[cid] for cid in active],
                closed_question_refs=[list(q) for q in sorted(question_refs)], stale_case_ids=stale,
                expired_binding_case_ids=expired, absent_current_case_ids=absent,
                scientific_cases_changed=False, native_raw_pending_preserved=True)
