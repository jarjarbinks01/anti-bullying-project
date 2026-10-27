import copy
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from study2.common import PipelineError, atomic_json, file_hash
from study2 import checkpoints, dyad_operator, dyads, review_core, runner
from study2.lean_recovery import scientific_program_hash, sqlite_revision, recovery_assets, enabled
from study2.store import connect
from test_pipeline_integration import project, execute


@pytest.fixture
def lean(tmp_path, monkeypatch):
    for key in ('STUDY2_MANUAL_EXCLUSION_MANIFEST', 'STUDY2_CURRENT_REVIEW_WORKLOAD', 'STUDY2_REVIEW_STATE_DIR'):
        monkeypatch.delenv(key, raising=False)
    state = tmp_path / 'state'
    cfg = {'state_dir': str(state), 'mapping_dir': str(tmp_path / 'mappings'),
           'recovery_policy': {'mode': 'lean', 'required_assets': [], 'protected_paths': []},
           # The new policy must override the old destructive setting.
           'checkpoint_policy': {'latest_complete_only': True}}
    Path(cfg['mapping_dir']).mkdir()
    db = connect(state)
    dyads.migrate(db)
    db.commit()
    db.close()
    review_core.workspace(cfg).close()
    return cfg


def pointer(cfg):
    return json.loads((Path(cfg['state_dir']) / 'CURRENT_CHECKPOINT.json').read_text())


def test_review_backup_reuses_exact_content_and_captures_changes(lean):
    with patch('study2.review_core.backup', wraps=review_core.backup) as backup:
        first = review_core.backup_workspace(lean, 'first')
        assert review_core.backup_workspace(lean, 'unchanged') == first
        assert backup.call_count == 1
        db = review_core.workspace(lean)
        with db:
            review_core.event(db, 'synthetic', 'example', {'accepted': True})
        db.close()
        second = review_core.backup_workspace(lean, 'changed')
        assert second != first and backup.call_count == 2
    assert not Path(first).samefile(Path(lean['state_dir']) / 'review.sqlite')
    with sqlite3.connect(second) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_corrupt_review_cache_is_not_reused(lean):
    saved = Path(review_core.backup_workspace(lean))
    saved.write_bytes(b'corrupt synthetic snapshot')
    with pytest.raises(PipelineError, match='corrupt'):
        review_core.backup_workspace(lean)


def test_wal_is_part_of_review_revision(tmp_path):
    path = tmp_path / 'wal.sqlite'
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE events(value)')
    db.commit()
    before = sqlite_revision(path)
    db.execute('INSERT INTO events VALUES (1)')
    db.commit()
    assert sqlite_revision(path) != before
    db.close()


def test_unchanged_ledger_reuses_bundle_and_new_event_is_preserved(lean):
    state = Path(lean['state_dir'])
    db = connect(state)
    first = dyad_operator.backup_tracking(db, lean)
    assert dyad_operator.backup_tracking(db, lean, 'same') == first
    with db:
        db.execute('INSERT INTO dyad_events VALUES (?,?,?,?,?,?,?)',
                   ('synthetic', 'now', 'example', None, 'researcher', 'accepted', '{}'))
    second = dyad_operator.backup_tracking(db, lean, 'changed')
    assert second != first
    assert len(list((state / 'dyad_backups').glob('bundle_*'))) == 2
    saved, data = dyad_operator.verify_bundle(second)
    assert data['dyad_events'][0]['event_id'] == 'synthetic'
    # Recovery does not need to materialize the large membership/lineage tables.
    with patch('study2.dyad_operator.workspace_snapshot', side_effect=AssertionError('unnecessary full snapshot')):
        dyad_operator.recovery_check(db, lean)
    db.close()


@pytest.mark.parametrize('name', ['static_assets.py', 'descriptive_dashboard.py', 'parent_panel_dashboard.py'])
def test_ui_only_change_does_not_change_scientific_revision(tmp_path, name):
    (tmp_path / 'matching.py').write_text('RULE = 1\n')
    (tmp_path / name).write_text('LABEL = "first"\n')
    before = scientific_program_hash(tmp_path)
    (tmp_path / name).write_text('LABEL = "second"\n')
    assert scientific_program_hash(tmp_path) == before
    (tmp_path / 'matching.py').write_text('RULE = 2\n')
    assert scientific_program_hash(tmp_path) != before
    before = scientific_program_hash(tmp_path)
    (tmp_path / 'unknown_new_engine.py').write_text('RULE = 3\n')
    assert scientific_program_hash(tmp_path) != before


