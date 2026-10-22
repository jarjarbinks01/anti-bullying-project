"""Synthetic publication-to-six-tab integration. No research pipeline is run.

The inherited 23-record oracle is copied in memory. Source aliases are adapted
to legacy UI categories; kb1's toy day is May 2 for a literal 90-day independent
adult pair. Published scores below are fixtures, never recalculated answers.
"""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from static_scope_cases import synthetic_inputs, EXPECTED_COUNTS
from study2.common import PipelineError, digest, file_hash
from study2.descriptive_spec import DICTIONARY_VERSION, VERSION
from study2.static_export import (DEPLOY_FILES, PUBLICATION_INPUTS, build_scope_export,
    export_static, validate_scope_export, write_site)
from study2.static_scope import default_selection, query_scope
from study2.store import SCHEMA


def synthetic_publication(root, *, adult=True, raw=True, independent=True):
    root = Path(root)
    state, releases = root/'state', root/'releases'
    folder = releases/'synthetic-r04'
    state.mkdir(parents=True); folder.mkdir(parents=True)
    records, selected, formal, summary = synthetic_inputs()
    summary.update(release_id='synthetic-r04', descriptive={'version': VERSION})
    sources = {'Alpha': ('qualtrics', 'demo_qualtrics'),
               'Beta': ('paperform', 'paperform_demo'),
               'Gamma': ('school_batch', 'separate_data_demo')}
    for record in records:
        record['source_type'], record['source_label'] = sources[record['source_type']]
        if record['fixture_version'] == 'ks0':
            record['answer']['Survey'] = 'Synthetic student baseline questionnaire with a complete long original label'
        if record['fixture_version'] == 'kp0':
            record['answer']['Survey'] = '合成家長問卷（保留原文）'
        if record['submission_id'] == 'toy-record-kb1':
            record.update(observed_at='2025-05-02T00:00:00+08:00', hk_creation_day='2025-05-02')
    by_id = {row['submission_id']: row for row in records}

    def published(slot):
        row = {**deepcopy(by_id[slot['submission_id']]), **slot}
        child = row['child_id'].removeprefix('toy-child-')
        base = {'kite': 0., 'lily': 1., 'moss': 2.}[child]
        phq = base + ({'kite': 1., 'lily': 2., 'moss': 0.}[child] if row['wave']=='T1' else 0.)
        if row['submission_id']=='toy-record-kb1': phq=2.
        # No answer, private fixture annotations or contacts enter the analysis.
        for key in ('answer', 'formal_sample_slots', 'fixture_version', 'adult_continuity'):
            row.pop(key, None)
        row.update(longitudinal=True, child_report_longitudinal=True, dyad=True,
            longitudinal_dyad=True, mainstream=child!='lily', school='Synthetic '+child,
            school_type='primary', gender='1' if child=='lily' else '0', grade=4,
            identity_rules='synthetic_fixed', PHQ_total=phq, PHQ_anxiety=phq/2,
            PHQ_depression=phq/2, FQOL_total=2.+base/4, SEC_total=2.+base/4,
            TBV_mean=1., TBP_mean=1., CBV_mean=1., CBP_mean=1.)
        row.update({domain+'_prevalence'+str(threshold): float(base>=threshold)
                    for domain in ('TBV','TBP','CBV','CBP') for threshold in (1,2)})
        return row
    frame = pd.DataFrame([published(row) for row in selected])
    parents = pd.DataFrame([published(row) for row in formal])
    frame.to_parquet(folder/'analysis.parquet',index=False)
    if adult: parents.to_parquet(folder/'parent_longitudinal.parquet',index=False)
    measurements = pd.DataFrame([dict(submission_id=sid,
        descriptive_dictionary_version=DICTIONARY_VERSION,school_stage='primary')
        for sid in dict.fromkeys(list(frame.submission_id)+list(parents.submission_id))])
    measurements.to_parquet(folder/'descriptive_measurements.parquet',index=False)
    if raw:
        with gzip.open(folder/'records.jsonl.gz','wt',encoding='utf-8') as stream:
            for row in records: stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    summary['stage_counts'].update({'1.1':23,'2.1.4':dict(eligible_submissions=19,child_groups=3),
        '3.1.1':dict(A=3,B=3,C=3,D=3),'3.1.2/3.1.3':dict(E=3,F=3,EF=3)})
    summary['case_status_counts']=dict(confirmed=2,pending=1,rejected=1,unmatched=0)
    if independent:
        panel=[]; pairs=[]
        for branch,follow,days in [('child_report','kp1',120),('same_adult','kb1',90)]:
            for alias,wave in [('kp0','T0'),(follow,'T1')]:
                row=published(dict(submission_id='toy-record-'+alias,child_id='toy-child-kite',role='parent',wave=wave))
                row.update(panel_branch=branch,panel_wave=wave,panel_longitudinal=True)
                panel.append(row)
            pairs.append(dict(panel_branch=branch,child_id='toy-child-kite',t0='toy-record-kp0',
                              t1='toy-record-'+follow,interval_days=days))
        tables=dict(analysis=pd.DataFrame(panel),pairs=pd.DataFrame(pairs),
            audit=pd.DataFrame([{'submission_id':row['submission_id']} for row in records if row['role']=='parent']),
            candidates=pd.DataFrame({'one_digit_candidate':pd.Series(dtype=bool)}),
            sensitivity=pd.DataFrame({'experiment':pd.Series(dtype=str)}))
        for name,table in tables.items(): table.to_parquet(folder/f'independent_parent_{name}.parquet',index=False)
        summary['independent_parent']=dict(parent_submissions=12,baselines=1,child_report_pairs=1,
            same_adult_pairs=1,same_adult_alternative_T1=1,minimum_followup_days=90,one_digit_candidates=0)
    pd.DataFrame(dict(registration_state=['active','active','paused'],
        followup_status=['both_complete','student_only','neither_complete'])).to_parquet(folder/'dyad_tracking.parquet',index=False)
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False))
    (releases/'CURRENT.json').write_text(json.dumps({'release_id':summary['release_id']}))
    with sqlite3.connect(state/'study2.sqlite') as db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('synthetic-run','fixed','2026-01-01','published','{}',json.dumps(summary),None))
        for row in records:
            db.execute('INSERT INTO normalized_records VALUES(?,?,?)',('synthetic-run',row['submission_id'],json.dumps(row)))
        db.execute('INSERT INTO releases VALUES(?,?,?,?,?)',(summary['release_id'],'synthetic-run','2026-01-01',str(folder),json.dumps(summary)))
        db.execute('INSERT INTO publication VALUES(1,?)',(summary['release_id'],))
    cfg=dict(state_dir=str(state),release_dir=str(releases),project_root=str(root/'sources'))
    return dict(cfg=cfg,folder=folder,summary=summary,records=records,frame=frame,parents=parents)


