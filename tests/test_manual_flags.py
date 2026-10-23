"""Invented fixtures / temporary local ledgers only. No real survey/state access."""
from copy import deepcopy
import csv
import gzip
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from study2 import manual_flags as flags
from study2.analysis_eligibility import (COPY_POLICY, MANIFEST_FORMAT,
    inventory_revision, manifest_revision, project_eligibility, validate_manifest)
from study2.common import digest


def record(sid='toy-a', *, raw=None, role='student', version='v1', wave=None, child=None):
    raw = raw if raw is not None else dict(zip(flags.MATCH_FIELDS,
        ['Toy survey', '2025-09-03T10:00:00+08:00', '23450001', '23450002',
         '2013-01-02', 'toy@example.com', '1980']))
    return dict(submission_id=sid, version_id=version, role=role, raw=deepcopy(raw),
                raw_hash=digest(raw), status='eligible', selected_wave=wave, child_id=child)


def distinct(sid, suffix):
    raw = record()['raw']
    raw['Survey'] = 'Toy survey ' + suffix
    return record(sid, raw=raw)


def inv(*rows, release='toy-release-1'):
    return flags.Inventory.from_records(release, list(rows))


def write_csv(path, *rows, headers=flags.COLUMNS):
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def marked(row, *, review=flags.MARKER, email='separate@example.com', **overrides):
    return {**{k: str(row['raw'][k]) for k in flags.MATCH_FIELDS},
            'Email': email, 'Review': review, **overrides}


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'synthetic-flags.sqlite3'
    flags.initialize_registry(path, operator='Invented operator')
    return path


def import_one(ledger, tmp_path, rows, *, inventory=None, filename='batch.csv', **kwargs):
    inventory = inventory or inv(*rows)
    path = write_csv(tmp_path / filename, *(marked(r) for r in rows))
    return flags.import_csv(ledger, path, inventory, operator='Invented operator', **kwargs)


def accepted(inventory, ids):
    versions = {r['submission_id']: r['version_id'] for r in inventory.records}
    manifest = dict(format=MANIFEST_FORMAT, status='accepted', release_id=inventory.release_id,
        inventory_revision=inventory.revision, copy_policy=COPY_POLICY,
        approved_by='Invented seed reviewer', approved_at='2026-10-23T12:00:00+08:00',
        entries=[dict(submission_id=s, version_id=versions[s]) for s in ids])
    manifest['revision'] = manifest_revision(manifest)
    return manifest


def test_literal_contains_projection_and_exact_normalization(tmp_path):
    raw = record()['raw']
    raw.update(Survey='ＡＢＣ', contact_01=23450001.0, adult_demographics_03=1980)
    row = record(raw=raw)
    selected = marked(row, review='note; suspected fake case; follow-up')
    selected.update(Survey=' ABC ', contact_01='２３４５０００１', adult_demographics_03='1980')
    # Unapproved extra columns are neither projected into the report nor matched.
    selected['unused_private'] = 'MUST-NOT-BE-STORED'
    csv_path = write_csv(tmp_path / 'synthetic.csv', selected,
        {**selected, 'Review': 'Suspected fake case'},
        {**selected, 'Review': 'suspected FAKE case'},
        headers=(*flags.COLUMNS, 'unused_private'))
    result = flags.preview_csv(csv_path, inv(row))
    assert result['selected_csv_rows'] == result['matched_csv_rows'] == 1
    assert result['observations'][0]['outcome'] == 'matched'
    assert 'MUST-NOT-BE-STORED' not in json.dumps(result)
    assert result['binding']['rule'] == flags.RULE
    assert 'contains_case_sensitive' in flags.RULE
    assert result['observations'][0]['row_numbers'] == [2]
    assert flags.scalar(1000.0) == '1000' and flags.scalar('1e3') == '1e3'
    assert flags.scalar(None) == flags.scalar(float('nan')) == ''
    assert flags.scalar('NaT') == 'NaT'


@pytest.mark.parametrize('defect', ['email_fallback', 'missing_key', 'case', 'phone_punctuation', 'container'])
def test_no_fuzzy_email_or_cross_container_fill(tmp_path, defect):
    row = record()
    selected = marked(row)
    if defect == 'email_fallback':
        selected['Email'] = row['raw']['contact_03.1']
        selected['contact_03.1'] = ''
    elif defect == 'missing_key':
        row['answer'] = deepcopy(row['raw'])
        del row['raw']['contact_02']
        row['raw_hash'] = digest(row['raw'])
    elif defect == 'case':
        selected['contact_03.1'] = selected['contact_03.1'].upper()
    elif defect == 'phone_punctuation':
        selected['contact_01'] = '2345-0001'
    else:
        row['answer'] = row.pop('raw')
    result = flags.preview_csv(write_csv(tmp_path / 'no-fill.csv', selected), inv(row))
    assert result['observations'][0]['outcome'] == 'unmatched'


@pytest.mark.parametrize('defect', ['missing_header', 'duplicate_header', 'truncated', 'invalid_utf8'])
def test_malformed_csv_leaves_ledger_untouched(ledger, tmp_path, defect):
    path = tmp_path / 'broken.csv'
    if defect == 'missing_header':
        path.write_text(','.join(flags.COLUMNS[:-1]) + '\n')
    elif defect == 'duplicate_header':
        path.write_text(','.join((*flags.COLUMNS, 'Email')) + '\n')
    elif defect == 'truncated':
        path.write_text(','.join(flags.COLUMNS) + '\nx,y\n')
    else:
        path.write_bytes(b'\xff')
    before = flags.status(ledger, include_history=True)
    with pytest.raises(flags.FlagError):
        flags.import_csv(ledger, path, inv(record()), operator='Invented operator')
    assert flags.status(ledger, include_history=True) == before


def test_two_week_batches_carry_forward_absence_and_idempotence(ledger, tmp_path):
    a, b = record(), distinct('toy-b', 'B')
    first = import_one(ledger, tmp_path, [a])
    before = flags.status(ledger, include_history=True)
    again = import_one(ledger, tmp_path, [a])
    assert again['batch_id'] == first['batch_id'] and again['idempotent']
    assert again['flag_counts']['newly_active'] == 0
    assert again['original_import_flag_counts']['newly_active'] == 1
    assert flags.status(ledger, include_history=True) == before
    second = import_one(ledger, tmp_path, [b], inventory=inv(a, b, release='toy-release-2'), filename='week2.csv')
    assert second['flag_counts'] == dict(newly_active=1, already_active=0, held=0)
    current = flags.status(ledger)
    assert current['active'] == 2 and current['batches'] == 2
    snapshot = flags.compile_snapshot(ledger, inv(a, b, release='toy-release-2'), operator='Invented operator')
    assert snapshot['status'] == 'accepted'
    assert {r['submission_id'] for r in snapshot['manifest']['entries']} == {'toy-a', 'toy-b'}
    # Empty new CSV does not remove either flag.
    empty = write_csv(tmp_path / 'empty.csv')
    flags.import_csv(ledger, empty, inv(a, b), operator='Invented operator')
    assert flags.status(ledger)['active'] == 2


