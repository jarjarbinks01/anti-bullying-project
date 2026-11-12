"""One designated master; history retirement remains a separate reviewed action."""
import json
import sqlite3
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from study2 import checkpoints, dyad_operator, review_core
from study2.common import PipelineError, atomic_json, file_hash
from study2.lean_recovery import enabled, retention_plan
from study2.store import connect
from test_lean_recovery import lean, pointer


@pytest.fixture
def single(lean):
    lean['recovery_policy']['checkpoint_retention'] = 'single_master'
    return lean


def ledger(cfg):
    return json.loads((Path(cfg['state_dir'])/'DYAD_LEDGER.json').read_text())


def test_master_owns_reusable_tracking_and_compressed_review(single, tmp_path):
    state = Path(single['state_dir'])
    work = review_core.workspace(single)
    with work:
        review_core.event(work, 'synthetic', 'example', {'accepted': True})
    work.close()
    result = checkpoints.save_checkpoint(single, force=True)
    root = Path(result['path'])
    assert ledger(single)['bundle'] == str(root/'recovered_tracking')
    assert (root/'review.sqlite.gz').samefile(root/'recovered_tracking/review.sqlite.gz')
    db = connect(state)
    before = list((state/'dyad_backups').glob('bundle_*'))
    assert dyad_operator.backup_tracking(db, single) == str(root/'recovered_tracking')
    assert list((state/'dyad_backups').glob('bundle_*')) == before
    dyad_operator.recovery_check(db, single)
    db.close()
    # Both public recovery forms preserve the pending review workspace.
    for mode in ('checkpoint', 'administrative'):
        destination = tmp_path/mode
        if mode == 'checkpoint':
            checkpoints.restore_checkpoint(root, destination)
        else:
            dyad_operator.restore_bundle(root/'recovered_tracking', root/'study2.sqlite.gz', destination)
        with sqlite3.connect(destination/'review.sqlite') as restored:
            assert restored.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_replacement_keeps_history_but_only_current_is_required(single):
    first = Path(checkpoints.save_checkpoint(single, force=True)['path'])
    old_tracking = (first/'recovered_tracking/manifest.json').read_bytes()
    work = review_core.workspace(single)
    with work:
        review_core.event(work, 'synthetic', 'changed', {})
    work.close()
    final = Path(checkpoints.save_checkpoint(single, force=True)['path'])
    manifest = checkpoints.checkpoint_manifest(final)
    assert 'previous_verified_checkpoint' not in manifest
    assert manifest['supersedes_checkpoint']['path'] == str(first)
    assert first.is_dir() and (first/'recovered_tracking/manifest.json').read_bytes() == old_tracking
    assert ledger(single)['bundle'] == str(final/'recovered_tracking')
    plan = json.loads((Path(single['state_dir'])/'CHECKPOINT_RETENTION_PLAN.json').read_text())
    rows = {row['path']: row for row in plan['checkpoints']}
    assert rows[str(first)]['disposition'] == 'needs_dependency_review'
    assert rows[str(final)]['disposition'] == 'retain'
    assert not plan['automatic_deletion']
    assert all(not row['deletion_authorized'] for row in rows.values())
    single['recovery_policy']['protected_paths'] = [str(first)]
    protected = retention_plan(single, final, first)
    assert next(row for row in protected['checkpoints'] if row['path'] == str(first))['disposition'] == 'retain'


@pytest.mark.parametrize('failure', ['restore', 'pointer'])
def test_failed_replacement_keeps_master_and_ledger(single, failure):
    checkpoints.save_checkpoint(single, force=True)
    before, prior = pointer(single), ledger(single)
    atomic_json(Path(single['state_dir'])/'analysis_eligibility/changed.json', {'synthetic': 2})
    original = checkpoints.atomic_json
    def fail_pointer(path, value):
        if Path(path).name == 'CURRENT_CHECKPOINT.json':
            raise OSError('synthetic pointer failure')
        return original(path, value)
    target = 'restore_checkpoint' if failure == 'restore' else 'atomic_json'
    action = OSError('synthetic restore failure') if failure == 'restore' else fail_pointer
    with patch.object(checkpoints, target, side_effect=action):
        with pytest.raises(OSError):
            checkpoints.save_checkpoint(single, force=True)
    assert pointer(single) == before and ledger(single) == prior
    assert Path(before['path']).is_dir()


