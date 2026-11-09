"""Live-checked derived carry workload; original closure events stay untouched.

Uses the existing publication tuple/journal. Per-case drift is an explicit hold;
incoherent source tuples, controls, rules or history fail the whole preparation.
"""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .common import digest
from .review_dispositions import _bindings, _case, _history, administrative_revision, project_closures, CLOSE
from .administrative_carry_preview import _current_code_pins

FORMAT='study2_current_admin_carry_v1'
from .compatibility_profiles import administrative_scope_sha256

# Test seam only; production trust is configured at startup.
SCOPED_CERTIFICATE_SHA256 = None
HOLD_REASONS={
    'source_closure_no_longer_current':'The earlier closure is no longer the current source disposition.',
    'source_closure_authority_or_evidence_changed':'Source authority or closure evidence changed.',
    'closed_source_case_missing_from_target':'The closed source comparison is absent from the target correction inventory.',
    'closed_source_case_evidence_changed':'Target reasons, endpoints, versions or evidence changed.',
    'source_closure_outside_accepted_scope':'A source closure falls outside the accepted carry scope.',
    'unresolved_source_case_missing_from_target':'An unresolved source comparison is absent from the target inventory.',
    'unresolved_source_hold_still_missing':'An earlier unresolved source hold remains absent from the target inventory.',
}


def need(ok,code):
    if not ok:raise ValueError('current_admin_carry_'+code)


def check_scope(scope):
    need(isinstance(scope,dict) and digest(scope)==(SCOPED_CERTIFICATE_SHA256 or administrative_scope_sha256()),'unaccepted_scope')
    need(scope['format']=='study2_admin_carry_scope_v1' and
         _current_code_pins(scope['target_code_sha256'])==scope['target_code_sha256'],'rules_code_changed')
    return scope


def _ro(path):
    p=Path(path);need(p.is_file() and not p.is_symlink(),'database_missing')
    db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON');return db


def controls(main):
    from .review import active_decisions
    active=active_decisions(main)
    return {'decision_revision':digest([tuple(r) for r in main.execute(
                'SELECT decision_id,payload_json,supersedes FROM decisions ORDER BY decision_id')]),
            'main_revision':digest({'decisions':active,'labels':[dict(r) for r in main.execute('SELECT * FROM labels ORDER BY case_id')]}),
            'decisions':active}


def canonical_cases(records,cases,ids,decisions):
    from .review_dispatch import Router
    from .matching import identity_evidence
    router=Router(records,decisions);result=[]
    need(len(ids)==len(set(ids)),'duplicate_target_case')
    for cid in sorted(ids):
        need(cid in cases,'target_case_missing')
        c=cases[cid];route=router.classify(c)
        need(route['route']=='correction','target_correction_inventory_changed')
        a,b=c['record_a'],c['record_b']
        result.append(_case({'case_id':cid,'route':'correction','record_a':a,'record_b':b,
            'version_a':records[a]['version_id'],'version_b':records[b]['version_id'],'reasons':route['reasons'],
            'evidence_hash':digest({'case':c,'a':identity_evidence(records[a]),'b':identity_evidence(records[b]),
                                    'correction_reasons':sorted(route['reasons'])})}))
    return result


