"""One exact, snapshot-bound administrative carry plan. No state writer.

The startup-configured profile authenticates accepted scoped evidence, not a
global rules alias. The result proposes a transition; it cannot apply one.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .analysis_eligibility import sha
from .common import digest
from .review_dispositions import _bindings, _case

FORMAT = 'study2_admin_carry_preview_v1'
from .compatibility_profiles import ADMINISTRATIVE_PREVIEW as PROFILE
OUTPUT_ROOT = Path(__file__).resolve().parents[2]


def need(condition,code):
    if not condition:raise ValueError('admin_carry_'+code)


def mapping(value,name):
    need(isinstance(value,dict),name+'_shape')
    return value


def rows(value,name):
    need(isinstance(value,list) and all(isinstance(r,dict) for r in value),name+'_shape')
    return value


def _current_code_pins(names):
    root=Path(__file__).resolve().parent;result={}
    for name in names:
        need(isinstance(name,str) and re.fullmatch(r'[a-z_]+\.py',name) is not None,'code_name')
        p=root/name;s=p.lstat()
        need(p.is_file() and not p.is_symlink() and not getattr(s,'st_flags',0)&0x40000000,'code_not_resident')
        result[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def _verified_inputs(blobs):
    need(bool(PROFILE), 'trusted_profile_required')
    need(isinstance(blobs,dict) and set(blobs)==set(PROFILE['inputs']),'input_inventory')
    for name,want in PROFILE['inputs'].items():
        need(isinstance(blobs[name],bytes) and hashlib.sha256(blobs[name]).hexdigest()==want,'unverified_'+name)
    data={name:json.loads(raw) for name,raw in blobs.items() if name!='acceptance_report'}
    for name in data:mapping(data[name],name)
    manifest=data['evidence_manifest']['files']
    for name,filename in [('inventory','TARGET_CASE_INVENTORY.private.json'),('compatibility','RULE_COMPATIBILITY_EVIDENCE.json'),('assessment','ASSESSMENT.json')]:
        need(manifest[filename]==PROFILE['inputs'][name],'evidence_manifest_binding')
    return data


def _transition(data):
    proposal,inventory,compat,assessment=(data[k] for k in ('proposal','inventory','compatibility','assessment'))
    base=mapping(proposal.get('base'),'target_context')
    need(proposal.get('revision')==sha({k:v for k,v in proposal.items() if k!='revision'}),'proposal_revision')
    block=mapping(data['source_workload'].get('administrative_disposition'),'source_disposition')
    source=_bindings(block['bindings']);target=_bindings(inventory['recorded_target_bindings'])
    projection=mapping(block.get('projection'),'source_projection')
    need(projection.get('projection_ready') is True and projection['bindings']==source and
         projection['admin_revision']==block['admin_revision']==inventory['source_admin_revision'],'source_projection_binding')
    need(all(not projection.get(k) for k in ('stale_case_ids','expired_binding_case_ids','absent_current_case_ids')),'source_projection_stale')
    need(inventory['target_context']==base and inventory['source_bindings']==source,'context_changed')
    need(inventory['target_controls_decision_and_main_revisions_recomputed'] is True and
         inventory['target_run_manifest_body_verified_this_capture'] is True and inventory['state_written'] is False,'unverified_target_inputs')
    need(source['rules_hash']==compat['source_rules_hash']==PROFILE['source_rules_hash'] and
         target['rules_hash']==base['rules_hash']==compat['target_rules_hash']==PROFILE['target_rules_hash'] and
         target['release_id']==base['release_id']==PROFILE['target_release_id'],'rules_or_release_scope_changed')
    need(target['decision_revision']==inventory['decision_revision']==data['source_workload']['decision_revision'],'decision_context_changed')
    need(compat['semantic_config_equal'] is True and compat['review_module_rest_ast_equal'] is True and
         compat['only_changed_definitions']==['backup_workspace','workspace'] and
         compat['global_rule_equivalence_claimed'] is False and compat['operational_rebind_permitted'] is False,'compatibility_scope_changed')
    code_pins=mapping(compat.get('target_code_sha256'),'code_pins')
    need(_current_code_pins(code_pins)==code_pins,'current_rules_code_changed')
    source_rows=rows(block.get('case_inventory'),'source_cases');target_rows=rows(inventory.get('case_inventory'),'target_cases')
    old={r['case_id']:_case(r) for r in source_rows};new={r['case_id']:_case(r) for r in target_rows}
    need(len(old)==len(source_rows) and len(new)==len(target_rows)==PROFILE['target_comparisons'],'case_inventory_changed')
    closed=projection.get('closed_case_ids')
    need(isinstance(closed,list) and all(isinstance(cid,str) for cid in closed) and
         len(closed)==len(set(closed))==PROFILE['closed_comparisons'] and
         set(closed)==set(inventory['preserved_source_closure_case_ids']),'closure_scope_changed')
    need(all(cid in old and cid in new and old[cid]==new[cid] for cid in closed),'case_reasons_endpoints_or_evidence_changed')
    output=mapping(target['output_bindings'],'target_outputs')
    need(output['correction_inventory']==digest(target_rows) and
         output['run_manifest']==inventory['target_run_manifest_sha256'],'target_output_binding_changed')
    need(assessment['target_closures_exactly_matching']==len(closed) and
         assessment['case_equality_counterfactual_closed']==len(closed) and
         assessment['case_equality_counterfactual_active']==len(new)-len(closed) and
         assessment['actual_target_bound_closed']==0 and assessment['actual_target_bound_active']==len(new) and
         assessment['actual_target_expired_bindings']==len(closed) and assessment['formal_rebind_performed'] is False,'projection_evidence_changed')
    return {'format':'study2_admin_carry_transition_plan_v1','status':'provisional_snapshot_plan_not_rebound',
        'profile_id':PROFILE['id'],'accepted_evidence_sha256':PROFILE['inputs']['evidence_manifest'],
        'acceptance_report_sha256':PROFILE['inputs']['acceptance_report'],
        'source_admin_revision':block['admin_revision'],'source_bindings':deepcopy(source),
        'target_bindings':deepcopy(target),'target_context':deepcopy(base),
        'preserve_case_ids':sorted(closed),'preserve_case_binding_sha256':digest([new[cid] for cid in sorted(closed)]),
        'target_inventory_sha256':PROFILE['inputs']['inventory'],
        'target_raw_comparisons':len(new),'proposed_preserved_comparisons':len(closed),
        'projected_active_comparisons':len(new)-len(closed),'native_target_closed':0,
        'native_target_active':len(new),'native_target_expired':len(closed),
        'research_judgments_changed':False,'formal_rebind_performed':False,'activation_permitted':False}


def build_preview(blobs):
    data=_verified_inputs(blobs);transition=_transition(data)
    result={'format':FORMAT,'profile_id':PROFILE['id'],
        'inputs':{k:base64.b64encode(v).decode() for k,v in blobs.items()},'transition':transition}
    result['revision']=sha(result)
    return result


def validate_preview(value):
    need(bool(PROFILE), 'trusted_profile_required')
    value=mapping(value,'preview')
    need(set(value)=={'format','profile_id','inputs','transition','revision'} and
         value['format']==FORMAT and value['profile_id']==PROFILE['id'],'preview_scope')
    need(value['revision']==sha({k:v for k,v in value.items() if k!='revision'}),'preview_revision')
    encoded=mapping(value.get('inputs'),'encoded_inputs');blobs={}
    need(set(encoded)==set(PROFILE['inputs']),'input_inventory')
    for name,text in encoded.items():
        need(isinstance(text,str),'encoded_input_shape')
        try:blobs[name]=base64.b64decode(text,validate=True)
        except (ValueError,TypeError):raise ValueError('admin_carry_invalid_base64') from None
    data=_verified_inputs(blobs);expected=_transition(data)
    need(value['transition']==expected,'transition_changed')
    view={k:expected[k] for k in ('status','target_raw_comparisons','proposed_preserved_comparisons',
        'projected_active_comparisons','native_target_closed','native_target_active','native_target_expired')}
    view['rows']=[{'Earlier closure':f'Closure {i}','Recorded disposition':'Unresolvable',
                   'Provisional plan':'Preserve the recorded closure','Case binding':'Unchanged in accepted scoped evidence'}
                  for i in range(1,expected['proposed_preserved_comparisons']+1)]
    return data['proposal'],view


def prepare_preview(proposal_path,source_workload_path,evidence_dir,acceptance_report_path,output_dir):
    """Write-new private plan/HTML in this isolated candidate only. No DB access."""
    evidence_dir=Path(evidence_dir)
    paths={'proposal':Path(proposal_path),'source_workload':Path(source_workload_path),
        'inventory':evidence_dir/'TARGET_CASE_INVENTORY.private.json','compatibility':evidence_dir/'RULE_COMPATIBILITY_EVIDENCE.json',
        'assessment':evidence_dir/'ASSESSMENT.json','evidence_manifest':evidence_dir/'EVIDENCE_MANIFEST.json',
        'acceptance_report':Path(acceptance_report_path)}
    blobs={}
    for name,p in paths.items():
        s=p.lstat();need(p.is_file() and not p.is_symlink() and not getattr(s,'st_flags',0)&0x40000000,'input_not_resident')
        blobs[name]=p.read_bytes()
        t=p.lstat();need((s.st_ino,s.st_size,s.st_mtime_ns)==(t.st_ino,t.st_size,t.st_mtime_ns),'input_changed_during_read')
    preview=build_preview(blobs)
    output=Path(output_dir).absolute()
    need(output.parent==OUTPUT_ROOT and re.fullmatch(r'admin-carry-preview-[a-z0-9_-]+',output.name) is not None,'candidate_output_required')
    need(all(not p.is_symlink() for p in [output,*output.parents]) and not output.exists(),'new_regular_output_required')
    from .group_intent_review import review_html
    page=review_html(preview)
    output.mkdir(mode=0o700)
    payloads={'preview.private.json':json.dumps(preview,sort_keys=True,ensure_ascii=False,indent=2),
        'transition.private.json':json.dumps(preview['transition'],sort_keys=True,ensure_ascii=False,indent=2),'preview.html':page}
    pins={}
    for name,text in payloads.items():
        p=output/name
        with p.open('x',encoding='utf-8') as f:f.write(text+'\n')
        p.chmod(0o600);pins[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    p=output/'MANIFEST.json'
    with p.open('x',encoding='utf-8') as f:json.dump({'status':'provisional_not_rebound','files':pins},f,sort_keys=True,indent=2);f.write('\n')
    p.chmod(0o600)
    return {'status':'provisional_not_rebound','preview':str(output/'preview.private.json'),
        'preview_sha256':pins['preview.private.json'],'transition':str(output/'transition.private.json'),
        'html':str(output/'preview.html'),'proposed_preserved_comparisons':preview['transition']['proposed_preserved_comparisons'],
        'projected_active_comparisons':preview['transition']['projected_active_comparisons'],'formal_rebind_performed':False}