def test_duplicate_csv_rows_are_one_observation_and_distinct_ids_are_not_row_counts(ledger, tmp_path):
    row = record()
    path = write_csv(tmp_path / 'repeat.csv', marked(row), marked(row))
    report = flags.import_csv(ledger, path, inv(row), operator='Invented operator')
    assert report['selected_csv_rows'] == report['matched_csv_rows'] == 2
    assert report['unique_selected_rows'] == report['distinct_matched_ids'] == 1
    assert report['observations'][0]['row_numbers'] == [2, 3]
    assert len(flags.status(ledger)['observations']) == 1


def test_removed_tombstone_requires_explicit_restore_and_preserves_history(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    removed = flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Operator B', reason='Synthetic correction')
    assert removed['changed'] == 1
    count = flags.status(ledger)['event_count']
    assert flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Operator B', reason='Same correction')['idempotent']
    assert flags.status(ledger)['event_count'] == count
    # A later distinct batch observes the same removed ID; does not restore it.
    path = write_csv(tmp_path / 'week2.csv', marked(row, review='note; suspected fake case; second check'))
    report = flags.import_csv(ledger, path, inv(row, release='toy-release-2'), operator='Operator C')
    assert report['flag_counts']['held'] == 1
    current = flags.status(ledger)
    assert current['active'] == 0 and current['removed'] == 1 and len(current['pending']) == 1
    blocked = flags.compile_snapshot(ledger, inv(row, release='toy-release-2'), operator='Operator C')
    assert blocked['status'] == 'blocked' and blocked['manifest'] is None
    flags.decide_flags(ledger, ['toy-a'], action='restore', inventory=inv(row),
                       operator='Operator B', reason='Synthetic explicit reflag')
    assert not flags.status(ledger)['pending']
    assert flags.compile_snapshot(ledger, inv(row), operator='Operator B')['status'] == 'accepted'
    history = flags.status(ledger, include_history=True)['history']
    assert [e['action'] for e in history] == ['csv_import', 'remove', 'csv_import', 'restore']
    assert history[1]['reason'] == 'Synthetic correction'
    assert history[3]['payload']['before']['toy-a']['state'] == 'removed'


def test_rebind_cannot_restore_removed_flag_and_reason_is_required(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Invented reviewer', reason='Correction')
    before = flags.status(ledger, include_history=True)
    with pytest.raises(flags.FlagError, match='removed_flag_needs_restore'):
        flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(row),
                           operator='Invented reviewer', reason='Wrong operation')
    with pytest.raises(flags.FlagError, match='reason_required'):
        flags.decide_flags(ledger, ['toy-a'], action='restore', inventory=inv(row),
                           operator='Invented reviewer', reason=' ')
    assert flags.status(ledger, include_history=True) == before


def test_same_batch_replay_after_removal_reports_zero_new_effects(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Invented reviewer', reason='Explicit removal')
    before = flags.status(ledger, include_history=True)
    replay = import_one(ledger, tmp_path, [row])
    assert replay['idempotent'] and replay['flag_counts'] == dict(newly_active=0, already_active=0, held=0)
    assert replay['original_import_flag_counts']['newly_active'] == 1
    assert flags.status(ledger, include_history=True) == before


def test_explicit_removal_after_changed_observation_resolves_it(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    changed = record(version='v2')
    import_one(ledger, tmp_path, [changed], inventory=inv(changed), filename='changed.csv')
    assert flags.status(ledger)['pending']
    flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Invented reviewer', reason='Reject changed case')
    assert not flags.status(ledger)['pending']
    report = flags.compile_snapshot(ledger, inv(changed), operator='Invented reviewer')
    assert report['status'] == 'accepted' and report['manifest']['entries'] == []


@pytest.mark.parametrize('change', ['version', 'content', 'role'])
def test_changed_pin_blocks_until_explicit_rebind(ledger, tmp_path, change):
    row = record()
    import_one(ledger, tmp_path, [row])
    changed = deepcopy(row)
    if change == 'version':
        changed['version_id'] = 'v2'
    elif change == 'content':
        changed['raw']['extra_item'] = 'changed content, same opaque version'
        changed['raw_hash'] = digest(changed['raw'])
    else:
        changed['role'] = 'parent'
    new = inv(changed, release='toy-release-2')
    before = flags.compile_snapshot(ledger, new, operator='Invented operator')
    assert before['status'] == 'blocked'
    assert before['blockers'][0]['code'] == 'active_flag_content_changed'
    # Import of the exact new seven fields also cannot silently rebind the pin.
    import_one(ledger, tmp_path, [changed], inventory=new, filename='changed.csv')
    assert flags.status(ledger)['flags']['toy-a']['pin']['version_id'] == 'v1'
    assert flags.compile_snapshot(ledger, new, operator='Invented operator')['status'] == 'blocked'
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=new,
                       operator='Invented reviewer', reason='Explicit synthetic version verification')
    assert not flags.status(ledger)['pending']
    assert flags.compile_snapshot(ledger, new, operator='Invented operator')['status'] == 'accepted'


def test_missing_id_acknowledgement_is_inventory_specific_and_reversible(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    absent = inv(release='toy-release-2')
    assert flags.compile_snapshot(ledger, absent, operator='Invented operator')['status'] == 'blocked'
    flags.acknowledge_absent(ledger, ['toy-a'], absent, operator='Invented operator', reason='Absent in this synthetic release')
    assert flags.compile_snapshot(ledger, absent, operator='Invented operator')['manifest']['entries'] == []
    assert flags.status(ledger)['active'] == 1
    assert flags.compile_snapshot(ledger, inv(release='toy-release-3'), operator='Invented operator')['status'] == 'blocked'
    returned = flags.compile_snapshot(ledger, inv(row, release='toy-release-4'), operator='Invented operator')
    assert returned['status'] == 'accepted' and len(returned['manifest']['entries']) == 1


def test_absence_acknowledgement_does_not_apply_to_later_content_version(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    absent = inv(release='toy-absent-release')
    flags.acknowledge_absent(ledger, ['toy-a'], absent, operator='Invented operator', reason='Version one absent')
    changed = record(version='v2')
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(changed),
                       operator='Invented reviewer', reason='Verified version two')
    report = flags.compile_snapshot(ledger, absent, operator='Invented operator')
    assert report['status'] == 'blocked'
    assert report['blockers'][0]['code'] == 'active_flag_absent'


def test_cached_snapshot_cannot_drop_a_current_flag(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    first = flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')
    with sqlite3.connect(ledger) as db:
        damaged = deepcopy(first)
        damaged['manifest']['entries'] = []
        damaged['manifest']['revision'] = manifest_revision(damaged['manifest'])
        db.execute('UPDATE snapshots SET value=?', (json.dumps(damaged),))
    with pytest.raises(flags.FlagError, match='invalid_cached_snapshot'):
        flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')


def test_malformed_flag_history_reference_rejected(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    with sqlite3.connect(ledger) as db:
        state = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
        state['flags']['toy-a']['event_seq'] = 999
        db.execute('UPDATE ledger SET value=?', (json.dumps(state),))
    before = ledger.read_bytes()
    with pytest.raises(flags.FlagError, match='invalid_registry'):
        flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('kind', ['unmatched', 'ambiguous_nonidentical'])
def test_unresolved_observations_block_partial_output_until_explicit_resolution(ledger, tmp_path, kind):
    a, b = record(), distinct('toy-b', 'B')
    selected = marked(a)
    if kind == 'unmatched':
        selected['Survey'] = 'Not in synthetic inventory'
        rows = [a, b]
    else:
        duplicate_key = record('toy-c', raw={**a['raw'], 'other_answer': 'different'})
        rows = [a, b, duplicate_key]
    path = write_csv(tmp_path / 'mixed.csv', marked(b), selected)
    flags.import_csv(ledger, path, inv(*rows), operator='Invented operator', copy_policy=COPY_POLICY)
    target = tmp_path / 'accepted.json'
    target.write_bytes(b'previous accepted artifact remains')
    before = target.read_bytes()
    report = flags.export_manifest(ledger, inv(*rows), target, operator='Invented operator')
    assert report['status'] == 'blocked' and report['manifest'] is None
    assert target.read_bytes() == before
    assert flags.status(ledger)['active'] == 1
    pending = flags.status(ledger)['pending']
    assert len(pending) == 1 and pending[0]['code'] == kind
    flags.dismiss_observations(ledger, [pending[0]['observation_id']],
                               operator='Invented reviewer', reason='Synthetic reviewed nonmatch')
    result = flags.export_manifest(ledger, inv(*rows), tmp_path / 'new-accepted.json', operator='Invented operator')
    assert result['status'] == 'accepted'
    assert {r['submission_id'] for r in result['manifest']['entries']} == {'toy-b'}


@pytest.mark.parametrize('policy,kind', [(None, 'copy_policy_required'), (COPY_POLICY, 'matched')])
def test_identical_copies_require_explicit_policy_and_are_all_flagged(ledger, tmp_path, policy, kind):
    a, b = record(), record('toy-copy')
    path = write_csv(tmp_path / 'copies.csv', marked(a))
    report = flags.import_csv(ledger, path, inv(a, b), operator='Invented operator', copy_policy=policy)
    assert report['observations'][0]['outcome'] == kind
    if policy:
        assert report['distinct_matched_ids'] == 2 and report['selected_csv_rows'] == 1
        snapshot = flags.compile_snapshot(ledger, inv(a, b), operator='Invented operator')
        assert snapshot['status'] == 'accepted' and len(snapshot['manifest']['entries']) == 2
        # Removing one copy must not silently remove the other, nor produce a partial accepted set.
        flags.decide_flags(ledger, ['toy-copy'], action='remove', operator='Invented reviewer', reason='Synthetic partial removal')
        blocked = flags.compile_snapshot(ledger, inv(a, b), operator='Invented operator')
        assert blocked['status'] == 'blocked'
        assert blocked['blockers'][0]['code'] == 'manifest_incomplete_identical_copies'
    else:
        assert flags.status(ledger)['active'] == 0


def test_new_identical_copy_is_not_silently_added_by_compile(ledger, tmp_path):
    a, b = record(), record('toy-copy')
    import_one(ledger, tmp_path, [a])
    assert flags.compile_snapshot(ledger, inv(a, b), operator='Invented operator')['status'] == 'blocked'
    import_one(ledger, tmp_path, [a], inventory=inv(a, b), filename='new-copy.csv', copy_policy=COPY_POLICY)
    assert flags.compile_snapshot(ledger, inv(a, b), operator='Invented operator')['status'] == 'accepted'


def test_full_raw_hash_and_role_proof_required_for_multiple_matches(tmp_path):
    a, b = record(), record('toy-copy', role='parent')
    path = write_csv(tmp_path / 'copies.csv', marked(a))
    assert flags.preview_csv(path, inv(a, b), copy_policy=COPY_POLICY)['observations'][0]['outcome'] == 'ambiguous_nonidentical'
    b['role'] = 'student'
    a.update(a.pop('raw'))
    b.update(b.pop('raw'))
    assert flags.preview_csv(path, inv(a, b), copy_policy=COPY_POLICY,
                             field_container='record')['observations'][0]['outcome'] == 'unverified_copies'
    corrupted = record()
    corrupted['raw_hash'] = '0' * 64
    with pytest.raises(flags.FlagError, match='inventory_raw_hash_mismatch'):
        inv(corrupted)


def test_export_repeated_bytes_and_revision_stable_and_create_only(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row])
    target = tmp_path / 'snapshot.json'
    first = flags.export_manifest(ledger, inv(row), target, operator='First reviewer')
    data, stat = target.read_bytes(), target.stat()
    second = flags.export_manifest(ledger, inv(row), target, operator='Second operator')
    assert second == first
    assert target.read_bytes() == data and target.stat().st_mtime_ns == stat.st_mtime_ns
    assert second['manifest']['approved_by'] == 'First reviewer'
    flags.decide_flags(ledger, ['toy-a'], action='remove', operator='First reviewer', reason='Synthetic correction')
    with pytest.raises(flags.FlagError, match='immutable_output_exists'):
        flags.export_manifest(ledger, inv(row), target, operator='First reviewer')
    assert target.read_bytes() == data


def test_output_link_failure_does_not_leave_partial_file(ledger, tmp_path, monkeypatch):
    row = record()
    import_one(ledger, tmp_path, [row])
    target = tmp_path / 'failed.json'
    def fail(*args):
        raise OSError('invented link failure')
    monkeypatch.setattr(flags.os, 'link', fail)
    with pytest.raises(OSError):
        flags.export_manifest(ledger, inv(row), target, operator='Invented operator')
    assert not target.exists()
    assert not list(tmp_path.glob('.manual-flags-*'))
    assert flags.compile_snapshot(ledger, inv(row), operator='Invented operator')['status'] == 'accepted'


@pytest.mark.parametrize('kind', ['foreign_sqlite', 'empty_file', 'non_database', 'symlink'])
def test_foreign_registry_never_initialized_or_modified(tmp_path, kind):
    path = tmp_path / 'foreign.sqlite3'
    if kind == 'foreign_sqlite':
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE research_state (value TEXT)')
            db.execute("INSERT INTO research_state VALUES ('synthetic protected state')")
    elif kind == 'non_database':
        path.write_bytes(b'not a SQLite registry')
    elif kind == 'symlink':
        target = tmp_path / 'target'
        target.write_bytes(b'untouchable synthetic target')
        path.symlink_to(target)
    else:
        path.write_bytes(b'')
    before = path.read_bytes()
    with pytest.raises(flags.FlagError):
        flags.initialize_registry(path, operator='Invented operator')
    with pytest.raises(flags.FlagError):
        flags.status(path)
    row = record()
    csv_path = write_csv(tmp_path / 'foreign-attempt.csv', marked(row))
    with pytest.raises(flags.FlagError):
        flags.import_csv(path, csv_path, inv(row), operator='Invented operator')
    assert path.read_bytes() == before
    assert not any(Path(str(path) + s).exists() for s in ('-journal', '-wal', '-shm'))


@pytest.mark.parametrize('kind', ['extra_table', 'bad_state', 'bad_version', 'bad_metadata'])
def test_malformed_owned_registry_fails_before_mutation(ledger, kind):
    with sqlite3.connect(ledger) as db:
        if kind == 'extra_table':
            db.execute('CREATE TABLE foreign_extra (value TEXT)')
        elif kind == 'bad_state':
            db.execute("UPDATE ledger SET value='{}'")
        elif kind == 'bad_version':
            db.execute('PRAGMA user_version=999')
        else:
            db.execute("UPDATE metadata SET value='{}'")
    before = ledger.read_bytes()
    with pytest.raises(flags.FlagError):
        flags.compile_snapshot(ledger, inv(record()), operator='Invented operator')
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('point', ['after_apply', 'commit'])
def test_failed_import_rolls_back_flags_batches_observations_and_history(ledger, tmp_path, monkeypatch, point):
    row = record()
    before = flags.status(ledger, include_history=True)
    if point == 'after_apply':
        original = flags._apply_pins
        def fail(*args):
            original(*args)
            raise RuntimeError('invented failure after flag mutation')
        monkeypatch.setattr(flags, '_apply_pins', fail)
    else:
        def fail(*args):
            raise RuntimeError('invented precommit failure')
        monkeypatch.setattr(flags, '_commit', fail)
    with pytest.raises(RuntimeError):
        import_one(ledger, tmp_path, [row])
    assert flags.status(ledger, include_history=True) == before


def test_seed_existing_manifest_explicit_and_idempotent(ledger):
    row = record()
    inventory = inv(row)
    seed = accepted(inventory, ['toy-a'])
    first = flags.seed_manifest(ledger, seed, inventory, operator='Invented operator', reason='Synthetic bootstrap')
    before = flags.status(ledger, include_history=True)
    assert first['flag_counts']['newly_active'] == 1
    assert flags.seed_manifest(ledger, seed, inventory, operator='Other operator', reason='Retry')['idempotent']
    assert flags.status(ledger, include_history=True) == before
    assert flags.compile_snapshot(ledger, inventory, operator='Invented operator')['status'] == 'accepted'


def test_invalid_seed_and_mutated_inventory_do_not_mutate_ledger(ledger, tmp_path):
    row = record()
    inventory = inv(row)
    before = flags.status(ledger, include_history=True)
    seed = accepted(inventory, ['toy-a'])
    seed['entries'][0]['version_id'] = 'not-current'
    seed['revision'] = manifest_revision(seed)
    with pytest.raises(flags.FlagError, match='manifest_version_mismatch'):
        flags.seed_manifest(ledger, seed, inventory, operator='Invented operator', reason='Invalid synthetic seed')
    inventory.records[0]['version_id'] = 'mutated-after-pin'
    with pytest.raises(flags.FlagError, match='inventory_changed_after_pin'):
        flags.compile_snapshot(ledger, inventory, operator='Invented operator')
    assert flags.status(ledger, include_history=True) == before


def test_failed_snapshot_transaction_does_not_store_compilation(ledger, tmp_path, monkeypatch):
    row = record()
    import_one(ledger, tmp_path, [row])
    before = flags.status(ledger, include_history=True)
    def fail(*args):
        raise RuntimeError('invented snapshot precommit failure')
    with monkeypatch.context() as patch:
        patch.setattr(flags, '_commit', fail)
        with pytest.raises(RuntimeError):
            flags.compile_snapshot(ledger, inv(row), operator='Invented operator')
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 0
    assert flags.status(ledger, include_history=True) == before
    assert flags.compile_snapshot(ledger, inv(row), operator='Invented operator')['status'] == 'accepted'


def test_exported_manifest_core_off_on_keeps_original_members_no_reselection(ledger, tmp_path):
    a = record('toy-t0', wave='T0', child='toy-child')
    b = distinct('toy-t1', 'later'); b.update(selected_wave='T1', child_id='toy-child')
    extra = distinct('toy-extra', 'repeat'); extra.update(status='extra_followup', child_id='toy-child')
    records = [a, b, extra]
    frame = pd.DataFrame([dict(submission_id=r['submission_id'], child_id=r['child_id'],
        role=r['role'], wave=r['selected_wave'], version_id=r['version_id']) for r in [a, b]])
    inventory = inv(*records)
    import_one(ledger, tmp_path, [a], inventory=inventory)
    target = tmp_path / 'core-manifest.json'
    report = flags.export_manifest(ledger, inventory, target, operator='Invented reviewer')
    manifest = json.loads(target.read_bytes())
    assert validate_manifest(manifest, records, inventory.release_id) == frozenset({'toy-t0'})
    assert manifest == report['manifest']
    off = project_eligibility(records, frame, None, {'malformed': True}, inventory.release_id, enabled=False)
    on = project_eligibility(records, frame, None, manifest, inventory.release_id)
    assert off.members['AC'] == (('toy-t0', 'toy-t1'),)
    assert on.members['AC'] == () and on.members['A'] == ()
    assert on.members['C'] == (('toy-t1',),)
    assert 'toy-extra' not in set(on.frame.submission_id)
    assert len(frame) == 2 and extra['status'] == 'extra_followup'


def test_inventory_loaders_explicit_files_only(tmp_path):
    row = record()
    path = tmp_path / 'inventory.json'
    path.write_text(json.dumps(dict(format=flags.INVENTORY_FORMAT, release_id='toy-release', records=[row])))
    supplied = flags.load_inventory(inventory_path=path)
    release = tmp_path / 'published'; release.mkdir()
    (release / 'summary.json').write_text(json.dumps({'release_id': 'toy-release'}))
    (release / 'records.jsonl.gz').write_bytes(gzip.compress((json.dumps(row) + '\n').encode()))
    published = flags.load_inventory(release_folder=release)
    assert supplied.revision == published.revision == inventory_revision([row])
    assert 'sha256' in supplied.provenance
    assert set(published.provenance) == {'summary', 'records'}


def test_preview_csv_hash_pin_prevents_changed_batch(ledger, tmp_path):
    row = record()
    path = write_csv(tmp_path / 'batch.csv', marked(row))
    preview = flags.preview_csv(path, inv(row))
    write_csv(path, marked(row, review='note; suspected fake case; changed'))
    with pytest.raises(flags.FlagError, match='csv_changed_since_preview'):
        flags.import_csv(ledger, path, inv(row), operator='Invented operator',
                         expected_csv_sha256=preview['csv']['sha256'])
    assert flags.status(ledger)['batches'] == 0


def test_cli_synthetic_init_preview_import_export_status_and_remove(tmp_path):
    row = record()
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps(dict(format=flags.INVENTORY_FORMAT,
                                          release_id='toy-cli-release', records=[row])))
    csv_path = write_csv(tmp_path / 'batch.csv', marked(row, review='note; suspected fake case; follow-up'))
    registry = tmp_path / 'cli.sqlite3'
    output = tmp_path / 'manifest.json'
    def run(*args, code=0):
        result = subprocess.run([sys.executable, '-m', 'study2.manual_flags', *map(str, args)],
                                text=True, capture_output=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        assert result.returncode == code, result.stderr
        assert 'toy-a' not in result.stdout and 'example.com' not in result.stdout
        return json.loads(result.stdout) if result.stdout else json.loads(result.stderr)
    run('init', '--registry', registry, '--operator', 'Invented CLI operator')
    assert run('preview', '--inventory', inventory, '--csv', csv_path)['selected_csv_rows'] == 1
    assert run('import', '--registry', registry, '--inventory', inventory, '--csv', csv_path,
               '--operator', 'Invented CLI operator')['distinct_matched_ids'] == 1
    run('export', '--registry', registry, '--inventory', inventory, '--output', output,
        '--operator', 'Invented CLI reviewer')
    assert output.is_file()
    assert run('status', '--registry', registry)['active'] == 1
    run('remove', '--registry', registry, '--submission-id', 'toy-a',
        '--operator', 'Invented CLI reviewer', '--reason', 'Synthetic correction')
    assert run('status', '--registry', registry)['removed'] == 1


def merged_record(role):
    """Published merged shape: common four, then only this role's own fields."""
    raw = dict(Survey='Invented merged ' + role, contact_01='23450001', contact_02='23450002')
    raw['建立時間'] = '2025-09-03T10:00:00+08:00'
    if role == 'student':
        raw['student_demographics_06'] = '2013-01-02'
    else:
        raw.update({'contact_03.1': 'parent@example.com', 'adult_demographics_03': '1980'})
    return record('toy-merged-' + role, raw=raw, role=role)


def merged_csv_row(row):
    # The explicitly approved merged audit/CSV has nine headers and blank slots.
    return {**{name: row['raw'].get(name, '') for name in flags.MATCH_FIELDS},
            'Email': 'separate@example.com', 'Review': 'note; suspected fake case; follow-up'}


@pytest.mark.parametrize('role', ['student', 'parent'])
@pytest.mark.parametrize('container', ['raw', 'answer'])
def test_merged_projection_opt_in_matches_only_structurally_absent_role_fields(tmp_path, role, container):
    row = merged_record(role)
    if container == 'answer':
        row['answer'] = deepcopy(row['raw'])
    original = deepcopy(row)
    path = write_csv(tmp_path / 'merged.csv', merged_csv_row(row))
    inventory = inv(row)
    strict = flags.preview_csv(path, inventory, field_container=container)
    assert strict['unindexable_records'] == 1 and strict['matched_csv_rows'] == 0
    projected = flags.preview_csv(path, inventory, field_container=container, merged_role_structural_blanks=True)
    assert projected['unindexable_records'] == 0 and projected['matched_csv_rows'] == 1
    assert projected['observations'][0]['candidates'][0]['submission_id'] == row['submission_id']
    assert strict['binding']['projection_rule'] == flags.STRICT_PROJECTION
    assert projected['binding']['projection_rule'] == flags.MERGED_ROLE_PROJECTION
    assert projected['binding']['normalization_rule'] == 'all_seven_retained_fields_nfkc_trim_exact_v1'
    assert strict['batch_id'] != projected['batch_id']
    assert row == original and inventory.records[0] == original
    assert digest(row['raw']) == row['raw_hash']


@pytest.mark.parametrize('role,missing', [
    ('student', 'Survey'), ('student', '建立時間'), ('student', 'contact_01'),
    ('student', 'contact_02'), ('student', 'student_demographics_06'),
    ('parent', 'Survey'), ('parent', '建立時間'), ('parent', 'contact_01'),
    ('parent', 'contact_02'), ('parent', 'contact_03.1'), ('parent', 'adult_demographics_03'),
])
def test_merged_projection_cannot_fill_missing_common_or_own_role_key(tmp_path, role, missing):
    row = merged_record(role)
    selected = merged_csv_row(row)
    row['answer'] = deepcopy(row['raw'])  # No fallback from another complete container.
    del row['raw'][missing]
    row['raw_hash'] = digest(row['raw'])
    preview = flags.preview_csv(write_csv(tmp_path / 'missing.csv', selected), inv(row),
                                merged_role_structural_blanks=True)
    assert preview['unindexable_records'] == 1
    assert preview['observations'][0]['outcome'] == 'unmatched'


@pytest.mark.parametrize('role,field', [
    ('student', 'contact_03.1'), ('student', 'adult_demographics_03'),
    ('parent', 'student_demographics_06'),
])
def test_merged_projection_nonblank_csv_opposite_role_value_cannot_match_empty(tmp_path, role, field):
    row = merged_record(role)
    selected = merged_csv_row(row)
    selected[field] = 'Nonblank opposite-role value'
    selected['Email'] = selected[field]  # Independent Email never supplies a match.
    preview = flags.preview_csv(write_csv(tmp_path / 'nonblank.csv', selected), inv(row),
                                merged_role_structural_blanks=True)
    assert preview['unindexable_records'] == 0 and preview['matched_csv_rows'] == 0


@pytest.mark.parametrize('role,field', [
    ('student', 'contact_03.1'), ('student', 'adult_demographics_03'),
    ('parent', 'student_demographics_06'),
])
def test_merged_projection_never_overwrites_a_present_opposite_role_value(tmp_path, role, field):
    row = merged_record(role)
    row['raw'][field] = 'Present value stays exact'
    row['raw_hash'] = digest(row['raw'])
    selected = merged_csv_row(row)
    path = write_csv(tmp_path / 'present.csv', selected)
    assert flags.preview_csv(path, inv(row), merged_role_structural_blanks=True)['matched_csv_rows'] == 1
    selected[field] = ''
    write_csv(path, selected)
    assert flags.preview_csv(path, inv(row), merged_role_structural_blanks=True)['matched_csv_rows'] == 0
    assert row['raw'][field] == 'Present value stays exact'


@pytest.mark.parametrize('value,expected', [
    (' 001980 ', '001980'), ('1980.0', '1980.0'), ('1.98e3', '1.98e3'),
    ('００１９８０', '001980'), ('１９８０．０', '1980.0'), ('１．９８ｅ３', '1.98e3'),
])
def test_numeric_looking_strings_keep_exact_nfkc_trimmed_text(value, expected):
    assert flags.scalar(value) == expected
    assert flags.scalar(value) != flags.scalar(1980)
    assert flags.scalar(1980) == flags.scalar(1980.0) == '1980'


@pytest.mark.parametrize('value', ['023450001', '23450001.0', '2.3450001e7'])
def test_numeric_string_variants_do_not_collapse_into_csv_match(tmp_path, value):
    row = record()
    selected = marked(row)
    row['raw']['contact_01'] = value
    row['raw_hash'] = digest(row['raw'])
    result = flags.preview_csv(write_csv(tmp_path / 'string-variant.csv', selected), inv(row))
    assert result['observations'][0]['outcome'] == 'unmatched'


@pytest.mark.parametrize('nonidentical', [False, True])
def test_merged_projection_keeps_full_raw_copy_proof(ledger, tmp_path, nonidentical):
    row = merged_record('student')
    other = deepcopy(row)
    other['submission_id'] = 'toy-merged-copy'
    if nonidentical:
        other['raw']['other_item'] = 'Distinct full payload'
        other['raw_hash'] = digest(other['raw'])
    path = write_csv(tmp_path / 'merged-copies.csv', merged_csv_row(row))
    report = flags.import_csv(ledger, path, inv(row, other), operator='Invented operator',
                              merged_role_structural_blanks=True, copy_policy=COPY_POLICY)
    assert report['observations'][0]['outcome'] == ('ambiguous_nonidentical' if nonidentical else 'matched')
    assert report['distinct_matched_ids'] == (0 if nonidentical else 2)
    assert flags.compile_snapshot(ledger, inv(row, other), operator='Invented reviewer')['status'] == (
        'blocked' if nonidentical else 'accepted')


def test_merged_projection_two_roles_import_replay_and_core_manifest(ledger, tmp_path):
    rows = [merged_record('student'), merged_record('parent')]
    original = deepcopy(rows)
    inventory = inv(*rows)
    path = write_csv(tmp_path / 'two-roles.csv', *(merged_csv_row(r) for r in rows))
    report = flags.import_csv(ledger, path, inventory, operator='Invented operator',
                              merged_role_structural_blanks=True, copy_policy=COPY_POLICY)
    assert report['selected_csv_rows'] == report['matched_csv_rows'] == report['distinct_matched_ids'] == 2
    before = flags.status(ledger, include_history=True)
    replay = flags.import_csv(ledger, path, inventory, operator='Retry operator',
                              merged_role_structural_blanks=True, copy_policy=COPY_POLICY)
    assert replay['idempotent'] and replay['flag_counts']['newly_active'] == 0
    assert flags.status(ledger, include_history=True) == before
    target = tmp_path / 'merged.manifest.json'
    snapshot = flags.export_manifest(ledger, inventory, target, operator='Invented reviewer')
    assert snapshot['status'] == 'accepted'
    assert validate_manifest(json.loads(target.read_bytes()), rows, inventory.release_id) == frozenset(
        {'toy-merged-student', 'toy-merged-parent'})
    assert rows == original


def test_merged_projection_option_requires_an_explicit_boolean(tmp_path):
    row = merged_record('student')
    path = write_csv(tmp_path / 'option.csv', merged_csv_row(row))
    with pytest.raises(flags.FlagError, match='structural_blank_option_invalid'):
        flags.preview_csv(path, inv(row), merged_role_structural_blanks='yes')


def test_cli_merged_projection_is_opt_in_and_fingerprinted(tmp_path):
    row = merged_record('student')
    inventory = tmp_path / 'merged-inventory.json'
    inventory.write_text(json.dumps(dict(format=flags.INVENTORY_FORMAT,
        release_id='toy-merged-cli-release', records=[row])))
    path = write_csv(tmp_path / 'merged.csv', merged_csv_row(row))
    registry = tmp_path / 'merged.sqlite3'
    def run(*args):
        r = subprocess.run([sys.executable, '-m', 'study2.manual_flags', *map(str, args)],
            text=True, capture_output=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    run('init', '--registry', registry, '--operator', 'Invented operator')
    strict = run('preview', '--csv', path, '--inventory', inventory)
    projected = run('preview', '--csv', path, '--inventory', inventory, '--merged-role-structural-blanks')
    assert strict['matched_csv_rows'] == 0 and projected['matched_csv_rows'] == 1
    assert strict['batch_id'] != projected['batch_id']
    imported = run('import', '--registry', registry, '--csv', path, '--inventory', inventory,
                   '--operator', 'Invented operator', '--merged-role-structural-blanks')
    assert imported['distinct_matched_ids'] == 1


def restored_held_case(ledger, tmp_path):
    row = record()
    import_one(ledger, tmp_path, [row], filename='held-week1.csv')
    flags.decide_flags(ledger, ['toy-a'], action='remove', operator='Invented reviewer', reason='Correction')
    held = import_one(ledger, tmp_path, [row], inventory=inv(row, release='held-week2'), filename='held-week2.csv')
    observation = held['observations'][0]['observation_id']
    assert flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')['status'] == 'blocked'
    flags.decide_flags(ledger, ['toy-a'], action='restore', inventory=inv(row),
                       operator='Invented reviewer', reason='Verified original evidence')
    assert not flags.status(ledger)['pending']
    return row, observation


def test_completed_held_resolution_survives_sequential_multiple_rebinds(ledger, tmp_path):
    row, original_id = restored_held_case(ledger, tmp_path)
    completed = flags.status(ledger, include_history=True)
    original = completed['observations'][original_id]
    decision = original['resolved_event']
    assert next(e for e in completed['history'] if e['seq'] == decision)['action'] == 'restore'
    for version in ('v2', 'v3'):
        later = {**deepcopy(row), 'version_id': version}
        current = inv(later, release='held-' + version)
        held = import_one(ledger, tmp_path, [later], inventory=current, filename=version + '.csv')
        new_id = held['observations'][0]['observation_id']
        assert {r['observation_id'] for r in flags.status(ledger)['pending']} == {new_id}
        flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=current,
                           operator='Invented reviewer', reason='Verified later ' + version)
        state = flags.status(ledger, include_history=True)
        assert not state['pending']
        assert state['observations'][original_id] == original
        assert state['observations'][new_id]['resolved_event'] > decision
        assert state['history'][:len(completed['history'])] == completed['history']
        assert flags.compile_snapshot(ledger, current, operator='Invented reviewer')['status'] == 'accepted'
    # Closed historical evidence cannot bypass the CURRENT flag/version check.
    old_inventory = flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')
    assert old_inventory['status'] == 'blocked'
    assert old_inventory['blockers'][0]['code'] == 'active_flag_content_changed'


def test_new_observations_after_resolution_remain_pending_and_are_not_blanket_dismissed(ledger, tmp_path):
    row, old_id = restored_held_case(ledger, tmp_path)
    newer = {**deepcopy(row), 'version_id': 'v2'}
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(newer),
                       operator='Invented reviewer', reason='Verified v2')
    new_held = import_one(ledger, tmp_path, [row], inventory=inv(row, release='new-old-evidence'), filename='new-old.csv')
    held_id = new_held['observations'][0]['observation_id']
    unknown = {**marked(newer), 'Survey': 'No such survey'}
    unknown_report = flags.import_csv(ledger, write_csv(tmp_path / 'unmatched-new.csv', unknown),
                                      inv(newer), operator='Invented operator')
    other = record('toy-other', raw={**row['raw'], 'different_full_item': 'distinct'})
    ambiguity = flags.import_csv(ledger, write_csv(tmp_path / 'ambiguous-new.csv', marked(newer)),
        inv(newer, other), operator='Invented operator', copy_policy=COPY_POLICY)
    latest = {**deepcopy(row), 'version_id': 'v3'}
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(latest),
                       operator='Invented reviewer', reason='Verified v3 does not resolve old-pin evidence')
    state = flags.status(ledger)
    assert {r['observation_id'] for r in state['pending']} == {
        held_id, unknown_report['observations'][0]['observation_id'], ambiguity['observations'][0]['observation_id']}
    assert {r['code'] for r in state['pending']} == {'held_existing_decision', 'unmatched', 'ambiguous_nonidentical'}
    assert state['observations'][old_id]['resolved_event'] is not None
    assert state['observations'][held_id].get('resolved_event') is None
    assert flags.compile_snapshot(ledger, inv(latest), operator='Invented reviewer')['status'] == 'blocked'


def test_legacy_held_resolution_is_recovered_from_history_without_new_decision(ledger, tmp_path):
    row, old_id = restored_held_case(ledger, tmp_path)
    later = {**deepcopy(row), 'version_id': 'v2'}
    held = import_one(ledger, tmp_path, [later], inventory=inv(later), filename='legacy-v2.csv')
    new_id = held['observations'][0]['observation_id']
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(later),
                       operator='Invented reviewer', reason='Verified v2')
    reference = flags.status(ledger, include_history=True)
    expected = {key: reference['observations'][key]['resolved_event'] for key in (old_id, new_id)}
    # r1/r2 stored exactly this candidate/history state, without resolution refs.
    with sqlite3.connect(ledger) as db:
        value = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
        for observation in value['observations'].values():
            observation.pop('resolved_event', None)
        db.execute('UPDATE ledger SET value=?', (json.dumps(value),))
    before = ledger.read_bytes()
    recovered = flags.status(ledger, include_history=True)
    assert ledger.read_bytes() == before  # Read-only history proof writes nothing.
    assert not recovered['pending'] and recovered['history'] == reference['history']
    assert {key: recovered['observations'][key]['resolved_event'] for key in expected} == expected
    assert flags.compile_snapshot(ledger, inv(later), operator='Invented reviewer')['status'] == 'accepted'
    with sqlite3.connect(ledger) as db:
        persisted = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
    assert {key: persisted['observations'][key]['resolved_event'] for key in expected} == expected


def test_held_resolution_and_flag_rebind_roll_back_together(ledger, tmp_path, monkeypatch):
    row, _ = restored_held_case(ledger, tmp_path)
    later = {**deepcopy(row), 'version_id': 'v2'}
    import_one(ledger, tmp_path, [later], inventory=inv(later), filename='rollback-v2.csv')
    before = flags.status(ledger, include_history=True)
    def fail(*args):
        raise RuntimeError('invented resolution precommit failure')
    with monkeypatch.context() as patch:
        patch.setattr(flags, '_commit', fail)
        with pytest.raises(RuntimeError):
            flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(later),
                               operator='Invented reviewer', reason='Verified v2')
    assert flags.status(ledger, include_history=True) == before