def project_current(work,scope,source_summary,target_bindings,target_cases):
    """Read-only per-case overlay, delegating valid closures to native projection."""
    scope=check_scope(scope);target_bindings=_bindings(target_bindings)
    need(isinstance(source_summary,dict) and isinstance(source_summary.get('administrative_disposition'),dict),'source_summary_shape')
    source=source_summary['administrative_disposition']
    current_revision=administrative_revision(work)
    need(current_revision==source['admin_revision'],'source_workload_stale')
    events,heads,mirrors=_history(work)
    accepted={r['case_id']:_case(r) for r in scope['closed_cases']}
    current={r['case_id']:_case(r) for r in target_cases}
    need(len(current)==len(target_cases),'duplicate_target_case')
    holds={}
    def hold(cid,reason,source_case=None):
        row=holds.setdefault(cid,{'case_id':cid,'reasons':[],'source_case':deepcopy(source_case)})
        row['reasons']=sorted(set(row['reasons'])|{reason})
    for cid,old in accepted.items():
        event=heads.get(cid)
        if event is None or event['kind']!=CLOSE:
            hold(cid,'source_closure_no_longer_current',old);continue
        request=event['body']['request']
        need(mirrors[cid]==event['body']['after_rows'][cid],'source_followup_mirror_changed')
        saved={r['case_id']:_case(r) for r in request['cases']}
        if request['bindings']!=scope['source_bindings'] or saved.get(cid)!=old:
            hold(cid,'source_closure_authority_or_evidence_changed',old)
        elif cid not in current:
            hold(cid,'closed_source_case_missing_from_target',old)
        elif current[cid]!=old:
            hold(cid,'closed_source_case_evidence_changed',old)
    # New source closures are not silently ignored or borrowed into this scope.
    for cid,event in heads.items():
        if event['kind']==CLOSE and cid not in accepted:
            need(mirrors[cid]==event['body']['after_rows'][cid],'source_followup_mirror_changed')
            saved={r['case_id']:_case(r) for r in event['body']['request']['cases']}
            hold(cid,'source_closure_outside_accepted_scope',saved[cid])
    source_cases={r['case_id']:_case(r) for r in source['case_inventory']}
    for cid in source['projection']['active_case_ids']:
        if cid not in current:hold(cid,'unresolved_source_case_missing_from_target',source_cases[cid])
    prior=source.get('carry_forward')
    need(prior is None or isinstance(prior,dict),'source_carry_shape')
    previous=prior.get('holds',[]) if prior else []
    need(isinstance(previous,list) and all(isinstance(row,dict) for row in previous),'source_holds_shape')
    for row in previous:
        cid=row['case_id']
        if cid not in current:hold(cid,'unresolved_source_hold_still_missing',row['source_case'])
    # Native projection is intentionally given only evidence-consistent cases.
    # Its existing all-or-nothing stale rule remains unchanged. Held cases have
    # an explicit lane and cannot erase valid closures in unrelated cases.
    filtered=[r for r in target_cases if r['case_id'] not in holds]
    native=project_closures(work,scope['source_bindings'],filtered)
    need(native['projection_ready'],'native_projection_inconsistent')
    expected=set(accepted)-set(holds)
    need(set(native['closed_case_ids'])==expected,'unexpected_source_closure_scope')
    result=deepcopy(native)
    result.update(bindings=deepcopy(target_bindings),raw_correction_comparisons=len(current),
        held_case_ids=sorted(holds),held_comparisons=len(holds),
        held_current_comparisons=len(set(holds)&set(current)),
        source_only_hold_comparisons=len(set(holds)-set(current)),
        carry_scope_revision=(SCOPED_CERTIFICATE_SHA256 or administrative_scope_sha256()))
    need(len(current)==result['closed_unresolvable_comparisons']+result['active_correction_comparisons']+
         result['held_current_comparisons'],'projection_partition_mismatch')
    return result,[holds[cid] for cid in sorted(holds)]


def _read_pin(pin):
    from .group_cleaning_operator import _read_file
    p=Path(pin['path']);s=p.lstat()
    need(not getattr(s,'st_flags',0)&0x40000000,'input_not_resident')
    return _read_file(pin)[1]


def _source_summary(state,pointer):
    p=Path(pointer['workload_path']).absolute()
    need(p.resolve().is_relative_to((Path(state)/'review_dispositions').resolve()),'source_workload_outside_state')
    value=json.loads(_read_pin({'path':str(p),'sha256':pointer['workload_sha256']}))
    need(isinstance(value,dict) and value.get('release_id')==pointer['release_id'],'source_pointer_release_changed')
    block=value.get('administrative_disposition')
    need(isinstance(block,dict) and pointer.get('admin_revision')==block['admin_revision'] and
         pointer.get('operation_id')==block['operation_id'],'source_pointer_administrative_binding_changed')
    return value


