"""Closed ON view/table shapes; actual invented frozen core bundle only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

from study2.static_eligibility_ui import JS_SOURCE as UI
from study2.static_scope_client import JS_SOURCE as SCOPE


def test_js_rejects_private_and_unexpected_nested_fields(tmp_path):
    root=Path(os.environ['MANUAL_UI_CORE_FIXTURE_DIR'])
    payload=dict(data=json.loads((root/'SYNTHETIC_FIXTURE.json').read_text()),ui=UI,
                 scope=SCOPE,hash=(root/'HASH_CANONICAL.js').read_text())
    code=r'''
const fs=require('node:fs');globalThis.crypto=require('node:crypto').webcrypto;
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const body=p.hash+';'+p.scope+';'+p.ui+`;
const base=await Study2ManualEligibility.create(data.snapshot,data.scope_export,data.manual_exclusion,Study2Scope);
const full=structuredClone(data),name='parent_child_longitudinal';
if(!full.snapshot.samples.some(r=>r.sample===name)){
 const originalCount=full.snapshot.counts[name]??3,activeCount=full.manual_exclusion.on.snapshot.counts[name]??2;
 const row={...full.snapshot.samples[0],sample:name,label:'Same child parent responses',count:originalCount};
 full.snapshot.samples.push(row);full.snapshot.counts[name]=originalCount;
 full.manual_exclusion.on.snapshot.samples.push({...row,count:activeCount});full.manual_exclusion.on.snapshot.counts[name]=activeCount;
}
full.manual_exclusion.off.snapshot_revision=await Study2EligibilityHash.digest(full.snapshot);
full.manual_exclusion.on_revision=await Study2EligibilityHash.digest(full.manual_exclusion.on);
const complete=await Study2ManualEligibility.create(full.snapshot,full.scope_export,full.manual_exclusion,Study2Scope);
const full_catalogue={available:complete.available,reason:complete.reason,samples:full.snapshot.samples.length,native_deltas:full.manual_exclusion.impact.samples.length};
const results=[];
for(const kind of ['view','statistics_row','histogram_row','grade_cell','grade_schema','table_columns','metric_label','grouping_anchor','source_filter_anchor','grade_anchor','grade_status','source_pairs_status','raw_submissions','root_count_type','legacy_count_type','legacy_count_changed','active_count_type','independent_count_type','negative_statistics_count','invalid_inference_status','empty_statistics','missing_statistics_row','duplicate_statistics_row','append_duplicate_statistic','missing_grade_cell','empty_grade_cells','duplicate_grade_cell','duplicate_sample','missing_source_cell']){
 const f=structuredClone(data),w=f.manual_exclusion,v=w.on.snapshot.views.find(v=>v.source==='all');
 if(kind==='view')v.private_response_ids=['synthetic-private-value'];
 if(kind==='statistics_row'){const t=v.statistics;t.columns.push('private_response_ids');for(const r of t.rows)r.push(['synthetic-private-value']);}
 if(kind==='histogram_row'){const t=v.histograms;t.columns.push('private_response_ids');for(const r of t.rows)r.push(['synthetic-private-value']);}
 if(kind==='grade_cell')v.grade.cells[0].private_response_ids=['synthetic-private-value'];
 if(kind==='grade_schema')v.grade.statistics_schema[0].private_response_ids=['synthetic-private-value'];
 if(kind==='table_columns')v.changes.columns.push('private_response_ids');
 if(kind==='metric_label')v.statistics.rows[0][v.statistics.columns.indexOf('variable')]='synthetic-private-response-id';
 if(kind==='grouping_anchor')v.grouping_anchor='R_'+'Q'.repeat(14);
 if(kind==='source_filter_anchor')v.source_filter_anchor='R_'+'Q'.repeat(14);
 if(kind==='grade_anchor')v.grade.anchor='R_'+'Q'.repeat(14);
 if(kind==='grade_status')v.grade.status='R_'+'Q'.repeat(14);
 if(kind==='source_pairs_status')v.source_pairs.status='R_'+'Q'.repeat(14);
 if(kind==='raw_submissions')w.on.snapshot.counts.submissions=999;
 if(kind==='root_count_type')w.on.snapshot.counts.submissions='R_'+'Q'.repeat(14);
 if(kind.startsWith('legacy_count_')){
   f.snapshot.counts.legacy_historical_total=23;
   w.on.snapshot.counts.legacy_historical_total=kind==='legacy_count_type'?'R_'+'Q'.repeat(14):999;
   w.off.snapshot_revision=await Study2EligibilityHash.digest(f.snapshot);
 }
 if(kind==='active_count_type')w.on.snapshot.counts.A='R_'+'Q'.repeat(14);
 if(kind==='independent_count_type')w.on.snapshot.independent_counts.same_adult_alternative_T1='R_'+'Q'.repeat(14);
 if(kind==='negative_statistics_count')v.statistics.rows[0][v.statistics.columns.indexOf('sample_n')]=-1;
 if(kind==='invalid_inference_status'){
   const view=w.on.snapshot.views.find(x=>x.changes?.rows?.length);
   view.changes.rows[0][view.changes.columns.indexOf('inference_status')]='R_'+'Q'.repeat(14);
 }
 if(kind==='empty_statistics')v.statistics=[];
 if(kind==='missing_statistics_row')v.statistics.rows.pop();
 if(kind==='duplicate_statistics_row')v.statistics.rows[1]=structuredClone(v.statistics.rows[0]);
 if(kind==='append_duplicate_statistic')v.statistics.rows.push(structuredClone(v.statistics.rows[0]));
 if(kind==='missing_grade_cell')v.grade.cells.pop();
 if(kind==='empty_grade_cells')v.grade.cells=[];
 if(kind==='duplicate_grade_cell')v.grade.cells[1]=structuredClone(v.grade.cells[0]);
 if(kind==='duplicate_sample')w.on.snapshot.samples[1]=structuredClone(w.on.snapshot.samples[0]);
 if(kind==='missing_source_cell')v.source_pairs.groups[0].cells.pop();
 w.on_revision=await Study2EligibilityHash.digest(w.on);
 const checked=await Study2ManualEligibility.create(f.snapshot,f.scope_export,w,Study2Scope);
 results.push({kind,available:checked.available,reason:checked.reason,off_intact:checked.select('off').snapshot===f.snapshot});
}
return {base_available:base.available,base_reason:base.reason,full_catalogue,results};`;
(async()=>{const fn=new(Object.getPrototypeOf(async function(){}).constructor)('data',body);console.log(JSON.stringify(await fn(p.data)));})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''
    run=subprocess.run([shutil.which('node'),'-e',code],input=json.dumps(payload),text=True,capture_output=True,timeout=90)
    evidence=Path(os.environ.get('MANUAL_SCHEMA_EVIDENCE_DIR',tmp_path));evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'stdout.json').write_text(run.stdout);(evidence/'stderr.log').write_text(run.stderr)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout);assert result['base_available'],result['base_reason']
    assert result['full_catalogue']['available'],result['full_catalogue']['reason']
    assert result['full_catalogue']['samples']==10 and result['full_catalogue']['native_deltas']==9
    for case in result['results']:
        assert not case['available'],f"Unexpected/private field accepted: {case['kind']}"
        assert case['off_intact']


@pytest.mark.parametrize('exclude_all',[False,True])
def test_js_accepts_core_generated_empty_manifest_and_all_excluded_catalogues(tmp_path,monkeypatch,exclude_all):
    """Actual frozen core builders retain fixed zero catalogues and dynamic arrays."""
    from study2.common import plain
    from study2.static_export import pack_snapshot
    import test_manual_exclusion_validation as core
    root=Path(os.environ['MANUAL_UI_ORIGINAL_CORE_FIXTURE_DIR'])
    monkeypatch.setattr(core,'FROZEN',root)
    value=json.loads((root/'SYNTHETIC_FIXTURE.json').read_text())
    original=(value,core._unpack(value['snapshot']))
    records,frame,parents,measurements,panel,summary,off,scope,imported,_=core.residual_inputs(monkeypatch,original)
    ids={r['submission_id'] for r in records} if exclude_all else set()
    manifest=core.manifest_for(records,ids,summary['release_id'])
    wrapper=core.build_manual_export(off,scope,records,frame,parents,measurements,summary,imported,manifest,panel=panel)
    assert wrapper['status']=='available',wrapper['code']
    payload=dict(snapshot=plain(pack_snapshot(off)),scope=scope,wrapper=wrapper,
        source=(root/'HASH_CANONICAL.js').read_text()+SCOPE+UI)
    script=r'''
const fs=require('node:fs');globalThis.crypto=require('node:crypto').webcrypto;
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const f=new(Object.getPrototypeOf(async function(){}).constructor)('p',p.source+`;
const c=await Study2ManualEligibility.create(p.snapshot,p.scope,p.wrapper,Study2Scope);
return {available:c.available,reason:c.reason,samples:p.wrapper.on.snapshot.samples.length,impacts:p.wrapper.impact.samples.length};`);
f(p).then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.stack);process.exitCode=1;});
'''
    run=subprocess.run([shutil.which('node'),'-e',script],input=json.dumps(payload),text=True,capture_output=True,timeout=90)
    evidence=Path(os.environ.get('MANUAL_SCHEMA_EVIDENCE_DIR',tmp_path));evidence.mkdir(parents=True,exist_ok=True)
    (evidence/('all-excluded.json' if exclude_all else 'empty-manifest.json')).write_text(run.stdout)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout);assert result['available'],result['reason']
    assert result['samples']==10 and result['impacts']==9
