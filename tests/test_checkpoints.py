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
    pkg=review_core.create_package(cfg,'synthetic-reviewer',limit=1,purpose='validation')
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
    review_core.create_package(cfg,'synthetic-reviewer',limit=1,purpose='validation')
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


@pytest.mark.parametrize('asset',[
    'dashboard.py','requirements.lock.txt','pyproject.toml','study2/assets/review_template.xlsx'])
@pytest.mark.parametrize('remove',[False,True])
def test_every_captured_application_asset_invalidates_checkpoint(project,tmp_path,monkeypatch,asset,remove):
    import shutil
    import study2.checkpoints as checkpoints
    code=tmp_path/'application';(code/'study2/assets').mkdir(parents=True)
    (code/'study2/__init__.py').write_text('# synthetic application\n')
    original=Path(checkpoints.__file__).parent.parent
    for name in ['dashboard.py','requirements.lock.txt','pyproject.toml','study2/assets/review_template.xlsx']:
        shutil.copy2(original/name,code/name)
    monkeypatch.setattr(checkpoints,'__file__',str(code/'study2/checkpoints.py'))
    cfg,_,_,_=project;execute(project);before=latest(cfg)
    target=code/asset
    if remove:target.unlink()
    else:target.write_bytes(target.read_bytes()+b'\n# synthetic asset revision\n')
    result=save_checkpoint(cfg)
    assert result.get('verified_recovery') and latest(cfg)!=before
    restored=tmp_path/'revised-application';restore_checkpoint(result['path'],restored)
    saved=restored/'code'/asset
    if remove:assert not saved.exists()
    else:assert saved.read_bytes()==target.read_bytes()
    assert save_checkpoint(cfg)['unchanged']


@pytest.mark.parametrize('failure',['ledger','prune'])
def test_checkpoint_replacement_interruption_keeps_administrative_ledger_usable(project,monkeypatch,failure):
    import study2.checkpoints as checkpoints
    from study2.dyad_operator import recovery_check
    cfg,_,_,_=project;cfg['checkpoint_policy']={'latest_complete_only':True};execute(project)
    state=Path(cfg['state_dir']);old=latest(cfg);ledger=state/'DYAD_LEDGER.json'
    db=connect(state)
    with db:
        dyad_id=db.execute('SELECT dyad_id FROM dyad_registry LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',
                   ('synthetic-new-event','now','synthetic',dyad_id,'synthetic','synthetic event','{}'))
    db.close()
    atomic=checkpoints.atomic_json;rmtree=checkpoints.shutil.rmtree
    def fail_ledger(path,data):
        if Path(path)==ledger:raise OSError('synthetic ledger update interruption')
        return atomic(path,data)
    def fail_prune(path,*args,**kwargs):
        if Path(path)==Path(old['path']):raise OSError('synthetic checkpoint pruning interruption')
        return rmtree(path,*args,**kwargs)
    with monkeypatch.context() as m:
        if failure=='ledger':m.setattr(checkpoints,'atomic_json',fail_ledger)
        else:m.setattr(checkpoints.shutil,'rmtree',fail_prune)
        with pytest.raises(OSError,match='synthetic'):save_checkpoint(cfg)
    replacement=latest(cfg);assert replacement!=old
    assert Path(old['path']).exists()
    expected=old if failure=='ledger' else replacement
    assert json.loads(ledger.read_text())['bundle']==str(Path(expected['path'])/'recovered_tracking')
    live=connect(state,readonly=True);recovery_check(live,cfg);live.close()
    assert save_checkpoint(cfg)['unchanged']
    assert not Path(old['path']).exists()
    assert len(list((state/'checkpoints').glob('CHECKPOINT_*')))==1
    assert json.loads(ledger.read_text())['bundle']==str(Path(replacement['path'])/'recovered_tracking')
    live=connect(state,readonly=True);recovery_check(live,cfg);live.close()
    destination=state.parent/'interrupted-checkpoint-recovery'
    restore_checkpoint(replacement['path'],destination)
    with sqlite3.connect(destination/'study2.sqlite') as db:
        assert db.execute('SELECT count(*) FROM dyad_events WHERE event_id=?',('synthetic-new-event',)).fetchone()[0]==1