def _historical_reader(cfg, block):
    """Authenticate the exact archived workload and declared recovery bytes.

    The startup profile is independent authority for this READ contract, not a
    global rules alias. Signed paths and certificates are never rewritten.
    """
    from .compatibility_profiles import administrative_read_contract
    from .review_core import rules_hash
    from .controls_capture import read_pin, code_revision
    trust = administrative_read_contract()
    need(isinstance(trust, dict), 'historical_read_not_configured')
    scope = block['carry_forward']['scope']
    need(digest(scope) == trust['scope_sha256'], 'unaccepted_scope')
    need(scope['format'] == 'study2_admin_carry_scope_v1', 'scope_format')
    need(set(scope['target_code_sha256']) == set(trust['reader_code_sha256']) ==
         set(trust['original_code']), 'historical_code_inventory_changed')
    need(_current_code_pins(trust['reader_code_sha256']) == trust['reader_code_sha256'] and
         rules_hash(cfg) == trust['reader_rules_hash'] and code_revision() == trust['reader_revision'], 'historical_reader_changed')
    manifest = read_pin(trust['recovery_manifest'])
    need(manifest.get('format_version') == 1, 'recovery_manifest_format')
    root = Path(trust['recovery_root'])
    need(root.resolve() == Path(cfg['state_dir']).resolve() and
         not any(p.is_symlink() for p in (root, *root.parents)), 'recovery_root_changed')
    assets = {}
    for name, entry in manifest['files'].items():
        relative = entry.get('restore_path', name)
        need(relative not in assets, 'duplicate_recovery_asset')
        assets[relative] = entry['uncompressed_sha256'] if entry.get('gzip') else entry['sha256']

    def asset(relative, expected):
        relative = Path(relative)
        need(not relative.is_absolute() and '..' not in relative.parts and
             assets.get(relative.as_posix()) == expected, 'unregistered_recovery_asset')
        path = root / relative
        need(not any(p.is_symlink() for p in (path, *path.parents)) and
             path.resolve().is_relative_to(root.resolve()), 'unsafe_recovery_path')
        before = path.stat()
        need(path.is_file() and not getattr(before, 'st_flags', 0) & 0x40000000, 'recovery_asset_not_resident')
        raw = path.read_bytes(); after = path.stat()
        need((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns) and
             hashlib.sha256(raw).hexdigest() == expected, 'recovery_asset_changed')
        return path, raw

    def resolve(pin):
        need(pin['path'] in trust['path_map'], 'unregistered_historical_path')
        return asset(trust['path_map'][pin['path']], pin['sha256'])

    for name, expected in scope['target_code_sha256'].items():
        asset(trust['original_code'][name], expected)
    _, raw = resolve(trust['workload_pin'])
    original = json.loads(raw)
    need(original.get('administrative_disposition') == block, 'historical_workload_changed')
    pointer = json.loads((root / 'CURRENT_REVIEW_DISPOSITION.json').read_bytes())
    need(pointer.get('workload_sha256') == trust['workload_pin']['sha256'] and
         pointer.get('release_id') == original['release_id'] and
         pointer.get('admin_revision') == block['admin_revision'] and
         pointer.get('operation_id') == block['operation_id'], 'historical_current_pointer_changed')
    return scope, resolve, original