def test_partial_copy_resolution_waits_for_every_candidate_then_stays_closed(ledger, tmp_path):
    a, b = record(), record('toy-copy')
    import_one(ledger, tmp_path, [a], inventory=inv(a, b), copy_policy=COPY_POLICY)
    flags.decide_flags(ledger, ['toy-a', 'toy-copy'], action='remove',
                       operator='Invented reviewer', reason='Both removed')
    held = import_one(ledger, tmp_path, [a], inventory=inv(a, b, release='copies-held'),
                      filename='copies-held.csv', copy_policy=COPY_POLICY)
    obs_id = held['observations'][0]['observation_id']
    flags.decide_flags(ledger, ['toy-a'], action='restore', inventory=inv(a, b),
                       operator='Invented reviewer', reason='First copy verified')
    assert flags.status(ledger)['pending']
    flags.decide_flags(ledger, ['toy-copy'], action='restore', inventory=inv(a, b),
                       operator='Invented reviewer', reason='Second copy verified')
    closed = deepcopy(flags.status(ledger)['observations'][obs_id])
    assert not flags.status(ledger)['pending']
    later_a = {**deepcopy(a), 'version_id': 'v2'}
    flags.decide_flags(ledger, ['toy-a'], action='rebind', inventory=inv(later_a, b),
                       operator='Invented reviewer', reason='New version of one verified copy')
    assert flags.status(ledger)['observations'][obs_id] == closed
    assert flags.compile_snapshot(ledger, inv(later_a, b), operator='Invented reviewer')['status'] == 'accepted'


