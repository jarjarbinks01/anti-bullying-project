"""Synthetic parity, invariant and bounded-memory checks for tracking streams."""
import hashlib
import json
import os
import sqlite3
import time
import tracemalloc

import pytest

from study2 import dyads, dyad_operator as tracking
from study2.common import PipelineError, digest, dumps


def database(path=':memory:'):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(dyads.SCHEMA)
    db.execute('INSERT INTO dyad_schema VALUES(?,?)', (1, 'synthetic'))
    db.execute('INSERT INTO dyad_registry VALUES(?,?,?,?,?,?,?,?)',
               ('id', 'student', 'parent', 'old', 'now', '{"文字":"é"}', 'reserved', None))
    for sid in ('z', 'a'):
        db.execute('INSERT INTO dyad_lineage VALUES(?,?,?,?)', ('id', sid, 'evidence', 1))
    for key in ('z', 'a'):
        db.execute('INSERT INTO dyad_memberships VALUES(?,?,?,?,?,?)',
                   ('old', key, None, key, 'reserved', '{"quotes":"\\\"", "null":null}'))
    db.execute('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',
               ('middle', 'now', 'restriction', 'id', 'researcher', 'synthetic', '{}'))
    db.commit()
    return db


def add_event(db, key, kind='published_mapping', target='target'):
    db.execute('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',
               (key, 'now', kind, 'id', 'pipeline', 'synthetic', json.dumps({'run_id': target})))


def test_stream_preserves_exact_existing_json_and_digest(tmp_path):
    db = database()
    expected = tracking.workspace_snapshot(db)
    assert ''.join(tracking._tracking_json(db)) == dumps(expected)
    assert tracking.workspace_revision(db) == digest(expected)
    path = tmp_path/'tracking.json'
    assert tracking._write_tracking(db, path) == digest(expected)
    assert path.read_text() == dumps({'schema_version': dyads.SCHEMA_VERSION, 'tables': expected})
    assert path.stat().st_mode & 0o777 == 0o600
    db.close()


def test_absent_and_empty_tables_match_old_digest():
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    assert tracking.workspace_revision(db) == digest({})
    db.executescript(dyads.SCHEMA)
    assert tracking.workspace_revision(db) == digest(tracking.workspace_snapshot(db))
    db.close()


def test_stream_reads_uncommitted_changes_and_never_reuses_stale_hash():
    db = database(); original = tracking.workspace_revision(db)
    add_event(db, 'new')
    changed = tracking.workspace_revision(db)
    assert changed != original and changed == digest(tracking.workspace_snapshot(db))
    db.rollback()
    assert tracking.workspace_revision(db) == original
    db.close()


def test_publication_comparison_allows_only_existing_changes():
    before, after = database(), database()
    add_event(after, 'a'); add_event(after, 'z')
    after.execute("UPDATE dyad_registry SET lifecycle='active',first_published_run_id='target'")
    tracking.check_publication_tracking(before, after, 'target')
    before.close(); after.close()


@pytest.mark.parametrize('mutation,reason', [
    ("DELETE FROM dyad_events", 'tracking_history_removed'),
    ("UPDATE dyad_events SET reason='changed'", 'tracking_history_removed'),
    ("UPDATE dyad_events SET event_id='changed'", 'tracking_history_removed|unrelated_tracking_history_changed'),
    ("INSERT INTO dyad_registry VALUES('extra','s','p','old','now','{}','reserved',NULL)", 'issued_id_set_changed'),
    ("DROP TRIGGER dyad_no_delete; DELETE FROM dyad_registry", 'issued_id_set_changed'),
    ("DROP TRIGGER dyad_immutable_registration; UPDATE dyad_registry SET first_student_id='other'", 'issued_id_anchor_changed'),
    ("UPDATE dyad_lineage SET active=0", 'unrelated_tracking_table_changed'),
    ("DELETE FROM dyad_memberships", 'unrelated_tracking_table_changed'),
])
def test_stream_comparison_refuses_changed_history(mutation, reason):
    before, after = database(), database()
    after.executescript(mutation)
    with pytest.raises(PipelineError, match=reason):
        tracking.check_publication_tracking(before, after, 'target')
    before.close(); after.close()