def _validate_historical_workload(cfg, work, block, *, inventory=None):
    """Exact historical READ only. Drift fails; no new holds or authority."""
    from .manual_flags import load_inventory
    from .analysis_eligibility import inventory_revision
    scope, resolve, original = _historical_reader(cfg, block)
    carry = block['carry_forward']; context = carry['target_context']
    need(carry.get('format') == FORMAT and carry['holds'] == [], 'historical_carry_shape')
    need(scope['target_rules_hash'] == context['rules_hash'] == block['bindings']['rules_hash'],
         'rules_context_changed')
    main = _ro(Path(cfg['state_dir']) / 'study2.sqlite')
    try:
        current = controls(main)
        from .store import current as publication
        published = publication(main)
        need(published is not None and published['release_id'] == context['release_id'], 'historical_publication_changed')
    finally: main.close()
    need(all(current[k] == context[k] for k in ('decision_revision', 'main_revision')),
         'main_or_decision_revision_changed')
    need(block['bindings']['release_id'] == context['release_id'] == original['release_id'] and
         block['bindings']['decision_revision'] == context['decision_revision'] == original['decision_revision'],
         'target_binding_context_changed')
    pins = carry['release_inputs']
    record_path, _ = resolve(pins['records'])
    if inventory is None: inventory = load_inventory(release_folder=record_path.parent)
    need(inventory.release_id == context['release_id'] and inventory.revision == context['inventory_revision'] and
         inventory_revision(inventory.records) == inventory.revision and
         inventory.provenance.get('records') == {'path': str(record_path), 'sha256': pins['records']['sha256']},
         'record_inventory_changed')
    _, raw = resolve(pins['cases'])
    rows = [json.loads(line) for line in gzip.decompress(raw).splitlines() if line.strip()]
    cases = {r['case_id']: r for r in rows}
    need(len(cases) == len(rows), 'duplicate_release_case')
    actual = canonical_cases({r['submission_id']: r for r in inventory.records}, cases,
                             carry['target_case_ids'], current['decisions'])
    need(actual == block['case_inventory'], 'target_case_evidence_changed_since_preparation')
    pointer = carry['source_pointer']
    source_path, raw = resolve({'path': pointer['workload_path'], 'sha256': pointer['workload_sha256']})
    need(source_path.resolve().is_relative_to((Path(cfg['state_dir']) / 'review_dispositions').resolve()),
         'source_workload_outside_state')
    source = json.loads(raw); source_block = source['administrative_disposition']
    need(source['release_id'] == pointer['release_id'] and
         source_block['operation_id'] == pointer['operation_id'] == scope['source_operation_id'] and
         source_block['admin_revision'] == pointer['admin_revision'] == scope['source_admin_revision'] ==
         block['admin_revision'] == administrative_revision(work), 'source_pointer_administrative_binding_changed')
    need(source_block['bindings'] == scope['source_bindings'] and
         project_closures(work, scope['source_bindings'], source_block['case_inventory']) == source_block['projection'],
         'source_history_changed')
    native = project_closures(work, scope['source_bindings'], actual)
    need(native['projection_ready'] and all(not native[k] for k in
         ('stale_case_ids', 'expired_binding_case_ids', 'absent_current_case_ids')), 'native_projection_inconsistent')
    accepted = {r['case_id']: _case(r) for r in scope['closed_cases']}
    need(len(accepted) == len(scope['closed_cases']) and set(native['closed_case_ids']) == set(accepted) and
         all(accepted[c['case_id']] == c for c in actual if c['case_id'] in accepted), 'unexpected_source_closure_scope')
    projection = deepcopy(native)
    projection.update(bindings=deepcopy(block['bindings']), raw_correction_comparisons=len(actual),
        held_case_ids=[], held_comparisons=0, held_current_comparisons=0, source_only_hold_comparisons=0,
        carry_scope_revision=digest(scope))
    need(projection == block['projection'], 'derived_projection_changed')
    return projection