def test_completed_journal_keeps_owned_backup_until_retirement(single):
    root = Path(checkpoints.save_checkpoint(single, force=True)['path'])
    state = Path(single['state_dir'])
    owned = state/'operation-owned-bundle'
    shutil.copytree(root/'recovered_tracking', owned)
    previous = {**ledger(single), 'bundle': str(owned)}
    atomic_json(state/'DYAD_LEDGER.json', previous)
    journal = state/'COORDINATED_UPDATE.json'
    atomic_json(journal, {'status': 'complete'})
    checkpoints._finish_retention(single, root)
    assert ledger(single) == previous
    journal.unlink()  # Synthetic completed journal retirement.
    assert checkpoints.save_checkpoint(single, force=True)['unchanged']
    assert ledger(single)['bundle'] == str(root/'recovered_tracking')


def test_opt_out_preserves_ledger_and_restores_without_dangling_review(single, tmp_path):
    checkpoints.save_checkpoint(single, force=True)
    before = ledger(single)
    single['recovery_policy']['checkpoint_retention'] = 'preserve_all'
    result = checkpoints.save_checkpoint(single, force=True)
    assert ledger(single) == before
    checkpoints.restore_checkpoint(result['path'], tmp_path/'restored')
    tracking = json.loads((Path(result['path'])/'recovered_tracking/manifest.json').read_text())
    assert 'review.sqlite.gz' not in tracking['files']
    assert 'review_logical_sha256' not in tracking


@pytest.mark.parametrize('kind', ['missing_hash', 'wrong_logical_hash', 'corrupt_archive'])
def test_compressed_review_tampering_is_refused(single, kind):
    root = Path(checkpoints.save_checkpoint(single, force=True)['path'])/'recovered_tracking'
    path = root/'manifest.json'
    manifest = json.loads(path.read_text())
    if kind == 'missing_hash':
        manifest.pop('review_logical_sha256')
    elif kind == 'wrong_logical_hash':
        manifest['review_logical_sha256'] = '0'*64
    else:
        # Atomic replacement avoids modifying the master archive's hardlink.
        replacement = root/'invalid.gz'
        replacement.write_bytes(b'not gzip')
        replacement.replace(root/'review.sqlite.gz')
        manifest['files']['review.sqlite.gz'] = file_hash(root/'review.sqlite.gz')
    atomic_json(path, manifest)
    with pytest.raises(PipelineError):
        dyad_operator.verify_bundle(root)


@pytest.mark.parametrize('policy', [
    {'mode': 'lean', 'checkpoint_retention': 'typo'},
    {'mode': 'legacy', 'checkpoint_retention': 'single_master'},
])
def test_unknown_or_nonlean_master_policy_refuses(policy):
    with pytest.raises(PipelineError, match='Checkpoint retention'):
        enabled({'recovery_policy': policy})


@pytest.mark.parametrize('damage', ['missing_event', 'conflicting_event', 'corrupt_bundle'])
@pytest.mark.parametrize('protected', [False, True])
def test_stale_or_corrupt_history_cannot_replace_either_pointer(single, damage, protected):
    state = Path(single['state_dir'])
    db = connect(state)
    with db:
        db.execute('INSERT INTO dyad_events VALUES (?,?,?,?,?,?,?)',
                   ('synthetic-event', 'now', 'example', None, 'researcher', 'accepted', '{}'))
    db.close()
    checkpoints.save_checkpoint(single, force=True)
    before, prior = pointer(single), ledger(single)
    if damage == 'corrupt_bundle':
        path = Path(prior['bundle'])/'tracking.json.gz'
        path.write_bytes(b'corrupt synthetic archive')
    else:
        db = connect(state)
        with db:
            if damage == 'missing_event':
                db.execute('DELETE FROM dyad_events')
            else:
                db.execute("UPDATE dyad_events SET payload_json=?", ('{"changed": true}',))
        db.close()
    def failed_operation(cfg):
        main = connect(state)
        try:
            dyad_operator.recovery_check(main, cfg)
        finally:
            main.close()
    with pytest.raises(PipelineError):
        if protected:
            checkpoints.protect_mutation(failed_operation)(single)
        else:
            checkpoints.save_checkpoint(single, force=True)
    assert pointer(single) == before and ledger(single) == prior


