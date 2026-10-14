"""One verified portable checkpoint of main data, reviews and required assets."""
from __future__ import annotations

import functools
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zlib
from pathlib import Path

from .common import PipelineError, atomic_json, dumps, file_hash, secure_directory, utcnow


def _gzip(source,target):
    h=hashlib.sha256()
    with Path(source).open('rb') as origin,Path(target).open('xb') as output:
        Path(target).chmod(0o600)
        with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as zipped:
            for chunk in iter(lambda:origin.read(1024*1024),b''):h.update(chunk);zipped.write(chunk)
        output.flush();os.fsync(output.fileno())
    return h.hexdigest()


def _safe_relative(name):
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:raise PipelineError('Unsafe checkpoint asset path')
    return path


def _unpack(archive,target,expected):
    h=hashlib.sha256();secure_directory(Path(target).parent)
    try:
        with gzip.open(archive,'rb') as origin,Path(target).open('xb') as output:
            Path(target).chmod(0o600)
            for chunk in iter(lambda:origin.read(1024*1024),b''):h.update(chunk);output.write(chunk)
    except (OSError,EOFError,zlib.error) as error:raise PipelineError('Checkpoint archive is corrupt or cannot be restored') from error
    if h.hexdigest()!=expected:raise PipelineError('Checkpoint restored content checksum mismatch')


