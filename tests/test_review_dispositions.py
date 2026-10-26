"""Synthetic in-memory schema only; no native imports, fixtures or databases."""
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from study2.review_dispositions import (
    DispositionError, administrative_revision,
    apply_closed_unresolvable, project_closures, reopen_closed_unresolvable,
)


def cases(count=30):
    return [dict(case_id=f'case-{i}', route='correction', record_a=f'record-{i}-A',
                 record_b=f'record-{i}-B', version_a=f'version-{i}-A', version_b=f'version-{i}-B',
                 evidence_hash=hashlib.sha256(f'synthetic full evidence {i}'.encode()).hexdigest(),
                 reasons=['child_school_missing'], retained_detail={'synthetic': i}) for i in range(count)]


def request():
    selected = cases(5)
    groups = [[(i + 1, 1), (i + 1, 2)] for i in range(5)]
    questions = []
    for case, refs in zip(selected, groups):
        for index, (source_case, question) in enumerate(refs):
            side = 'a' if index == 0 else 'b'
            questions.append(dict(case_index=source_case, question_index=question,
                                  record_id=case['record_' + side], version_id=case['version_' + side],
                                  field='synthetic_field', comparison_ids=[case['case_id']]))
    return dict(operation_id='synthetic-close', bindings=dict(release_id='RUN_SYNTHETIC_ANY',
                decision_revision='synthetic-main-revision', rules_hash='synthetic-rules',
                source_bindings={'mapping': 'synthetic-frozen-source'},
                output_bindings={'case_inventory': 'synthetic-verified-output'}),
                authorization=dict(authorizer='synthetic-operator', reference='synthetic-authority', reason='synthetic unresolvable instruction'),
                questions=questions, cases=selected)


@pytest.fixture
def work():
    db = sqlite3.connect(':memory:')
    db.executescript('''
      CREATE TABLE events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,target TEXT,payload TEXT);
      CREATE TABLE followups(case_id TEXT PRIMARY KEY,task_id TEXT,state TEXT,payload TEXT);
      CREATE TABLE tasks(id TEXT PRIMARY KEY,state TEXT,payload TEXT);
      CREATE TABLE reviews(id TEXT PRIMARY KEY,task_id TEXT,payload TEXT);
      CREATE TABLE labels(id TEXT PRIMARY KEY,payload TEXT);
      CREATE TABLE decisions(id TEXT PRIMARY KEY,payload TEXT);
      CREATE TABLE record_values(id TEXT PRIMARY KEY,payload TEXT);
      CREATE TABLE flags(id TEXT PRIMARY KEY,payload TEXT);
      INSERT INTO events VALUES(1,'old','legacy_event','legacy-target','{}');
      INSERT INTO tasks VALUES('task-original','applied','{"immutable":"task"}');
      INSERT INTO reviews VALUES('review-original','task-original','{"immutable":"review"}');
      INSERT INTO followups VALUES('case-0','task-original','pending','{ "native_payload": "keep exact before image" }');
      INSERT INTO followups VALUES('case-unrelated','task-unrelated','pending','{"unrelated":true}');
      INSERT INTO labels VALUES('scientific-label','{"do_not_touch":true}');
      INSERT INTO decisions VALUES('scientific-decision','{"do_not_touch":true}');
      INSERT INTO record_values VALUES('scientific-record','{"eligibility":"unchanged"}');
      INSERT INTO flags VALUES('scientific-flag','{"unchanged":true}');
    ''')
    yield db
    db.close()


def snapshot(db):
    tables = ['tasks', 'reviews', 'labels', 'decisions', 'record_values', 'flags']
    return {table: list(db.execute('SELECT * FROM ' + table + ' ORDER BY 1')) for table in tables}


@pytest.mark.parametrize('raw_count', [5, 30, 31])
def test_five_exact_cases_close_without_baking_raw_or_active_count(work, raw_count):
    payload = request();raw = cases(raw_count);untouched = snapshot(work)
    apply_closed_unresolvable(work, payload)
    result = project_closures(work, payload['bindings'], raw)
    assert result['projection_ready'] and result['raw_correction_comparisons'] == raw_count
    assert result['closed_unresolvable_comparisons'] == 5 and result['projected_closed_questions'] == 10
    assert result['active_correction_comparisons'] == raw_count - 5
    assert result['active_cases'] == sorted(raw[5:], key=lambda row: row['case_id'])
    assert result['admin_revision'] == administrative_revision(work)
    assert snapshot(work) == untouched
    assert work.execute("SELECT task_id FROM followups WHERE case_id='case-0'").fetchone()[0] == 'task-original'
    assert work.execute("SELECT payload FROM followups WHERE case_id='case-unrelated'").fetchone()[0] == '{"unrelated":true}'


