"""Actual synthetic browser/filter/download integration; never reads research state."""
from contextlib import contextmanager
import json
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
from static_source_ui_fixture import ui_snapshot,expected_phq,SOURCE_CODES

PLAYWRIGHT_ROOT=Path(os.environ.get('SOURCE_UI_NODE_MODULES',Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))


class SyntheticSite(dict):
    def __repr__(self):
        return f"SyntheticSite(base={self['base']!r}, site={str(self['site'])!r}, credentials='<ephemeral runtime only>')"


@pytest.fixture(scope='module')
def browser_site(tmp_path_factory):
    folder=tmp_path_factory.mktemp('source-ui-site')
    snap=ui_snapshot();write_site(snap,folder)
    no_residual=folder/'no-residual-fixture.json';no_residual.write_text(json.dumps(ui_snapshot(include_residual=False,projections=[('abcd','student')]),ensure_ascii=False))
    node=shutil.which('node')
    if not node or not (PLAYWRIGHT_ROOT/'playwright').is_dir():pytest.skip('Existing Node/Playwright runtime required')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port not in (8501,8894)
    password=secrets.token_urlsafe(24)
    env={**os.environ,'PORT':str(port),'STUDY2_ACCESS_PASSWORD':password,'STUDY2_SESSION_SECRET':secrets.token_urlsafe(48),'VERCEL':'0'}
    log=(folder/'preview-runtime.log').open('w')
    process=subprocess.Popen([node,'preview.mjs'],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('Owned synthetic preview exited before readiness')
            try:
                with urllib.request.urlopen(base+'/login.html',timeout=1) as reply:
                    if reply.status==200:break
            except (OSError,urllib.error.URLError):time.sleep(.05)
        else:raise AssertionError('Owned loopback preview did not become ready')
        yield SyntheticSite(base=base,password=password,site=folder,node=node,no_residual=str(no_residual))
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
        (folder/'SERVICE_STOPPED.json').write_text(json.dumps({'port':port,'own_process_exited':process.poll() is not None,'production_ports_touched':False})+'\n')


def run_browser(site,kind):
    out=Path(os.environ.get('SOURCE_UI_EVIDENCE_DIR',site['site'].parent/'browser-evidence'))/kind
    assert not out.exists(), 'Preserve prior browser attempts; use a fresh evidence root'
    out.mkdir(parents=True)
    payload={k:site[k] for k in ('base','password')};payload.update(kind=kind,output=str(out),no_residual=site.get('no_residual',''),legacy_expected=site.get('legacy_expected',''))
    env={**os.environ,'NODE_PATH':str(PLAYWRIGHT_ROOT)}
    run=subprocess.run([site['node'],str(Path(__file__).with_name('static_source_ui_browser.cjs'))],
        input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=180)
    (out/'driver-stdout.log').write_text(run.stdout);(out/'driver-stderr.log').write_text(run.stderr)
    assert run.returncode==0, f'Browser integration failed; retained evidence at {out}'
    return json.loads((out/'RESULTS.json').read_text()),out


def test_sidebar_scroll_keyboard_and_focus_three_viewports(browser_site):
    result,_=run_browser(browser_site,'sidebar')
    assert result['status']=='passed'
    assert len(result['viewports'])==3
    for case in result['viewports']:
        assert case['scrollHeight']>case['clientHeight']
        assert case['scrollWidth']<=case['clientWidth']
        assert case['last_reachable_by_tab'] and case['focus_retained_after_change']
        assert abs(case['scroll_before_change']-case['scroll_after_change'])<=2


def test_source_controls_actual_downloads_reset_and_capabilities(browser_site):
    import csv
    import math
    from static_source_ui_fixture import expected_pairs,expected_overview_pairs
    result,out=run_browser(browser_site,'integration')
    assert result['status']=='passed'
    for entry in result['downloads']:
        with (out/entry['file']).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        assert rows
        meta=rows[0]
        assert meta['filter_source_codes']=='|'.join(entry['sources'])
        assert meta['source_all']==str(entry['sources']==['all']).lower()
        assert meta['source_format']=='study2_descriptive_sources_v1'
        assert meta['release_id']=='synthetic-source-ui'
        assert meta['source_filter_anchor']==entry['source_anchor']
        assert meta['grade_anchor']==entry['grade_anchor']
        assert meta['filter_grade_codes']=='|'.join(entry['grades'])
        assert meta['projection_version']=='study2_g12_v1'
        selected=None if entry['sources']==['all'] else entry['sources']
        grades=None if len(entry['grades'])==13 else entry['grades']
        if entry['kind']=='statistics':
            row=next(r for r in rows if r['Variable ID']=='PHQ_total')
            expected=expected_phq(entry['mode'],selected,grades=grades,mainstream=entry.get('mainstream',False))
            for wave in ['T0','T1']:
                for label,key in [('sample N','sample_n'),('valid N','valid_n'),('missing N','missing_n'),('mean (raw)','mean'),('sd (raw)','sd')]:
                    text=row[wave+' '+label];want=expected[wave][key]
                    if want is None:assert text==''
                    elif key.endswith('_n'):assert int(text)==want
                    else:assert math.isclose(float(text),want,rel_tol=1e-10,abs_tol=1e-10)
            if entry['mode']=='abcd' and len(entry['grades'])==13:
                paired=expected_overview_pairs(selected,mainstream=entry.get('mainstream',False))
                assert int(row['Formal paired N'])==paired['pairs_n']
                assert int(row['Both-valid paired N'])==paired['paired_valid_n']
                assert math.isclose(float(row['T0 mean (paired-valid)']),paired['t0_mean'],rel_tol=1e-10,abs_tol=1e-10)
                assert math.isclose(float(row['T1 mean (paired-valid)']),paired['t1_mean'],rel_tol=1e-10,abs_tol=1e-10)
                if entry['sources']!=['all']:assert 'p-value (raw)' not in row
            if len(entry['grades'])<13:
                assert 'p-value (raw)' not in row
                if entry['mode'] in {'abcd','ef','independent_all'}:assert 'Formal paired N' not in row
                else:
                    paired=expected_pairs(selected,grades=grades,mainstream=entry.get('mainstream',False))
                    assert int(row['Formal paired N'])==paired['pairs_n']
                    assert int(row['Both-valid paired N'])==paired['paired_valid_n']
                    assert math.isclose(float(row['T0 mean (paired-valid)']),paired['t0_mean'],rel_tol=1e-10,abs_tol=1e-10)
                    assert math.isclose(float(row['T1 mean (paired-valid)']),paired['t1_mean'],rel_tol=1e-10,abs_tol=1e-10)
        elif entry['kind']=='paired_changes':
            if entry.get('adult_phq_blocked'):
                assert not any(r['Variable ID'].startswith('PHQ_') for r in rows)
                assert any(r['Variable ID']=='SEC_total' for r in rows)
                continue
            row=next(r for r in rows if r['Variable ID']=='PHQ_total');expected=expected_pairs(selected,grades=grades,mainstream=entry.get('mainstream',False))
            for label,key in [('Formal paired N','pairs_n'),('Valid in both waves N','paired_valid_n'),('Only T0 valid N','only_t0_valid_n'),('Only T1 valid N','only_t1_valid_n'),('Both missing N','both_missing_n'),('T0 mean (raw, paired-valid)','t0_mean'),('T1 mean (raw, paired-valid)','t1_mean'),('Mean change (raw)','mean_change'),('Change SD (raw)','sd_change')]:
                if expected[key] is None:assert row[label]==''
                elif key.endswith('_n'):assert int(row[label])==expected[key]
                else:assert math.isclose(float(row[label]),expected[key],rel_tol=1e-10,abs_tol=1e-10)
            if entry['sources']!=['all']:assert 'p-value (raw)' not in row and 'Cohen dz (raw)' not in row
    assert result['empty_has_no_stale_outputs'] and result['unsupported_has_no_stale_outputs']
    assert result['reset_restores_unrestricted'] and result['all_retains_residual']
    assert result['legacy_all_and_single_work'] and result['legacy_union_unavailable']


@pytest.fixture(scope='module')
def legacy_browser_site(tmp_path_factory):
    """Only the new bounded pre-detail fixture, not the broad source/UI suite."""
    from static_source_ui_fixture import legacy_summary_snapshot,expected_legacy_summary
    folder=tmp_path_factory.mktemp('legacy-summary-ui-site')
    snap=legacy_summary_snapshot();write_site(snap,folder)
    expected={role:{source:expected_legacy_summary(role,source) for source in ['all','qualtrics']} for role in ['student','parent']}
    expected_path=folder/'legacy-original-expected.json';expected_path.write_text(json.dumps(expected,indent=2)+'\n')
    node=shutil.which('node')
    if not node or not (PLAYWRIGHT_ROOT/'playwright').is_dir():pytest.skip('Existing Node/Playwright runtime required')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port not in (8501,8894,8901)
    password=secrets.token_urlsafe(24)
    env={**os.environ,'PORT':str(port),'STUDY2_ACCESS_PASSWORD':password,'STUDY2_SESSION_SECRET':secrets.token_urlsafe(48),'VERCEL':'0'}
    log=(folder/'preview-runtime.log').open('w')
    process=subprocess.Popen([node,'preview.mjs'],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('Owned legacy preview exited before readiness')
            try:
                with urllib.request.urlopen(base+'/login.html',timeout=1) as reply:
                    if reply.status==200:break
            except (OSError,urllib.error.URLError):time.sleep(.05)
        else:raise AssertionError('Owned legacy loopback preview did not become ready')
        yield SyntheticSite(base=base,password=password,site=folder,node=node,legacy_expected=str(expected_path))
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
        (folder/'SERVICE_STOPPED.json').write_text(json.dumps({'port':port,'own_process_exited':process.poll() is not None,'protected_ports_touched':False})+'\n')


def test_legacy_predetail_all_single_summaries_and_inference_browser(legacy_browser_site):
    import csv
    import math
    from static_source_ui_fixture import expected_legacy_summary
    result,out=run_browser(legacy_browser_site,'legacy_summary')
    assert result['status']=='passed'
    assert len(result['legacy_cases'])==4 and len(result['downloads'])==8
    for case in result['legacy_cases']:
        assert case['stored_summary_finite'] and case['overview_paired_headers_visible']
        assert case['paired_download_available'] and case['paired_summary_visible']
        assert case['new_detail_not_fabricated']
    for item in result['downloads']:
        with (out/item['file']).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        expected=expected_legacy_summary(item['role'],item['source'])
        metric='PHQ_total' if item['role']=='student' else 'SEC_total'
        row=next(r for r in rows if r['Variable ID']==metric);target=expected[metric]
        assert row['source_format']=='not_provided' and row['grade_format']=='not_provided'
        assert row['filter_source_codes']==('all' if item['source']=='all' else 'qualtrics')
        assert row['source_all']==str(item['source']=='all').lower()
        assert row['role']==item['role'] and row['mode']=='acbd'
        assert int(row['Formal paired N'])==target['pairs_n']
        valid='Both-valid paired N' if item['kind']=='statistics' else 'Valid in both waves N'
        assert int(row[valid])==target['paired_valid_n']
        mean='Mean paired change (raw)' if item['kind']=='statistics' else 'Mean change (raw)'
        for label,key in [(mean,'mean_change'),('Change SD (raw)','sd_change'),('p-value (raw)','p_value'),('Cohen dz (raw)','cohen_dz')]:
            assert math.isfinite(float(row[label])) and math.isclose(float(row[label]),target[key],rel_tol=1e-12,abs_tol=1e-12)
        for label in ['Only T0 valid N','Only T1 valid N','Both missing N']:
            assert row[label]=='', 'Absent newer detail must not become zero'
        pair_means=['T0 mean (paired-valid)','T1 mean (paired-valid)'] if item['kind']=='statistics' else ['T0 mean (raw, paired-valid)','T1 mean (raw, paired-valid)']
        assert all(row[k]=='' for k in pair_means)
        status='Paired availability status' if item['kind']=='statistics' else 'Availability status'
        assert row[status]==('not_provided' if item['kind']=='statistics' else ''), 'Existing display status marks missing detail unavailable'
        if item['role']=='parent':
            if item['kind']=='paired_changes':assert not any(r['Variable ID'].startswith('PHQ_') for r in rows)
            else:
                phq=next(r for r in rows if r['Variable ID']=='PHQ_total')
                assert phq['Formal paired N']==phq['p-value (raw)']==phq['Cohen dz (raw)']==''
    assert result['unsupported_legacy_union_unavailable'] and result['adult_negative_gate_preserved']
