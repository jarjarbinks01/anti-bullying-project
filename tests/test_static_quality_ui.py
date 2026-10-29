"""Real Chromium tests for the pure presenter, with hand-built synthetic slots.

Requires Node and a resolvable Playwright module (NODE_PATH may supply an
existing installation). No server, research files, or package installation.
"""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from study2.static_scope import ADULT_POLICY, build_scope_index
from study2.static_scope_client import JS_SOURCE as ENGINE
from study2.static_quality_ui import JS_SOURCE, STYLES


def synthetic_index():
    """One formal case; BD uses an earlier parent response than D/F."""
    records, analysis, adults = [], [], []
    for sid, role, wave, source, date, selected in [
        ('s0', 'student', 'T0', 'alpha', '2025-01-31T16:00:00Z', True),
        ('s1', 'student', 'T1', 'beta', '2025-06-01T00:00:00+08:00', True),
        ('p0', 'parent', 'T0', 'alpha', '2025-02-01T00:00:00+08:00', True),
        ('p1', 'parent', 'T1', 'beta', '2025-07-01T00:00:00+08:00', True),
        ('bd1', 'parent', 'T1', 'alpha', '2025-06-01T00:00:00+08:00', False),
    ]:
        records.append(dict(submission_id=sid, child_id='synthetic-child', role=role,
            source_type=source, source_label=source, observed_at=date,
            time_confidence='observed', date_basis='system_creation', claimed_wave=wave,
            selected_wave=wave if selected else None, status='eligible' if selected else 'extra_followup',
            wave_reason=None if selected else 'parent_other_same_phase_response',
            answer={'Survey': 'Shared questionnaire with a complete original label ' + 'long ' * 20},
            survey_form_id=sid, survey_form_version='v1'))
        slot=dict(submission_id=sid, child_id='synthetic-child', role=role, wave=wave)
        if selected:
            analysis.append(slot)
        if sid in ('p0', 'bd1'):
            adults.append(slot)
    for sid, role, status in [('u0', 'student', 'incomplete'), ('u1', 'parent', 'sparse_response')]:
        records.append(dict(submission_id=sid, child_id=sid, role=role,
            source_type='alpha', source_label='alpha', observed_at=None,
            time_confidence='unknown', date_basis=None, claimed_wave='T0', selected_wave=None,
            status=status, wave_reason=None, answer={'Survey': None}))
    summary=dict(release_id='synthetic-ui-test', adult_identity_policy=ADULT_POLICY,
        submissions=len(records), status_counts=dict(Counter(r['status'] for r in records)),
        **{code:1 for code in ['A','B','C','D','AC','BD','E','F','EF']})
    return build_scope_index(records, analysis, adults, summary)


