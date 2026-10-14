import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from study2.checkpoints import restore_checkpoint, save_checkpoint
from study2.common import PipelineError, file_hash
from study2.store import connect
from test_pipeline_integration import execute, project


def latest(cfg):
    return json.loads((Path(cfg['state_dir'])/'CURRENT_CHECKPOINT.json').read_text())


def test_unchanged_run_keeps_exact_database_bytes_and_checkpoint(project):
    cfg,_,_,_=project;execute(project)
    pointer=latest(cfg);state=Path(cfg['state_dir'])
    before={p.name:file_hash(p) for p in state.glob('*.sqlite')}
    assert execute(project)['unchanged']
    assert {p.name:file_hash(p) for p in state.glob('*.sqlite')}==before
    assert latest(cfg)==pointer
    assert save_checkpoint(cfg)['unchanged']


def test_latest_only_checkpoint_restores_pending_reviews_and_prunes_after_verification(project):
    from study2 import review_core
    cfg,_,_,_=project;cfg['checkpoint_policy']={'latest_complete_only':True}
    result=execute(project);first=latest(cfg)
    assert not (Path(cfg['release_dir'])/result['release_id']/'backup.sqlite').exists()
    pkg=review_core.create_package(cfg,'synthetic-reviewer',limit=1)
    review_core.submit_reviews(cfg,pkg['package_id'],[{'task_id':pkg['tasks'][0]['task_id'],
        'verdict':'資料不足','evidence_source':'沒有足夠證據','reason':'合成待核實個案'}])
    second=latest(cfg)
    assert second['checkpoint_id']!=first['checkpoint_id']
    assert not Path(first['path']).exists()
    assert len(list((Path(cfg['state_dir'])/'checkpoints').glob('CHECKPOINT_*')))==1
    state=Path(cfg['state_dir'])
    assert not list((state/'dyad_backups').glob('*/tracking.json'))
    assert json.loads((state/'DYAD_LEDGER.json').read_text())['bundle']==str(Path(second['path'])/'recovered_tracking')
    from study2.dyad_operator import recovery_check
    live=connect(state,readonly=True);recovery_check(live,cfg);live.close()
    destination=Path(cfg['state_dir']).parent/'recovered-portable'
    restore_checkpoint(second['path'],destination)
    with sqlite3.connect((destination/'review.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT count(*) FROM reviews').fetchone()[0]==1
        assert json.loads(db.execute('SELECT payload FROM packages').fetchone()[0])['package_id']==pkg['package_id']
    with sqlite3.connect((destination/'study2.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT count(*) FROM submissions').fetchone()[0]==4
    assert (destination/'code/study2/assets/review_template.xlsx').is_file()
    from study2.common import load_config
    from study2.runner import verify_release
    from study2.store import current
    recovered=connect(destination,readonly=True)
    assert verify_release(recovered,current(recovered)['release_id'])['path'].startswith(str(destination))
    recovered.close()


def test_failed_replacement_retains_previous_verified_checkpoint(project):
    cfg,_,_,_=project;execute(project);before=latest(cfg)
    db=connect(Path(cfg['state_dir']))
    with db:db.execute('INSERT INTO labels VALUES(?,?,?,?,?,?)',('synthetic-label','UNRESOLVED','synthetic','reason','now','{}'))
    db.close()
    with patch('study2.checkpoints.restore_checkpoint',side_effect=OSError('synthetic insufficient disk space')):
        with pytest.raises(OSError):save_checkpoint(cfg)
    assert latest(cfg)==before and Path(before['path']).exists()
    assert not list((Path(cfg['state_dir'])/'checkpoints').glob('.building_*'))
    restore_checkpoint(before['path'],Path(cfg['state_dir']).parent/'previous-proof')


def test_corrupt_checkpoint_fails_without_leaving_a_partial_restore(project):
    cfg,_,_,_=project;execute(project);pointer=latest(cfg)
    archive=Path(pointer['path'])/'study2.sqlite.gz';archive.write_bytes(b'synthetic corrupt archive')
    destination=Path(cfg['state_dir']).parent/'corrupt-restored'
    with pytest.raises(PipelineError,match='checksum'):
        restore_checkpoint(pointer['path'],destination)
    assert not destination.exists()


def test_archive_with_updated_physical_hash_still_checks_restored_hash(project):
    import gzip
    from study2.common import atomic_json
    cfg,_,_,_=project;execute(project);folder=Path(latest(cfg)['path'])
    archive=folder/'study2.sqlite.gz';archive.write_bytes(gzip.compress(b'synthetic wrong database'))
    manifest=json.loads((folder/'manifest.json').read_text())
    manifest['files'][archive.name]['sha256']=file_hash(archive)
    atomic_json(folder/'manifest.json',manifest)
    atomic_json(folder/'manifest.sha256.json',{'manifest.json':file_hash(folder/'manifest.json')})
    with pytest.raises(PipelineError,match='restored content checksum'):
        restore_checkpoint(folder,Path(cfg['state_dir']).parent/'wrong-content')


def test_mapping_change_replaces_checkpoint_without_changing_database(project):
    cfg,_,_,_=project;execute(project);before=latest(cfg)
    mapping=Path(cfg['mapping_dir'])/'synthetic.py';mapping.parent.mkdir(exist_ok=True)
    mapping.write_text('# synthetic asset revision\n')
    assert save_checkpoint(cfg)['verified_recovery']
    assert latest(cfg)['checkpoint_id']!=before['checkpoint_id']


def test_failed_archive_creation_keeps_old_checkpoint_and_reports_pending(project):
    import errno
    from study2.checkpoints import protect_mutation
    cfg,_,_,_=project;execute(project);before=latest(cfg)
    @protect_mutation
    def synthetic_operation(cfg):
        db=connect(Path(cfg['state_dir']))
        with db:db.execute('INSERT INTO labels VALUES(?,?,?,?,?,?)',('synthetic-label','UNRESOLVED','synthetic','reason','now','{}'))
        db.close();return {'saved':True}
    with patch('study2.checkpoints._gzip',side_effect=OSError(errno.ENOSPC,'synthetic full disk')):
        result=synthetic_operation(cfg)
    assert result['saved'] and result['checkpoint_warning']
    assert latest(cfg)==before and Path(before['path']).exists()
    assert (Path(cfg['state_dir'])/'CHECKPOINT_PENDING.json').exists()
    assert not list((Path(cfg['state_dir'])/'checkpoints').glob('.building_*'))


def test_identical_review_snapshots_share_across_operations(tmp_path):
    from study2.review_core import workspace,backup_workspace
    cfg={'state_dir':str(tmp_path)};workspace(cfg).close()
    first=Path(backup_workspace(cfg,'synthetic-first'));second=Path(backup_workspace(cfg,'synthetic-second'))
    assert first.samefile(second) and not first.samefile(tmp_path/'review.sqlite')


def test_review_only_checkpoint_reuses_main_archive(project):
    from study2 import review_core
    cfg,_,_,_=project;execute(project);first=latest(cfg)
    original=Path(first['path'])/'study2.sqlite.gz';inode=original.stat().st_ino
    review_core.create_package(cfg,'synthetic-reviewer',limit=1)
    new=Path(latest(cfg)['path'])/'study2.sqlite.gz'
    assert new.stat().st_ino==inode


def test_reuse_prunes_redundant_review_copy_and_repairs_corrupt_archive(project):
    from study2.review_core import workspace,backup_workspace
    cfg,_,_,_=project;cfg['checkpoint_policy']={'latest_complete_only':True};execute(project)
    workspace(cfg).close();save_checkpoint(cfg);old=latest(cfg)
    copy=Path(backup_workspace(cfg,'synthetic-unneeded'))
    assert save_checkpoint(cfg)['unchanged']
    assert not copy.exists()
    archive=Path(old['path'])/'study2.sqlite.gz';archive.write_bytes(b'synthetic corrupt bytes')
    replacement=save_checkpoint(cfg)
    assert replacement['verified_recovery'] and replacement['checkpoint_id']!=old['checkpoint_id']


def test_missing_source_cannot_replace_a_complete_checkpoint(project):
    cfg,_,_,_=project;execute(project);old=latest(cfg)
    source=Path(cfg['project_root'])/'1.1_raw_file/synthetic.csv';source.unlink()
    with pytest.raises(PipelineError,match='source asset is missing'):save_checkpoint(cfg)
    assert latest(cfg)==old and Path(old['path']).exists()
