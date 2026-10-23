"""Synthetic full-app browser acceptance, with no listening service or real data."""
import csv
import gzip
import hashlib
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
from statistics import stdev
import subprocess

import pytest

from study2.static_assets import APP_JS,HTML,STYLES
from study2.static_quality_ui import JS_SOURCE as QUALITY
from study2.static_scope_client import JS_SOURCE as SCOPE
from manual_exclusion_ui_fixture import fixture,stub_engine,typed_hash,REVISION
from static_source_ui_fixture import SPEC

NODE_MODULES=Path(os.environ.get('SOURCE_UI_NODE_MODULES',Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))


@pytest.fixture(scope='module')
def ui_data():
    cache=os.environ.get('MANUAL_UI_INPUT_BUNDLE')
    if cache:
        with gzip.open(cache,'rt',encoding='utf-8') as stream:stored=json.load(stream)
        assert stored['fixture_sha256']==hashlib.sha256(Path(__file__).with_name('manual_exclusion_ui_fixture.py').read_bytes()).hexdigest()
        value=stored['data']
    else:value=fixture()
    hash_source=Path(os.environ['MANUAL_UI_HASH_JS']).read_text()
    stub=os.environ.get('MANUAL_UI_STUB')=='1'
    assert stub or 'study2_scope_eligibility_v1' in SCOPE,'Frozen core scope dependency is required'
    value['stage']='explicit_synthetic_stub' if stub else 'frozen_core_scope'
    html=HTML.replace('<script defer src="app.js">','<script defer src="manual-exclusion.js"></script><script defer src="app.js">')
    encode=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    value['assets']={'/':html,'/styles.css':STYLES,'/app.js':APP_JS,'/quality-ui.js':QUALITY,
        '/scope-engine.js':stub_engine(SCOPE) if stub else SCOPE,
        '/snapshot.js':'window.STUDY2_SNAPSHOT='+encode(value['snapshot'])+';',
        '/scope-index.js':'window.STUDY2_SCOPE_EXPORT='+encode(value['scope'])+';',
        '/manual-exclusion.js':hash_source+'\nwindow.STUDY2_MANUAL_EXCLUSION='+encode(value['wrapper'])+';',
        '/access.js':''}
    values=[1,1.,0.,-0.,1e-6,1e-7,1.2e25,1.2345678901234567,
        {'😀':'astral','\ue000':'BMP','中':'繁體','a':[True,None,1.] }]
    value['hash_cases']=[dict(value=v,digest=typed_hash(v)) for v in values]
    return value


def run(ui_data,check):
    node=shutil.which('node');assert node and (NODE_MODULES/'playwright').is_dir()
    out=Path(os.environ['MANUAL_UI_EVIDENCE_DIR'])/check;assert not out.exists();out.mkdir(parents=True)
    payload={**ui_data,'output':str(out),'check':check}
    with gzip.open(out/'PAYLOAD.json.gz','wt',encoding='utf-8') as stream:json.dump(payload,stream,ensure_ascii=False)
    proc=subprocess.run([node,str(Path(__file__).with_name('manual_exclusion_ui_browser.cjs'))],input=json.dumps(payload,ensure_ascii=False),text=True,capture_output=True,
        env={**os.environ,'NODE_PATH':str(NODE_MODULES)},timeout=300)
    (out/'driver-stdout.log').write_text(proc.stdout);(out/'driver-stderr.log').write_text(proc.stderr)
    assert proc.returncode==0,f'Browser failure retained at {out}'
    return json.loads((out/'RESULTS.json').read_text()),out


def expected_pairs(mode,sources,grades):
    cells=[(i,r) for i,r in enumerate(SPEC) if (sources==['all'] or r[0] in sources) and (grades=='all' or r[1] in grades) and not(mode=='on' and i==0)]
    complete=[r for _,r in cells if r[2] is not None and r[3] is not None]
    a=[r[2] for r in complete];b=[r[3] for r in complete]
    return dict(pairs_n=len(cells),paired_valid_n=len(complete),t0_mean=sum(a)/len(a) if a else None,
                t1_mean=sum(b)/len(b) if b else None,t0_sd=stdev(a) if len(a)>1 else None,t1_sd=stdev(b) if len(b)>1 else None)


