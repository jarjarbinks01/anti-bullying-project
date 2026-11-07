import csv
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from study2 import flag_binding as binding
from study2 import manual_flags as flags
from study2.common import PipelineError, digest
from study2.group_cleaning import exclusion_manifest

R1 = 'RUN_' + '1' * 32
R2 = 'RUN_' + '2' * 32
R3 = 'RUN_' + '3' * 32
AT = '2026-10-28T00:00:00+00:00'


def record(name, role='student'):
    raw = {key: '' for key in flags.MATCH_FIELDS}
    raw.update(Survey='fixture-' + name, synthetic=name)
    return dict(submission_id=name, version_id='version-' + name, role=role,
                raw_hash=digest(raw), raw=raw, child_id='child-' + name,
                selected_wave='T0', status='eligible')


def release(parent, release_id, rows):
    folder = parent / release_id
    folder.mkdir()
    (folder / 'summary.json').write_text(json.dumps({'release_id': release_id}))
    with gzip.open(folder / 'records.jsonl.gz', 'wt', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row) + '\n')
    return folder


def setup(tmp_path, monkeypatch, *, overlapping_policy=False):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'analysis_eligibility').mkdir()
    control = state / 'analysis_eligibility' / 'control'
    control.mkdir()
    (control / 'control.json').write_text(json.dumps({'format': binding.CONTROL_FORMAT,
        'baseline_release_id': R1, 'baseline_policy_head': 'a' * 64}))
    releases = tmp_path / 'scientific'
    releases.mkdir()
    rows = [record('remove'), record('keep'), record('policy'), record('ordinary')]
    first, second = release(releases, R1, rows), release(releases, R2, rows)
    inventory = flags.Inventory.from_records(R1, rows)
    spam = exclusion_manifest(rows, R1, {'remove', 'keep'}, operator='fixture', at=AT)
    registry = control / 'registry.sqlite3'
    flags.initialize_registry(registry, operator='fixture')
    flags.seed_manifest(registry, spam, inventory, operator='fixture', reason='baseline')
    flags.decide_flags(registry, ['remove'], action='remove', operator='fixture', reason='genuine')
    policy_root = tmp_path / 'group-policy'
    policy_root.mkdir()
    (policy_root / 'CURRENT.json').write_text('{}')
    group = policy_root / 'generation'
    group.mkdir()
    group_registry = group / 'policy-flags.sqlite'
    flags.initialize_registry(group_registry, operator='fixture')
    group_ids = {'policy', 'remove'} if overlapping_policy else {'policy'}
    group_manifest = exclusion_manifest(rows, R1, group_ids, operator='fixture', at=AT)
    flags.seed_manifest(group_registry, group_manifest, inventory, operator='fixture', reason='group baseline')
    active = dict(folder=group, policy={'policy_active': True, 'release_id': R1},
                  policy_manifest=group_manifest, receipt={'review': {'accepted': True}},
                  pointer={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr(binding, 'read_active', lambda root: active)
    monkeypatch.setenv(binding.CONTROL_ENV, str(control / 'control.json'))
    monkeypatch.setenv(binding.POLICY_ENV, str(policy_root / 'CURRENT.json'))
    monkeypatch.delenv(binding.MANIFEST_ENV, raising=False)
    db = sqlite3.connect(state / 'study2.sqlite')
    db.executescript('CREATE TABLE releases(release_id TEXT PRIMARY KEY,run_id TEXT,path TEXT,stats_json TEXT);'
                     'CREATE TABLE publication(singleton INTEGER PRIMARY KEY,release_id TEXT);'
                     'CREATE TABLE runs(run_id TEXT PRIMARY KEY,status TEXT);'
                     'CREATE TABLE release_candidates(release_id TEXT,payload_json TEXT);')
    db.executemany('INSERT INTO releases VALUES(?,?,?,?)',
        [(R1, R1, str(first), '{}'), (R2, R2, str(second), '{}')])
    db.executemany('INSERT INTO runs VALUES(?,?)', [(R1, 'published'), (R2, 'validated')])
    db.execute('INSERT INTO publication VALUES(1,?)', (R1,))
    db.commit()
    cfg = {'state_dir': str(state), 'release_dir': str(releases),
           'recovery_policy': {'mode': 'lean', 'required_assets': [
               {'kind': 'directory', 'path': str(policy_root), 'restore_path': 'dependencies/policy'}]}}
    initial = binding.prepare_generation(cfg, first)
    monkeypatch.setenv(binding.MANIFEST_ENV, str(initial))
    return dict(state=state, control=control, registry=registry, group_registry=group_registry,
                first=first, second=second, rows=rows, active=active, cfg=cfg, db=db,
                initial=initial, policy_root=policy_root, spam=spam, inventory=inventory)


@pytest.fixture
def env(tmp_path, monkeypatch):
    result = setup(tmp_path, monkeypatch)
    # The current managed consumer contract also requires a real bound workload.
    from test_workload_activation_guard import bind_workload
    result['workload'], result['pointer'], result['summary'] = bind_workload(result, monkeypatch)
    yield result
    result['db'].close()


def rebind_workload(env, release_id, manifest):
    """Explicit synthetic operator step, never automatic production rebinding."""
    summary = {**env['summary'], 'release_id': release_id,
               'exclusion_manifest_revision': json.loads(Path(manifest).read_text())['revision']}
    env['workload'].write_text(json.dumps(summary))
    pointer = {**env['pointer'], 'release_id': release_id,
               'workload_sha256': hashlib.sha256(env['workload'].read_bytes()).hexdigest()}
    (env['state'] / 'CURRENT_REVIEW_DISPOSITION.json').write_text(json.dumps(pointer))


def ids(path):
    return {e['submission_id'] for e in json.loads(Path(path).read_text())['entries']}


def simulate_reviewed_future(env):
    # Isolates generation mechanics only. The real group-control workflow's
    # reviewed-head transition remains an explicit integration blocker.
    env['active']['policy']['release_id'] = R2
    revision = 'f' * 64
    env['active']['policy']['proposal_revision'] = revision
    env['active']['proposal'] = {'revision': revision}
    env['active']['receipt']['review'] = {'format': 'study2_group_cleaning_acceptance_v1',
        'proposal_revision': revision, 'accepted': True, 'reviewer': 'fixture',
        'reason': 'fixture', 'review_manifest_sha256': 'e' * 64}


def test_idempotency_and_future_release_preserve_tombstone(env):
    assert binding.resolve_current(env['cfg']) == env['initial']
    assert ids(env['initial']) == {'keep', 'policy'}
    before = env['initial'].read_bytes()
    history_before = flags.status(env['registry'])['event_count']
    assert binding.prepare_generation(env['cfg'], env['first']) == env['initial']
    assert env['initial'].read_bytes() == before
    assert flags.status(env['registry'])['event_count'] == history_before
    again = flags.decide_flags(env['registry'], ['remove'], action='remove', operator='fixture', reason='genuine')
    assert again['idempotent'] and again['changed'] == 0
    replay = flags.seed_manifest(env['registry'], env['spam'], env['inventory'], operator='fixture', reason='retry')
    assert replay['idempotent'] and flags.status(env['registry'])['flags']['remove']['state'] == 'removed'
    simulate_reviewed_future(env)
    with binding.guarded_publication(env['cfg'], env['second'], R2) as after:
        env['db'].execute('UPDATE publication SET release_id=? WHERE singleton=1', (R2,))
        env['db'].commit()
    # Direct publication does not authorize the old workload for a new release.
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(env['cfg'])
    rebind_workload(env, R2, after)
    assert binding.resolve_current(env['cfg']) == after
    assert ids(after) == {'keep', 'policy'}


def test_other_policy_reason_survives_spam_removal(tmp_path, monkeypatch):
    item = setup(tmp_path, monkeypatch, overlapping_policy=True)
    try:
        assert flags.status(item['registry'])['flags']['remove']['state'] == 'removed'
        assert ids(item['initial']) == {'keep', 'policy', 'remove'}
    finally:
        item['db'].close()


def test_later_review_csv_cannot_implicitly_restore_tombstone(env, tmp_path):
    csv_path = tmp_path / 'synthetic-review.csv'
    row = {key: '' for key in flags.COLUMNS}
    row.update(env['rows'][0]['raw'])
    row['Review'] = flags.MARKER
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=flags.COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerow(row)
    report = flags.import_csv(env['registry'], csv_path, env['inventory'], operator='fixture')
    assert report['flag_counts']['held'] == 1
    assert flags.status(env['registry'])['flags']['remove']['state'] == 'removed'
    with pytest.raises(PipelineError, match='flag_ledger_pending_evidence'):
        binding.resolve_current(env['cfg'])


def test_ledger_or_policy_drift_fails_closed(env):
    flags.decide_flags(env['registry'], ['keep'], action='remove', operator='fixture', reason='changed')
    with pytest.raises(PipelineError, match='flag_ledger_generation_mismatch'):
        binding.resolve_current(env['cfg'])
    with pytest.raises(PipelineError, match='flag_ledger_generation_mismatch'):
        with binding.guarded_publication(env['cfg'], env['second'], R2):
            pytest.fail('publication must not start')


def test_group_head_drift_fails_closed(env):
    env['active']['pointer']['manifest_sha256'] = 'b' * 64
    with pytest.raises(PipelineError, match='baseline_group_policy_head_changed'):
        binding.resolve_current(env['cfg'])


def test_unreviewed_group_carry_blocks_future_publication(env):
    next_inventory = flags.load_inventory(release_folder=env['second'])
    carried = flags.compile_snapshot(env['registry'], next_inventory, operator='fixture')
    assert carried['status'] == 'accepted'
    assert {row['submission_id'] for row in carried['manifest']['entries']} == {'keep'}
    with pytest.raises(PipelineError, match='reviewed_group_policy_required_for_release'):
        with binding.guarded_publication(env['cfg'], env['second'], R2):
            pytest.fail('unreviewed group policy must not publish')
    assert binding.resolve_current(env['cfg']) == env['initial']


def test_wrong_review_binding_blocks_future_publication(env):
    simulate_reviewed_future(env)
    env['active']['receipt']['review']['proposal_revision'] = 'd' * 64
    with pytest.raises(PipelineError, match='reviewed_group_policy_required_for_release'):
        with binding.guarded_publication(env['cfg'], env['second'], R2):
            pytest.fail('mismatched acceptance must not publish')


def test_manifest_tampering_and_missing_release_fail_closed(env):
    env['initial'].write_bytes(b'{}')
    with pytest.raises(PipelineError, match='flag_generation_file_changed'):
        binding.resolve_current(env['cfg'])
    env['db'].execute('UPDATE publication SET release_id=? WHERE singleton=1', (R2,))
    env['db'].commit()
    with pytest.raises(PipelineError, match='flag_generation_missing'):
        binding.resolve_current(env['cfg'])


def test_control_descriptor_tampering_fails_closed(env):
    path = env['control'] / 'control.json'
    descriptor = json.loads(path.read_text())
    descriptor['baseline_release_id'] = R2
    path.write_text(json.dumps(descriptor))
    with pytest.raises(PipelineError, match='flag_ledger_generation_mismatch'):
        binding.resolve_current(env['cfg'])


@pytest.mark.parametrize('fail_name', ['spam.json', 'policy.json', 'combined.json', 'generation.json'])
def test_partial_generation_never_replaces_current(env, monkeypatch, fail_name):
    simulate_reviewed_future(env)
    original = flags._exclusive_output
    def fail(path, data):
        if Path(path).name == fail_name:
            raise OSError('injected write failure')
        return original(path, data)
    monkeypatch.setattr(flags, '_exclusive_output', fail)
    with pytest.raises(OSError, match='injected'):
        binding.prepare_generation(env['cfg'], env['second'])
    assert binding.resolve_current(env['cfg']) == env['initial']
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R1
    monkeypatch.setattr(flags, '_exclusive_output', original)
    assert ids(binding.prepare_generation(env['cfg'], env['second'])) == {'keep', 'policy'}


@pytest.mark.parametrize('fail_call', [1, 2])
def test_sync_interrupt_keeps_old_release_and_retry_is_safe(env, monkeypatch, fail_call):
    simulate_reviewed_future(env)
    original = binding._sync_dir
    calls = []
    def fail(path):
        calls.append(path)
        if len(calls) == fail_call:
            raise OSError('injected sync failure')
        original(path)
    monkeypatch.setattr(binding, '_sync_dir', fail)
    with pytest.raises(OSError, match='injected'):
        binding.prepare_generation(env['cfg'], env['second'])
    assert binding.resolve_current(env['cfg']) == env['initial']
    monkeypatch.setattr(binding, '_sync_dir', original)
    assert ids(binding.prepare_generation(env['cfg'], env['second'])) == {'keep', 'policy'}


def test_rename_interrupt_keeps_old_release_and_retry_is_safe(env, monkeypatch):
    simulate_reviewed_future(env)
    original = binding.os.rename
    monkeypatch.setattr(binding.os, 'rename', lambda *args: (_ for _ in ()).throw(OSError('injected rename failure')))
    with pytest.raises(OSError, match='injected'):
        binding.prepare_generation(env['cfg'], env['second'])
    assert binding.resolve_current(env['cfg']) == env['initial']
    monkeypatch.setattr(binding.os, 'rename', original)
    assert ids(binding.prepare_generation(env['cfg'], env['second'])) == {'keep', 'policy'}


@pytest.mark.parametrize('changed_id,expected', [('keep', 'flag_ledger_export_blocked'),
                                                  ('policy', 'group_policy_pin_changed'),
                                                  ('remove', 'removed_flag_content_changed')])
def test_changed_future_pin_blocks_before_publication(env, tmp_path, changed_id, expected):
    simulate_reviewed_future(env)
    env['active']['policy']['release_id'] = R3
    changed = [dict(r) for r in env['rows']]
    next(r for r in changed if r['submission_id'] == changed_id)['version_id'] = 'changed-version'
    newer = release(tmp_path / 'scientific', R3, changed)
    with pytest.raises(PipelineError, match=expected):
        binding.prepare_generation(env['cfg'], newer)
    assert binding.resolve_current(env['cfg']) == env['initial']
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R1


def test_registry_reader_prevents_concurrent_commit(env):
    simulate_reviewed_future(env)
    with binding.guarded_publication(env['cfg'], env['second'], R2):
        other = sqlite3.connect(env['registry'], timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError):
                other.execute('BEGIN IMMEDIATE')
                other.execute("UPDATE ledger SET value=value WHERE id=1")
                other.commit()
            other.rollback()
        finally:
            other.close()


def test_recovery_captures_and_relocates_all_bindings(env, tmp_path, monkeypatch):
    from study2.lean_recovery import recovery_assets, recovery_bindings
    assets = recovery_assets(env['cfg'])
    paths = {str(p.resolve()) for p in assets.values()}
    for path in (env['control'] / 'control.json', env['registry'],
                 env['initial'], env['policy_root'] / 'CURRENT.json'):
        assert str(path.resolve()) in paths
    recovered = recovery_bindings(env['cfg'], assets)['environment']
    assert recovered[binding.CONTROL_ENV].endswith('/control/control.json')
    assert recovered[binding.POLICY_ENV] == 'dependencies/policy/CURRENT.json'
    assert recovered[binding.MANIFEST_ENV].endswith('/combined.json')
    restored = tmp_path / 'restored'
    restored.mkdir()
    for relative, source in assets.items():
        destination = restored / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    shutil.copyfile(env['state'] / 'study2.sqlite', restored / 'study2.sqlite')
    recovered_release = release(restored, R1, env['rows'])
    with sqlite3.connect(restored / 'study2.sqlite') as db:
        db.execute('UPDATE releases SET path=? WHERE release_id=?', (str(recovered_release), R1))
    for name, relative in recovered.items():
        monkeypatch.setenv(name, str(restored / relative) if relative != '.' else str(restored))
    relocated_active = dict(env['active'])
    relocated_active['folder'] = restored / 'dependencies/policy/generation'
    monkeypatch.setattr(binding, 'read_active', lambda root: relocated_active)
    # Recovery retains absolute references until explicitly rebound.
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current({'state_dir': str(restored)})
    pointer_path = restored / 'CURRENT_REVIEW_DISPOSITION.json'
    pointer = json.loads(pointer_path.read_text())
    pointer['workload_path'] = os.environ['STUDY2_CURRENT_REVIEW_WORKLOAD']
    pointer_path.write_text(json.dumps(pointer))
    assert ids(binding.resolve_current({'state_dir': str(restored)})) == {'keep', 'policy'}


def test_export_guard_holds_shared_writer_lock(env):
    with binding.guarded_current(env['cfg']):
        with (env['state'] / 'writer.lock').open('a') as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_release_pin_mismatch_and_registry_sidecar_block(env):
    simulate_reviewed_future(env)
    with pytest.raises(PipelineError, match='flag_target_release_mismatch'):
        with binding.guarded_publication(env['cfg'], env['second'], R3):
            pass
    journal = Path(str(env['registry']) + '-journal')
    journal.write_bytes(b'synthetic pending journal')
    with pytest.raises(PipelineError, match='registry_recovery_required'):
        binding.resolve_current(env['cfg'])


def test_real_publication_failure_then_success(env, monkeypatch):
    simulate_reviewed_future(env)
    from study2 import runner, dyads, dyad_operator, review_core, lean_recovery
    row = {'release_id': R2, 'run_id': R2, 'path': str(env['second']), 'stats_json': '{}'}
    monkeypatch.setattr(runner, 'verify_release', lambda db, release_id: row)
    monkeypatch.setattr(runner, 'validation_report', lambda *args: None)
    monkeypatch.setattr(review_core, 'backup_workspace', lambda *args: 'synthetic-review-backup')
    monkeypatch.setattr(dyad_operator, 'recovery_check', lambda *args: None)
    tracking = env['state'] / 'synthetic-tracking'
    tracking.mkdir()
    (tracking / 'manifest.json').write_text(json.dumps({'tracking_hash': 'fixture'}))
    monkeypatch.setattr(dyad_operator, 'backup_tracking', lambda *args, **kwargs: str(tracking))
    monkeypatch.setattr(dyads, 'publish_memberships', lambda *args: None)
    monkeypatch.setattr(lean_recovery, 'recovery_assets', lambda cfg: {})
    current = Path(env['cfg']['release_dir']) / 'CURRENT.json'
    current.write_text(json.dumps({'release_id': R1}))
    original_atomic = runner.atomic_json
    calls = []
    def fail_once(path, value):
        if Path(path) == current and not calls:
            calls.append(1)
            raise OSError('injected publication pointer failure')
        return original_atomic(path, value)
    monkeypatch.setattr(runner, 'atomic_json', fail_once)
    with pytest.raises(OSError, match='injected'):
        runner.publish_release(env['db'], env['cfg'], R2)
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R1
    assert json.loads(current.read_text())['release_id'] == R1
    assert os.environ[binding.MANIFEST_ENV] == str(env['initial'])
    assert binding.resolve_current(env['cfg']) == env['initial']
    monkeypatch.setattr(runner, 'atomic_json', original_atomic)
    runner.publish_release(env['db'], env['cfg'], R2)
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R2
    assert json.loads(current.read_text())['release_id'] == R2
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(env['cfg'])
    rebind_workload(env, R2, Path(os.environ[binding.MANIFEST_ENV]))
    assert binding.resolve_current(env['cfg']) == Path(os.environ[binding.MANIFEST_ENV])
    assert ids(binding.resolve_current(env['cfg'])) == {'keep', 'policy'}
    old_row = {'release_id': R1, 'run_id': R1, 'path': str(env['first']), 'stats_json': '{}'}
    monkeypatch.setattr(runner, 'verify_release', lambda db, release_id: old_row)
    runner.publish_release(env['db'], env['cfg'], R1, rollback=True)
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(env['cfg'])
    rebind_workload(env, R1, env['initial'])
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R1
    assert binding.resolve_current(env['cfg']) == env['initial']
    assert os.environ[binding.MANIFEST_ENV] == str(env['initial'])


def test_recovery_coverage_failure_rolls_back_publication(env, monkeypatch):
    simulate_reviewed_future(env)
    from study2 import runner, dyads, dyad_operator, review_core, lean_recovery
    row = {'release_id': R2, 'run_id': R2, 'path': str(env['second']), 'stats_json': '{}'}
    monkeypatch.setattr(runner, 'verify_release', lambda db, release_id: row)
    monkeypatch.setattr(runner, 'validation_report', lambda *args: None)
    monkeypatch.setattr(review_core, 'backup_workspace', lambda *args: 'fixture')
    monkeypatch.setattr(dyad_operator, 'recovery_check', lambda *args: None)
    tracking = env['state'] / 'tracking'
    tracking.mkdir()
    (tracking / 'manifest.json').write_text(json.dumps({'tracking_hash': 'fixture'}))
    monkeypatch.setattr(dyad_operator, 'backup_tracking', lambda *args, **kwargs: str(tracking))
    monkeypatch.setattr(dyads, 'publish_memberships', lambda *args: None)
    monkeypatch.setattr(lean_recovery, 'recovery_assets', lambda cfg: (_ for _ in ()).throw(PipelineError('coverage_failure')))
    current = Path(env['cfg']['release_dir']) / 'CURRENT.json'
    current.write_text(json.dumps({'release_id': R1}))
    with pytest.raises(PipelineError, match='coverage_failure'):
        runner.publish_release(env['db'], env['cfg'], R2)
    assert env['db'].execute('SELECT release_id FROM publication').fetchone()[0] == R1
    assert json.loads(current.read_text())['release_id'] == R1
    assert os.environ[binding.MANIFEST_ENV] == str(env['initial'])
    assert binding.resolve_current(env['cfg']) == env['initial']


def test_managed_consumers_reject_an_unbound_manifest(env, tmp_path):
    from study2.ac_export import export_student_ac
    from study2.static_export import export_static
    from study2.streamlit_eligibility import load_eligibility
    stale = tmp_path / 'stale.json'
    stale.write_text('{}')
    with pytest.raises(PipelineError, match='managed exclusion manifest mismatch'):
        export_student_ac(env['cfg'], tmp_path / 'student-export', manifest_path=stale,
                          enabled=True, dataset_version='fixture')
    assert not (tmp_path / 'student-export').exists()
    with pytest.raises(PipelineError, match='Managed exclusion manifest'):
        export_static(env['cfg'], tmp_path / 'static-export', manual_manifest={})
    assert not (tmp_path / 'static-export').exists()
    outcome = load_eligibility(env['first'], {'release_id': R1}, None, None,
                               manifest_path=stale, cfg=env['cfg'])
    assert not outcome.ready and outcome.reason == 'managed_exclusion_manifest_mismatch'