DRIVER = r'''
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
let input='';process.stdin.on('data',c=>input+=c);
process.stdin.on('end',async()=>{
  let browser;
  try{
    const data=JSON.parse(input);
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:data.viewport||{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.setContent('<!doctype html><html lang="en"><body><main id="quality"></main><input id="other" value="unchanged"></body></html>');
    await page.addStyleTag({content:data.styles});
    await page.addScriptTag({content:data.engine});
    await page.addScriptTag({content:data.view});
    await page.evaluate(({index})=>{window.idx=index;window.host=document.getElementById('quality');window.ui=Study2Quality.mount(host,idx);},data);
    await page.waitForSelector('#quality[data-state=ready]');
    await page.evaluate(async({check})=>{
      const assert=(v,msg)=>{if(!v)throw Error(msg);};
      const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      const raw=role=>host.querySelector(`[data-raw="${role}"]`)?.textContent;
      const count=code=>host.querySelector(`[data-sample="${code}"]`)?.textContent;
      const findButton=name=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===name);
      const wait=async()=>{for(let i=0;i<100&&host.dataset.state==='loading';i++)await new Promise(r=>setTimeout(r,5));assert(host.dataset.state==='ready','scope must finish ready');};
      const reset=async()=>{await ui.reset();await wait();};
      const expectDownload=()=>{
        const d=ui.getDownload();assert(d&&same(d.result.scope,Study2Scope.normalizeSelection(idx,ui.getSelection())),'download selection');
        for(const s of d.result.samples)assert(count(s.code)===(s.status==='available'?String(s.count):'Unavailable'),'sample/download '+s.code);
        for(const role of ['student','parent'])assert(raw(role)===String(d.result.raw[role]),'raw/download '+role);
        assert(d.result.date_policy.timezone==='Asia/Hong_Kong','timezone');return d;
      };
      if(check==='full'){
        assert(raw('student')==='3'&&raw('parent')==='4','raw role records');
        for(const code of ['A','C','AC','B','D','BD','E','F','EF'])assert(count(code)==='1','nine samples '+code);
        assert(host.querySelectorAll('.q-lane').length===2&&host.querySelectorAll('.q-node').length===8,'connected lanes');
        for(const word of ['Entering','Remaining','Selected','questionnaire records','longitudinal cases','dyads','Retained but not selected','Original claimed-wave intake audit','Samples overlap','First-tab scope only','Missing survey name'])assert(host.textContent.includes(word),'English label/unit '+word);
        assert(host.textContent.includes('Same adult across waves'),'BD artifact label');
        assert(document.getElementById('other').value==='unchanged','other tab');expectDownload();
      }
      if(check==='filter_reset'){
        const alpha=idx.sources.find(x=>x.label==='alpha').key;
        await ui.setSelection({...ui.getSelection(),sources:[alpha]});
        for(const code of ['A','B','BD','E'])assert(count(code)==='1','source retained '+code);
        for(const code of ['C','D','AC','F','EF'])assert(count(code)==='0','source removed '+code);
        expectDownload();await reset();assert(count('EF')==='1','reset');
        findButton('Clear sources').click();await wait();assert(raw('student')==='0'&&raw('parent')==='0','empty sources');expectDownload();
        findButton('Select all sources').click();await wait();assert(raw('student')==='3','all sources');
        findButton('Clear questionnaire versions').click();await wait();assert(raw('student')==='0','empty versions');
        const chosen=idx.surveys.filter(x=>['s0','s1'].includes(x.form_id)).map(x=>x.key);
        await ui.setSelection({...ui.getSelection(),surveys:chosen});assert(count('AC')==='1'&&count('BD')==='0','two versions');expectDownload();
      }
      if(check==='search'){
        const before=ui.getDownload(),s=host.querySelector('input[type=search][aria-label="Search questionnaire versions"]');
        s.value='no matching name';s.dispatchEvent(new Event('input'));
        assert(same(before,ui.getDownload()),'search must not change counts/download');
        assert(host.textContent.includes('No catalogue options match'),'empty search');
        findButton('Clear questionnaire versions').click();await wait();
        findButton('Select all questionnaire versions').click();await wait();assert(ui.getSelection().surveys.length===idx.surveys.length,'select all search-hidden options');
        findButton('Reset scope and search').click();await wait();assert(s.value==='','search reset');
        assert(host.querySelectorAll('input[data-facet=surveys]').length===7,'all duplicate and missing catalogue values visible');
        assert(host.textContent.includes('long '.repeat(20)),'long label kept complete');
      }
      if(check==='dates'){
        const setDate=async(key,value)=>{const x=host.querySelector(`input[type=date][aria-label^="${key}"]`);x.value=value;x.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,10));};
        await setDate('Start','2025-02-01');await setDate('End','2025-02-01');await wait();
        assert(ui.getSelection().include_unknown===false,'first bound excludes unknown');
        assert(count('A')==='1'&&count('B')==='1'&&count('C')==='0','inclusive HK boundary');
        const unknown=Array.from(host.querySelectorAll('label')).find(e=>e.textContent.includes('Include entries with unknown')).querySelector('input');
        unknown.click();await wait();assert(raw('student')==='2'&&raw('parent')==='2','explicit unknown inclusion');assert(host.textContent.includes('not known to satisfy this interval'),'honest unknown interval');expectDownload();
        await setDate('Start','2025-08-01');assert(host.dataset.state==='unavailable'&&!ui.getDownload(),'reversed clears numbers');assert(!host.querySelector('[data-raw]'),'no stale raw counts');
        await setDate('End','2025-09-01');await wait();assert(ui.getSelection().start==='2025-08-01'&&ui.getSelection().end==='2025-09-01','correct other date preserves draft start');
        await reset();assert(ui.getSelection().include_unknown&&ui.getSelection().start===null,'date reset');
      }
      if(check.startsWith('remove_')){
        const form=check.slice(7),key=idx.surveys.find(x=>x.form_id===form).key;
        await ui.setSelection({...ui.getSelection(),surveys:ui.getSelection().surveys.filter(k=>k!==key)});
        const removed={s0:['A','AC','E','EF'],s1:['C','AC','F','EF'],p0:['B','BD','E','EF'],p1:['D','F','EF'],bd1:['BD']}[form];
        for(const code of ['A','C','AC','B','D','BD','E','F','EF'])assert(count(code)===(removed.includes(code)?'0':'1'),'fixed slot '+form+' '+code);
        expectDownload();
      }
      if(check==='failure'){
        ui.destroy();ui=Study2Quality.mount(host,idx,{query:()=>{throw Error('test failure')}});
        await new Promise(r=>setTimeout(r,10));assert(host.dataset.state==='unavailable'&&!ui.getDownload(),'query failure clears');assert(!host.querySelector('[data-sample]'),'no stale samples');
        ui.destroy();ui=Study2Quality.mount(host,{...idx,format:'old'});assert(host.textContent.includes('Compatible scope export required'),'unsupported schema actionable');assert(!ui.getDownload(),'unsupported no download');
        ui.destroy();ui=Study2Quality.mount(host,idx,{query:(i,s)=>({...Study2Scope.query(i,s),schema:'unsupported'})});await new Promise(r=>setTimeout(r,10));assert(host.dataset.state==='unavailable','bad result schema');
      }
      if(check==='async'){
        ui.destroy();let pending=[];ui=Study2Quality.mount(host,idx,{query:(i,s)=>new Promise(resolve=>pending.push(()=>resolve(Study2Scope.query(i,s))))});
        const initial=ui.getSelection();const changed=ui.setSelection({...initial,sources:[]});
        assert(!ui.getDownload()&&!host.querySelector('[data-raw]'),'loading clears everything');
        pending[1]();await changed;assert(raw('student')==='0','new result first');pending[0]();await new Promise(r=>setTimeout(r,10));assert(raw('student')==='0','old asynchronous result ignored');expectDownload();
        ui.destroy();pending=[];ui=Study2Quality.mount(host,idx,{indexRevision:'pin',schoolProjectionFor:()=>new Promise(resolve=>pending.push(resolve))});
        await new Promise(r=>setTimeout(r,10));const changedAgain=ui.setSelection({...ui.getSelection(),sources:[]});await new Promise(r=>setTimeout(r,10));
        pending[1](null);await changedAgain;pending[0](null);await new Promise(r=>setTimeout(r,10));assert(raw('student')==='0','stale school response ignored');expectDownload();
      }
      if(check==='safe_text'){
        const hostile='<img src=x onerror="window.executed=true">';host.append(Study2Quality.text('p',hostile));
        assert(host.textContent.includes(hostile)&&!host.querySelector('img')&&!window.executed,'hostile label literal text');
        const bad=structuredClone(idx);bad.surveys[0].label=hostile;ui.destroy();ui=Study2Quality.mount(host,bad);
        assert(host.dataset.state==='unavailable'&&!host.querySelector('img'),'engine rejects invalid catalogue');
      }
      if(check==='empty'){
        assert(!idx.sources.length&&!idx.surveys.length,'zero options fixture');assert(raw('student')==='0'&&raw('parent')==='0','zero options raw');assert(host.textContent.includes('No catalogue options match'),'empty catalogue explicit');expectDownload();
      }
      if(check==='adult_unavailable'){
        assert(count('BD')==='Unavailable','BD unknown is not zero');assert(!host.textContent.includes('Same adult across waves'),'no invented adult continuity');expectDownload();
      }
      if(check==='selected_child_bd'){
        assert(count('BD')==='3','selected B/D count');
        assert(host.textContent.includes('Same child across waves (BD)'),'selected B/D label');
        assert(host.textContent.includes('Uses the selected parent B and D for the same child; the responding adult may differ.'),'selected B/D explanation');
        assert(!host.textContent.includes('its follow-up can differ from D/F'),'no alternative follow-up claim');
        expectDownload();
      }
      if(check==='keyboard'){
        const target=host.querySelector('input[data-facet=sources]');target.focus();window.targetKey=target.dataset.key;
      }
      if(check==='layout')assert(document.documentElement.scrollWidth<=innerWidth,'no page-wide horizontal overflow');
    },data);
    if(data.check==='keyboard'){
      await page.keyboard.press('Space');await page.waitForSelector('#quality[data-state=ready]');
      const focus=await page.evaluate(()=>({key:document.activeElement.dataset.key,width:getComputedStyle(document.activeElement).outlineWidth,style:getComputedStyle(document.activeElement).outlineStyle,checked:document.activeElement.checked,target:window.targetKey}));
      assert.equal(focus.key,focus.target,'checkbox focus retained after async rendering');assert.equal(focus.checked,false);assert.equal(focus.width,'3px');assert.equal(focus.style,'solid');
      await page.keyboard.press('Space');await page.waitForSelector('#quality[data-state=ready]');
      assert.equal(await page.locator('[data-sample=EF]').textContent(),'1');
    }
    assert.deepEqual(errors,[],'no browser exceptions');
    console.log(JSON.stringify({check:data.check,viewport:page.viewportSize(),status:'passed'}));
  }catch(e){console.error(e);process.exitCode=1;}finally{if(browser)await browser.close();}
});
'''