def test_app_switches_complete_bundles_and_preserves_controls(ui_data):
    result,out=run(ui_data,'integration');assert result['status']=='passed'
    assert len(result['sidebars'])==3
    for item in result['downloads']:
        if item['kind']=='quality':
            data=json.loads((out/item['file']).read_text());e=data['eligibility']
            assert e['mode']==item['mode'] and e['revision']==REVISION
            assert e['release_id']==ui_data['snapshot']['release_id']
            assert e['policy']=='fixed_original_members_no_reselection'
            if item.get('scoped'):assert data['result']['scope']['start']=='2025-01-02'
            continue
        if item['kind']=='snapshot':
            data=json.loads((out/item['file']).read_text())
            assert data['eligibility']['eligibility_mode']==item['mode']
            wanted=ui_data['snapshot'] if item['mode']=='off' else ui_data['wrapper']['on']['snapshot']
            assert data['snapshot']==wanted
            continue
        with (out/item['file']).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        assert rows
        assert all(r['eligibility_mode']==item['mode'] and r['eligibility_revision']==REVISION and r['eligibility_release_id']==ui_data['snapshot']['release_id'] for r in rows)
        if item.get('adult_phq_blocked'):
            assert not any(r['Variable ID'].startswith('PHQ_') for r in rows)
            assert any(r['Variable ID']=='SEC_total' for r in rows)
        elif item['sample']=='acbd':
            row=next(r for r in rows if r['Variable ID']=='PHQ_total')
            expected=expected_pairs(item['mode'],item['sources'],item['grades'])
            for label,key in [('Formal paired N','pairs_n'),('Valid in both waves N','paired_valid_n'),('T0 mean (raw, paired-valid)','t0_mean'),('T1 mean (raw, paired-valid)','t1_mean'),('T0 SD (raw, paired-valid)','t0_sd'),('T1 SD (raw, paired-valid)','t1_sd')]:
                assert math.isclose(float(row[label]),expected[key],rel_tol=1e-10,abs_tol=1e-10)
            if item['sources']!=['all']:assert 'p-value (raw)' not in row and 'Cohen dz (raw)' not in row
        elif item['sample']=='abcd':
            row=next(r for r in rows if r['Variable ID']=='PHQ_total')
            assert row['T0 sample N']=='10' and row['T1 sample N']=='11'
            assert row['T0 valid N']=='9' and row['T1 valid N']=='10'
            assert math.isclose(float(row['T0 mean (raw)']),47/9,rel_tol=1e-10)
    # A student-only flag leaves independent-adult scores/inference unchanged.
    def parent(name):
        with (out/name).open(encoding='utf-8-sig',newline='') as stream:return [{k:v for k,v in r.items() if not k.startswith('eligibility_')} for r in csv.DictReader(stream)]
    assert parent('on-independent-adult.csv')==parent('off-independent-adult.csv')


def test_invalid_bundles_hash_parity_and_explicit_unavailable_on(ui_data):
    result,_=run(ui_data,'invalid');assert result['status']=='passed'
    assert result['hash_cases']==9 and len(result['invalid'])==15 and result['invalid_app_state']
    assert all(r['off_preserved'] for r in result['invalid'])


def test_manual_asset_stays_behind_existing_authentication(tmp_path):
    """Execute existing Request/Response gate without starting a server."""
    from study2.static_access import ACCESS_CORE
    module=tmp_path/'access.mjs';module.write_text(ACCESS_CORE)
    script=r'''
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
const {gate,handleAuth}=await import(process.argv[1]);
const base='https://manual-ui.test',password=randomBytes(32).toString('hex');
const env={STUDY2_ACCESS_PASSWORD:password,STUDY2_SESSION_SECRET:'1'.repeat(64)};
const request=(headers={})=>new Request(base+'/manual-exclusion.js',{headers});
assert.equal(gate(request(),env).status,401);
assert.equal(gate(request(),{}).status,503);
const nav=gate(request({accept:'text/html'}),env);assert.equal(nav.status,303);assert.equal(nav.headers.get('location'),'/login.html');
const login=await handleAuth(new Request(base+'/api/auth',{method:'POST',headers:{origin:base,'content-type':'application/json'},body:JSON.stringify({action:'login',password})}),env);
assert.equal(login.status,200);const cookie=login.headers.get('set-cookie').split(';')[0];
assert.equal(gate(request({cookie}),env),null);
console.log(JSON.stringify({status:'passed',checks:4,servers_started:0}));
'''
    proc=subprocess.run([shutil.which('node'),'--input-type=module','-e',script,module.as_uri()],text=True,capture_output=True)
    assert proc.returncode==0,proc.stderr