@pytest.mark.parametrize('outcome', ['matched', 'unmatched', 'copy_policy_required',
                                    'ambiguous_nonidentical', 'unverified_copies'])
def test_nonheld_observation_cannot_borrow_an_unrelated_resolution_event(ledger, tmp_path, outcome):
    known = distinct('toy-known', 'Known unrelated flag')
    import_one(ledger, tmp_path, [known], filename='known-unrelated.csv')
    a, b = record(), record('toy-copy')
    selected = marked(a)
    rows, options = [known, a], {}
    if outcome == 'unmatched':
        selected['Survey'] = 'Unmatched invented survey'
    elif outcome != 'matched':
        if outcome == 'ambiguous_nonidentical':
            b['raw']['other_item'] = 'Different full payload'
            b['raw_hash'] = digest(b['raw'])
            options['copy_policy'] = COPY_POLICY
        elif outcome == 'unverified_copies':
            for r in (a, b):
                r.update(r.pop('raw'))
            options.update(copy_policy=COPY_POLICY, field_container='record')
        rows.append(b)
    inventory = inv(*rows)
    report = flags.import_csv(ledger, write_csv(tmp_path / 'scope-observation.csv', selected),
                              inventory, operator='Invented operator', **options)
    assert report['observations'][0]['outcome'] == outcome
    flags.decide_flags(ledger, ['toy-known'], action='remove',
                       operator='Invented reviewer', reason='Remove only the unrelated known flag')
    state = flags.status(ledger, include_history=True)
    unrelated = next(e['seq'] for e in state['history'] if e['action'] == 'remove')
    obs_id = report['observations'][0]['observation_id']
    with sqlite3.connect(ledger) as db:
        value = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
        assert value['observations'][obs_id]['dismissed_event'] is None
        value['observations'][obs_id]['resolved_event'] = unrelated
        db.execute('UPDATE ledger SET value=?', (json.dumps(value),))
    before = ledger.read_bytes()
    with pytest.raises(flags.FlagError, match='invalid_registry_resolution'):
        flags.compile_snapshot(ledger, inventory, operator='Invented reviewer')
    output = tmp_path / 'prior-manifest.json'
    output.write_bytes(b'Prior artifact remains unchanged')
    with pytest.raises(flags.FlagError, match='invalid_registry_resolution'):
        flags.export_manifest(ledger, inventory, output, operator='Invented reviewer')
    assert ledger.read_bytes() == before
    assert output.read_bytes() == b'Prior artifact remains unchanged'