def test_added_release_recovery_asset_replaces_checkpoint(project,tmp_path):
    cfg,_,_,_=project;result=execute(project);before=latest(cfg)
    asset=Path(cfg['release_dir'])/result['release_id']/'reproduce/synthetic-notes.txt'
    asset.write_text('synthetic recovery instructions\n')
    replacement=save_checkpoint(cfg)
    assert replacement.get('verified_recovery') and latest(cfg)!=before
    destination=tmp_path/'release-asset-recovery';restore_checkpoint(replacement['path'],destination)
    assert (destination/'releases'/result['release_id']/'reproduce/synthetic-notes.txt').read_bytes()==asset.read_bytes()
    assert save_checkpoint(cfg)['unchanged']


def test_asset_change_during_capture_keeps_previous_checkpoint(project,monkeypatch):
    import study2.checkpoints as checkpoints
    cfg,_,_,_=project;mapping=Path(cfg['mapping_dir'])/'synthetic.py'
    mapping.write_text('# synthetic first revision\n');execute(project);before=latest(cfg)
    mapping.write_text('# synthetic second revision\n')
    capture=checkpoints._capture_assets
    def change_after_capture(*args,**kwargs):
        capture(*args,**kwargs)
        mapping.write_text('# synthetic third revision\n')
    monkeypatch.setattr(checkpoints,'_capture_assets',change_after_capture)
    with pytest.raises(PipelineError,match='asset inventory changed'):save_checkpoint(cfg)
    assert latest(cfg)==before and Path(before['path']).is_dir()
    assert not list((Path(cfg['state_dir'])/'checkpoints').glob('.building_*'))


def test_disabling_latest_only_policy_keeps_its_referenced_ledger_checkpoint(project):
    from study2.dyad_operator import recovery_check
    cfg,_,_,_=project;cfg['checkpoint_policy']={'latest_complete_only':True};execute(project)
    state=Path(cfg['state_dir']);old=latest(cfg);ledger=(state/'DYAD_LEDGER.json').read_bytes()
    cfg['checkpoint_policy']={'latest_complete_only':False}
    assert save_checkpoint(cfg)['verified_recovery']
    assert Path(old['path']).is_dir() and (state/'DYAD_LEDGER.json').read_bytes()==ledger
    live=connect(state,readonly=True);recovery_check(live,cfg);live.close()
    cfg['checkpoint_policy']={'latest_complete_only':True}
    assert save_checkpoint(cfg)['verified_recovery']
    assert len(list((state/'checkpoints').glob('CHECKPOINT_*')))==1
    live=connect(state,readonly=True);recovery_check(live,cfg);live.close()


@pytest.mark.parametrize('policy', [None, {'latest_complete_only': False}])
def test_preserve_all_retains_every_prior_checkpoint_and_ledger(tmp_path, monkeypatch, policy):
    from study2 import checkpoints
    state = tmp_path / 'state'
    for name in ('CHECKPOINT_old_a', 'CHECKPOINT_old_b', 'CHECKPOINT_new'):
        folder = state / 'checkpoints' / name
        folder.mkdir(parents=True)
        (folder / 'retained').write_text(name)
    ledger = state / 'DYAD_LEDGER.json'
    ledger.write_text(json.dumps({'bundle': str(state / 'legacy_bundle'), 'hash': 'synthetic'}))
    before = {str(p.relative_to(state)): p.read_bytes() for p in state.rglob('*') if p.is_file()}
    cfg = {'state_dir': str(state)}
    if policy is not None:
        cfg['checkpoint_policy'] = policy
    def forbidden_prune(*args):
        raise AssertionError('Preserve-all must not invoke a destructive cleanup')
    monkeypatch.setattr(checkpoints, '_prune_full_copies', forbidden_prune)
    checkpoints._finish_retention(cfg, state / 'checkpoints/CHECKPOINT_new')
    assert {str(p.relative_to(state)): p.read_bytes() for p in state.rglob('*') if p.is_file()} == before