@pytest.mark.parametrize('owner', ['both', 'ledger_only', 'checkpoint_only'])
def test_missing_review_cannot_replace_master(single, owner):
    state = Path(single['state_dir'])
    checkpoints.save_checkpoint(single, force=True)
    if owner == 'ledger_only':
        (state/'CURRENT_CHECKPOINT.json').unlink()
    elif owner == 'checkpoint_only':
        (state/'DYAD_LEDGER.json').unlink()
    paths = [state/name for name in ('CURRENT_CHECKPOINT.json', 'DYAD_LEDGER.json')]
    before = [p.read_bytes() if p.exists() else None for p in paths]
    (state/'review.sqlite').rename(state/'review-moved.sqlite')
    with pytest.raises(PipelineError, match='review workspace is missing'):
        checkpoints.save_checkpoint(single, force=True)
    assert [p.read_bytes() if p.exists() else None for p in paths] == before


@pytest.mark.parametrize('damage', [
    'missing_alias', 'conflicting_alias', 'revived_id', 'changed_anchor',
    'lost_publication', 'changed_publication',
])
def test_registry_history_cannot_be_erased_by_new_master(single, damage):
    state = Path(single['state_dir'])
    db = connect(state)
    with db:
        db.execute('INSERT INTO dyad_registry VALUES (?,?,?,?,?,?,?,?)',
                   ('old-id', 'student', 'parent', 'run', 'now', '{}', 'retired', 'published-run'))
        db.execute('INSERT INTO dyad_registry VALUES (?,?,?,?,?,?,?,?)',
                   ('current-id', 'student', 'parent', 'run', 'now', '{}', 'active', None))
        db.execute('INSERT INTO dyad_aliases VALUES (?,?,?)', ('old-id', 'current-id', 'merge'))
    db.close()
    checkpoints.save_checkpoint(single, force=True)
    before, prior = pointer(single), ledger(single)
    db = connect(state)
    with db:
        if damage == 'missing_alias':
            db.execute('DELETE FROM dyad_aliases')
        elif damage == 'conflicting_alias':
            db.execute("UPDATE dyad_aliases SET operation_id='changed'")
        elif damage == 'revived_id':
            db.execute("UPDATE dyad_registry SET lifecycle='active' WHERE dyad_id='old-id'")
        elif damage == 'changed_anchor':
            db.execute('DROP TRIGGER dyad_immutable_registration')
            db.execute("UPDATE dyad_registry SET first_student_id='changed' WHERE dyad_id='old-id'")
        else:
            db.execute('DROP TRIGGER dyad_first_publication_immutable')
            db.execute("UPDATE dyad_registry SET first_published_run_id=? WHERE dyad_id='old-id'",
                       (None if damage == 'lost_publication' else 'changed-run',))
    with pytest.raises(PipelineError):
        dyad_operator.recovery_check(db, single)
    db.close()
    with pytest.raises(PipelineError):
        checkpoints.save_checkpoint(single, force=True)
    assert pointer(single) == before and ledger(single) == prior


def test_legitimate_registry_progress_can_replace_master(single):
    state = Path(single['state_dir'])
    db = connect(state)
    with db:
        db.execute('INSERT INTO dyad_registry VALUES (?,?,?,?,?,?,?,?)',
                   ('reserved-id', 'student', 'parent', 'run', 'now', '{}', 'reserved', None))
    db.close()
    checkpoints.save_checkpoint(single, force=True)
    db = connect(state)
    with db:
        db.execute("UPDATE dyad_registry SET lifecycle='active', first_published_run_id='published-run'")
    dyad_operator.recovery_check(db, single)
    db.close()
    final = checkpoints.save_checkpoint(single, force=True)
    assert ledger(single)['bundle'] == str(Path(final['path'])/'recovered_tracking')
    _, saved = dyad_operator.verify_bundle(ledger(single)['bundle'])
    assert saved['dyad_registry'][0]['lifecycle'] == 'active'
    assert saved['dyad_registry'][0]['first_published_run_id'] == 'published-run'