def test_full_program_provenance_still_changes_for_ui(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, '__file__', str(tmp_path / 'runner.py'))
    (tmp_path / 'runner.py').write_text('RULE = 1\n')
    ui = tmp_path / 'static_assets.py'
    ui.write_text('LABEL = "first"\n')
    cfg = {'recovery_policy': {'mode': 'lean'}}
    science, full = runner.calculation_hash(cfg), runner.program_hash()
    ui.write_text('LABEL = "second"\n')
    assert runner.calculation_hash(cfg) == science
    assert runner.program_hash() != full
    assert runner.calculation_hash({}) == runner.program_hash()


def test_complete_restore_covers_controls_registry_and_runtime(lean, tmp_path, monkeypatch):
    state = Path(lean['state_dir'])
    flag = state / 'analysis_eligibility' / 'accepted.json'
    workload = state / 'review_dispositions' / 'accepted' / 'workload.json'
    atomic_json(flag, {'synthetic_flags': ['one'], 'history': ['approved']})
    atomic_json(workload, {'synthetic_pending': 0})
    atomic_json(state / 'CURRENT_REVIEW_DISPOSITION.json', {'path': str(workload)})
    registry = tmp_path / 'private_flags.sqlite'
    with sqlite3.connect(registry) as db:
        db.execute('CREATE TABLE events(reason TEXT)')
        db.execute('INSERT INTO events VALUES (?)', ('synthetic approved exclusion',))
    runtime = tmp_path / 'launcher'
    runtime.mkdir()
    (runtime / 'start.sh').write_text('# synthetic runtime dependency\n')
    lean['recovery_policy']['required_assets'] = [
        {'path': str(registry), 'restore_path': 'dependencies/flags.sqlite', 'kind': 'file'},
        {'path': str(runtime), 'restore_path': 'dependencies/runtime', 'kind': 'directory'}]
    monkeypatch.setenv('STUDY2_MANUAL_EXCLUSION_MANIFEST', str(flag))
    monkeypatch.setenv('STUDY2_CURRENT_REVIEW_WORKLOAD', str(workload))
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', str(state))
    result = checkpoints.save_checkpoint(lean, force=True)
    restored = tmp_path / 'restored'
    checkpoints.restore_checkpoint(result['path'], restored)
    for original in (flag, workload, state / 'CURRENT_REVIEW_DISPOSITION.json'):
        assert (restored / original.relative_to(state)).read_bytes() == original.read_bytes()
    assert (restored / 'dependencies/runtime/start.sh').read_bytes() == (runtime / 'start.sh').read_bytes()
    with sqlite3.connect(restored / 'dependencies/flags.sqlite') as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    environment = json.loads((restored / 'recovery_environment.json').read_text())
    assert environment['STUDY2_CURRENT_REVIEW_WORKLOAD'] == str(restored / workload.relative_to(state))
    assert environment['STUDY2_REVIEW_STATE_DIR'] == str(restored)
    config = json.loads((restored / 'config.restored.json').read_text())
    assert config['recovery_policy']['required_assets'][0]['path'] == str(restored / 'dependencies/flags.sqlite')


def test_asset_reuse_is_immutable_and_retention_never_deletes(lean, tmp_path):
    mapping = Path(lean['mapping_dir']) / 'example.py'
    mapping.write_text('RULE = 1\n')
    first = checkpoints.save_checkpoint(lean, force=True)
    old = Path(first['path'])
    assert not (old / 'code/mappings/example.py').samefile(mapping)
    assert checkpoints.save_checkpoint(lean, force=True)['unchanged']
    state = Path(lean['state_dir'])
    historical = state / 'checkpoints/CHECKPOINT_historical'
    historical.mkdir()
    (historical / 'keep.txt').write_text('historical runtime')
    lean['recovery_policy']['required_assets'] = [
        {'path': str(historical / 'keep.txt'), 'restore_path': 'dependencies/old_runtime.txt', 'kind': 'file'}]
    atomic_json(state / 'analysis_eligibility/accepted.json', {'revision': 2})
    second = checkpoints.save_checkpoint(lean, force=True)
    new = Path(second['path'])
    assert (old / 'code/mappings/example.py').samefile(new / 'code/mappings/example.py')
    assert (old / 'study2.sqlite.gz').samefile(new / 'study2.sqlite.gz')
    assert old.is_dir() and historical.is_dir()
    manifest = checkpoints.checkpoint_manifest(new)
    assert manifest['previous_verified_checkpoint']['path'] == str(old)
    plan = json.loads((state / 'CHECKPOINT_RETENTION_PLAN.json').read_text())
    assert not plan['automatic_deletion']
    assert all(row['disposition'] == 'retain' and not row['deletion_authorized'] for row in plan['checkpoints'])
    mapping.write_text('RULE = 2\n')
    assert (old / 'code/mappings/example.py').read_text() == 'RULE = 1\n'