@pytest.mark.parametrize('kind,target', [('restriction', 'target'), ('published_mapping', 'wrong')])
def test_stream_comparison_refuses_unrelated_additions(kind, target):
    before, after = database(), database()
    add_event(after, 'a', kind, target)
    with pytest.raises(PipelineError, match='unrelated_tracking_history_changed'):
        tracking.check_publication_tracking(before, after, 'target')
    before.close(); after.close()


def test_stream_comparison_preserves_retirement_and_first_publication():
    before, after = database(), database()
    for db in (before, after):
        db.execute("UPDATE dyad_registry SET lifecycle='retired',first_published_run_id='old'")
    after.execute("UPDATE dyad_registry SET lifecycle='active'")
    with pytest.raises(PipelineError, match='retired_id_reactivated'):
        tracking.check_publication_tracking(before, after, 'target')
    after.execute("UPDATE dyad_registry SET lifecycle='retired'")
    after.execute('DROP TRIGGER dyad_first_publication_immutable')
    after.execute("UPDATE dyad_registry SET first_published_run_id='target'")
    with pytest.raises(PipelineError, match='issued_id_first_publication_changed'):
        tracking.check_publication_tracking(before, after, 'target')
    before.close(); after.close()


@pytest.mark.parametrize('mode', ['DELETE', 'WAL'])
def test_prewrite_reader_is_stable_and_can_close_before_commit(tmp_path, mode):
    path = tmp_path/'tracking.sqlite'
    writer = database(path)
    writer.execute('PRAGMA journal_mode='+mode)
    writer.execute('BEGIN IMMEDIATE')
    reader = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    reader.row_factory = sqlite3.Row
    reader.execute('BEGIN')
    original = tracking.workspace_revision(reader)
    add_event(writer, 'added')
    assert tracking.workspace_revision(reader) == original
    assert tracking.workspace_revision(writer) != original
    tracking.check_publication_tracking(reader, writer, 'target')
    reader.close()
    writer.commit()
    assert writer.execute('SELECT COUNT(*) FROM dyad_events').fetchone()[0] == 2
    writer.close()


@pytest.mark.skipif(os.environ.get('STUDY2_TRACKING_BENCHMARK') != '1',
                    reason='Explicit half-million-row memory benchmark')
def test_half_million_event_stream_is_bounded(tmp_path, capsys):
    before = database(tmp_path/'before.sqlite')
    before.execute('DELETE FROM dyad_events')
    before.executemany('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',
        ((f'event-{i:07}', 'now', 'restriction', 'id', 'researcher', 'synthetic',
          '{"note":"synthetic history only"}') for i in range(500_000)))
    before.commit()
    after = sqlite3.connect(tmp_path/'after.sqlite'); after.row_factory = sqlite3.Row
    before.backup(after)
    add_event(after, 'zz-added')
    tracemalloc.start()
    started = time.monotonic()
    revision = tracking.workspace_revision(before)
    tracking.check_publication_tracking(before, after, 'target')
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.monotonic() - started
    assert len(revision) == 64 and peak < 4 * 1024 * 1024
    with capsys.disabled():
        print(f'\nSynthetic 500000 events: digest + comparison {elapsed:.2f}s, Python allocation peak {peak} bytes')
    before.close(); after.close()


# Reuse synthetic real-publication fixtures; do not bypass the native validators.
from test_coordinated_update import environment
from test_coordinated_update_r2 import seed_nonempty, assert_published_once


def test_native_publication_streams_and_scopes_integrity_reuse(environment, monkeypatch):
    from study2 import coordinated_update as update, store
    env = seed_nonempty(environment)
    original = store._check_backup_integrity
    checks = []
    def checked(path):
        checks.append(path)
        return original(path)
    monkeypatch.setattr(store, '_check_backup_integrity', checked)
    with monkeypatch.context() as scoped:
        def no_snapshot(*args):
            raise AssertionError('Publication must stream current tracking tables')
        scoped.setattr(tracking, 'workspace_snapshot', no_snapshot)
        update._publish_fenced(env['cfg'], env['planpin'], env['accepted'], operator='SYNTHETIC PREPARER')
    assert len(checks) == 2  # OLD and TARGET, not nine repeated integrity scans.
    assert_published_once(env)
    checks.clear()
    assert update.recover(env['cfg'])['read_only']
    assert len(checks) == 2  # A later independent operation starts fresh.