def run_browser(index, check, viewport=None):
    assert shutil.which('node'), 'Node required for browser acceptance'
    run=subprocess.run(['node','-e',DRIVER], input=json.dumps(dict(
        index=index, check=check, viewport=viewport, styles=STYLES, engine=ENGINE, view=JS_SOURCE)),
        capture_output=True, text=True, timeout=45)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('check', ['full','filter_reset','search','dates','failure','async','safe_text','keyboard',
    'remove_s0','remove_s1','remove_p0','remove_p1','remove_bd1'])
def test_presenter_browser_contract(check):
    run_browser(synthetic_index(), check)


@pytest.mark.parametrize('viewport', [{'width':1440,'height':1000},{'width':390,'height':844}])
def test_presenter_layout(viewport):
    run_browser(synthetic_index(), 'layout', viewport)


def test_zero_catalogue_options():
    index=build_scope_index([], [], [], dict(release_id='synthetic-empty',adult_identity_policy=ADULT_POLICY))
    run_browser(index, 'empty')


def test_adult_continuity_unavailable_is_not_zero():
    index=synthetic_index()
    # Build a second valid synthetic index without the formal parent artifact.
    index['meta']['adult']={'status':'unavailable','policy':None,'evidence':None,'reason':'formal_parent_longitudinal_artifact_missing'}
    index['samples']=[x for x in index['samples'] if x['code']!='BD']
    index['meta']['reconciliation']['status']='partial'
    run_browser(index, 'adult_unavailable')