def load_script(path, prefix):
    return json.loads(Path(path).read_text().removeprefix(prefix).removesuffix(';\n'))


def tree_bytes(folder):
    return {p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}


@pytest.fixture(scope='module')
def exported(tmp_path_factory):
    root=tmp_path_factory.mktemp('r04-complete')
    fixture=synthetic_publication(root/'inputs')
    destination=root/'site'
    result=export_static(fixture['cfg'],destination)
    return fixture,destination,result


def test_complete_published_export_counts_assets_inventory_and_privacy(exported):
    fixture,site,result=exported
    scope=load_script(site/'scope-index.js','window.STUDY2_SCOPE_EXPORT=')
    query=query_scope(scope['index'])
    samples={row['code']:row['count'] for row in query['samples']}
    assert tuple([query['raw']['student'],query['raw']['parent']]+[samples[k] for k in ('A','B','C','D','AC','BD','E','F','EF')])==EXPECTED_COUNTS['all']
    assert scope['reconciliation']==query['reconciliation']
    assert not scope['school_bindings']
    manifest=json.loads((site/'snapshot-manifest.json').read_text())
    assert set(PUBLICATION_INPUTS)<=set(manifest['input_inventory'])
    assert manifest['input_inventory']['records.jsonl.gz']['sha256']==file_hash(fixture['folder']/'records.jsonl.gz')
    assert manifest['input_revision']==digest(manifest['input_inventory'])
    for name,pin in manifest['files'].items(): assert file_hash(site/name)==pin
    assert set(tree_bytes(site))==DEPLOY_FILES and not result['deployed']
    for name in ('snapshot.js','scope-index.js'):
        text=(site/name).read_text()
        for private in ('toy-record-','toy-child-','toy-input-revision-','Synthetic kite','/Users/','contact_01'):
            assert private not in text
    assert '合成家長問卷（保留原文）' in (site/'scope-index.js').read_text()


