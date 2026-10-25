"""Human-invoked local policy controls, with immutable generations and undo.

No scientific DB writes, publication or CSV rematching. Existing manual_flags
APIs own a SEPARATE registry in each generation; Eric's registry is never opened.
Only CURRENT.json is replaced, after every generation file/receipt is complete.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import uuid

from .analysis_eligibility import sha, validate_manifest, project_eligibility, inventory_revision
from .common import digest, file_hash, utcnow
from .group_cleaning import (PolicyError, need, make_proposal, validate_proposal,
    exclusion_manifest, combined_manifest, project_workload)
from .group_cleaning import implementation_revision
from .manual_flags import (Inventory, initialize_registry, seed_manifest,
    export_manifest, decide_flags, status as registry_status)
from .review import active_decisions
from .review_core import rules_hash as current_rules_hash

BUNDLE_FORMAT='study2_group_cleaning_inputs_v1'
POINTER_FORMAT='study2_group_cleaning_pointer_v1'
GEN_FORMAT='study2_group_cleaning_generation_v1'
REVIEW_FORMAT='study2_group_cleaning_acceptance_v1'
REQUIRED_FILES={'config','records','cases','groups','decisions','eric_manifest',
                'source_evidence','authorization','partitions','user_exclusions'}
OPTIONAL_FILES={'analysis','parents','prior_policy_manifest','carry'}


def _json(path):
    return json.loads(Path(path).read_text())


def _read_file(pin):
    need(isinstance(pin,dict) and set(pin)=={'path','sha256'},'input_pin_shape')
    p=Path(pin['path']);need(p.is_absolute() and p.is_file() and not p.is_symlink(),'regular_pinned_input_required')
    data=p.read_bytes();need(hashlib.sha256(data).hexdigest()==pin['sha256'],'input_pin_changed')
    return p,data


def load_bundle(path):
    b=_json(path)
    need(set(b)=={'format','release_id','main_revision','rules_hash','files','revision'} and
         b['format']==BUNDLE_FORMAT,'input_bundle_shape')
    need(b['revision']==sha({k:v for k,v in b.items() if k!='revision'}),'input_bundle_revision')
    need(REQUIRED_FILES<=b['files'].keys() and not set(b['files'])-REQUIRED_FILES-OPTIONAL_FILES,'input_bundle_files')
    data={}
    for name,pin in b['files'].items():
        p,blob=_read_file(pin)
        if name in {'analysis','parents'}:
            import pandas as pd
            data[name]=pd.read_parquet(io.BytesIO(blob))
        elif p.suffix=='.gz':data[name]=[json.loads(line) for line in gzip.decompress(blob).decode().splitlines() if line.strip()]
        else:data[name]=json.loads(blob)
    for name,key in [('records','submission_id'),('cases','case_id')]:
        if isinstance(data[name],list):
            rows=data[name];data[name]={r[key]:r for r in rows}
            need(len(rows)==len(data[name]),'duplicate_input_identity')
        need(isinstance(data[name],dict) and all(k==r[key] for k,r in data[name].items()),'input_identity_index')
    need(isinstance(data['groups'],dict),'group_index_required')
    need(current_rules_hash(data['config'])==b['rules_hash'],'scientific_rules_hash_changed')
    options={k:b[k] for k in ('release_id','main_revision','rules_hash')}
    options.update({k:data[k] for k in ('eric_manifest','source_evidence','authorization','partitions','user_exclusions')})
    if 'prior_policy_manifest' in data:options['prior_policy_manifest']=data['prior_policy_manifest']
    if 'carry' in data:
        c=data['carry']
        need('prior_policy_manifest' not in data and c.get('revision')==sha({k:v for k,v in c.items() if k!='revision'})
             and c.get('format')=='study2_group_policy_carry_v1','carry_shape_or_revision')
        options.update(prior_policy_manifest=c['recompiled_manifest'],
                       prior_policy_origin_revision=c['old_policy_manifest_revision'],
                       prior_policy_head=c['old_pointer']['manifest_sha256'])
    data['_input_pins']=deepcopy(b['files'])
    return b,data,options


def _main_revision(cfg):
    """Bare read-only existing control revision; no project connector/recovery."""
    p=Path(cfg['state_dir'])/'study2.sqlite'
    need(p.is_file() and not p.is_symlink(),'main_database_required')
    need(not any(Path(str(p)+s).exists() for s in ('-journal','-wal','-shm')),'main_database_requires_existing_recovery_workflow')
    db=sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True);db.row_factory=sqlite3.Row
    try:
        revision=digest(dict(decisions=active_decisions(db),labels=[dict(r) for r in db.execute('SELECT * FROM labels ORDER BY case_id')]))
        row=db.execute('SELECT r.release_id FROM releases r JOIN publication p USING(release_id)').fetchone()
        return dict(main_revision=revision,release_id=row[0] if row else None)
    finally:db.close()


@contextmanager
def _writer_control(state):
    """Same writer.lock + flock protocol as store.writer_lock, without recovery.

    This deliberately does not call a helper that may recover research state.
    It is invoked only by reviewed operator apply/undo, never by pure preview.
    """
    state=Path(state);need(state.is_dir() and not state.is_symlink(),'writer_state_directory')
    path=state/'writer.lock';need(not path.is_symlink(),'writer_lock_symlink')
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PolicyError('existing_writer_busy') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


@contextmanager
def _reader_control(state):
    path=Path(state)/'writer.lock'
    need(path.is_file() and not path.is_symlink(),'existing_writer_control_required')
    with path.open('r') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise PolicyError('existing_writer_busy') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def _guard_live(data,expected):
    for p in data['_input_pins'].values():_read_file(p)
    _,config_blob=_read_file(data['_input_pins']['config']);cfg=json.loads(config_blob)
    need(cfg==data['config'],'live_config_changed')
    need(current_rules_hash(cfg)==expected['rules_hash'],'live_scientific_rules_changed')
    actual=_main_revision(cfg)
    need(actual['main_revision']==expected['main_revision'],'main_controls_changed')
    need(actual['release_id']==expected['release_id'],'source_publication_changed')


def _write_new(path,value):
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())


def _pointer(root,value):
    temporary=root/('CURRENT.pending.'+uuid.uuid4().hex+'.json')
    _write_new(temporary,value)
    os.replace(temporary,root/'CURRENT.json')
    fd=os.open(root,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _control_root(root):
    root=Path(root)
    need(not root.is_symlink(),'control_root_symlink')
    if root.exists():
        need(root.is_dir(),'control_root_directory')
        allowed=lambda n:n in {'CURRENT.json','writer.lock'} or bool(re.fullmatch(
            r'gen_[0-9a-f]{32}|CURRENT\.pending\.[0-9a-f]{32}\.json',n))
        need(all(allowed(p.name) for p in root.iterdir()),'foreign_control_directory')
    return root


def read_active(root):
    root=_control_root(root)
    p=root/'CURRENT.json'
    if not p.exists():return None
    need(not p.is_symlink(),'control_pointer_symlink')
    pointer=_json(p)
    return _load_generation(root,pointer)


def _load_generation(root,pointer):
    root=Path(root)
    need(set(pointer)=={'format','generation','manifest_sha256'} and pointer['format']==POINTER_FORMAT
         and re.fullmatch('gen_[0-9a-f]{32}',pointer['generation']),'control_pointer_shape')
    folder=root/pointer['generation'];need(folder.is_dir() and not folder.is_symlink(),'generation_directory')
    need(file_hash(folder/'MANIFEST.json')==pointer['manifest_sha256'],'generation_manifest_hash')
    manifest=_json(folder/'MANIFEST.json')
    need(set(manifest)=={'format','files'} and manifest['format']==GEN_FORMAT,'generation_manifest_shape')
    required={'policy.json','policy-flags.sqlite','policy-manifest.json','combined-manifest.json','receipt.json','proposal.json','eric-reference.json','before-pointer.json'}
    need(set(manifest['files'])==required,'generation_files_shape')
    for name,h in manifest['files'].items():
        q=folder/name;need(q.is_file() and not q.is_symlink() and file_hash(q)==h,'generation_file_changed')
    registry_status(folder/'policy-flags.sqlite')  # Existing strict ledger validation.
    return dict(pointer=pointer,folder=folder,policy=_json(folder/'policy.json'),
                proposal=_json(folder/'proposal.json'),receipt=_json(folder/'receipt.json'),
                policy_manifest=_json(folder/'policy-manifest.json'),combined_manifest=_json(folder/'combined-manifest.json'))


def preview(bundle_path):
    _,d,options=load_bundle(bundle_path)
    return make_proposal(d['records'],d['cases'],d['groups'],d['decisions'],**options)


def _review(path,proposal):
    review=_json(path)
    need(set(review)=={'format','proposal_revision','accepted','reviewer','reason','review_manifest_sha256'}
         and review['format']==REVIEW_FORMAT and review['accepted'] is True,'independent_acceptance_required')
    need(review['proposal_revision']==proposal['revision'] and
         all(isinstance(review[k],str) and review[k].strip() for k in ('reviewer','reason')) and
         re.fullmatch('[0-9a-f]{64}',review['review_manifest_sha256']),'acceptance_binding')
    return review


def _stage(root,current,proposal,data,receipt,*,restore=None,fault=None):
    """Create all resources privately, then commit one pointer; retain failures."""
    fault=fault or (lambda phase:None)
    generation=root/('gen_'+uuid.uuid4().hex);generation.mkdir(mode=0o700)
    _write_new(generation/'before-pointer.json',current['pointer'] if current else None)
    fault('after_before_backup')
    rows=list(data['records'].values());release=receipt['release_id']
    inventory=Inventory.from_records(release,rows,provenance=dict(kind='exact_group_policy_no_csv_rematching'))
    registry=generation/'policy-flags.sqlite'
    if current:shutil.copyfile(current['folder']/'policy-flags.sqlite',registry)
    else:initialize_registry(registry,operator=receipt['operator'])
    fault('after_registry_copy')
    if restore is not None:
        target=restore['policy_manifest']['entries'] if restore else []
        # Restore exact earlier IDs/versions, never rebind them to changed rows.
        by_id=data['records']
        need(all(p['submission_id'] in by_id and by_id[p['submission_id']]['version_id']==p['version_id'] for p in target),'undo_source_version_drift')
        desired={p['submission_id'] for p in target}
        existing=validate_manifest(current['policy_manifest'],rows,release) if current else set()
        if existing-desired:decide_flags(registry,existing-desired,action='remove',operator=receipt['operator'],reason=receipt['reason'])
        if desired-existing:decide_flags(registry,desired-existing,action='restore',operator=receipt['operator'],reason=receipt['reason'],inventory=inventory)
    else:
        desired={p['submission_id'] for p in proposal['flag_entries']}
        previous_flags=registry_status(registry,include_history=True).get('flags',{})
        removed={sid for sid,flag in previous_flags.items() if flag['state']=='removed' and sid in desired}
        if removed:
            decide_flags(registry,removed,action='restore',operator=receipt['operator'],reason=receipt['reason'],inventory=inventory)
        manifest=exclusion_manifest(rows,release,desired,operator=receipt['operator'],at=receipt['at'])
        seed_manifest(registry,manifest,inventory,operator=receipt['operator'],reason=receipt['reason'])
    fault('after_registry_update')
    flag_report=export_manifest(registry,inventory,generation/'policy-manifest.json',operator=receipt['operator'])
    need(flag_report['status']=='accepted','policy_flags_export_blocked')
    policy_manifest=flag_report['manifest']
    need(validate_manifest(policy_manifest,rows,release)==desired,'unexpected_preserved_or_rebound_flag')
    combined=combined_manifest(rows,release,data['eric_manifest'],policy_manifest,operator=receipt['operator'],at=receipt['at'])
    _write_new(generation/'combined-manifest.json',combined)
    _write_new(generation/'eric-reference.json',data['eric_manifest'])
    _write_new(generation/'proposal.json',proposal)
    _write_new(generation/'policy.json',dict(format='study2_group_policy_control_v1',proposal_revision=proposal['revision'] if proposal else None,
        release_id=release,inventory_revision=inventory.revision,main_revision=receipt['main_revision'],
        policy_active=proposal is not None,partitions=proposal['partitions'] if proposal else {}))
    receipt.update(generation=generation.name,previous_pointer=current['pointer'] if current else None,
                   before_backup_generation=current['pointer']['generation'] if current else None,
                   after_backup_generation=generation.name,
                   proposal_revision=proposal['revision'] if proposal else None,
                   policy_manifest_revision=policy_manifest['revision'],combined_revision=combined['revision'])
    _write_new(generation/'receipt.json',receipt)
    files={n:file_hash(generation/n) for n in ('before-pointer.json','policy.json','policy-flags.sqlite','policy-manifest.json',
        'combined-manifest.json','receipt.json','proposal.json','eric-reference.json')}
    _write_new(generation/'MANIFEST.json',dict(format=GEN_FORMAT,files=files))
    fault('after_complete_backup')
    pointer=dict(format=POINTER_FORMAT,generation=generation.name,manifest_sha256=file_hash(generation/'MANIFEST.json'))
    # Source controls cannot change while the existing writer lock is held.
    _guard_live(data,dict(main_revision=receipt['main_revision'],release_id=receipt['release_id'],
                          rules_hash=receipt['rules_hash']))
    if proposal:need(implementation_revision()==proposal['base']['implementation_revision'],'policy_implementation_changed_during_apply')
    _pointer(root,pointer)
    fault('after_pointer_commit')
    return read_active(root)


def apply(root,bundle_path,proposal_path,review_path,*,operator,reason,fault=None):
    need(isinstance(operator,str) and operator.strip() and isinstance(reason,str) and reason.strip(),'operator_reason_required')
    _,d,options=load_bundle(bundle_path);proposal=_json(proposal_path)
    validate_proposal(proposal,d['records'],d['cases'],d['groups'],d['decisions'],**options)
    review=_review(review_path,proposal)
    op_id=sha(['apply',proposal['revision'],sha(review)])
    root=_control_root(root)
    need(root.resolve()!=Path(d['config']['state_dir']).resolve(),'policy_registry_must_be_separate')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with _writer_control(d['config']['state_dir']):
        _guard_live(d,proposal['base'])
        with _writer_control(root):
            current=read_active(root)
            if current and current['receipt']['operation_id']==op_id:
                return dict(status='applied',idempotent=True,pointer=current['pointer'])
            prior=current['policy_manifest']['revision'] if current and current['policy']['policy_active'] else None
            if 'carry' in d:
                need(current is not None and d['carry']==_carry_from_active(current,d,options),'carry_head_or_target_drift')
                need(prior==proposal['base']['prior_policy_origin_revision'] and
                     current['pointer']['manifest_sha256']==proposal['base']['prior_policy_head'],'policy_carry_head_changed')
            else:need(prior==proposal['base']['prior_policy_revision'],'policy_control_head_changed')
            receipt=dict(format='study2_group_policy_application_v1',operation='apply',operation_id=op_id,
                release_id=proposal['base']['release_id'],main_revision=proposal['base']['main_revision'],
                rules_hash=proposal['base']['rules_hash'],
                operator=operator,reason=reason,at=utcnow(),review=review,live_scientific_database_written=False)
            active=_stage(root,current,proposal,d,receipt,fault=fault)
            return dict(status='applied',idempotent=False,pointer=active['pointer'])


def undo(root,bundle_path,*,expected_head,operator,reason,fault=None):
    need(operator and reason,'operator_reason_required')
    _,d,options=load_bundle(bundle_path);root=Path(root)
    op_id=sha(['undo',expected_head,operator,reason])
    with _writer_control(d['config']['state_dir']):
        _guard_live(d,options)
        with _writer_control(root):
            current=read_active(root);need(current is not None,'no_active_policy_control')
            if current['receipt']['operation_id']==op_id:return dict(status='undone',idempotent=True,pointer=current['pointer'])
            need(current['pointer']['manifest_sha256']==expected_head,'undo_head_changed')
            prev=current['receipt']['previous_pointer']
            restored=None
            if prev:
                # Verify the complete earlier generation through the same loader,
                # without moving CURRENT or modifying any historical resource.
                restored=_read_named_generation(root,prev)
                need(restored['policy']['main_revision']==options['main_revision'],'undo_context_drift')
                # A refresh may point back to a proposal for an older inventory.
                # Reject before staging any generation, rather than commit a
                # restored view that project/status cannot read with this bundle.
                rows=list(d['records'].values())
                need(restored['policy']['release_id']==options['release_id'] and
                     restored['policy']['inventory_revision']==inventory_revision(rows),
                     'undo_incompatible_source_or_inventory')
                if restored['proposal'] is not None:
                    validate_proposal(restored['proposal'],d['records'],d['cases'],
                                      d['groups'],d['decisions'],**options)
                old_policy=validate_manifest(restored['policy_manifest'],rows,options['release_id'])
                old_union=validate_manifest(restored['combined_manifest'],rows,options['release_id'])
                eric=validate_manifest(d['eric_manifest'],rows,options['release_id'])
                need(old_union==eric|old_policy,'undo_incompatible_combined_flags')
            target=restored or dict(policy_manifest=dict(entries=[]))
            receipt=dict(format='study2_group_policy_application_v1',operation='undo',operation_id=op_id,
                release_id=options['release_id'],main_revision=options['main_revision'],operator=operator,
                rules_hash=options['rules_hash'],
                reason=reason,at=utcnow(),restored_pointer=prev,live_scientific_database_written=False)
            active=_stage(root,current,restored['proposal'] if restored else None,d,receipt,restore=target,fault=fault)
            return dict(status='undone',idempotent=False,pointer=active['pointer'])


def _read_named_generation(root,pointer):
    # read_active accepts a pointer value only through the same immutable checks;
    # use a nonwriting lightweight view rather than a temporary CURRENT file.
    return _load_generation(root,pointer)


def _local_snapshot_locked(bundle_path,root,*,include_cases=False):
    bundle,d,options=load_bundle(bundle_path);active=read_active(root)
    _guard_live(d,options)
    rows=list(d['records'].values());eric=validate_manifest(d['eric_manifest'],rows,options['release_id'])
    if active and active['proposal']:
        validate_proposal(active['proposal'],d['records'],d['cases'],d['groups'],d['decisions'],**options)
        excluded=validate_manifest(active['combined_manifest'],rows,options['release_id'])
        policy_ids=validate_manifest(active['policy_manifest'],rows,options['release_id'])
        need(excluded==eric|policy_ids,'combined_flag_union_mismatch')
        projection=project_workload(d['records'],d['cases'],d['groups'],d['decisions'],excluded=excluded,
                                    partitions=active['proposal']['partitions'])
        status='applied_local_policy'
    else:
        # OFF/undone does not apply generic closures merely because a classifier
        # is available. Raw baseline scopes remain the accepted original view.
        excluded=eric;projection=None;status='inactive'
    # Deliberately a separate explicit local workflow. Do not impersonate the
    # legacy queue_snapshot schema consumed by the existing dashboard.
    result=dict(status=status,release_id=options['release_id'],main_revision=options['main_revision'],
                production_publication_changed=False,policy_pointer=active['pointer'] if active else None,
                baseline_child_groups=len(d['groups']),baseline_field_corrections=len(project_workload(
                    d['records'],d['cases'],{},d['decisions'],excluded=eric)['correction_comparison_ids']))
    if projection:
        result.update(projection['counts'],remaining_general_reviews=projection['counts']['similarity_questions'],
            pending_candidates_total=len(projection['pending_comparison_ids']),
            child_groups_pending=projection['counts']['similarity_scopes'],
            awaiting_evidence_groups=projection['counts']['held_scopes'],
            awaiting_evidence_work=projection['counts']['held_scopes']+len(projection['adult_comparison_ids']))
        if include_cases:result['projection']=projection
    if 'analysis' in d:
        parents=d.get('parents')
        before=project_eligibility(rows,d['analysis'],parents,d['eric_manifest'],options['release_id'])
        after=project_eligibility(rows,d['analysis'],parents,active['combined_manifest'] if active and active['proposal'] else d['eric_manifest'],options['release_id'])
        result['native_counts_before']={k:len(v) for k,v in before.members.items()}
        result['native_counts_after']={k:len(v) for k,v in after.members.items()}
    return result


def local_snapshot(bundle_path,root,*,include_cases=False):
    _,data,_=load_bundle(bundle_path)
    with _reader_control(data['config']['state_dir']):
        return _local_snapshot_locked(bundle_path,root,include_cases=include_cases)


def _carry_from_active(active,data,options):
    need(active['policy']['policy_active'],'no_active_policy_to_carry')
    rows=list(data['records'].values());inventory=Inventory.from_records(options['release_id'],rows)
    flags=registry_status(active['folder']/'policy-flags.sqlite')['flags']
    old=[v['pin'] for v in flags.values() if v['state']=='active']
    current={r['submission_id']:{k:r[k] for k in ('submission_id','version_id','role','raw_hash')} for r in rows}
    need(all(p['submission_id'] in current and current[p['submission_id']]==p for p in old),'carry_missing_or_changed_flag_target')
    # Current-inventory compilation is explicit, while the old control head and
    # original full pin history are retained separately and checked at apply.
    m=exclusion_manifest(rows,options['release_id'],[p['submission_id'] for p in old],
                         operator='explicit_carry_preview',at=active['policy_manifest']['approved_at'])
    c=dict(format='study2_group_policy_carry_v1',old_pointer=active['pointer'],
           old_policy_manifest_revision=active['policy_manifest']['revision'],
           registry_sha256=file_hash(active['folder']/'policy-flags.sqlite'),
           target_release_id=options['release_id'],target_inventory_revision=inventory.revision,
           active_pins=sorted(old,key=lambda p:p['submission_id']),recompiled_manifest=m)
    c['revision']=sha(c)
    return c


def carry_preview(bundle_path,root):
    _,data,options=load_bundle(bundle_path)
    with _reader_control(data['config']['state_dir']):
        _guard_live(data,options);active=read_active(root)
        need(active is not None,'no_policy_control_to_carry')
        return _carry_from_active(active,data,options)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for name in ('dry-run','carry','apply','undo','project','status'):
        q=sub.add_parser(name);q.add_argument('--bundle',required=True,type=Path);q.add_argument('--output',type=Path)
        if name!='dry-run':q.add_argument('--control-root',required=True,type=Path)
        if name=='apply':q.add_argument('--proposal',required=True,type=Path);q.add_argument('--review',required=True,type=Path)
        if name=='undo':q.add_argument('--expected-head',required=True)
        if name in {'apply','undo'}:q.add_argument('--operator',required=True);q.add_argument('--reason',required=True)
    a=p.parse_args()
    try:
        if a.command=='dry-run':r=preview(a.bundle)
        elif a.command=='carry':r=carry_preview(a.bundle,a.control_root)
        elif a.command=='apply':r=apply(a.control_root,a.bundle,a.proposal,a.review,operator=a.operator,reason=a.reason)
        elif a.command=='undo':r=undo(a.control_root,a.bundle,expected_head=a.expected_head,operator=a.operator,reason=a.reason)
        else:r=local_snapshot(a.bundle,a.control_root,include_cases=a.command=='project')
        if a.output:_write_new(a.output,r)
        print(json.dumps({k:r[k] for k in ('status','revision','idempotent','flag_counts','production_publication_changed') if k in r},sort_keys=True))
        return 0
    except (PolicyError,OSError,ValueError,sqlite3.Error):
        print('{"status":"blocked","code":"group_policy_operation_requires_inspection"}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