def test_selected_child_bd_uses_selected_waves_and_does_not_claim_same_adult():
    from test_bd_scope_policy import inputs
    records, frame, parents, summary = inputs()
    run_browser(build_scope_index(records, frame, parents, summary), 'selected_child_bd')


# R2 additions. All original 17 cases and their assertions above stay unchanged.
from study2.static_scope import canonical_json, query_scope


def synthetic_public_projection():
    """Explicit public-only fixture, normatively checked in the repair evidence.

    One unreviewed label touches one student and one parent. Other records have
    no queue label. These are display facts, never a browser counting algorithm.
    """
    zero=dict(student=0,parent=0)
    return dict(format='study2_school_status_v1',release_id='synthetic-ui-test',
        availability='available',reconciliation_status='not_reconciled',revision='school-'+'c'*24,
        evidence=dict(dictionary_sha256='a'*64,review_state='no_recorded_review',
            decision_revision=None,criteria_revision=None,bundle_sha256='b'*64,
            decision_source_sha256='4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'),
        problems=[],release_wide=dict(basis='release_wide',labels=dict(unit='normalized_labels',
            historical_queue=1,current_queue=1,review_universe=1,
            states=dict(mapped=0,invalid=0,historical_only=0,pending=0,unreviewed=1,not_reconciled=0),
            historical_accounted=1,historical_resolved=0,all_historical_accounted=True,all_historical_resolved=False),
            schools=dict(unit='canonical_school_names',verified_reviewed_canonical_schools=0)),
        current_scope=dict(unit='questionnaire_records',raw=dict(student=3,parent=4),
            affected=dict(student=1,parent=1),excluded_school=zero.copy(),
            verified_queue_attributed_exclusion=zero.copy(),actionable_pending=zero.copy(),
            status_partition=dict(not_reconciled=zero.copy(),unreviewed=dict(student=1,parent=1),
                pending=zero.copy(),invalid=zero.copy(),mapped=zero.copy(),historical_only=zero.copy(),
                no_queue_label=dict(student=2,parent=3)),
            label_record_links=2,school_field_occurrences=2,records_with_multiple_labels=0,
            labels=dict(unit='normalized_labels',affected=1,actionable_pending=0,unreviewed=1,not_reconciled=0),
            schools=dict(status='unavailable',count=None,reason='filtered_canonical_school_signatures_not_provided')))