def validate_workload(cfg,work,block,*,inventory=None,historical_read=False):
    """Called by the existing live workload validator, also under publication fences."""
    if historical_read:
        return _validate_historical_workload(cfg,work,block,inventory=inventory)
    from .manual_flags import load_inventory
    from .review_core import rules_hash
    carry=block['carry_forward'];need(isinstance(carry,dict) and carry.get('format')==FORMAT,'format')
    scope=check_scope(carry['scope']);context=carry['target_context']
    need(isinstance(context,dict),'target_context_shape')
    need(rules_hash(cfg)==scope['target_rules_hash']==context['rules_hash']==block['bindings']['rules_hash'],'rules_context_changed')
    main=_ro(Path(cfg['state_dir'])/'study2.sqlite')
    try:current=controls(main)
    finally:main.close()
    need(all(current[k]==context[k] for k in ('decision_revision','main_revision')),'main_or_decision_revision_changed')
    need(block['bindings']['release_id']==context['release_id'] and
         block['bindings']['decision_revision']==context['decision_revision'],'target_binding_context_changed')
    pins=carry['release_inputs'];record_pin=pins['records']
    if inventory is None:inventory=load_inventory(release_folder=Path(record_pin['path']).parent)
    need(inventory.release_id==context['release_id'] and inventory.revision==context['inventory_revision'] and
         inventory.provenance.get('records')==record_pin,'record_inventory_changed')
    # Inventory may be supplied by the existing flag guard to avoid reloading it.
    from .analysis_eligibility import inventory_revision
    need(inventory_revision(inventory.records)==inventory.revision,'record_inventory_mutated')
    case_blob=_read_pin(pins['cases'])
    case_rows=[json.loads(line) for line in gzip.decompress(case_blob).splitlines() if line.strip()]
    cases={r['case_id']:r for r in case_rows};need(len(cases)==len(case_rows),'duplicate_release_case')
    actual=canonical_cases({r['submission_id']:r for r in inventory.records},cases,carry['target_case_ids'],current['decisions'])
    need(actual==block['case_inventory'],'target_case_evidence_changed_since_preparation')
    source=_source_summary(cfg['state_dir'],carry['source_pointer'])
    projection,holds=project_current(work,scope,source,block['bindings'],actual)
    need(projection==block['projection'] and holds==carry['holds'] and
         projection['admin_revision']==block['admin_revision'],'derived_projection_changed')
    return projection


def validate_transition_source(plan):
    """Bind staged carry provenance to the journal's actual old workload tuple."""
    value=json.loads(_read_pin({'path':plan['target_workload']['workload_path'],
                               'sha256':plan['target_workload']['workload_sha256']}))
    block=value.get('administrative_disposition') or {};carry=block.get('carry_forward')
    if carry is not None:
        need(carry['source_pointer']==plan['old_workload'] and
             carry['target_context']['release_id']==plan['target_release_id'] and
             carry['target_context']['main_revision']==plan['revisions']['main'],'transition_source_tuple_changed')