def test_published_numerical_values_and_parent_phq_gates(exported):
    _,site,_=exported
    from study2.static_export import build_snapshot
    fixture=exported[0]
    # Reuse actual exporter snapshot payload, unpacking columns without recalculating.
    packed=load_script(site/'snapshot.js','window.STUDY2_SNAPSHOT=')
    def unpack(table): return [dict(zip(table['columns'],row)) for row in table['rows']]
    views=packed['views']
    def view(mode,role): return next(v for v in views if v['mode']==mode and v['role']==role and not v['mainstream'] and v['source']=='all')
    student=view('acbd','student')
    stats=unpack(student['statistics']); changes=unpack(student['changes'])
    phq=[r for r in stats if r['variable_id']=='PHQ_total' and r['group']=='all']
    assert [r['mean'] for r in phq]==[1.,2.]
    assert [r['valid_n'] for r in phq]==[3,3]
    change=next(r for r in changes if r['variable_id']=='PHQ_total' and r['group']=='all')
    assert change['paired_valid_n']==3 and change['mean_change']==1. and change['sd_change']==1. and change['cohen_dz']==1.
    for mode in ('efmatched','independent_child'):
        assert not any(r['variable_id'].startswith('PHQ') for r in unpack(view(mode,'parent')['changes']))
    adult=next(r for r in unpack(view('independent_adult','parent')['changes']) if r['variable_id']=='PHQ_total' and r['group']=='all')
    assert adult['paired_valid_n']==1 and adult['mean_change']==2.
    overview=next(r for r in unpack(view('abcd','parent')['changes']) if r['variable_id']=='PHQ_total' and r['group']=='all')
    assert overview['paired_valid_n']==1 and overview['mean_change']==0.


@pytest.mark.parametrize('adult,raw,minimum,code',[(False,True,0,None),(True,False,0,'complete_published_records_required'),(True,True,2,'exact_scope_incompatible_with_suppression')])
def test_missing_formal_raw_and_suppression_are_explicit(tmp_path,adult,raw,minimum,code,monkeypatch):
    # Boundary variants need both ordinary/formal modes, not all 132 views.
    # The module export fixture and protected browser use the complete matrix.
    import study2.static_export as module
    monkeypatch.setattr(module,'MODES',{'abcd':'per_wave','acbd':'formal'})
    monkeypatch.setattr(module,'SOURCE_NAMES',{'qualtrics':'Qualtrics'})
    monkeypatch.setattr(module,'GROUPS',{'all':'All'})
    fixture=synthetic_publication(tmp_path/'inputs',adult=adult,raw=raw,independent=False)
    site=tmp_path/'site';export_static(fixture['cfg'],site,minimum)
    side=load_script(site/'scope-index.js','window.STUDY2_SCOPE_EXPORT=')
    data=load_script(site/'snapshot.js','window.STUDY2_SNAPSHOT=')
    if code:
        assert side['status']=='unavailable' and side['code']==code and 'index' not in side
    else:
        assert next(r['count'] for r in query_scope(side['index'])['samples'] if r['code']=='BD') is None
        assert data['counts']['BD'] is None
        assert not any(v['mode']=='acbd' and v['role']=='parent' for v in data['views'])
    assert data['views']


@pytest.mark.parametrize('name', ['summary.json','analysis.parquet','descriptive_measurements.parquet'])
def test_required_file_missing_preserves_previous(tmp_path,exported,name):
    import shutil
    fixture=synthetic_publication(tmp_path/'inputs',independent=False)
    site=tmp_path/'site';shutil.copytree(exported[1],site);before=tree_bytes(site)
    (fixture['folder']/name).unlink()
    with pytest.raises(PipelineError,match='Required published inputs'):export_static(fixture['cfg'],site)
    assert tree_bytes(site)==before