EQUIVALENCE_DRIVER = r'''
const assert=require('node:assert/strict'),{chromium}=require('playwright');
let input='';process.stdin.on('data',c=>input+=c);process.stdin.on('end',async()=>{
  let browser;
  try{
    const data=JSON.parse(input),test=data.check;
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.setContent('<!doctype html><html lang="en"><body><main id="q"></main></body></html>');
    await page.addStyleTag({content:data.styles});await page.addScriptTag({content:data.engine});await page.addScriptTag({content:data.view});
    const got=await page.evaluate(async({index,precomputed,school,check})=>{
      const root=document.getElementById('q'),copy=x=>structuredClone(x);
      const settle=async()=>{for(let i=0;i<100&&root.dataset.state==='loading';i++)await new Promise(r=>setTimeout(r,5));};
      let view=Study2Quality.mount(root,index);await settle();const control=view.getDownload();view.destroy();
      const p=copy(school),r=copy(precomputed);let options={};
      const queryChanges={
        scope_value:()=>r.scope.start='2024-01-01',
        scope_extra:()=>r.scope.extra=null,
        scope_missing:()=>delete r.scope.include_unknown,
        scope_null:()=>r.scope.start=undefined,
        scope_type:()=>r.scope.include_unknown=1,
        sources_order:()=>r.scope.sources.reverse(),
        surveys_order:()=>r.scope.surveys.reverse(),
        sources_object:()=>r.scope.sources={...r.scope.sources},
        sources_length:()=>r.scope.sources.push(undefined),
        sources_value:()=>r.scope.sources[0]='different-source',
        scope_nested:()=>r.scope.start={},
        result_release:()=>r.release_id='different-release',
        result_schema:()=>r.schema='different-schema',
        result_timezone:()=>r.date_policy.timezone='UTC'
      };
      if(check==='canonical_query'||check==='canonical_both'||Object.hasOwn(queryChanges,check)){
        if(queryChanges[check])queryChanges[check]();options.query=()=>copy(r);
      }
      const schoolChanges={
        school_parent_first:()=>p.current_scope.raw={parent:4,student:3},
        school_student_first:()=>p.current_scope.raw={student:3,parent:4},
        school_count:()=>p.current_scope.raw.parent=5,
        school_type:()=>p.current_scope.raw.student='3',
        school_missing:()=>delete p.current_scope.raw.parent,
        school_extra:()=>p.current_scope.raw.extra=0,
        school_null:()=>p.current_scope.raw.student=null,
        school_array:()=>p.current_scope.raw=[3,4],
        school_release:()=>p.release_id='different-release',
        stale_binding:()=>{}
      };
      let requestedKey=null,returnedKey=null;
      if(Object.hasOwn(schoolChanges,check)||check==='canonical_both'){
        if(schoolChanges[check])schoolChanges[check]();
        if(check==='canonical_both')p.current_scope.raw={parent:4,student:3};
        options.indexRevision='synthetic-r2-pin';
        options.schoolProjectionFor=({key,result})=>{
          requestedKey=key;returnedKey=key;
          if(check==='stale_binding'){
            // All records still satisfy this other interval; raw margins are
            // identical. Its exact scope/binding is nevertheless different.
            returnedKey=JSON.stringify([options.indexRevision,result.release_id,result.schema,{...result.scope,start:'2024-01-01'}]);
          }
          return {key:returnedKey,validatedBy:'R03-r3',projection:copy(p)};
        };
      }
      view=Study2Quality.mount(root,index,options);await settle();
      return {state:root.dataset.state,download:view.getDownload(),control,requestedKey,returnedKey,
        raw:Object.fromEntries(Array.from(root.querySelectorAll('[data-raw]'),n=>[n.dataset.raw,n.textContent])),
        samples:Object.fromEntries(Array.from(root.querySelectorAll('[data-sample]'),n=>[n.dataset.sample,n.textContent])),
        overflow:document.documentElement.scrollWidth>innerWidth,
        downloadDisabled:Array.from(root.querySelectorAll('button')).find(b=>b.textContent==='Download current aggregate JSON').disabled};
    },data);
    if(test==='canonical_query'){
      assert.equal(got.state,'ready');assert.deepEqual(got.download,got.control,'complete canonical R01 download equals direct browser query');
    }else if(['school_parent_first','school_student_first','canonical_both'].includes(test)){
      assert.equal(got.state,'ready');assert.equal(got.download.school.status,'available');
      assert.deepEqual(got.download.result,got.control.result,'exact R01 result');
      assert.deepEqual(got.download.school.projection,data.school,'same entire public projection');
      assert.equal(got.requestedKey,got.returnedKey,'exact trusted-host binding');
    }else if(test.startsWith('school_')||test==='stale_binding'){
      assert.equal(got.state,'ready');assert.equal(got.download.school.status,'unavailable');
      assert.deepEqual(got.download.result,got.control.result,'rejected school input does not replace query result');
      if(test==='stale_binding')assert.notEqual(got.requestedKey,got.returnedKey,'same margins cannot collapse distinct scopes');
    }else{
      assert.equal(got.state,'unavailable');assert.equal(got.download,null);assert.deepEqual(got.raw,{});assert.deepEqual(got.samples,{});assert.equal(got.downloadDisabled,true);
    }
    if(got.state==='ready'){
      assert.equal(got.overflow,false);assert.deepEqual(got.raw,{student:'3',parent:'4'});
      assert.deepEqual(got.samples,{A:'1',C:'1',AC:'1',B:'1',D:'1',BD:'1',E:'1',F:'1',EF:'1'});
    }
    assert.deepEqual(errors,[]);console.log(JSON.stringify({check:test,status:'passed'}));
  }catch(e){console.error(e);process.exitCode=1;}finally{if(browser)await browser.close();}
});
'''


@pytest.mark.parametrize('check', ['canonical_query','school_parent_first','school_student_first','canonical_both',
    'scope_value','scope_extra','scope_missing','scope_null','scope_type','scope_nested',
    'sources_order','surveys_order','sources_object','sources_length','sources_value',
    'result_release','result_schema','result_timezone','school_count','school_type','school_missing',
    'school_extra','school_null','school_array','school_release','stale_binding'])
def test_json_content_equivalence_and_rejection(check):
    index=synthetic_index()
    precomputed=json.loads(canonical_json(query_scope(index)))
    run=subprocess.run(['node','-e',EQUIVALENCE_DRIVER],input=json.dumps(dict(index=index,
        precomputed=precomputed,school=synthetic_public_projection(),check=check,
        styles=STYLES,engine=ENGINE,view=JS_SOURCE)),capture_output=True,text=True,timeout=45)
    assert run.returncode==0,run.stdout+run.stderr