def test_idempotence_reopen_history_and_old_close_replay(work):
    payload = request();before = work.execute("SELECT * FROM followups WHERE case_id='case-0'").fetchone()
    first = apply_closed_unresolvable(work, payload);revision = administrative_revision(work)
    assert apply_closed_unresolvable(work, deepcopy(payload))['already_recorded']
    assert administrative_revision(work) == revision and work.execute('SELECT count(*) FROM events').fetchone()[0] == 2
    changed = deepcopy(payload);changed['authorization']['reason'] = 'different instruction'
    with pytest.raises(DispositionError, match='Conflicting reuse'):
        apply_closed_unresolvable(work, changed)
    reopen = dict(operation_id='synthetic-reopen', closure_operation_id=payload['operation_id'],
                  bindings=payload['bindings'], authorization=payload['authorization'])
    reopened = reopen_closed_unresolvable(work, reopen)
    assert reopened['reopened_comparisons'] == 5
    assert work.execute("SELECT * FROM followups WHERE case_id='case-0'").fetchone() == before
    assert work.execute('SELECT count(*) FROM followups').fetchone()[0] == 6  # Previously absent rows remain, never delete.
    assert project_closures(work, payload['bindings'], cases(5))['active_correction_comparisons'] == 5
    assert administrative_revision(work) != revision
    assert reopen_closed_unresolvable(work, deepcopy(reopen))['already_recorded']
    replay = apply_closed_unresolvable(work, payload)
    assert replay['already_recorded'] and not replay['currently_closed']
    assert work.execute('SELECT count(*) FROM events').fetchone()[0] == 3
    body = json.loads(work.execute('SELECT payload FROM events WHERE id=?', (first['event_id'],)).fetchone()[0])
    assert body['before_rows']['case-0']['payload'] == before[3]


@pytest.mark.parametrize('key', ['release_id', 'decision_revision', 'rules_hash', 'source_bindings', 'output_bindings'])
def test_changed_context_never_carries_closure(work, key):
    payload = request();apply_closed_unresolvable(work, payload)
    bindings = deepcopy(payload['bindings'])
    bindings[key] = {'changed': 'different'} if isinstance(bindings[key], dict) else 'CHANGED'
    result = project_closures(work, bindings, cases(5))
    assert result['active_correction_comparisons'] == 5 and not result['closed_case_ids']
    assert len(result['expired_binding_case_ids']) == 5


@pytest.mark.parametrize('change', ['missing_evidence', 'evidence', 'version', 'reasons'])
def test_stale_or_missing_case_evidence_fails_closed_for_whole_projection(work, change):
    payload = request();apply_closed_unresolvable(work, payload);raw = cases(30)
    if change == 'missing_evidence':
        del raw[0]['evidence_hash']
    elif change == 'evidence':
        raw[0]['evidence_hash'] = 'a' * 64
    elif change == 'version':
        raw[0]['version_a'] = 'different-version'
    else:
        raw[0]['reasons'] = ['different-current-issue']
    result = project_closures(work, payload['bindings'], raw)
    assert not result['projection_ready'] and result['active_correction_comparisons'] == 30
    assert not result['closed_case_ids'] and result['stale_case_ids'] == ['case-0']


def test_mirror_change_detectable_and_reopen_never_overwrites_it(work):
    payload = request();apply_closed_unresolvable(work, payload);before = administrative_revision(work)
    work.execute("UPDATE followups SET payload='{}' WHERE case_id='case-0'");work.commit()
    assert administrative_revision(work) != before
    with pytest.raises(DispositionError, match='mirror differs'):
        project_closures(work, payload['bindings'], cases())
    with pytest.raises(DispositionError, match='compare-and-set'):
        reopen_closed_unresolvable(work, dict(operation_id='reopen', closure_operation_id=payload['operation_id'],
                                   bindings=payload['bindings'], authorization=payload['authorization']))
    assert work.execute('SELECT count(*) FROM events').fetchone()[0] == 2


