"""Closed public aggregates derived from validated local control projections.

No files, databases, identities, private decision rows or approval operations.
Revisions identify captured inputs; a self-consistent hash is not approval.
"""
from copy import deepcopy
import hashlib
import json
import re

FORMAT='study2_controls_status_v1'
SECTIONS={
    'historical':('pending_decisions',),
    'burst':('held_scopes','distinct_submission_records'),
    'applied_carry':('raw_target_comparisons','closed_comparisons','active_comparisons','held_current_comparisons','source_only_hold_comparisons'),
    'candidate_carry':('raw_target_comparisons','closed_comparisons','active_comparisons','held_current_comparisons','source_only_hold_comparisons'),
}
BINDINGS=('context_revision','group_control_head','group_proposal_revision','review_control_revision','exclusion_revision')
CODES={'not_supplied','historical_unavailable','burst_unavailable','carry_unavailable'}


def revision(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def need(ok,code):
    if not ok:raise ValueError('controls_status_'+code)


def _hash(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None
def _count(value):return type(value) is int and 0<=value<=2**53-1
def _release(value):return isinstance(value,str) and re.fullmatch(r'(?:RUN_(?:[0-9a-f]{32}|SYN_[A-Za-z0-9_-]{1,80})|SYN[A-Za-z0-9_-]{0,92})',value) is not None


def binding(context):
    return dict(context_revision=context['revision'],group_control_head=context['group_control_head'],
        group_proposal_revision=context['group_proposal_revision'],review_control_revision=context['review_control_revision'],
        exclusion_revision=context['flags']['manifest_revision'])


def _missing(name,code):
    return dict(status='unavailable',code=code,target_release_id=None,source_revision=None,
                **{key:None for key in SECTIONS[name]})


def _available(name,target,source,counts):
    return dict(status='available',code=None,target_release_id=target,source_revision=source,
                **{key:counts[key] for key in SECTIONS[name]})


def project(context,*,candidate_model=None,applied_projection=None):
    """Consume backend review_model / live-validated project_closures results.

    The local bridge performs their source/state checks. Only these explicitly
    selected aggregate fields are returned; model rows never cross this boundary.
    """
    result={'format':FORMAT,'release_id':context['release_id'],'bindings':binding(context),
            **{name:_missing(name,'not_supplied') for name in SECTIONS}}
    if candidate_model is not None:
        target=candidate_model['release_id'];source=candidate_model['proposal_revision']
        pending=candidate_model['pending_intents']
        result['historical']=(_missing('historical','historical_unavailable') if pending is None else
                              _available('historical',target,source,{'pending_decisions':pending}))
        burst=candidate_model['burst_review']
        result['burst']=_available('burst',target,source,{'held_scopes':burst['scope_count'],
            'distinct_submission_records':burst['distinct_submission_count']})
        carry=candidate_model.get('administrative_carry')
        if carry is not None:
            raw=carry['native_target_closed']+carry['native_target_active']
            closed,active=carry['proposed_preserved_comparisons'],carry['projected_active_comparisons']
            result['candidate_carry']=_available('candidate_carry',target,source,dict(
                raw_target_comparisons=raw,closed_comparisons=closed,active_comparisons=active,
                held_current_comparisons=raw-closed-active,source_only_hold_comparisons=None))
    if applied_projection is not None:
        p=applied_projection
        need(p['projection_ready'] is True,'applied_projection_not_ready')
        need(p['bindings']['release_id']==context['release_id'],'applied_release_changed')
        need('held_current_comparisons' in p and 'source_only_hold_comparisons' in p,'live_carry_projection_required')
        result['applied_carry']=_available('applied_carry',context['release_id'],p['admin_revision'],dict(
            raw_target_comparisons=p['raw_correction_comparisons'],closed_comparisons=p['closed_unresolvable_comparisons'],
            active_comparisons=p['active_correction_comparisons'],held_current_comparisons=p['held_current_comparisons'],
            source_only_hold_comparisons=p['source_only_hold_comparisons']))
    result['revision']=revision(result)
    return validate(result,context['release_id'],context)


def validate(value,release_id,context):
    need(isinstance(value,dict) and set(value)=={'format','release_id','bindings','revision',*SECTIONS},'closed_fields_required')
    need(value['format']==FORMAT and _release(value['release_id']) and value['release_id']==release_id,'release_changed')
    need(isinstance(context,dict) and context['release_id']==release_id and value['bindings']==binding(context)
         and set(value['bindings'])==set(BINDINGS) and all(_hash(v) for v in value['bindings'].values()),'context_changed')
    for name,fields in SECTIONS.items():
        row=value[name];need(isinstance(row,dict) and set(row)=={'status','code','target_release_id','source_revision',*fields},'closed_section_required')
        if row['status']=='unavailable':
            need(row['code'] in CODES and all(row[k] is None for k in ('target_release_id','source_revision',*fields)),'unavailable_must_not_be_zero')
            continue
        need(row['status']=='available' and row['code'] is None and _release(row['target_release_id']) and _hash(row['source_revision']),'invalid_section')
        need(all(_count(row[k]) or name=='candidate_carry' and k=='source_only_hold_comparisons' and row[k] is None for k in fields),'invalid_count')
        if name.endswith('carry'):
            need(row['raw_target_comparisons']==row['closed_comparisons']+row['active_comparisons']+row['held_current_comparisons'],'comparison_partition_changed')
            if name=='applied_carry':need(row['target_release_id']==release_id,'applied_release_changed')
        if name=='burst':need((row['held_scopes']==0)==(row['distinct_submission_records']==0),'burst_units_changed')
    need(_hash(value['revision']) and value['revision']==revision({k:v for k,v in value.items() if k!='revision'}),'revision_changed')
    return deepcopy(value)


def capture(request_pin,release_id,context):
    """Read current controls from the explicitly pinned installed backend."""
    from .controls_capture import capture as capture_current, read_pin
    result = capture_current(read_pin(request_pin))
    return validate(result, release_id, context)



JS_SOURCE=r'''
const Study2Controls=(()=>{
const fields={historical:['pending_decisions'],burst:['held_scopes','distinct_submission_records'],applied_carry:['raw_target_comparisons','closed_comparisons','active_comparisons','held_current_comparisons','source_only_hold_comparisons'],candidate_carry:['raw_target_comparisons','closed_comparisons','active_comparisons','held_current_comparisons','source_only_hold_comparisons']};
const hash=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x),count=x=>Number.isSafeInteger(x)&&x>=0;
const releaseToken=x=>typeof x==='string'&&/^(?:RUN_(?:[0-9a-f]{32}|SYN_[A-Za-z0-9_-]{1,80})|SYN[A-Za-z0-9_-]{0,92})$/.test(x);
const keys=(x,k)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).sort().join('|')===[...k].sort().join('|');
function rows(v,release,context){
 const bad=()=>{throw Error('Control aggregates unavailable or incompatible');};
 if(!context||context.release_id!==release||!keys(v,['format','release_id','bindings','revision',...Object.keys(fields)])||v.format!=='study2_controls_status_v1'||!releaseToken(v.release_id)||v.release_id!==release||!hash(v.revision))bad();
 const b={context_revision:context.revision,group_control_head:context.group_control_head,group_proposal_revision:context.group_proposal_revision,review_control_revision:context.review_control_revision,exclusion_revision:context.flags.manifest_revision};
 if(!keys(v.bindings,Object.keys(b))||Object.keys(b).some(k=>!hash(b[k])||v.bindings[k]!==b[k]))bad();
 for(const [name,fs]of Object.entries(fields)){const r=v[name];if(!keys(r,['status','code','target_release_id','source_revision',...fs]))bad();
  if(r.status==='unavailable'){if(!['not_supplied','historical_unavailable','burst_unavailable','carry_unavailable'].includes(r.code)||['target_release_id','source_revision',...fs].some(k=>r[k]!==null))bad();continue;}
  if(r.status!=='available'||r.code!==null||!releaseToken(r.target_release_id)||!hash(r.source_revision)||fs.some(k=>!count(r[k])&&!(name==='candidate_carry'&&k==='source_only_hold_comparisons'&&r[k]===null)))bad();
  if(name.endsWith('carry')&&(r.raw_target_comparisons!==r.closed_comparisons+r.active_comparisons+r.held_current_comparisons||(name==='applied_carry'&&r.target_release_id!==release)))bad();
  if(name==='burst'&&((r.held_scopes===0)!==(r.distinct_submission_records===0)))bad();
 }
 const n=x=>x===null?'Unavailable':x;
 return {historical:[{item:'Earlier decisions awaiting evidence review',count:n(v.historical.pending_decisions),unit:'decisions'}],
 burst:[{item:'Burst scopes awaiting evidence',count:n(v.burst.held_scopes),unit:'scopes'},{item:'Distinct submission records in burst holds',count:n(v.burst.distinct_submission_records),unit:'submission records'}],
 ...Object.fromEntries(['applied_carry','candidate_carry'].map(name=>[name,[['Raw target correction inventory','raw_target_comparisons'],['Preserved closures','closed_comparisons'],['Active corrections','active_comparisons'],['Held target comparisons','held_current_comparisons'],['Source-only holds outside target inventory','source_only_hold_comparisons']].map(([item,key])=>({item,count:n(v[name][key]),unit:'comparisons'}))]))};
}
return Object.freeze({rows});})();
if(typeof module!=='undefined')module.exports=Study2Controls;
'''