def test_actual_core_generated_site_bundle_and_raw_pair_oracle():
    """Use the copied, hash-verified core site rather than a synthetic scope stub."""
    root=Path(os.environ['MANUAL_UI_CORE_FIXTURE_DIR'])
    data=json.loads((root/'SYNTHETIC_FIXTURE.json').read_text())
    oracle=json.loads((root/'SYNTHETIC_INPUT_ORACLE.json').read_text())
    assets={'/'+p.name:p.read_text() for p in (root/'synthetic_site').iterdir() if p.is_file() and p.suffix in {'.js','.css','.html'}}
    assets['/']=assets.pop('/index.html');assets.update({'/app.js':APP_JS,'/styles.css':STYLES,'/quality-ui.js':QUALITY,'/access.js':''})
    from study2.analysis_eligibility import sha
    values=[1,1.,0.,-0.,1e-6,1e-7,1.2e25,1.2345678901234567,{'😀':'astral','\ue000':'BMP','中':'繁體','a':[True,None,1.]}]
    assert all(sha(v)==typed_hash(v) for v in values)
    public=dict(snapshot=data['snapshot'],scope=data['scope_export'],wrapper=data['manual_exclusion'],assets=assets,
                stage='actual_frozen_core_generated_site',hash_cases=[dict(value=v,digest=sha(v)) for v in values])
    result,out=run(public,'core_generated');assert result['status']=='passed' and result['hash_cases']==9
    by_id={r['submission_id']:r for r in [*oracle['analysis'],*oracle['parents']]}
    checks=0
    for item in result['downloads']:
        if item['kind']=='quality':
            value=json.loads((out/item['file']).read_text())
            assert value['eligibility']['mode']==item['mode']
            if item['mode']=='on':
                assert {r['code']:r['count'] for r in value['result']['samples']}=={code:len(members) for code,members in oracle['retained_members'].items()}
                excluded={r['submission_id'] for r in oracle['accepted_manifest']['entries']}
                expected_intake={role:sum(r['role']==role and r['submission_id'] in excluded for r in oracle['records']) for role in ('student','parent')}
                assert {role:r['excluded'] for role,r in value['eligibility']['intake'].items()}==expected_intake
            continue
        if item['kind']=='snapshot':
            value=json.loads((out/item['file']).read_text())
            assert value['snapshot']==data['manual_exclusion']['on']['snapshot']
            continue
        with (out/item['file']).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        assert rows and all(r['eligibility_mode']=='on' and r['eligibility_revision']==data['manual_exclusion']['revision'] for r in rows)
        row=next(r for r in rows if r['Variable ID']=='PHQ_total')
        if item.get('custom'):
            assert 'p-value (raw)' not in row and 'Cohen dz (raw)' not in row
            continue
        if item['kind']=='statistics':
            for wave,code in [('T0','A'),('T1','C')]:
                values=[by_id[ids[0]]['PHQ_total'] for ids in oracle['retained_members'][code]]
                valid=[v for v in values if v is not None and math.isfinite(v)]
                assert int(row[wave+' sample N'])==len(values) and int(row[wave+' valid N'])==len(valid)
                assert math.isclose(float(row[wave+' mean (raw)']),sum(valid)/len(valid),rel_tol=1e-10,abs_tol=1e-10)
                checks+=3
            continue
        if item['sample']=='acbd':
            code='AC' if item['role']=='student' else 'BD';members=oracle['retained_members'][code]
            pairs=[(by_id[a]['PHQ_total'],by_id[b]['PHQ_total']) for a,b in members]
            pairs=[(a,b) for a,b in pairs if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
            a=[a for a,b in pairs];b=[b for a,b in pairs];delta=[y-x for x,y in pairs]
            assert int(row['Formal paired N'])==len(members) and int(row['Valid in both waves N'])==len(pairs)
            for label,want in [('T0 mean (raw, paired-valid)',sum(a)/len(a)),('T1 mean (raw, paired-valid)',sum(b)/len(b)),
                               ('T0 SD (raw, paired-valid)',stdev(a) if len(a)>1 else None),('T1 SD (raw, paired-valid)',stdev(b) if len(b)>1 else None)]:
                if want is None:assert row[label]==''
                else:assert math.isclose(float(row[label]),want,rel_tol=1e-10,abs_tol=1e-10)
                checks+=1
            if len(delta)>1 and stdev(delta)>0:
                from scipy.stats import ttest_1samp
                assert math.isclose(float(row['p-value (raw)']),float(ttest_1samp(delta,0).pvalue),rel_tol=1e-10,abs_tol=1e-10)
                assert math.isclose(float(row['Cohen dz (raw)']),(sum(delta)/len(delta))/stdev(delta),rel_tol=1e-10,abs_tol=1e-10)
                checks+=2
        if item['sample']=='independent_adult':
            excluded={r['submission_id'] for r in oracle['accepted_manifest']['entries']}
            expected=sum(r['panel_branch']=='same_adult' and r['t0'] not in excluded and r['t1'] not in excluded for r in oracle['panel']['pairs'])
            assert int(row['Formal paired N'])==expected
    (out/'RAW_MEMBER_CSV_PARITY.json').write_text(json.dumps(dict(status='passed',numeric_checks=checks,source='frozen invented original rows and retained native-member oracle'),indent=2)+'\n')
