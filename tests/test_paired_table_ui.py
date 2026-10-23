"""Actual authenticated synthetic DOM and audit downloads for the AC/BD layout."""
import csv
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from study2.static_export import write_site
from paired_table_ui_fixture import snapshot_bundle
from test_static_source_ui import PLAYWRIGHT_ROOT


@pytest.fixture(scope='module')
def paired_table_evidence(tmp_path_factory):
    folder=tmp_path_factory.mktemp('paired-table-ui')
    variants,cases=snapshot_bundle()
    site=folder/'site';write_site(variants['normal'],site)
    variant_paths={}
    for key,value in variants.items():
        target=folder/(key+'.json');target.write_text(json.dumps(value,ensure_ascii=False))
        variant_paths[key]=str(target)
    cases_path=folder/'cases.json';cases_path.write_text(json.dumps(cases,ensure_ascii=False,indent=2))
    # Baseline renderer with the same adapter dependency and same snapshot bytes
    # isolates the presentation delta when comparing every old CSV value.
    baseline_path=Path(os.environ['PAIRED_TABLE_BASELINE_ASSET'])
    spec=importlib.util.spec_from_file_location('study2._paired_table_baseline',baseline_path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    baseline_app=folder/'baseline-app.js';baseline_app.write_text(module.APP_JS)
    node=shutil.which('node')
    if not node or not (PLAYWRIGHT_ROOT/'playwright').is_dir():pytest.skip('Existing Node/Playwright runtime required')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port not in (8501,8894,8901,8902,8903)
    password=secrets.token_urlsafe(24)
    env={**os.environ,'PORT':str(port),'STUDY2_ACCESS_PASSWORD':password,
         'STUDY2_SESSION_SECRET':secrets.token_urlsafe(48),'VERCEL':'0'}
    out=Path(os.environ['PAIRED_TABLE_EVIDENCE_DIR'])
    assert not out.exists(),'Preserve each prior attempt in a fresh evidence root'
    out.mkdir(parents=True)
    log=(out/'preview-runtime.log').open('w')
    process=subprocess.Popen([node,'preview.mjs'],cwd=site,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        base=f'http://127.0.0.1:{port}'
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('Owned synthetic preview exited before readiness')
            try:
                with urllib.request.urlopen(base+'/login.html',timeout=1) as reply:
                    if reply.status==200:break
            except (OSError,urllib.error.URLError):time.sleep(.05)
        else:raise AssertionError('Owned loopback preview did not become ready')
        payload=dict(base=base,password=password,output=str(out),cases=str(cases_path),
                     variants=variant_paths,baseline_app=str(baseline_app))
        run=subprocess.run([node,str(Path(__file__).with_name('paired_table_ui_browser.cjs'))],
                           input=json.dumps(payload),text=True,capture_output=True,
                           env={**os.environ,'NODE_PATH':str(PLAYWRIGHT_ROOT)},timeout=180)
        (out/'driver-stdout.log').write_text(run.stdout);(out/'driver-stderr.log').write_text(run.stderr)
        assert run.returncode==0,f'Browser checks failed; retained evidence at {out}'
        result=json.loads((out/'RESULTS.json').read_text())
        yield result,out,{c['name']:c for c in cases}
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
        (out/'SERVICE_STOPPED.json').write_text(json.dumps(dict(port=port,
            own_process_exited=process.poll() is not None,protected_ports_touched=False))+'\n')


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);rows=list(reader)
        return reader.fieldnames,rows


def fixed(value,places=2):
    """Match the existing Number.toFixed display, including exact half ties."""
    return str(Decimal.from_float(float(value)).quantize(
        Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP))


def test_exact_six_columns_full_audit_csv_and_unavailable_states(paired_table_evidence):
    result,out,cases=paired_table_evidence
    assert result['status']=='passed' and len(result['cases'])==32
    baseline={r['name']:r for r in result['cases'] if r['phase']=='baseline'}
    compact_count=0;families=set()
    for run in [r for r in result['cases'] if r['phase']=='candidate']:
        case=cases[run['name']]
        old_headers,old=read_csv(out/baseline[run['name']]['file'])
        headers,rows=read_csv(out/run['file'])
        assert rows and len(rows)==len(old),'Audit parity requires actual nonempty rows'
        additions=['T0 SD (raw, paired-valid)','T1 SD (raw, paired-valid)'] if run['mode']=='acbd' else []
        assert headers==old_headers+additions,'Every old detailed field and its order must remain'
        assert [{k:r[k] for k in old_headers} for r in rows]==old,'All old values/metadata retain exact precision'
        assert run['summary']==baseline[run['name']]['summary']
        if run['mode']!='acbd':continue
        compact_count+=1
        expected_headers=['Metric','Valid in both waves, N','T0 Mean (SD)','T1 Mean (SD)','p-value',"Cohen's d"]
        inference=run['sources'] in (['all'],['qualtrics'],['paperform']) and len(run['grades'])==13
        for table in run['tables']:
            families.add(table['family'])
            assert table['headers']==expected_headers
            for cells in table['rows']:
                assert len(cells)==6
                if not inference:assert cells[4:]==['Unavailable','Unavailable']
                else:
                    raw=next(r for r in rows if r['Metric']==cells[0])
                    p=raw['p-value (raw)'];dz=raw['Cohen dz (raw)']
                    assert cells[4]==('Unavailable' if p=='' else '<0.001' if float(p)<.001 else fixed(p,3))
                    assert cells[5]==('Unavailable' if dz=='' else fixed(dz))
        if run['name']=='all':
            assert run['summary']==['11','11']
            phq=next(r for r in rows if r['Variable ID']=='PHQ_total')
            assert phq['Valid in both waves N']=='9'
        if run['variant']=='legacy':
            assert all(r['T0 SD (raw, paired-valid)']==r['T1 SD (raw, paired-valid)']=='' for r in rows)
            for table in run['tables']:
                for cells in table['rows']:assert cells[2:4]==['Unavailable','Unavailable']
        if run['variant']=='mean_only':
            by_label={cells[0]:cells for table in run['tables'] for cells in table['rows']}
            for row in rows:
                want=case['metrics'][row['Variable ID']];cells=by_label[want['label']]
                assert row['T0 SD (raw, paired-valid)']==row['T1 SD (raw, paired-valid)']==''
                for wave,index in [('t0',2),('t1',3)]:
                    mean=want[wave+'_mean']
                    assert cells[index]==('Unavailable' if mean is None else fixed(mean)+' (SD unavailable)')
        if run['name']=='suppressed':
            row=next(c for t in run['tables'] for c in t['rows'] if c[0]=='PHQ_total')
            assert row[2:4]==['Suppressed (small sample)']*2 and row[1]!='0'
            raw=next(r for r in rows if r['Variable ID']=='PHQ_total')
            assert raw['T0 SD (raw, paired-valid)']==raw['T1 SD (raw, paired-valid)']==''
        if run['name']=='legacy-parent':assert not any(r['Variable ID'].startswith('PHQ_') for r in rows)
    assert compact_count==15 and len(families)==4
    assert (out/'six-column-table.png').is_file()
    for run in result['cases']:
        if run['name']=='union-grades':assert run['reset']
    (out/'AUDIT_PARITY.json').write_text(json.dumps(dict(status='passed',
        actual_csvs=32,candidate_contexts=16,compact_contexts=compact_count,
        all_old_fields_and_values_unchanged=True),indent=2)+'\n')


def test_complete_pair_wave_sd_matches_raw_synthetic_values(paired_table_evidence):
    if os.environ.get('PAIRED_TABLE_FROZEN_SD')!='1':
        pytest.skip('Pending leader-supplied frozen Worker1 wave-SD dependency')
    result,out,cases=paired_table_evidence
    checks=0
    for run in [r for r in result['cases'] if r['phase']=='candidate' and r['mode']=='acbd' and r['variant']=='normal']:
        case=cases[run['name']];_,rows=read_csv(out/run['file'])
        by_label={cells[0]:cells for table in run['tables'] for cells in table['rows']}
        for row in rows:
            want=case['metrics'][row['Variable ID']];cells=by_label[want['label']]
            assert int(row['Valid in both waves N'])==want['paired_valid_n']
            for wave,index in [('t0',2),('t1',3)]:
                mean,sd=want[wave+'_mean'],want[wave+'_sd']
                text=row[wave.upper()+' SD (raw, paired-valid)']
                if sd is None:assert text==''
                else:assert math.isclose(float(text),sd,rel_tol=1e-10,abs_tol=1e-10)
                display='Unavailable' if mean is None else fixed(mean)+' ('+('SD unavailable' if sd is None else fixed(sd))+')'
                assert cells[index]==display
                checks+=2
    assert checks>200
    (out/'RAW_SD_PARITY.json').write_text(json.dumps(dict(status='passed',checks=checks,
        source='independent synthetic raw tuples',sample_sd_denominator='n-1'),indent=2)+'\n')
