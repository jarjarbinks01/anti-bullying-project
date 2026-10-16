"""Local storage reporting and journalled activation of a verified DB pair."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import uuid
from pathlib import Path

from .common import PipelineError, atomic_json, file_hash, secure_directory


def _scan(root):
    root=Path(root);seen=set();groups={}
    for here,dirs,names in os.walk(root,followlinks=False):
        for name in names:
            p=Path(here)/name;s=p.lstat()
            if not stat.S_ISREG(s.st_mode):continue
            key=(s.st_dev,s.st_ino);relative=p.relative_to(root)
            group=groups.setdefault(relative.parts[0],{'files':0,'logical_bytes':0,'allocated_bytes':0,'cloud_placeholder_bytes':0,'shared_path_bytes':0})
            group['files']+=1;group['logical_bytes']+=s.st_size
            if key in seen:group['shared_path_bytes']+=s.st_size
            else:seen.add(key);group['allocated_bytes']+=s.st_blocks*512
            if getattr(s,'st_flags',0)&0x40000000:group['cloud_placeholder_bytes']+=s.st_size
    return {'root':str(root),'groups':groups,'logical_bytes':sum(g['logical_bytes'] for g in groups.values()),
            'allocated_bytes':sum(g['allocated_bytes'] for g in groups.values()),
            'measurement':'Allocated file blocks counted once per inode; APFS clones may also share blocks'}


def storage_report(cfg):
    state=Path(cfg['state_dir']);recover_activation(state)
    result={'state':_scan(state),'checkout':_scan(Path(__file__).parent.parent),'databases':{}}
    for name in ['study2.sqlite','review.sqlite']:
        p=state/name
        if not p.is_file():continue
        db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
        try:
            data={'bytes':p.stat().st_size,'page_count':db.execute('PRAGMA page_count').fetchone()[0],
                  'freelist_pages':db.execute('PRAGMA freelist_count').fetchone()[0]}
            for table in ['record_values','normalized_record_refs','processed_record_values','processed_run_refs',
                          'run_payload_values','release_candidate_refs','dyad_membership_refs',
                          'review_components','review_task_values','review_tasks']:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(table,)).fetchone():
                    data[table]=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            result['databases'][name]=data
        finally:db.close()
    result['checkpoints']={'managed_complete':len(list((state/'checkpoints').glob('CHECKPOINT_*'))),
                           'pending':(state/'CHECKPOINT_PENDING.json').exists()}
    return result


def recover_activation(state):
    """Before opening either DB, recover an interrupted pair replacement."""
    state=Path(state);path=state/'STORAGE_ACTIVATION.json'
    if not path.exists():return
    journal=json.loads(path.read_text())
    if journal.get('status')!='applying':return
    import fcntl
    with (state/'writer.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PipelineError('Storage activation is in progress; retry when it completes') from None
        journal=json.loads(path.read_text())
        if journal.get('status')!='applying':return
        previous=Path(journal['previous'])
        if previous.parent!=(state/'storage_previous') or previous.is_symlink():raise PipelineError('Unsafe activation recovery path')
        for name in ['study2.sqlite','review.sqlite']:
            saved=previous/name
            if file_hash(saved)!=journal['previous_hashes'][name]:raise PipelineError('Previous DB pair does not match its activation journal')
        for name in ['study2.sqlite','review.sqlite']:
            temporary=state/(name+'.recovering');shutil.copy2(previous/name,temporary);temporary.chmod(0o600);os.replace(temporary,state/name)
        journal['status']='rolled_back';atomic_json(path,journal)


def activate_pair(state,candidate,expected_live_hashes,expected_candidate_hashes,after_install=None):
    """Call after preservation and checkpoint proofs, with clients stopped."""
    from .store import writer_lock
    state=Path(state);candidate=Path(candidate)
    recover_activation(state)
    with writer_lock(state):
        names=['study2.sqlite','review.sqlite']
        for name in names:
            if file_hash(state/name)!=expected_live_hashes[name]:raise PipelineError('Live data changed after baseline capture; rebase before activation')
            if file_hash(candidate/name)!=expected_candidate_hashes[name]:raise PipelineError('Candidate DB changed after verification')
            db=sqlite3.connect((candidate/name).as_uri()+'?mode=ro',uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                    raise PipelineError('Candidate database integrity failed')
            finally:db.close()
        previous=state/'storage_previous'/uuid.uuid4().hex;secure_directory(previous)
        for name in names:shutil.copy2(state/name,previous/name);(previous/name).chmod(0o600)
        journal={'format_version':1,'status':'applying','previous':str(previous),'previous_hashes':expected_live_hashes,
                 'candidate_hashes':expected_candidate_hashes}
        atomic_json(state/'STORAGE_ACTIVATION.json',journal)
        try:
            for name in names:
                temporary=state/(name+'.installing');shutil.copy2(candidate/name,temporary);temporary.chmod(0o600);os.replace(temporary,state/name)
            if after_install:after_install()
            journal['status']='complete';atomic_json(state/'STORAGE_ACTIVATION.json',journal)
        except BaseException:
            for name in names:
                temporary=state/(name+'.rollback');shutil.copy2(previous/name,temporary);temporary.chmod(0o600);os.replace(temporary,state/name)
            journal['status']='rolled_back';atomic_json(state/'STORAGE_ACTIVATION.json',journal);raise
        return journal


def migrate_copy(cfg,destination):
    """Produce an independently verified replacement without changing live data."""
    from .store import writer_lock
    from .storage import migrate_records
    from .review_storage import migrate_reviews
    source=Path(cfg['state_dir']);destination=Path(destination)
    resume=destination.exists()
    if resume:
        journal=destination/'storage_migration.json'
        if not journal.is_file():raise PipelineError('Existing migration destination has no resumable journal')
        receipt=json.loads(journal.read_text())
        if receipt.get('format_version')!=1 or Path(receipt.get('source','')).resolve()!=source.resolve():
            raise PipelineError('Migration journal belongs to another source')
        if receipt.get('status')=='verified_copy':return receipt
        if not (destination/'study2.sqlite').is_file():raise PipelineError('Interrupted initial copy must use a new destination')
        if (source/'review.sqlite').is_file() and not (destination/'review.sqlite').is_file():
            raise PipelineError('Interrupted initial pair copy must use a new destination')
    else:
        secure_directory(destination)
        receipt={'format_version':1,'status':'copying','source':str(source),'destination':str(destination)}
    def progress(value):
        receipt.update(value);atomic_json(destination/'storage_migration.json',receipt)
    try:
        with writer_lock(source):
            connections=[]
            try:
                for name in [] if resume else ['study2.sqlite','review.sqlite']:
                    if not (source/name).exists():continue
                    db=sqlite3.connect((source/name).as_uri()+'?mode=ro',uri=True)
                    db.execute('BEGIN');db.execute('SELECT count(*) FROM sqlite_master').fetchone();connections.append((name,db))
                for name,db in connections:
                    target=sqlite3.connect(destination/name);db.backup(target);target.close();(destination/name).chmod(0o600)
            finally:
                for _,db in connections:db.close()
        receipt['status']='migrating';progress({})
        db=sqlite3.connect(destination/'study2.sqlite');db.row_factory=sqlite3.Row
        try:
            receipt['records']=migrate_records(db,progress);db.commit();db.execute('VACUUM')
            from .compact_storage import migrate as compact_records
            from .run_storage import migrate as run_payloads
            receipt['compact_records']=compact_records(db)
            receipt['run_payloads']=run_payloads(db,progress);db.commit();db.execute('VACUUM')
            from .dense_storage import migrate as dense_refs
            receipt['dense_refs']=dense_refs(db);db.execute('VACUUM')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise PipelineError('Migrated main database failed integrity checks')
        finally:db.close()
        if (destination/'review.sqlite').exists():
            db=sqlite3.connect(destination/'review.sqlite');db.row_factory=sqlite3.Row
            try:
                receipt['reviews']=migrate_reviews(db,progress);db.commit();db.execute('VACUUM')
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise PipelineError('Migrated review database failed integrity checks')
            finally:db.close()
        for name in ['school_dictionary.xlsx','DYAD_LEDGER.json','review_rule_compatibility.json']:
            if (source/name).is_file():shutil.copy2(source/name,destination/name);(destination/name).chmod(0o600)
        receipt['candidate_hashes']={name:file_hash(destination/name) for name in ['study2.sqlite','review.sqlite'] if (destination/name).exists()}
        receipt['status']='verified_copy';progress({})
        receipt['requires_separate_activation_and_rule_compatibility_proof']=True
        atomic_json(destination/'storage_migration.json',receipt)
        return receipt
    except BaseException as error:
        receipt['status']='failed';receipt['error']=str(error);progress({});raise


def storage_gc(cfg,apply=False):
    """Collect only values and file objects outside every retained reference."""
    from .store import writer_lock
    state=Path(cfg['state_dir']);journal=state/'STORAGE_ACTIVATION.json'
    if journal.exists() and json.loads(journal.read_text()).get('status')=='applying':
        raise PipelineError('Cannot collect objects during storage activation')
    result={'apply':apply,'database_objects':{},'artifact_objects':0,'artifact_bytes':0}
    with writer_lock(state):
        for name,queries in [('study2.sqlite',[
            ('record_values',"value_hash NOT IN (SELECT record_hash FROM normalized_record_refs UNION SELECT raw_hash FROM normalized_record_refs WHERE raw_hash IS NOT NULL UNION SELECT answer_hash FROM normalized_record_refs WHERE answer_hash IS NOT NULL UNION SELECT raw_hash FROM version_value_refs UNION SELECT answer_hash FROM version_value_refs)")]),
            ('review.sqlite',[
            ('review_task_values',"value_hash NOT IN (SELECT value_hash FROM review_tasks UNION SELECT value_hash FROM review_package_task_refs)"),
            ('review_components',"component_hash NOT IN (SELECT component_hash FROM review_task_values WHERE component_hash IS NOT NULL)")])]:
            p=state/name
            if not p.exists():continue
            db=sqlite3.connect(p);db.execute('PRAGMA foreign_keys=ON')
            try:
                if name=='study2.sqlite':
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='processed_record_values'").fetchone():
                        count=db.execute('SELECT count(*) FROM processed_record_values WHERE instance_hash NOT IN (SELECT instance_hash FROM processed_run_refs)').fetchone()[0]
                        result['database_objects']['processed_record_values']=count
                        if apply and count:db.execute('DELETE FROM processed_record_values WHERE instance_hash NOT IN (SELECT instance_hash FROM processed_run_refs)')
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='run_payload_values'").fetchone():
                        refs=[]
                        for table in ['release_candidate_refs','dyad_membership_refs']:
                            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():refs.append('SELECT value_hash FROM '+table)
                        predicate='value_hash NOT IN ('+' UNION '.join(refs)+')' if refs else '1'
                        count=db.execute('SELECT count(*) FROM run_payload_values WHERE '+predicate).fetchone()[0]
                        result['database_objects']['run_payload_values']=count
                        if apply and count:db.execute('DELETE FROM run_payload_values WHERE '+predicate)
                for table,predicate in queries:
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(table,)).fetchone():continue
                    count=db.execute('SELECT count(*) FROM '+table+' WHERE '+predicate).fetchone()[0]
                    result['database_objects'][table]=count
                    if apply and count:db.execute('DELETE FROM '+table+' WHERE '+predicate)
                if apply:db.commit()
            finally:db.close()
        referenced=set();roots={Path(cfg.get('release_dir',state/'releases')),
                                Path(__file__).parent.parent/'releases'}
        db=sqlite3.connect((state/'study2.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='releases'").fetchone():
                roots.update(Path(p) for (p,) in db.execute('SELECT path FROM releases'))
        finally:db.close()
        for root in roots:
            for pattern in ['checksums.json','artifact_manifest.json']:
                for p in root.rglob(pattern) if root.exists() else []:
                    data=json.loads(p.read_text())
                    values=data.get('objects',data).values()
                    referenced.update(v for v in values if isinstance(v,str) and len(v)==64)
        # Review and administrative recovery paths remain references even
        # when their scientific release is no longer current.
        for p in (state/'review_backups').glob('*.sha256.json'):
            referenced.add(json.loads(p.read_text())['snapshot_sha256'])
        for p in (state/'dyad_backups').glob('*/manifest.json'):
            referenced.update(json.loads(p.read_text()).get('files',{}).values())
        pointer=state/'CURRENT_CHECKPOINT.json'
        if pointer.exists():
            checkpoint=Path(json.loads(pointer.read_text())['path']);manifest=json.loads((checkpoint/'manifest.json').read_text())
            referenced.update(e['sha256'] for e in manifest['files'].values())
        objects=state/'artifact_objects/objects'
        for p in objects.glob('*/*'):
            h=p.parent.name+p.name
            if p.is_file() and not p.is_symlink() and h not in referenced:
                result['artifact_objects']+=1;result['artifact_bytes']+=p.stat().st_size
                if apply:p.unlink()
        if apply:
            for p in (state/'artifact_objects/excel_keys').glob('*/*.json'):
                if json.loads(p.read_text()).get('object_hash') not in referenced:p.unlink()
    if apply:
        from .checkpoints import save_checkpoint
        result['checkpoint']=save_checkpoint(cfg,'storage_gc')
    return result