def test_failed_recovery_keeps_prior_bundle_and_pointer(lean, monkeypatch):
    checkpoints.save_checkpoint(lean, force=True)
    before = pointer(lean)
    atomic_json(Path(lean['state_dir']) / 'analysis_eligibility/accepted.json', {'changed': True})
    with patch('study2.checkpoints.restore_checkpoint', side_effect=OSError('synthetic disk full')):
        with pytest.raises(OSError, match='disk full'):
            checkpoints.save_checkpoint(lean, force=True)
    assert pointer(lean) == before and Path(before['path']).is_dir()
    assert not list((Path(lean['state_dir']) / 'checkpoints').glob('.building_*'))


def test_failed_pointer_promotion_keeps_verified_rollback(lean, monkeypatch, tmp_path):
    checkpoints.save_checkpoint(lean, force=True)
    state = Path(lean['state_dir'])
    before = pointer(lean)
    atomic_json(state / 'analysis_eligibility/accepted.json', {'changed': True})
    original = checkpoints.atomic_json
    def fail_pointer(path, data):
        if Path(path) == state / 'CURRENT_CHECKPOINT.json':
            raise OSError('synthetic pointer failure')
        return original(path, data)
    with patch('study2.checkpoints.atomic_json', side_effect=fail_pointer):
        with pytest.raises(OSError, match='pointer failure'):
            checkpoints.save_checkpoint(lean, force=True)
    assert pointer(lean) == before
    checkpoints.restore_checkpoint(before['path'], tmp_path / 'rollback-proof')
    assert not list((state / 'checkpoints').glob('.building_*'))


def test_unknown_policy_and_missing_inventory_do_not_fall_back_to_pruning(lean):
    with pytest.raises(PipelineError, match='Unknown recovery policy'):
        enabled({'recovery_policy': {'mode': 'leaan'}})
    del lean['recovery_policy']['required_assets']
    with pytest.raises(PipelineError, match='explicit required_assets'):
        recovery_assets(lean)


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'escape', 'unregistered_environment', 'wal'])
def test_incomplete_dependencies_fail_closed(lean, tmp_path, monkeypatch, kind):
    path = tmp_path / 'dependency'
    path.write_text('synthetic')
    entry = {'path': str(path), 'restore_path': 'dependencies/example', 'kind': 'file'}
    lean['recovery_policy']['required_assets'] = [entry]
    connection = None
    if kind == 'missing':
        path.unlink()
    elif kind == 'symlink':
        link = tmp_path / 'link'
        link.symlink_to(path)
        entry['path'] = str(link)
    elif kind == 'escape':
        entry['restore_path'] = '../escape'
    elif kind == 'unregistered_environment':
        monkeypatch.setenv('STUDY2_MANUAL_EXCLUSION_MANIFEST', str(tmp_path / 'unregistered.json'))
    else:
        path.unlink()
        connection = sqlite3.connect(path)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE flags(value)')
        connection.commit()
    try:
        with pytest.raises(PipelineError):
            recovery_assets(lean)
    finally:
        if connection:
            connection.close()


def test_normal_run_reuses_unchanged_and_changed_input_recalculates(project, monkeypatch):
    cfg, manifest, rows, _ = project
    cfg['recovery_policy'] = {'mode': 'lean', 'required_assets': [], 'protected_paths': []}
    for key in ('STUDY2_MANUAL_EXCLUSION_MANIFEST', 'STUDY2_CURRENT_REVIEW_WORKLOAD', 'STUDY2_REVIEW_STATE_DIR'):
        monkeypatch.delenv(key, raising=False)
    first = execute(project)
    assert 'checkpoint_warning' not in first
    assert execute(project)['unchanged']
    source = Path(cfg['project_root']) / '1.1_raw_file/synthetic.csv'
    source.write_text('synthetic changed input\n')
    manifest['sources'][0]['sha256'] = file_hash(source)
    second = execute(project)
    assert second['release_id'] != first['release_id']
    assert 'checkpoint_warning' not in second
    assert all(second[name] == first[name] == 1 for name in ('A', 'B', 'C', 'D', 'AC', 'BD', 'E', 'F', 'EF'))
