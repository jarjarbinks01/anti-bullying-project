"""Fresh-run aggregate binding, default ON and exact OFF restoration, invented only."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pandas as pd
import pytest

from study2.analysis_eligibility import COPY_POLICY, MANIFEST_FORMAT, inventory_revision, manifest_revision, sha
from study2.common import PipelineError, digest
from study2.static_release_context import FORMAT, bind_release_context, validate_release_context
from study2.static_export import export_static
from test_static_quality_integration import synthetic_publication, load_script, tree_bytes


def context(release='fresh-synthetic', run='fresh-run', manifest=None):
    value=dict(format=FORMAT,release_id=release,run_id=run,run_fingerprint='f'*64,program_hash='c'*64,
        group_control_head='a'*64,group_proposal_revision='b'*64,group_implementation_revision='d'*64,
        review_control_revision='e'*64,flags=dict(manifest_revision='1'*64,inventory_revision='2'*64,
            eric_records=0,group_records=0,overlap_records=0,combined_records=0),
        workload=dict(child_groups=3,phone_groups=1,held_groups=2,correction_comparisons=5,
            correction_bundles=3,adult_comparisons=1))
    if manifest:
        value['flags'].update(manifest_revision=manifest['revision'],inventory_revision=manifest['inventory_revision'],
            group_records=len(manifest['entries']),combined_records=len(manifest['entries']))
    value['revision']=sha(value)
    return value


@pytest.mark.parametrize('mutate',[
    lambda v:v.update(extra='not permitted'),
    lambda v:v.update(release_id='../private'),
    lambda v:v.update(run_id='CASE_'+'a'*24),
    lambda v:v.update(group_control_head='short'),
    lambda v:v['flags'].update(eric_records=True),
    lambda v:v['flags'].update(group_records=-1),
    lambda v:v['flags'].update(overlap_records=1),
    lambda v:v['flags'].update(combined_records=1),
    lambda v:v['flags'].update(contact='not permitted'),
    lambda v:v['workload'].update(phone_groups=4),
    lambda v:v['workload'].update(correction_bundles=6),
    lambda v:v['workload'].update(adult_comparisons=1.5),
    lambda v:v['workload'].update(record_ids=[]),
])
def test_closed_aggregate_context_rejects_even_rehashed_invalid_input(mutate):
    value=context();mutate(value);value['revision']=sha({k:v for k,v in value.items() if k!='revision'})
    with pytest.raises(PipelineError):validate_release_context(value)


def test_revision_and_public_shape_are_checked():
    value=context();validate_release_context(value)
    value['workload']['adult_comparisons']+=1
    with pytest.raises(PipelineError,match='revision_mismatch'):validate_release_context(value)
    value=context();value.update(default_eligibility='unknown',workload_scope='release_wide_applied_controls',export_program_hash='a'*64)
    with pytest.raises(PipelineError):validate_release_context(value,public=True)


def publication(root):
    value=synthetic_publication(root)
    records=value['records']
    for r in records:r['raw_hash']=digest([r['submission_id'],r['version_id']])
    with gzip.open(value['folder']/'records.jsonl.gz','wt') as f:
        for r in records:f.write(json.dumps(r)+'\n')
    panel_path=value['folder']/'independent_parent_analysis.parquet'
    panel=pd.read_parquet(panel_path)
    loose=deepcopy(next(r for r in records if r['submission_id']=='toy-record-unanchored'))
    base=panel.loc[panel.panel_branch.eq('child_report')&panel.panel_wave.eq('T0')].iloc[0].to_dict()
    for k in ('submission_id','version_id','child_id','source_type','source_label','observed_at','date_basis','time_confidence'):
        base[k]=loose[k]
    base.update(panel_longitudinal=False,school='Synthetic detached school',PHQ_total=10.,wave='T0',panel_wave='T0')
    pd.concat([panel,pd.DataFrame([base])],ignore_index=True).to_parquet(panel_path,index=False)
    mp=value['folder']/'descriptive_measurements.parquet';m=pd.read_parquet(mp)
    addition=m.iloc[0].to_dict();addition['submission_id']=loose['submission_id']
    pd.concat([m,pd.DataFrame([addition])],ignore_index=True).to_parquet(mp,index=False)
    summary=value['summary'];summary['independent_parent']['baselines']=2;summary['program_hash']='c'*64
    (value['folder']/'summary.json').write_text(json.dumps(summary))
    with sqlite3.connect(Path(value['cfg']['state_dir'])/'study2.sqlite') as db:
        db.execute('UPDATE runs SET fingerprint=?,stats_json=?',('f'*64,json.dumps(summary)))
        db.execute('UPDATE releases SET stats_json=?',(json.dumps(summary),))
    manifest=dict(format=MANIFEST_FORMAT,release_id=summary['release_id'],inventory_revision=inventory_revision(records),
        status='accepted',approved_by='Synthetic independent review',approved_at='2026-01-01T00:00:00+00:00',
        copy_policy=COPY_POLICY,entries=[dict(submission_id=loose['submission_id'],version_id=loose['version_id'])])
    manifest['revision']=manifest_revision(manifest)
    return value,manifest,context(summary['release_id'],'synthetic-run',manifest)


@pytest.fixture(scope='module')
def exported(tmp_path_factory):
    import study2.static_export as module
    # All native/independent modes and source filters remain present. One
    # displayed subgroup avoids rerunning the unrelated nine-group matrix.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module,'GROUPS',{'all':'All'})
        root=tmp_path_factory.mktemp('current-release');value,manifest,ctx=publication(root/'inputs')
        site=root/'site';export_static(value['cfg'],site,manual_manifest=manifest,release_context=ctx,default_eligibility='on')
        yield value,manifest,ctx,site


def test_fresh_release_context_binds_real_export_and_preserves_all_nine_native_counts(exported):
    value,manifest,ctx,site=exported
    off=load_script(site/'snapshot.js','window.STUDY2_SNAPSHOT=')
    # manual-exclusion.js includes its accepted hash helper before the payload.
    raw=(site/'manual-exclusion.js').read_text().split('window.STUDY2_MANUAL_EXCLUSION=',1)[1]
    wrapper=json.loads(raw.removesuffix(';\n'));on=wrapper['on']['snapshot']
    assert wrapper['status']=='available' and wrapper['revision']==manifest['revision']
    assert off['release_context']==on['release_context']
    assert off['release_context']['default_eligibility']=='on'
    assert off['release_context']['revision']==ctx['revision']
    assert off['counts']==on['counts']  # The excluded response has no native student anchor.
    assert off['independent_counts']['baselines']==2 and on['independent_counts']['baselines']==1
    def select(s,mode):return next(v for v in s['views'] if v['mode']==mode and v['source']=='all' and not v['mainstream'])
    assert select(off,'independent_all')['counts']['all']==dict(T0=2,T1=1)
    assert select(on,'independent_all')['counts']['all']==dict(T0=1,T1=1)
    for mode in ('independent_child','independent_adult'):
        assert select(off,mode)==select(on,mode)
    manifest_public=json.loads((site/'snapshot-manifest.json').read_text())
    assert manifest_public['release_context']==off['release_context']
    for name in ('snapshot.js','scope-index.js','manual-exclusion.js','snapshot-manifest.json'):
        text=(site/name).read_text()
        for private in ('toy-record-','toy-child-','contact_01',str(value['folder']),str(value['cfg']['state_dir'])):
            assert private not in text


@pytest.mark.parametrize('field',['release_id','run_id','run_fingerprint','program_hash','manifest_revision','inventory_revision','combined_records'])
def test_mismatched_context_rejects_before_replacing_existing_site(exported,tmp_path,field):
    value,manifest,ctx,original=exported;bad=deepcopy(ctx)
    if field in bad:bad[field]='other-run' if field.endswith('_id') else '0'*64
    elif field=='combined_records':bad['flags']['group_records']=bad['flags']['combined_records']=2
    else:bad['flags'][field]='0'*64
    bad['revision']=sha({k:v for k,v in bad.items() if k!='revision'})
    from study2.static_release_context import bind_release_context
    with pytest.raises((PipelineError,ValueError)):
        bind_release_context(bad,dict(release_id=value['summary']['release_id'],run_id='synthetic-run'),
            value['summary'],'f'*64,value['records'],manifest)
    # Exercise actual export for one representative mismatch without repeating
    # the full unchanged scientific presentation matrix seven times.
    if field=='run_fingerprint':
        site=tmp_path/'site';shutil.copytree(original,site);before=tree_bytes(site)
        with pytest.raises(PipelineError):export_static(value['cfg'],site,manual_manifest=manifest,release_context=bad)
        assert tree_bytes(site)==before


def test_supplied_context_requires_manifest_and_valid_on_lane(exported,tmp_path,monkeypatch):
    value,manifest,ctx,original=exported
    import study2.static_export as module
    # Reuse already validated presentation rows; focus on explicit export gates.
    packed=load_script(original/'snapshot.js','window.STUDY2_SNAPSHOT=')
    from study2.manual_exclusion_export import _unpack
    off=_unpack(packed);off.pop('release_context')
    monkeypatch.setattr(module,'build_snapshot',lambda *a,**k:deepcopy(off))
    with pytest.raises(PipelineError,match='accepted composed manifest'):
        export_static(value['cfg'],tmp_path/'missing',release_context=ctx)
    monkeypatch.setattr('study2.manual_exclusion_export.build_manual_export',lambda *a,**k:dict(status='unavailable'))
    with pytest.raises(PipelineError,match='complete valid ON/OFF'):
        export_static(value['cfg'],tmp_path/'invalid',manual_manifest=manifest,release_context=ctx)


@pytest.mark.parametrize('drift',['context','run'])
def test_context_and_selected_run_drift_during_export_retains_previous(exported,tmp_path,monkeypatch,drift):
    value,manifest,ctx,original=exported
    import study2.static_export as module
    real=module.write_site
    site=tmp_path/'site';shutil.copytree(original,site);before=tree_bytes(site)
    def mutate(snapshot,destination,**kwargs):
        if drift=='context':ctx['workload']['adult_comparisons']+=1
        else:
            with sqlite3.connect(Path(value['cfg']['state_dir'])/'study2.sqlite') as db:
                db.execute('UPDATE runs SET fingerprint=?',('0'*64,))
        return real(snapshot,destination,**kwargs)
    # Avoid another full build; mutate exactly at the verified install boundary.
    packed=load_script(original/'snapshot.js','window.STUDY2_SNAPSHOT=')
    from study2.manual_exclusion_export import _unpack
    off=_unpack(packed);off.pop('release_context')
    monkeypatch.setattr(module,'build_snapshot',lambda *a,**k:deepcopy(off))
    monkeypatch.setattr(module,'write_site',mutate)
    try:
        with pytest.raises(PipelineError,match='changed during export'):
            export_static(value['cfg'],site,manual_manifest=manifest,release_context=ctx)
    finally:
        if drift=='context':ctx['workload']['adult_comparisons']-=1
        else:
            with sqlite3.connect(Path(value['cfg']['state_dir'])/'study2.sqlite') as db:
                db.execute('UPDATE runs SET fingerprint=?',('f'*64,))
    assert tree_bytes(site)==before


def test_default_on_is_explicit_and_requires_context():
    with pytest.raises(PipelineError,match='explicit validated'):
        export_static({},'unused',default_eligibility='on')
    from study2.static_release_context import bind_release_context
    from study2.group_cleaning import exclusion_manifest
    manifest=exclusion_manifest([], 'fresh-synthetic', [], operator='Synthetic',at='2026-01-01T00:00:00+00:00')
    ctx=context(manifest=manifest);release=dict(release_id=ctx['release_id'],run_id=ctx['run_id'])
    summary=dict(release_id=ctx['release_id'],program_hash=ctx['program_hash'])
    assert bind_release_context(ctx,release,summary,'f'*64,[],manifest)['default_eligibility']=='off'
    assert bind_release_context(ctx,release,summary,'f'*64,[],manifest,default_eligibility='on')['default_eligibility']=='on'


@pytest.mark.parametrize('drift',[False,True])
def test_export_code_hash_guard_runs_before_install(tmp_path,monkeypatch,drift):
    """Unit-level install gate; the full real-site retention cases are above."""
    value,manifest,ctx=publication(tmp_path/'inputs')
    import study2.static_export as module
    calls=[]
    def code_hash():
        calls.append('hash')
        return ('b' if drift and len(calls)>=3 else 'a')*64
    monkeypatch.setattr('study2.runner.program_hash',code_hash)
    monkeypatch.setattr(module,'build_snapshot',lambda *a,**k:dict(format='study2_static_v1',
        release_id=value['summary']['release_id'],generated_at='2026-01-01T00:00:00Z',views=[]))
    monkeypatch.setattr('study2.manual_exclusion_export.build_manual_export',lambda *a,**k:dict(status='available'))
    installed=[]
    def install(*a,**kwargs):installed.append(True);kwargs['verify_inputs']();return {'guarded':True}
    monkeypatch.setattr(module,'write_site',install)
    if drift:
        with pytest.raises(PipelineError,match='changed during export'):
            export_static(value['cfg'],tmp_path/'site',manual_manifest=manifest,release_context=ctx)
        assert not installed and not (tmp_path/'site').exists()
    else:
        assert export_static(value['cfg'],tmp_path/'site',manual_manifest=manifest,release_context=ctx)=={'guarded':True}
        assert installed and len(calls)>=3


BROWSER=r'''
const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{let browser;try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage({acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://release-ui.test/**',route=>{const p=new URL(route.request().url()).pathname;const body=input.assets[p];return body===undefined?route.abort():route.fulfill({status:200,contentType:p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':'text/html',body});});
 await page.goto('https://release-ui.test/');await page.locator('.manual-eligibility[data-state=ready]').waitFor();
 assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),true);
 await page.locator('.s2-quality[data-state=ready]').waitFor();
 const save=async(button)=>{const pending=page.waitForEvent('download');await page.getByRole('button',{name:button,exact:true}).click();const d=await pending;return fs.readFileSync(await d.path(),'utf8');};
 const on=JSON.parse(await save('Download aggregate snapshot'));assert.equal(on.eligibility.eligibility_mode,'on');
 assert.equal(on.snapshot.independent_counts.baselines,1);
 const scope=JSON.parse(await save('Download current aggregate JSON'));assert.equal(scope.release_context.revision,input.revision);
 assert.equal(scope.eligibility.mode,'on');
 await page.getByRole('button',{name:'Matching evidence',exact:true}).click();
 assert(await page.getByRole('heading',{name:'Current review workload',exact:true}).count());
 assert(await page.getByRole('heading',{name:'Historical candidate comparison inventory',exact:true}).count());
 assert((await page.locator('#content').innerText()).includes('must not be added'));
 const workload=page.locator('.section').filter({has:page.getByRole('heading',{name:'Current review workload',exact:true})});
 const rows=await workload.locator('tbody tr').allTextContents();
 assert(rows.some(x=>x.includes('Open child identity groups')&&x.includes('3')));
 const csvWait=page.waitForEvent('download');await workload.getByRole('button',{name:'Download current table (CSV)',exact:true}).click();const csv=fs.readFileSync(await (await csvWait).path(),'utf8');
 assert(csv.includes('release_context_revision')&&csv.includes(input.revision)&&csv.includes('analytical_run_fingerprint'));
 await page.locator('#manual-exclusion-enabled').uncheck();
 const off=JSON.parse(await save('Download aggregate snapshot'));assert.equal(off.eligibility.eligibility_mode,'off');assert.equal(off.snapshot.independent_counts.baselines,2);
 assert.deepEqual(await workload.locator('tbody tr').allTextContents(),rows); // current controls do not follow analytical masking
 await page.locator('#manual-exclusion-enabled').check();const restored=JSON.parse(await save('Download aggregate snapshot'));assert.deepEqual(restored,on);
 await page.getByRole('button',{name:'Independent parent analysis',exact:true}).click();await page.getByLabel('Analysis sample',{exact:true}).selectOption('independent_all');
 assert((await page.locator('.summary-n').innerText()).includes('1'));
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await page.getByRole('button',{name:'Period trends',exact:true}).click();
 assert((await page.locator('#content').innerText()).includes('T0'));
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',default_on:true,off_on_restoration:true,workload_units:true,csv_provenance:true,independent_parent:true,period_trend:true}));
}finally{if(browser)await browser.close();}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''


def test_browser_default_on_downloads_workload_units_and_off_restoration(exported,tmp_path):
    _,_,ctx,site=exported
    assets={'/'+p.name:p.read_text() for p in site.iterdir() if p.is_file() and p.suffix in {'.js','.css','.html'}}
    assets['/']=assets.pop('/index.html');assets['/access.js']=''
    node=shutil.which('node');assert node
    modules=Path(os.environ.get('SOURCE_UI_NODE_MODULES',Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
    result=subprocess.run([node,'-e',BROWSER],input=json.dumps(dict(assets=assets,revision=ctx['revision'])),text=True,
        capture_output=True,env=dict(os.environ,NODE_PATH=str(modules)),timeout=120)
    (tmp_path/'BROWSER.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