def checkpoint_manifest(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    expected=json.loads((folder/'manifest.sha256.json').read_text())['manifest.json']
    if file_hash(folder/'manifest.json')!=expected or manifest.get('format_version')!=1:
        raise PipelineError('Checkpoint manifest checksum or version mismatch')
    return manifest


def restore_checkpoint(folder,destination,verify_only=False):
    folder=Path(folder);destination=Path(destination)
    if destination.exists():raise PipelineError('Checkpoint restore destination must be new')
    manifest=checkpoint_manifest(folder);secure_directory(destination)
    try:
        for name,entry in manifest['files'].items():
            relative=_safe_relative(name);source=folder/relative
            if source.is_symlink() or file_hash(source)!=entry['sha256']:raise PipelineError('Checkpoint file checksum mismatch')
            target=destination/_safe_relative(entry.get('restore_path',name))
            if entry.get('gzip'):_unpack(source,target,entry['uncompressed_sha256'])
            else:
                secure_directory(target.parent);shutil.copy2(source,target);target.chmod(0o600)
        for name in ['study2.sqlite','review.sqlite']:
            p=destination/name
            if not p.exists():continue
            db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                    raise PipelineError('Restored checkpoint database integrity failed')
            finally:db.close()
        config=json.loads((destination/'checkpoint_config.json').read_text())
        config.update(state_dir=str(destination),release_dir=str(destination/'releases'),
                      mapping_dir=str(destination/'code/mappings'),project_root=str(destination/'source_project'),
                      inbox_dir=str(destination/'inbox'))
        atomic_json(destination/'config.restored.json',config)
        if manifest.get('release_id'):
            new_path=destination/'releases'/manifest['release_id']
            if not (new_path/'backup.sqlite').exists() and not (new_path/'backup.sqlite.gz').exists():
                atomic_json(new_path/'backup.retention.json',{'full_restore_available':False,
                            'checkpoint_id':manifest['checkpoint_id'],'reason':'Portable complete checkpoint replaces release DB copy'})
            atomic_json(destination/'release_locations.json',{manifest['release_id']:str(new_path)})
            secure_directory(destination/'releases')
            atomic_json(destination/'releases/CURRENT.json',{'release_id':manifest['release_id'],'path':str(new_path)})
        if (destination/'recovered_tracking/manifest.json').exists():
            from .dyad_operator import verify_bundle
            verify_bundle(destination/'recovered_tracking')
            tracking=json.loads((destination/'recovered_tracking/manifest.json').read_text())
            atomic_json(destination/'DYAD_LEDGER.json',{'bundle':str(destination/'recovered_tracking'),'hash':tracking['tracking_hash']})
        return {'restored_state':str(destination),'checkpoint_id':manifest['checkpoint_id'],
                'requires_config_and_source_check':True,'verified':True}
    except BaseException:
        shutil.rmtree(destination,ignore_errors=True);raise


def _add_asset(folder,manifest,source,relative):
    source=Path(source);relative=_safe_relative(relative);target=folder/relative
    if source.is_symlink() or not source.is_file():raise PipelineError('Checkpoint asset must be a regular file')
    original=file_hash(source)
    secure_directory(target.parent);shutil.copy2(source,target);target.chmod(0o600)
    if file_hash(target)!=original or file_hash(source)!=original:raise PipelineError('Checkpoint asset changed while being captured')
    manifest['files'][str(relative)]={'sha256':original,'restore_path':str(relative)}


def _capture_assets(folder,manifest,cfg,main):
    from .store import current
    from .dyad_operator import TABLES
    state=Path(cfg['state_dir']);release=current(main)
    manifest['release_id']=release['release_id'] if release else None
    atomic_json(folder/'checkpoint_config.json',cfg)
    manifest['files']['checkpoint_config.json']={'sha256':file_hash(folder/'checkpoint_config.json')}
    code=Path(__file__).parent.parent
    for p in (code/'study2').glob('*.py'):_add_asset(folder,manifest,p,'code/study2/'+p.name)
    for name in ['dashboard.py','requirements.lock.txt','pyproject.toml']:
        if (code/name).is_file():_add_asset(folder,manifest,code/name,'code/'+name)
    if (code/'study2/assets/review_template.xlsx').is_file():
        _add_asset(folder,manifest,code/'study2/assets/review_template.xlsx','code/study2/assets/review_template.xlsx')
    for p in Path(cfg.get('mapping_dir',code/'mappings')).glob('*.py'):_add_asset(folder,manifest,p,'code/mappings/'+p.name)
    for name in ['school_dictionary.xlsx','review_rule_compatibility.json']:
        if (state/name).is_file():_add_asset(folder,manifest,state/name,name)
    from .adapters import source_root
    if cfg.get('project_root'):
        for entry in cfg.get('sources',[]):
            sources=list(source_root(cfg).glob(entry['pattern']))
            if not sources:raise PipelineError('Checkpoint source asset is missing')
            for p in sources:
                _add_asset(folder,manifest,p,Path('source_project')/cfg.get('source_folder','1.1_raw_file')/p.name)
    if release and (Path(release['path'])/'checksums.json').is_file():
        release_path=Path(release['path'])
        from .artifacts import logical_hash
        for name,h in json.loads((release_path/'checksums.json').read_text()).items():
            if logical_hash(release_path/name)!=h:raise PipelineError('Checkpoint source release failed verification')
        for p in release_path.rglob('*'):
            if p.is_file() and not p.is_symlink() and p.name not in {'backup.sqlite','backup.sqlite.gz'}:
                relative=Path('releases')/release['release_id']/p.relative_to(release_path)
                # Older plain audit exports remain logically byte-exact while
                # their portable copy is compressed and self contained.
                if p.suffix=='.jsonl':
                    target=folder/relative.with_name(relative.name+'.gz');secure_directory(target.parent)
                    h=_gzip(p,target);manifest['files'][str(target.relative_to(folder))]={
                        'sha256':file_hash(target),'gzip':True,'uncompressed_sha256':h,'restore_path':str(relative)}
                else:_add_asset(folder,manifest,p,relative)
    # Administrative overlay is rebuilt from the same frozen main snapshot.
    present=main.execute("SELECT 1 FROM sqlite_master WHERE name='dyad_registry'").fetchone()
    if present:
        data={t:[dict(row) for row in main.execute('SELECT * FROM '+t+' ORDER BY 1')] for t in TABLES}
        from .common import digest
        secure_directory(folder/'recovered_tracking')
        from .dyads import SCHEMA_VERSION
        atomic_json(folder/'recovered_tracking/tracking.json',{'schema_version':SCHEMA_VERSION,'tables':data})
        plain=folder/'recovered_tracking/tracking.json';archive=plain.with_name('tracking.json.gz')
        logical=_gzip(plain,archive);plain.unlink()
        atomic_json(folder/'recovered_tracking/manifest.json',{'schema_version':SCHEMA_VERSION,'tracking_hash':digest(data),
                    'files':{'tracking.json.gz':file_hash(archive)},'tracking_logical_sha256':logical})
        for name in ['tracking.json.gz','manifest.json']:
            manifest['files']['recovered_tracking/'+name]={'sha256':file_hash(folder/'recovered_tracking'/name)}


def save_checkpoint(cfg,reason='operator',force=False,config_override=None):
    from .store import writer_lock
    from .storage import records_v2
    state=Path(cfg['state_dir']);root=state/'checkpoints';secure_directory(root)
    pointer=state/'CURRENT_CHECKPOINT.json'
    with writer_lock(state):
        sources={};connections=[]
        try:
            for name in ['study2.sqlite','review.sqlite']:
                p=state/name
                if not p.is_file():continue
                db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
                db.execute('BEGIN');db.execute('SELECT count(*) FROM sqlite_master').fetchone();sources[name]=db;connections.append(db)
            if not force and not records_v2(sources['study2.sqlite']):return {'legacy_storage':True}
            source_hashes={name:file_hash(state/name) for name in sources}
            from .common import digest
            code_hashes={p.name:file_hash(p) for p in Path(__file__).parent.glob('*.py')}
            from .adapters import source_root
            assets={}
            for p in Path(cfg.get('mapping_dir',Path(__file__).parent.parent/'mappings')).glob('*.py'):
                assets['mapping/'+p.name]=file_hash(p)
            if cfg.get('project_root'):
                for entry in cfg.get('sources',[]):
                    for p in source_root(cfg).glob(entry['pattern']):assets['source/'+p.name]=file_hash(p)
            for name in ['review_rule_compatibility.json']:
                if (state/name).is_file():assets[name]=file_hash(state/name)
            settings={'config':config_override or cfg,'code':code_hashes,
                      'assets':assets,
                      'dictionary':file_hash(state/'school_dictionary.xlsx') if (state/'school_dictionary.xlsx').exists() else None}
            input_revision=digest(settings)
            old=json.loads(pointer.read_text()) if pointer.exists() else None
            previous=None;old_manifest=None
            if old:
                previous=Path(old['path']);old_manifest=checkpoint_manifest(previous)
                if any((previous/_safe_relative(name)).is_symlink() or not (previous/_safe_relative(name)).is_file() or file_hash(previous/_safe_relative(name))!=entry['sha256']
                       for name,entry in old_manifest['files'].items()):old_manifest=None
                if old_manifest and old_manifest['source_hashes']==source_hashes and old_manifest.get('input_revision')==input_revision:
                    _prune_full_copies(cfg,previous)
                    (state/'CHECKPOINT_PENDING.json').unlink(missing_ok=True)
                    return {'unchanged':True,'checkpoint_id':old_manifest['checkpoint_id'],'path':str(previous)}
            cid='CHECKPOINT_'+uuid.uuid4().hex;temporary=root/('.building_'+cid);secure_directory(temporary)
            manifest={'format_version':1,'checkpoint_id':cid,'created_at':utcnow(),'reason':reason,
                      'source_hashes':source_hashes,'input_revision':input_revision,'files':{}}
            try:
                from .store import current
                release=current(sources['study2.sqlite'])
                if release and (Path(release['path'])/'checksums.json').is_file():
                    from .publication_baseline import ensure_baseline
                    ensure_baseline(release['path'],release['release_id'])
                for name,source in sources.items():
                    previous_entry=old_manifest['files'].get(name+'.gz') if old_manifest else None
                    if previous_entry and old_manifest['source_hashes'].get(name)==source_hashes[name]:
                        from .artifacts import copy_object
                        saved=previous/(name+'.gz')
                        if file_hash(saved)!=previous_entry['sha256']:raise PipelineError('Previous checkpoint archive checksum mismatch')
                        copy_object(saved,temporary/(name+'.gz'))
                        manifest['files'][name+'.gz']=dict(previous_entry)
                        continue
                    plain=temporary/name;target=sqlite3.connect(plain);source.backup(target);target.close();plain.chmod(0o600)
                    archive=temporary/(name+'.gz');h=_gzip(plain,archive);plain.unlink()
                    manifest['files'][archive.name]={'sha256':file_hash(archive),'gzip':True,
                                'uncompressed_sha256':h,'restore_path':name}
                _capture_assets(temporary,manifest,cfg,sources['study2.sqlite'])
                if config_override:
                    atomic_json(temporary/'checkpoint_config.json',config_override)
                    manifest['files']['checkpoint_config.json']['sha256']=file_hash(temporary/'checkpoint_config.json')
                atomic_json(temporary/'manifest.json',manifest)
                atomic_json(temporary/'manifest.sha256.json',{'manifest.json':file_hash(temporary/'manifest.json')})
                with tempfile.TemporaryDirectory(prefix='study2-checkpoint-proof-') as temp:
                    restore_checkpoint(temporary,Path(temp)/'restored',verify_only=True)
                final=root/cid;os.replace(temporary,final)
                atomic_json(pointer,{'checkpoint_id':cid,'path':str(final),'manifest_sha256':file_hash(final/'manifest.json')})
                # Prune only managed complete checkpoints after the new one is
                # independently recovered. Never follow paths from old hints.
                for p in root.glob('CHECKPOINT_*'):
                    if p!=final and p.is_dir() and not p.is_symlink():shutil.rmtree(p)
                _prune_full_copies(cfg,final)
                (state/'CHECKPOINT_PENDING.json').unlink(missing_ok=True)
                return {'checkpoint_id':cid,'path':str(final),'verified_recovery':True}
            except BaseException:
                shutil.rmtree(temporary,ignore_errors=True);raise
        finally:
            for db in connections:db.close()


def _prune_full_copies(cfg,final):
    state=Path(cfg['state_dir']);final=Path(final)
    # Scientific outputs and baseline manifests stay in place;
    # the complete current checkpoint replaces release DB copies.
    release_root=Path(cfg.get('release_dir',state/'releases'))
    legacy_backups=release_root.glob('**/backup.sqlite*') if cfg.get('checkpoint_policy',{}).get('latest_complete_only') else []
    for p in legacy_backups:
        if p.name not in {'backup.sqlite','backup.sqlite.gz'} or p.is_symlink():continue
        atomic_json(p.parent/'backup.retention.json',{'full_restore_available':False,
                    'checkpoint':str(final),'reason':'Latest verified complete checkpoint only'})
        p.unlink()
    if cfg.get('checkpoint_policy',{}).get('latest_complete_only'):
        # These are full review recovery copies, not review rows
        # or administrative tracking histories. The portable pair
        # includes all newer answers and administrative events.
        pruned_snapshots=set()
        for directory,pattern in [('review_backups','*.sqlite'),('dyad_backups','*/review.sqlite')]:
            for p in (state/directory).glob(pattern):
                if not p.is_file() or p.is_symlink():continue
                atomic_json(p.with_name(p.name+'.retention.json'),{'full_restore_available':False,
                            'checkpoint':str(final),'reason':'Latest verified complete checkpoint only'})
                sidecar=p.with_suffix('.sha256.json')
                if sidecar.is_file():pruned_snapshots.add(json.loads(sidecar.read_text())['snapshot_sha256'])
                p.unlink();sidecar.unlink(missing_ok=True)
        # A tracking manifest still proves its original small
        # history after its optional review copy was pruned.
        for p in (state/'dyad_backups').glob('*/manifest.json'):
            data=json.loads(p.read_text())
            if 'review.sqlite' in data.get('files',{}) and not (p.parent/'review.sqlite').exists():
                data['pruned_review_sha256']=data['files'].pop('review.sqlite')
                data['recovery_checkpoint']=str(final);atomic_json(p,data)
        tracking=final/'recovered_tracking/manifest.json'
        if tracking.is_file():
            saved=json.loads(tracking.read_text())
            atomic_json(state/'DYAD_LEDGER.json',{'bundle':str(tracking.parent),'hash':saved['tracking_hash']})
            for p in (state/'dyad_backups').glob('*/tracking.json'):
                if not p.is_file() or p.is_symlink():continue
                atomic_json(p.with_name('tracking.retention.json'),{'full_restore_available':False,
                            'checkpoint':str(final),'reason':'Complete administrative history retained in latest checkpoint and main database'})
                p.unlink()
        from .artifacts import _object_path
        for h in pruned_snapshots:
            obj=_object_path(state/'artifact_objects',h)
            if obj.is_file() and not obj.is_symlink() and obj.stat().st_nlink==1:obj.unlink()


def protect_mutation(function):
    """Checkpoint only after the public operation releases its transactions."""
    @functools.wraps(function)
    def wrapped(cfg,*args,**kwargs):
        try:
            result=function(cfg,*args,**kwargs)
        except Exception:
            try:save_checkpoint(cfg,function.__name__+'_failed')
            except Exception as error:
                atomic_json(Path(cfg['state_dir'])/'CHECKPOINT_PENDING.json',{'reason':str(error),'operation':function.__name__})
            raise
        return checkpoint_committed_result(cfg,result,function.__name__)
    return wrapped


def checkpoint_committed_result(cfg,result,operation):
    try:save_checkpoint(cfg,operation)
    except Exception as error:
        atomic_json(Path(cfg['state_dir'])/'CHECKPOINT_PENDING.json',{'reason':str(error),'operation':operation})
        if isinstance(result,dict):result={**result,'checkpoint_warning':'Operation saved; checkpoint needs retry: '+str(error)}
    return result
