"""Invented UI fixture. Stub scope engine is explicit, never production code."""
from collections import Counter
from copy import deepcopy
from math import isfinite
import hashlib
import json
from pathlib import Path
import struct
from unittest.mock import patch

import static_source_ui_fixture as original
from study2.common import digest
from study2.static_export import pack_snapshot
from study2.static_scope import ADULT_POLICY, SLOTS, _catalogue_profile, build_scope_index

CODES = ['A','B','C','D','AC','BD','E','F','EF']
REVISION='a'*64
INVENTORY='b'*64


def typed_hash(value):
    """Independent Python reference for the frozen f64/UTF16 hash contract."""
    def typed(v):
        if v is None:return ['null']
        if isinstance(v,bool):return ['bool',v]
        if isinstance(v,(int,float)):
            assert isfinite(v)
            return ['f64',struct.pack('>d',float(v)).hex()]
        if isinstance(v,str):
            v.encode('utf-16-be',errors='strict')
            return ['str',v]
        if isinstance(v,list):return ['array',[typed(x) for x in v]]
        assert isinstance(v,dict)
        return ['object',[[typed(k),typed(v[k])] for k in sorted(v,key=lambda x:x.encode('utf-16-be'))]]
    raw=json.dumps(typed(value),ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def fixture():
    record_factory=original.records
    projections=[('abcd','student'),('abcd','parent'),('acbd','student'),('acbd','parent'),
                 ('efmatched','parent'),('independent_all','parent'),
                 ('independent_child','parent'),('independent_adult','parent')]
    def rows(mode='abcd',role='student',**kwargs):
        frame=record_factory(mode,role,**kwargs)
        if role=='parent' and mode in {'acbd','independent_adult'}:
            # Its actual formal T1 differs from D / child-report T1.
            alt=frame.child_id.eq('source-ui-unit-0')&frame.wave.eq('T1')
            frame.loc[alt,'PHQ_total']=2.
            frame.loc[alt,'observed_at']='2025-04-02T00:00:00Z'
        return frame
    with patch.object(original,'records',rows):off=original.ui_snapshot(projections=projections)
    def retained(mode='abcd',role='student',**kwargs):
        frame=rows(mode,role,**kwargs)
        first=frame.child_id.eq('source-ui-unit-0')
        if role=='student':
            remove=first if mode in original.FORMAL else first&frame.wave.eq('T0')
        else:remove=first if mode=='efmatched' else first&False
        out=frame.loc[~remove].copy();out.attrs=frame.attrs.copy();return out
    with patch.object(original,'records',retained):on=original.ui_snapshot(projections=projections)
    off_counts={c:11 for c in CODES};on_counts={**off_counts,**{c:10 for c in ['A','AC','E','EF']}}
    off['counts']=off_counts;on['counts']=on_counts
    raw=[];analysis=[];adults=[];slots={};adult_slots={}
    for role in ['student','parent']:
        for row in rows('abcd',role).to_dict('records'):
            child=row['child_id'];i=child.rsplit('-',1)[1];wave=row['wave'];sid=f'manual-ui-{role}-{i}-{wave}'
            item=dict(submission_id=sid,child_id=child,version_id='synthetic-v1',role=role,
                source_type=row['source_type'],source_label=row['source_type'],claimed_wave=wave,
                observed_at=row['observed_at'],date_basis='system_creation',time_confidence='observed',
                selected_wave=wave,status='eligible',wave_reason=None,
                answer={'Survey':'Synthetic '+role+' questionnaire'},
                survey_form_id='synthetic-form-'+role,survey_form_version='v1')
            raw.append(item);slot=dict(submission_id=sid,child_id=child,role=role,wave=wave)
            analysis.append(slot);slots[child,role,wave]=sid
            if role=='parent':
                adult_sid=sid
                if i=='0' and wave=='T1':
                    adult_sid='manual-ui-parent-0-alternate-T1'
                    raw.append({**item,'submission_id':adult_sid,'observed_at':'2025-04-02T00:00:00Z',
                                'selected_wave':None,'status':'extra_followup','wave_reason':'parent_other_same_phase_response'})
                adults.append({**slot,'submission_id':adult_sid});adult_slots[child,role,wave]=adult_sid
    summary=dict(release_id=off['release_id'],adult_identity_policy=ADULT_POLICY,
        submissions=len(raw),status_counts=dict(Counter(r['status'] for r in raw)),**off_counts)
    index=build_scope_index(raw,analysis,adults,summary)
    refs={r['submission_id']:index['profiles'].index(_catalogue_profile(r)[2]) for r in raw}
    members={c:[] for c in CODES}
    for code in CODES:
        lookup=adult_slots if code=='BD' else slots
        for i in range(11):
            keys=[(f'source-ui-unit-{i}',role,wave) for role,wave in SLOTS[code]]
            if all(k in lookup for k in keys):members[code].append([lookup[k] for k in keys])
    def aggregate(keep):
        cells=Counter((code,tuple(refs[sid] for sid in ids)) for code in CODES for ids in members[code] if keep(ids))
        return [dict(code=c,profiles=list(ps),count=n) for (c,ps),n in sorted(cells.items())]
    assert aggregate(lambda ids:True)==index['samples']
    flagged='manual-ui-student-0-T0'
    on_index=deepcopy(index);on_index['samples']=aggregate(lambda ids:flagged not in ids)
    on_index['eligibility']=dict(format='study2_scope_eligibility_v1',revision=REVISION,
        inventory_revision=INVENTORY,baseline_samples=deepcopy(index['samples']),
        excluded_records=[dict(profile=refs[flagged],count=1)],
        excluded_selected=[dict(profile=refs[flagged],count=1)])
    def scope(i):return dict(format='study2_static_scope_export_v1',status='available',
        release_id=off['release_id'],index_revision=digest(i),index=i,school_bindings=[],reconciliation=i['meta']['reconciliation'])
    off_scope=scope(index);on_scope=scope(on_index)
    intake=dict(student=dict(baseline=22,excluded=1,retained=21),parent=dict(baseline=23,excluded=0,retained=23))
    impacts=[dict(code=c,baseline=off_counts[c],active=on_counts[c],excluded=off_counts[c]-on_counts[c]) for c in CODES]
    independent={k:dict(baseline=11,active=11,excluded=0) for k in ['baselines','child_report_pairs','same_adult_pairs']}
    on['eligibility_context']=dict(mode='on',revision=REVISION,inventory_revision=INVENTORY,policy='fixed_original_members_no_reselection')
    packed_off=pack_snapshot(off);packed_on=pack_snapshot(on)
    bundle=dict(snapshot=packed_on,scope_export=on_scope)
    wrapper=dict(format='study2_manual_exclusion_v1',hash_scheme='typed_f64_utf16_v1',
        status='available',code=None,release_id=off['release_id'],revision=REVISION,
        inventory_revision=INVENTORY,policy='fixed_original_members_no_reselection',
        off=dict(snapshot_revision=typed_hash(packed_off),scope_revision=typed_hash(off_scope)),
        on=bundle,on_revision=typed_hash(bundle),impact=dict(intake=intake,samples=impacts,independent=independent))
    # Student 0 and student 1 have the same coarse source/version/day profile.
    assert refs[flagged]==refs['manual-ui-student-1-T0']
    return dict(snapshot=packed_off,scope=off_scope,wrapper=wrapper)


def stub_engine(source):
    """Temporary UI-only stub until the frozen real scope dependency is supplied."""
    source=source.replace('const Study2Scope =','const Study2ScopeBase =')
    return source+r'''
const Study2Scope=(()=>{
 const clean=index=>{if(!index.eligibility)return index;const copy={...index,samples:index.eligibility.baseline_samples};delete copy.eligibility;return copy;};
 const matches=(p,s)=>s.sources.includes(p.source_key)&&s.surveys.includes(p.survey_key)&&(p.day===null?s.include_unknown:(!s.start||p.day>=s.start)&&(!s.end||p.day<=s.end));
 return Object.freeze({...Study2ScopeBase,validate:index=>{Study2ScopeBase.validate(clean(index));return index;},query:(index,selection)=>{
  const result=Study2ScopeBase.query(clean(index),selection),e=index.eligibility;if(!e)return result;
  const chosen=index.profiles.map(p=>matches(p,result.scope));
  const active=result.samples.map(row=>({...row,count:row.status==='available'?index.samples.filter(r=>r.code===row.code&&r.profiles.every(p=>chosen[p])).reduce((n,r)=>n+r.count,0):null}));
  const intake=Object.fromEntries(['student','parent'].map(role=>{const excluded=e.excluded_records.filter(r=>chosen[r.profile]&&index.profiles[r.profile].role===role).reduce((n,r)=>n+r.count,0);return [role,{baseline:result.raw[role],excluded,retained:result.raw[role]-excluded}];}));
  const samples=active.map(row=>{const before=result.samples.find(r=>r.code===row.code);return {code:row.code,baseline:before.count,active:row.count,excluded:row.status==='available'?before.count-row.count:null};});
  return {...result,samples:active,eligibility:{format:'study2_scope_eligibility_v1',mode:'on',revision:e.revision,inventory_revision:e.inventory_revision,intake,samples}};
 }});
})();
'''