@pytest.mark.parametrize('mutate', ['compressed','pointer','optional','database','source_counts','school'])
def test_input_change_after_construction_preserves_previous(tmp_path,exported,monkeypatch,mutate):
    import shutil
    import study2.static_export as module
    fixture=synthetic_publication(tmp_path/'inputs',independent=False)
    site=tmp_path/'site';shutil.copytree(exported[1],site);before=tree_bytes(site)
    real=module.build_snapshot
    binding={'synthetic':'initial'}
    def changed(*args,**kwargs):
        # Preserve original validated views to focus on the input recheck boundary.
        snapshot=load_script(exported[1]/'snapshot.js','window.STUDY2_SNAPSHOT=')
        # write_site accepts packed tables too; mutation must be caught first.
        if mutate=='compressed': (fixture['folder']/'records.jsonl.gz').write_bytes(b'changed')
        elif mutate=='pointer': (Path(fixture['cfg']['release_dir'])/'CURRENT.json').write_text('{}')
        elif mutate=='optional': (fixture['folder']/'scope_flow_evidence.json').write_text('{}')
        elif mutate=='school': binding['synthetic']='changed'
        else:
            with sqlite3.connect(Path(fixture['cfg']['state_dir'])/'study2.sqlite') as db:
                if mutate=='database':db.execute("UPDATE releases SET created_at='changed'")
                else:db.execute("DELETE FROM normalized_records WHERE submission_id='toy-record-ks0'")
        return snapshot
    monkeypatch.setattr(module,'build_snapshot',changed)
    with pytest.raises(PipelineError,match='changed during export'):
        export_static(fixture['cfg'],site,school_binding=binding)
    assert tree_bytes(site)==before


@pytest.mark.parametrize('field,value',[('release_id','other'),('records_sha256','0'*64),('format','future')])
def test_stale_persisted_flow_envelope_fails_before_install(tmp_path,field,value):
    fixture=synthetic_publication(tmp_path/'inputs',independent=False)
    envelope=dict(format='study2_published_scope_flow_v1',release_id=fixture['summary']['release_id'],
                  records_sha256=file_hash(fixture['folder']/'records.jsonl.gz'),evidence={})
    envelope[field]=value
    (fixture['folder']/'scope_flow_evidence.json').write_text(json.dumps(envelope))
    with pytest.raises(PipelineError,match='stale_or_unsupported'):build_scope_export(fixture['folder'],fixture['summary'])


@pytest.mark.parametrize('boundary',range(1,len(DEPLOY_FILES)+1))
def test_every_staging_file_write_failure_retains_entire_previous_export(tmp_path,monkeypatch,boundary):
    from test_static_export import snapshot
    site=tmp_path/'site';write_site(snapshot(),site);before=tree_bytes(site)
    original=Path.write_text;count=0
    def fail(path,*args,**kwargs):
        nonlocal count
        if path.parent==site.parent or '.study2-static-' in str(path):
            count+=1
            if count==boundary:raise OSError('synthetic staging failure')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',fail)
    with pytest.raises(OSError):write_site({**snapshot(),'release_id':'next'},site)
    assert tree_bytes(site)==before


@pytest.mark.parametrize('boundary',[1,2])
@pytest.mark.parametrize('after',[False,True])
def test_every_install_rename_interruption_retains_previous(tmp_path,monkeypatch,boundary,after):
    import study2.static_export as module
    from test_static_export import snapshot
    site=tmp_path/'site';write_site(snapshot(),site)
    (site/'.vercel').mkdir();(site/'.vercel/project.json').write_text('{"projectId":"synthetic"}')
    before=tree_bytes(site);original=module.os.replace;calls=0
    def fail(source,target):
        nonlocal calls
        calls+=1
        if calls==boundary:
            if after:original(source,target)
            raise KeyboardInterrupt('synthetic rename interruption')
        return original(source,target)
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(KeyboardInterrupt):write_site({**snapshot(),'release_id':'next'},site)
    assert tree_bytes(site)==before


@pytest.mark.parametrize('boundary',[1,2,3])
def test_input_recheck_failure_around_install_retains_previous(tmp_path,boundary):
    from test_static_export import snapshot
    site=tmp_path/'site';write_site(snapshot(),site);before=tree_bytes(site);calls=0
    def verify():
        nonlocal calls
        calls+=1
        if calls==boundary:raise PipelineError('synthetic inputs changed')
    with pytest.raises(PipelineError):write_site({**snapshot(),'release_id':'next'},site,verify_inputs=verify)
    assert tree_bytes(site)==before