def test_unauthorized_expansion_or_endpoint_change_never_writes(work):
    before = list(work.iterdump())
    for change in ('thirty', 'question', 'endpoint'):
        payload = request()
        if change == 'thirty':
            payload['cases'] = cases(30)
        elif change == 'question':
            payload['questions'][0]['comparison_ids'] = ['case-29']
        else:
            payload['questions'][0]['version_id'] = 'different-version'
        with pytest.raises(DispositionError):
            apply_closed_unresolvable(work, payload)
        assert list(work.iterdump()) == before


def test_native_review_and_scientific_tables_are_not_even_accessed(work):
    preserved = snapshot(work);statements = []
    def authorize(action, table, column, database, trigger):
        if table in {'tasks', 'reviews', 'labels', 'decisions', 'record_values', 'flags'}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_DELETE:
            return sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE} and table not in {'events', 'followups'}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    work.set_authorizer(authorize);work.set_trace_callback(statements.append)
    payload = request();apply_closed_unresolvable(work, payload)
    assert project_closures(work, payload['bindings'], cases(5))['active_cases'] == []
    reopen_closed_unresolvable(work, dict(operation_id='reopen', closure_operation_id=payload['operation_id'],
                              bindings=payload['bindings'], authorization=payload['authorization']))
    work.set_authorizer(None);work.set_trace_callback(None)
    assert snapshot(work) == preserved
    assert not any(sql.lstrip().upper().startswith(('DELETE', 'CREATE', 'DROP', 'ALTER')) for sql in statements)


def test_event_and_all_five_mirrors_rollback_together_on_write_failure(work):
    work.execute("CREATE TRIGGER synthetic_write_failure BEFORE INSERT ON followups WHEN NEW.case_id='case-2' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    work.commit();before = list(work.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
        apply_closed_unresolvable(work, request())
    assert list(work.iterdump()) == before and not work.in_transaction


def test_helper_refuses_to_commit_an_outer_transaction(work):
    work.execute("INSERT INTO events(at,kind,target,payload) VALUES('outer','legacy','uncommitted','{}')")
    with pytest.raises(DispositionError, match='idle connection'):
        apply_closed_unresolvable(work, request())
    assert work.in_transaction
    work.rollback()
    assert work.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_native_followup_replacement_cannot_enable_a_second_overlapping_closure(work):
    payload = request();apply_closed_unresolvable(work, payload)
    work.execute("UPDATE followups SET state='pending',payload='{}' WHERE case_id LIKE 'case-%' AND case_id<>'case-unrelated'")
    work.commit();before = list(work.iterdump())
    payload['operation_id'] = 'different-close-after-native-replacement'
    with pytest.raises(DispositionError, match='authoritative closure'):
        apply_closed_unresolvable(work, payload)
    assert list(work.iterdump()) == before


def test_missing_output_binding_or_noncorrection_inventory_never_hides_work(work):
    payload = request();del payload['bindings']['output_bindings']
    with pytest.raises(DispositionError, match='Missing pins'):
        apply_closed_unresolvable(work, payload)
    payload = request();apply_closed_unresolvable(work, payload)
    raw = cases(5);raw[0]['route'] = 'settled'
    with pytest.raises(DispositionError, match='current correction dataset'):
        project_closures(work, payload['bindings'], raw)


@pytest.mark.parametrize('size', [1, 2, 7])
def test_explicit_authorized_scopes_are_generic_without_private_case_indices(work, size):
    payload = request()
    payload['cases'] = cases(size)
    payload['questions'] = [dict(case_index=i+1, question_index=1,
        record_id=c['record_a'], version_id=c['version_a'], field='synthetic',
        comparison_ids=[c['case_id']]) for i, c in enumerate(payload['cases'])]
    result = apply_closed_unresolvable(work, payload)
    assert result['closed_questions'] == result['closed_comparisons'] == size
    assert project_closures(work, payload['bindings'], cases(size))['active_correction_comparisons'] == 0


def test_malformed_question_reference_fails_before_any_write(work):
    payload = request()
    payload['questions'][0]['case_index'] = []
    before = list(work.iterdump())
    with pytest.raises(DispositionError):
        apply_closed_unresolvable(work, payload)
    assert list(work.iterdump()) == before