@pytest.mark.parametrize('owner', ['both', 'ledger_only', 'checkpoint_only', 'older_ledger'])
@pytest.mark.parametrize('damage', ['missing_event', 'conflicting_event'])
def test_present_but_stale_review_cannot_replace_master(single, owner, damage):
    state = Path(single['state_dir'])
    checkpoints.save_checkpoint(single, force=True)
    older_ledger = ledger(single)
    work = review_core.workspace(single)
    with work:
        review_core.event(work, 'synthetic', 'accepted', {'evidence': 'synthetic'})
    work.close()
    checkpoints.save_checkpoint(single, force=True)
    if owner == 'ledger_only':
        (state/'CURRENT_CHECKPOINT.json').unlink()
    elif owner == 'checkpoint_only':
        (state/'DYAD_LEDGER.json').unlink()
    elif owner == 'older_ledger':
        atomic_json(state/'DYAD_LEDGER.json', older_ledger)
    paths = [state/name for name in ('CURRENT_CHECKPOINT.json', 'DYAD_LEDGER.json')]
    before = [p.read_bytes() if p.exists() else None for p in paths]
    work = review_core.workspace(single)
    with work:
        if damage == 'missing_event':
            work.execute('DELETE FROM events')
        else:
            work.execute("UPDATE events SET payload='{}'")
    work.close()
    with pytest.raises(PipelineError, match='saved review history'):
        checkpoints.save_checkpoint(single, force=True)
    assert [p.read_bytes() if p.exists() else None for p in paths] == before


@pytest.mark.parametrize('reuse', [False, True])
def test_detached_master_proves_once_without_changing_live_files(single, tmp_path, reuse):
    state = Path(single['state_dir'])
    (state/'writer.lock').touch(mode=0o600, exist_ok=True)
    if reuse:
        old = Path(checkpoints.save_checkpoint(single, force=True)['path'])
        # A reused historical manifest must keep its original permissions.
        (old/'recovered_tracking/manifest.json').chmod(0o644)
    atomic_json(state/'CHECKPOINT_PENDING.json', {'reason': 'must remain unchanged'})
    def snapshot():
        return {str(p.relative_to(state)): (file_hash(p), p.stat().st_mode & 0o777)
                for p in state.rglob('*') if p.is_file()}
    before = snapshot()
    target = tmp_path/'prepared/master'
    with patch('study2.store.writer_lock', side_effect=AssertionError('live activation recovery forbidden')), \
         patch.object(checkpoints, '_finish_retention', side_effect=AssertionError('live retention forbidden')), \
         patch.object(checkpoints, 'restore_checkpoint', wraps=checkpoints.restore_checkpoint) as restore:
        result = checkpoints.save_checkpoint(single, force=True, destination=target)
    assert result['detached'] and result['verified_recovery'] and result['path'] == str(target)
    assert restore.call_count == 1
    assert snapshot() == before
    assert checkpoints.checkpoint_manifest(target)['source_hashes']


@pytest.mark.parametrize('blocked', ['existing_destination', 'live_destination', 'activation', 'transition', 'proof'])
def test_detached_refusal_leaves_live_pointers_untouched(single, tmp_path, blocked):
    state = Path(single['state_dir'])
    checkpoints.save_checkpoint(single, force=True)
    before, prior = pointer(single), ledger(single)
    target = tmp_path/'prepared/master'
    if blocked == 'existing_destination':
        target.mkdir(parents=True)
    elif blocked == 'live_destination':
        target = state/'detached-must-not-write'
    elif blocked == 'activation':
        atomic_json(state/'STORAGE_ACTIVATION.json', {'status': 'applying'})
    elif blocked == 'transition':
        atomic_json(state/'COORDINATED_UPDATE.json', {'status': 'pending'})
    failure = PipelineError('synthetic restore failure') if blocked == 'proof' else None
    with patch.object(checkpoints, 'restore_checkpoint', side_effect=failure, wraps=checkpoints.restore_checkpoint):
        with pytest.raises(PipelineError):
            checkpoints.save_checkpoint(single, force=True, destination=target)
    assert pointer(single) == before and ledger(single) == prior
    if blocked != 'existing_destination':
        assert not target.exists()
    assert not list(target.parent.glob('.building_CHECKPOINT_*'))


@pytest.mark.parametrize('checksums_present', [False, True])
def test_detached_missing_publication_baseline_refuses_without_repair(single, tmp_path, checksums_present):
    release = tmp_path/'published'
    release.mkdir()
    if checksums_present:
        atomic_json(release/'checksums.json', {})
    target = tmp_path/'prepared/master'
    with patch('study2.store.current', return_value={'release_id': 'synthetic-release', 'path': str(release)}), \
         patch('study2.publication_baseline.ensure_baseline', side_effect=AssertionError('live repair forbidden')):
        with pytest.raises(PipelineError, match='Detached checkpoint requires'):
            checkpoints.save_checkpoint(single, force=True, destination=target)
    assert not target.exists()
    assert not (release/'PUBLICATION_BASELINE.json').exists()