def school_binding(fixture):
    from study2.static_school_status import (EVIDENCE_FORMAT,fingerprint,
        reconcile_school_status,project_school_status,normalize_school_key)
    name='Synthetic queue item';key=normalize_school_key(name)
    bundle=dict(format=EVIDENCE_FORMAT,release_id=fixture['summary']['release_id'],dictionary_sha256='a'*64,
        review_state='no_recorded_review',decision_revision=None,criteria_revision=None,
        historical_queue=[dict(raw_name=name,normalized_key=key)],current_queue=[dict(raw_name=name,normalized_key=key)],
        records=[],dictionary=[],decisions=[],criteria=[])
    blank=dict(raw_name='',use='none',actionable=False,criterion_id=None,published_action='missing',published_canonical=None,caused_exclusion=False)
    active=dict(raw_name=name,use='cleaning_and_identity',actionable=None,criterion_id=None,published_action='unmapped',published_canonical=None,caused_exclusion=False)
    for row in fixture['records']:
        fields={'school_from_student':deepcopy(blank),'school_from_parent':deepcopy(blank)}
        if row['submission_id'] in {'toy-record-ks0','toy-record-kp0'}:
            fields['school_from_'+row['role']]=deepcopy(active)
        bundle['records'].append(dict(submission_id=row['submission_id'],role=row['role'],status=row['status'],school_fields=fields))
    pins={key:bundle[key] for key in ('release_id','dictionary_sha256','review_state','decision_revision','criteria_revision')}
    pins['bundle_sha256']=fingerprint(bundle)
    projection=project_school_status(reconcile_school_status(bundle,pins))
    scope=build_scope_export(fixture['folder'],fixture['summary'])
    return dict(index_revision=scope['index_revision'],scope=default_selection(scope['index']),projection=projection)


def test_exact_bound_synthetic_school_projection_and_fail_closed_controls(exported):
    fixture,site,_=exported
    binding=school_binding(fixture)
    output=build_scope_export(fixture['folder'],fixture['summary'],school_binding=binding)
    assert len(output['school_bindings'])==1
    assert binding['projection']['reconciliation_status']=='not_reconciled'
    assert binding['projection']['release_wide']['labels']['states']['unreviewed']==1
    for field in ('index_revision','release_id','scope'):
        bad=deepcopy(binding)
        if field=='release_id':bad['projection']['release_id']='other'
        elif field=='index_revision':bad[field]='0'*64
        else:bad['scope']['sources']=[]
        result=build_scope_export(fixture['folder'],fixture['summary'],school_binding=bad)
        assert not result['school_bindings']


def test_scope_schema_revision_and_suppression_fail_before_replacement(exported,tmp_path):
    from test_static_export import snapshot
    fixture,_,_=exported
    scope=build_scope_export(fixture['folder'],fixture['summary'])
    compatible={**snapshot(),'release_id':fixture['summary']['release_id']}
    for bad in ({**scope,'format':'future'},{**scope,'index_revision':'0'*64},{**scope,'private':'forbidden'}):
        with pytest.raises(PipelineError):validate_scope_export(bad,compatible)
    with pytest.raises(PipelineError):validate_scope_export(scope,{**compatible,'minimum_cell_n':10})