def test_native_retirement_rechecks_mutable_tuple_but_reuses_integrity(environment, monkeypatch):
    from study2 import store
    from test_journal_retirement import complete, retire
    env = complete(environment, 'old')
    original = store._check_backup_integrity
    checks = []
    def checked(path):
        checks.append(path)
        return original(path)
    monkeypatch.setattr(store, '_check_backup_integrity', checked)
    assert retire(env)['status'] == 'retired'
    assert len(checks) == 2  # Both native verifiers still run; content checks are shared.


@pytest.mark.parametrize('data', [
    {}, {'empty': []}, {'extra': [{'文字': 'é', 'value': None}]},
    {'b': [{'id': 2}, {'id': 1}], 'a': [{'nested': {'z': 0, 'a': [1, None]}}]},
])
def test_loaded_tracking_stream_preserves_all_keys_and_row_order(data):
    assert tracking._saved_tracking_revision(data) == digest(data)


@pytest.mark.parametrize('change', ['row', 'order', 'extra'])
def test_saved_tracking_tampering_is_not_hidden_by_streaming(tmp_path, change):
    from study2.common import file_hash
    db = database(); data = tracking.workspace_snapshot(db); db.close()
    expected = digest(data)
    if change == 'row':
        data['dyad_events'][0]['reason'] = 'changed'
    elif change == 'order':
        data['dyad_lineage'].reverse()
    else:
        data['extra'] = []
    ledger = tmp_path/'tracking.json'
    ledger.write_text(dumps({'schema_version': dyads.SCHEMA_VERSION, 'tables': data}))
    (tmp_path/'manifest.json').write_text(dumps({'schema_version': dyads.SCHEMA_VERSION,
        'files': {'tracking.json': file_hash(ledger)}, 'tracking_hash': expected}))
    with pytest.raises(PipelineError):
        tracking.verify_bundle(tmp_path)


@pytest.mark.parametrize('value', [{}, '', None, 0])
def test_saved_tracking_malformed_table_cannot_hash_as_empty_list(tmp_path, value):
    from study2.common import file_hash
    data = {name: [] for name in tracking.TABLES}
    expected = digest(data)
    data['dyad_aliases'] = value
    assert tracking._saved_tracking_revision(data) == digest(data)
    assert tracking._saved_tracking_revision(data) != expected
    ledger = tmp_path/'tracking.json'
    ledger.write_text(dumps({'schema_version': dyads.SCHEMA_VERSION, 'tables': data}))
    (tmp_path/'manifest.json').write_text(dumps({'schema_version': dyads.SCHEMA_VERSION,
        'files': {'tracking.json': file_hash(ledger)}, 'tracking_hash': expected}))
    with pytest.raises(PipelineError):
        tracking.verify_bundle(tmp_path)



def test_completed_verification_rechecks_fresh_publication_expectation(environment, monkeypatch):
    from study2 import coordinated_update as update
    from test_coordinated_update import OLD
    env = seed_nonempty(environment)
    update._publish_fenced(env['cfg'], env['planpin'], env['accepted'], operator='SYNTHETIC PREPARER')
    path = env['state']/'study2.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('UPDATE publication SET release_id=release_id')
    original = update.Transition.validate_inputs
    calls = []
    def changed_publication(self, *, check_tracking=True):
        calls.append(check_tracking)
        if len(calls) == 2:
            # A noncooperating WAL writer can commit despite the held read snapshot.
            with sqlite3.connect(path) as writer:
                writer.execute('UPDATE publication SET release_id=? WHERE singleton=1', (OLD,))
        return original(self, check_tracking=check_tracking)
    monkeypatch.setattr(update.Transition, 'validate_inputs', changed_publication)
    with pytest.raises(PipelineError, match='issued_id_or_restriction_history_changed'):
        update.recover(env['cfg'])
    assert calls == [True, True]