def stage_workload(cfg,scope,bundle_path,proposal_path,target_manifest_pin,target_release_path,output_dir,*,fault=None):
    """Prepare derived files only. CURRENT and research/flag databases are not written.

    Existing native policy staging and an independently reviewed publication tuple
    remain mandatory. Operational calls are not authorized by this function.
    """
    from . import group_cleaning_operator as group, flag_binding as binding
    from .continuity_integration import validate_bound
    from .manual_flags import load_inventory
    from .analysis_eligibility import validate_manifest
    from .review_workload import load_summary
    check_scope(scope)
    fault=fault or (lambda phase:None)
    bundle,data,options=group.load_bundle(bundle_path);proposal=group._json(proposal_path)
    validate_bound(proposal,data,options)
    need(data['config']==cfg,'bundle_configuration_changed')
    state=Path(cfg['state_dir']);output=Path(output_dir).absolute()
    need(output.parent.resolve()==(state/'review_dispositions').resolve() and not output.exists() and
         all(not p.is_symlink() for p in [output,*output.parents]),'new_derived_output_required')
    with group._reader_control(state):
        source_pointer=group._json(state/'CURRENT_REVIEW_DISPOSITION.json')
        historical_read=binding.historical_current(cfg)
        old_manifest=binding.resolve_current(cfg,historical_read=historical_read)
        source=_source_summary(state,source_pointer)
        need(bundle['release_id'] != source['release_id'],'different_target_release_required')
        # The old active tuple is a global coherence boundary, not a per-case hold.
        load_summary(release_id=source['release_id'],decision_revision=source['decision_revision'],
                     exclusion_revision=source['exclusion_manifest_revision'],path=source_pointer['workload_path'],
                     review_state=state,cfg=cfg,historical_read=historical_read)
        target_manifest=json.loads(_read_pin(target_manifest_pin))
        inventory=load_inventory(release_folder=target_release_path)
        need(inventory.release_id==bundle['release_id'] and inventory.revision==proposal['base']['inventory_revision'],'target_inventory_context_changed')
        validate_manifest(target_manifest,list(inventory.records),inventory.release_id)
        need(target_manifest['entries']==group._json(old_manifest)['entries'],'existing_flag_entries_changed')
        need({r['submission_id']:r for r in inventory.records}==data['records'],'bundle_release_records_changed')
        case_path=Path(target_release_path)/'cases.jsonl.gz'
        need(not getattr(case_path.lstat(),'st_flags',0)&0x40000000,'case_input_not_resident')
        case_pin={'path':str(case_path),'sha256':group.file_hash(case_path)}
        case_rows=[json.loads(line) for line in gzip.decompress(_read_pin(case_pin)).splitlines() if line.strip()]
        release_cases={r['case_id']:r for r in case_rows};need(len(release_cases)==len(case_rows),'duplicate_release_case')
        ids=proposal['projection']['correction_comparison_ids']
        need(all(release_cases.get(cid)==data['cases'].get(cid) for cid in ids),'bundle_release_cases_changed')
        main=_ro(state/'study2.sqlite');work=_ro(state/'review.sqlite')
        try:
            current=controls(main)
            need(current['main_revision']==proposal['base']['main_revision'],'main_revision_changed')
            from .review_core import rules_hash
            need(rules_hash(cfg)==scope['target_rules_hash']==proposal['base']['rules_hash'],'rules_context_changed')
            cases=canonical_cases(data['records'],release_cases,ids,current['decisions'])
            bindings=deepcopy(scope['source_bindings'])
            bindings.update(release_id=bundle['release_id'],rules_hash=scope['target_rules_hash'],decision_revision=current['decision_revision'])
            bindings['output_bindings']={'correction_inventory':digest(cases),'native_case_file':case_pin['sha256'],
                'native_records':inventory.provenance['records']['sha256'],'proposal_revision':proposal['revision'],
                'combined_manifest':target_manifest_pin['sha256']}
            projection,holds=project_current(work,scope,source,bindings,cases)
            context={**proposal['base'],'decision_revision':current['decision_revision']}
            block={'bindings':bindings,'case_inventory':cases,'projection':projection,
                'admin_revision':projection['admin_revision'],'operation_id':scope['source_operation_id'],
                'carry_forward':{'format':FORMAT,'scope':deepcopy(scope),'source_pointer':source_pointer,
                    'target_context':context,'target_case_ids':sorted(ids),'release_inputs':{'records':inventory.provenance['records'],'cases':case_pin},'holds':holds}}
            summary=deepcopy(source);native=deepcopy(proposal['projection']['counts']);active=deepcopy(native)
            active['field_correction_comparisons']=projection['active_correction_comparisons']
            active['administrative_carry_holds']=len(holds)
            summary.update(release_id=bundle['release_id'],decision_revision=current['decision_revision'],
                exclusion_manifest_revision=target_manifest['revision'],native_workload=native,active_workload=active,
                administrative_disposition=block)
            validate_workload(cfg,work,block,inventory=inventory)
        finally:main.close();work.close()
        output.mkdir(mode=0o700)
        for name,value in [('workload.json',summary),('projection.private.json',projection),('holds.private.json',holds)]:
            group._write_new(output/name,value);(output/name).chmod(0o600)
            fault(name+':after_sync')
        pointer={'release_id':bundle['release_id'],'workload_path':str(output/'workload.json'),
            'workload_sha256':group.file_hash(output/'workload.json'),'admin_revision':block['admin_revision'],
            'operation_id':block['operation_id'],'active_dataset_path':str(output/'projection.private.json')}
        group._write_new(output/'pointer.json',pointer);(output/'pointer.json').chmod(0o600)
        for directory in (output,output.parent):
            descriptor=os.open(directory,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        return {'status':'prepared_not_activated','pointer':pointer,'closed_comparisons':projection['closed_unresolvable_comparisons'],
                'active_comparisons':projection['active_correction_comparisons'],'held_comparisons':len(holds)}