def test_held_resolution_cannot_reference_another_flags_later_removal(ledger, tmp_path):
    row, obs_id = restored_held_case(ledger, tmp_path)
    other = distinct('toy-unrelated', 'Unrelated')
    import_one(ledger, tmp_path, [other], inventory=inv(row, other), filename='other.csv')
    flags.decide_flags(ledger, ['toy-unrelated'], action='remove',
                       operator='Invented reviewer', reason='Unrelated later decision')
    state = flags.status(ledger, include_history=True)
    unrelated = state['history'][-1]['seq']
    assert unrelated != state['observations'][obs_id]['resolved_event']
    with sqlite3.connect(ledger) as db:
        value = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
        value['observations'][obs_id]['resolved_event'] = unrelated
        db.execute('UPDATE ledger SET value=?', (json.dumps(value),))
    before = ledger.read_bytes()
    with pytest.raises(flags.FlagError, match='invalid_registry_resolution_history'):
        flags.compile_snapshot(ledger, inv(row, other), operator='Invented reviewer')
    assert ledger.read_bytes() == before


def test_incomplete_held_copy_resolution_cannot_borrow_a_partial_decision(ledger, tmp_path):
    a, b = record(), record('toy-copy')
    import_one(ledger, tmp_path, [a], inventory=inv(a, b), copy_policy=COPY_POLICY)
    flags.decide_flags(ledger, ['toy-a', 'toy-copy'], action='remove',
                       operator='Invented reviewer', reason='Both removed')
    held = import_one(ledger, tmp_path, [a], inventory=inv(a, b, release='partial-held'),
                      filename='partial-held.csv', copy_policy=COPY_POLICY)
    obs_id = held['observations'][0]['observation_id']
    flags.decide_flags(ledger, ['toy-a'], action='restore', inventory=inv(a, b),
                       operator='Invented reviewer', reason='Only first copy verified')
    state = flags.status(ledger, include_history=True)
    assert state['pending'] and state['observations'][obs_id].get('resolved_event') is None
    partial = state['history'][-1]['seq']
    with sqlite3.connect(ledger) as db:
        value = json.loads(db.execute('SELECT value FROM ledger').fetchone()[0])
        value['observations'][obs_id]['resolved_event'] = partial
        db.execute('UPDATE ledger SET value=?', (json.dumps(value),))
    with pytest.raises(flags.FlagError, match='invalid_registry_resolution_history'):
        flags.compile_snapshot(ledger, inv(a, b), operator='Invented reviewer')


def test_valid_held_resolution_is_bound_to_original_candidates_and_history(ledger, tmp_path):
    row, obs_id = restored_held_case(ledger, tmp_path)
    state = flags.status(ledger, include_history=True)
    observation = state['observations'][obs_id]
    event = next(e for e in state['history'] if e['seq'] == observation['resolved_event'])
    assert observation['outcome'] == 'held_existing_decision'
    assert observation['candidates'] == [flags._pin(row)]
    assert event['action'] == 'restore' and event['seq'] > observation['event_seq']
    assert event['payload']['after_pins']['toy-a'] == observation['candidates'][0]
    report = flags.compile_snapshot(ledger, inv(row), operator='Invented reviewer')
    assert report['status'] == 'accepted' and not state['pending']
