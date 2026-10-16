import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from study2.common import file_hash
from study2.maintenance import activate_pair,recover_activation,storage_report
from study2.store import connect


def pair(path,label):
    path.mkdir()
    for name in ['study2.sqlite','review.sqlite']:
        with sqlite3.connect(path/name) as db:
            db.execute('CREATE TABLE synthetic(value TEXT)');db.execute('INSERT INTO synthetic VALUES(?)',(label,))
    return {name:file_hash(path/name) for name in ['study2.sqlite','review.sqlite']}


def test_activation_failure_restores_the_complete_original_pair(tmp_path):
    state=tmp_path/'state';candidate=tmp_path/'candidate';old=pair(state,'old');new=pair(candidate,'new')
    def fail():raise OSError('synthetic activation interruption')
    with pytest.raises(OSError):activate_pair(state,candidate,old,new,fail)
    assert {n:file_hash(state/n) for n in old}==old
    assert json.loads((state/'STORAGE_ACTIVATION.json').read_text())['status']=='rolled_back'


def test_startup_recovers_a_pair_interrupted_after_only_main_replacement(tmp_path):
    state=tmp_path/'state';candidate=tmp_path/'candidate';old=pair(state,'old');pair(candidate,'new')
    saved=state/'storage_previous'/'synthetic';saved.mkdir(parents=True)
    for n in old:shutil.copy2(state/n,saved/n)
    shutil.copy2(candidate/'study2.sqlite',state/'study2.sqlite')
    (state/'STORAGE_ACTIVATION.json').write_text(json.dumps({'status':'applying','previous':str(saved),'previous_hashes':old}))
    recover_activation(state)
    assert {n:file_hash(state/n) for n in old}==old


def test_storage_report_counts_shared_paths_without_reading_payloads(tmp_path):
    state=tmp_path/'state';state.mkdir();first=state/'first.bin';first.write_bytes(b'synthetic')
    import os
    os.link(first,state/'second.bin')
    report=storage_report({'state_dir':str(state)})
    assert report['state']['logical_bytes']==18
    assert sum(g['shared_path_bytes'] for g in report['state']['groups'].values())==9


def test_gc_protects_source_versions_review_snapshots_and_release_objects(tmp_path):
    from study2.artifacts import publish_object
    from study2.common import atomic_json,dumps
    from study2.maintenance import storage_gc
    from study2.storage import store_record
    from study2.store import ingest
    from study2.review_core import workspace,backup_workspace
    from test_identity_and_time import rec
    from test_store_and_review import source
    state=tmp_path/'state';db=connect(state)
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('synthetic-run','fp','now','validated','{}',None,None))
    row=source(rec('synthetic'));ingest(db,'synthetic-run',[row]);store_record(db,'synthetic-run',row['submission_id'],row)
    db.commit();db.close();cfg={'state_dir':str(state),'release_dir':str(state/'releases')}
    workspace(cfg).close();snapshot=Path(backup_workspace(cfg,'synthetic'))
    retained=tmp_path/'retained';retained.write_bytes(b'synthetic retained');h,good=publish_object(state/'artifact_objects',retained)
    unused=tmp_path/'unused';unused.write_bytes(b'synthetic unused');_,bad=publish_object(state/'artifact_objects',unused)
    release=state/'releases'/'synthetic';release.mkdir(parents=True);atomic_json(release/'artifact_manifest.json',{'objects':{'a':h}})
    dry=storage_gc(cfg);assert dry['artifact_objects']==1 and bad.exists()
    storage_gc(cfg,True);assert good.exists() and snapshot.exists() and not bad.exists()
    db=connect(state);assert db.execute('SELECT count(*) FROM normalized_records').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM submission_versions').fetchone()[0]==1;db.close()


def test_failed_private_migration_resumes_its_journal_without_overwriting_source(tmp_path):
    from unittest.mock import patch
    from study2.maintenance import migrate_copy
    state=tmp_path/'state';connect(state).close();source_hash=file_hash(state/'study2.sqlite')
    cfg={'state_dir':str(state)};destination=tmp_path/'replacement'
    with patch('study2.storage.migrate_records',side_effect=OSError('synthetic interrupted conversion')):
        with pytest.raises(OSError):migrate_copy(cfg,destination)
    assert json.loads((destination/'storage_migration.json').read_text())['status']=='failed'
    result=migrate_copy(cfg,destination)
    assert result['status']=='verified_copy' and file_hash(state/'study2.sqlite')==source_hash
    assert migrate_copy(cfg,destination)==result


def test_gc_keeps_historical_checkout_assets_outside_active_release_directory(tmp_path):
    from unittest.mock import patch
    from study2.artifacts import publish_object
    from study2.common import atomic_json
    from study2.maintenance import storage_gc
    state=tmp_path/'state';connect(state).close()
    checkout=tmp_path/'checkout';historical=checkout/'releases'/'synthetic-old';historical.mkdir(parents=True)
    source=tmp_path/'asset';source.write_bytes(b'synthetic historical asset')
    h,obj=publish_object(state/'artifact_objects',source)
    atomic_json(historical/'artifact_manifest.json',{'objects':{'source':h}})
    with patch('study2.maintenance.__file__',str(checkout/'study2/maintenance.py')):
        result=storage_gc({'state_dir':str(state),'release_dir':str(state/'releases')})
    assert result['artifact_objects']==0 and obj.exists()