SUPPRESSION_BROWSER_DRIVER=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const base='http://127.0.0.1:8895',out=input.output;
const result={checks:[],page_errors:[],request_failures:[],downloads:[]};
(async()=>{let browser;
 try{
  browser=await chromium.launch({headless:true});result.browser_version=browser.version();result.browser_executable=chromium.executablePath();
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const page=await context.newPage();page.on('pageerror',e=>result.page_errors.push(e.message));page.on('requestfailed',r=>result.request_failures.push(r.url()));
  let downloadEvents=0;page.on('download',()=>downloadEvents++);
  const ready=()=>page.locator('.s2-quality[data-state=ready]').waitFor();
  const first=()=>page.getByRole('button',{name:'Data quality & progress',exact:true}).click();
  async function saved(name){const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Download current aggregate JSON',exact:true}).click();const item=await pending;await item.saveAs(path.join(out,name));result.downloads.push(name);return JSON.parse(fs.readFileSync(path.join(out,name),'utf8'));}
  async function blocked(label,message){
    await page.getByText(message,{exact:false}).waitFor();
    assert.equal(await page.locator('.s2-quality').count(),0,label+' must not mount the presenter');
    assert.equal(await page.locator('[data-raw],[data-sample],input[data-facet]').count(),0,label+' must not render exact controls or figures');
    assert.equal(await page.getByRole('button',{name:'Download current aggregate JSON',exact:true}).count(),0,label+' must not retain a stale query download');
    const before=downloadEvents;await page.waitForTimeout(100);assert.equal(downloadEvents,before,label+' must not emit a stale download');
    result.checks.push(label+': no presenter, exact counts, controls or stale download');
  }
  async function otherTabs(label){
    for(const name of ['Descriptive statistics','Independent parent analysis','Matching evidence','Family tracking','Definitions & methods']){
      await page.getByRole('button',{name,exact:true}).click();assert((await page.locator('#content').innerText()).length>50);
      assert.equal(await page.getByText('The page could not be displayed.',{exact:false}).count(),0);
      if(['Descriptive statistics','Independent parent analysis','Definitions & methods'].includes(name))assert(await page.locator('#content table').count()>0);
    }result.checks.push(label+': other five aggregate tabs remain usable');
  }
  await page.goto(base+'/login.html');await page.locator('#password').fill(process.env.R04_BROWSER_PASSWORD);await page.locator('#submit').click();await page.waitForURL(base+'/');await ready();
  const zero=JSON.parse(input.zero.replace(/^window.STUDY2_SNAPSHOT=/,'').replace(/;\n$/,''));
  const positive=JSON.parse(input.positive.replace(/^window.STUDY2_SNAPSHOT=/,'').replace(/;\n$/,''));
  const exact=JSON.parse(input.exact.replace(/^window.STUDY2_SCOPE_EXPORT=/,'').replace(/;\n$/,''));
  assert.equal(zero.minimum_cell_n,0);assert.equal(zero.small_sample_policy,'none');
  assert.equal(positive.minimum_cell_n,2);assert.equal(positive.small_sample_policy,'threshold');
  assert.equal(exact.status,'available');assert.equal(positive.release_id,zero.release_id);assert.equal(exact.release_id,positive.release_id);
  await page.getByLabel('Start date · Hong Kong',{exact:true}).fill('2025-05-02');await ready();
  await page.getByLabel('End date · Hong Kong',{exact:true}).fill('2025-05-02');await ready();
  const visible=await saved('minimum-zero-one-parent.json');assert.deepEqual(visible.result.raw,{student:0,parent:1});
  result.checks.push('minimum=0 valid control displays and saves exact one-parent scope');
  const suppression="Exact first-tab filtering is unavailable under this snapshot's cell-suppression policy.";
  const invalid='Exact first-tab filtering is unavailable because this snapshot has missing or inconsistent cell-suppression settings.';
  // Retain the previous exact selection, change snapshot policy in memory,
  // navigate away and back. The obsolete presenter must not return a query.
  await page.evaluate(()=>{window.STUDY2_SNAPSHOT.minimum_cell_n=2;window.STUDY2_SNAPSHOT.small_sample_policy='threshold';});
  await otherTabs('changed policy after ready exact scope');await first();await blocked('changed policy after ready exact scope',suppression);
  await page.route('**/snapshot.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:input.positive}));
  await page.route('**/scope-index.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:input.unavailable}));
  await page.goto(base+'/');await blocked('normal positive-threshold export',suppression);await otherTabs('normal positive-threshold export');
  await page.unroute('**/scope-index.js');
  // Actual same-release exports are mixed without editing either payload.
  await page.goto(base+'/');await blocked('positive snapshot plus older exact sidecar',suppression);
  await page.screenshot({path:path.join(out,'suppression-mixed-assets-fixed.png'),fullPage:true});await otherTabs('mixed same-release assets');
  result.mixed={minimum:positive.minimum_cell_n,release:positive.release_id,sidecar_release:exact.release_id,sidecar_status:exact.status};
  await page.unroute('**/snapshot.js');
  const malformed=[['missing minimum',{small_sample_policy:'none'}],['string minimum',{minimum_cell_n:'0',small_sample_policy:'none'}],
    ['null minimum',{minimum_cell_n:null,small_sample_policy:'none'}],['missing policy',{minimum_cell_n:0}],
    ['inconsistent zero threshold',{minimum_cell_n:0,small_sample_policy:'threshold'}],['unknown policy',{minimum_cell_n:0,small_sample_policy:'future'}]];
  for(const [label,metadata]of malformed){
    const changed={...zero};delete changed.minimum_cell_n;delete changed.small_sample_policy;Object.assign(changed,metadata);
    await page.route('**/snapshot.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:'window.STUDY2_SNAPSHOT='+JSON.stringify(changed)+';\n'}));
    await page.goto(base+'/');await blocked(label,invalid);await page.unroute('**/snapshot.js');
  }
  await page.goto(base+'/');await ready();const restored=await saved('minimum-zero-restored.json');assert.deepEqual(restored.result.raw,{student:11,parent:12});
  result.checks.push('valid minimum=0 snapshot restores default exact query and download');
  assert.deepEqual(result.page_errors,[]);assert.deepEqual(result.request_failures,[]);result.status='passed';
 }catch(error){result.status='failed';result.error={message:error.message,stack:error.stack};process.exitCode=1;}
 finally{if(browser)await browser.close();fs.writeFileSync(path.join(out,'SUPPRESSION_BROWSER.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,checks:result.checks.length,error:result.error?.message}));}
})();
'''


def test_browser_snapshot_suppression_rejects_mixed_exact_sidecars(tmp_path,monkeypatch):
    """Real synthetic exports, original protected preview, only owned port8895."""
    import os
    import secrets
    import shutil
    import socket
    import subprocess
    import time
    import study2.static_export as module
    node=shutil.which('node')
    if not node:pytest.skip('Node and existing Playwright are required')
    # Every analysis mode remains represented. Narrow source/group fixtures
    # avoid repeating unaffected r1 scientific matrix coverage.
    monkeypatch.setattr(module,'SOURCE_NAMES',{'qualtrics':'Qualtrics'})
    monkeypatch.setattr(module,'GROUPS',{'all':'All'})
    fixture=synthetic_publication(tmp_path/'inputs')
    zero,positive=tmp_path/'minimum-zero',tmp_path/'minimum-two'
    export_static(fixture['cfg'],zero,0);export_static(fixture['cfg'],positive,2)
    output=Path(os.environ.get('R04_REGRESSION_OUTPUT',str(tmp_path/'browser')))
    output.mkdir(parents=True,exist_ok=False)
    pins={label:dict(manifest_sha256=file_hash(folder/'snapshot-manifest.json'),
        snapshot_sha256=file_hash(folder/'snapshot.js'),sidecar_sha256=file_hash(folder/'scope-index.js'))
        for label,folder in [('minimum_zero',zero),('minimum_two',positive)]}
    (output/'EXPORT_PINS.json').write_text(json.dumps(pins,indent=2))
    lifecycle=dict(port=8895,bind='127.0.0.1',other_preview_ports='not queried or operated')
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',8895))!=0,'Port8895 occupied; do not replace its listener'
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',8895))
    lifecycle['port_free_before']=True
    password=secrets.token_urlsafe(24)
    server_env=dict(os.environ,PORT='8895',STUDY2_ACCESS_PASSWORD=password,STUDY2_SESSION_SECRET=secrets.token_urlsafe(48))
    with (output/'SERVER.log').open('w') as log:
        server=subprocess.Popen([node,str(zero/'preview.mjs')],env=server_env,stdout=log,stderr=subprocess.STDOUT)
        lifecycle['pid']=server.pid
        try:
            for _ in range(100):
                assert server.poll() is None,'Owned preview exited'
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',8895))==0:break
                time.sleep(.1)
            payload=dict(zero=(zero/'snapshot.js').read_text(),positive=(positive/'snapshot.js').read_text(),
                exact=(zero/'scope-index.js').read_text(),unavailable=(positive/'scope-index.js').read_text(),output=str(output))
            browser=subprocess.run([node,'-e',SUPPRESSION_BROWSER_DRIVER],input=json.dumps(payload),
                text=True,capture_output=True,env=dict(os.environ,R04_BROWSER_PASSWORD=password),timeout=90)
            (output/'BROWSER.log').write_text(browser.stdout+browser.stderr)
            lifecycle['browser_exit_code']=browser.returncode
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            lifecycle['server_exit_code']=server.returncode
            with socket.socket() as sock:lifecycle['port_closed_after']=sock.connect_ex(('127.0.0.1',8895))!=0
            (output/'LIFECYCLE.json').write_text(json.dumps(lifecycle,indent=2))
    assert browser.returncode==0,browser.stdout+browser.stderr
    assert lifecycle['port_closed_after']
