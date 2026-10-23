"""Complete-pair wave SD, checked against independent raw-pair sample SD."""
from copy import deepcopy
import json
import math
import statistics as raw_statistics
import subprocess

import pytest

from study2.descriptive_spec import variables
from study2.static_export import pack_snapshot
from study2.static_grade import CODES as GRADES, JS_SOURCE as GRADE_JS
from study2.static_sources import CODES, JS_SOURCE as SOURCE_JS
from test_static_sources import context, invent, payload


@pytest.fixture(autouse=True)
def small_catalogue(monkeypatch):
    keys = {'PHQ_total', 'FQOL_total', 'SEC_total', 'phq_band'}
    def selected(role, section=None):
        return [v for v in variables(role, section) if v.key in keys]
    for module in ['study2.descriptives', 'study2.static_grade', 'study2.static_sources',
                   'study2.descriptive_exploration']:
        monkeypatch.setattr(module+'.variables', selected)


def example(role='student', mode='acbd'):
    frame = invent(mode, role).iloc[:16].copy()
    a = [1., 3., 11., 5., None, 7., 2., 8.]
    b = [2., 8., None, None, 6., 9., 2., 10.]
    fq0 = [2., 3., 1., 5., 4., None, 1., 5.]
    fq1 = [None, 4., 2., 4., 3., 1., 2., 3.]
    for i in range(8):
        take = frame.child_id.eq('person-'+str(i))
        frame.loc[take, 'anchor_source_type'] = 'qualtrics' if i in (0, 2, 4, 5, 7) else 'paperform'
        frame.loc[take, '_grade'] = ['P3', 'P4', 'Unknown'][i % 3]
        frame.loc[take & frame.wave.eq('T0'), 'PHQ_total'] = a[i]
        frame.loc[take & frame.wave.eq('T1'), 'PHQ_total'] = b[i]
        frame.loc[take & frame.wave.eq('T0'), 'FQOL_total'] = fq0[i]
        frame.loc[take & frame.wave.eq('T1'), 'FQOL_total'] = fq1[i]
    return frame


def run_client(snap, requests, packed=True, operation='source'):
    driver = GRADE_JS+SOURCE_JS+r'''
const x=JSON.parse(require('fs').readFileSync(0,'utf8')),before=JSON.stringify(x);
const result=x.requests.map(c=>{
 if(x.operation==='grade'){const decode=t=>Array.isArray(t)?t:t.rows.map(r=>Object.fromEntries(t.columns.map((k,i)=>[k,r[i]])));
  const v={...x.snapshot.views[0],statistics:decode(x.snapshot.views[0].statistics),changes:decode(x.snapshot.views[0].changes)};
  return {old:Grade.pool(x.snapshot,v,c.grades),view:Grade.pool(x.snapshot,v,c.grades,{wave_sd:true})};}
 return {old:Source.choose(x.snapshot,c),view:Source.withWaveSD(x.snapshot,c)};
});
if(before!==JSON.stringify(x))throw Error('Input mutated');
for(const r of result)for(const row of r.view.changes)for(const k of ['t0_sd','t1_sd'])if(k in row&&row[k]!==null&&!Number.isFinite(row[k]))throw Error('Nonfinite wave SD');
console.log(JSON.stringify(result));
'''
    run = subprocess.run(['node', '-e', driver], input=json.dumps(dict(
        snapshot=pack_snapshot(snap) if packed else snap, requests=requests, operation=operation)),
        text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


def original_fields(view):
    return {**view, 'changes': [{k: v for k, v in r.items() if k not in ('t0_sd', 't1_sd')}
                               for r in view['changes']]}


def selected_pairs(frame, request, variable, group):
    selected = frame
    if request['sources'] != ['all']:
        selected = selected.loc[selected.anchor_source_type.isin(request['sources'])]
    if request['mainstream']:
        selected = selected.loc[selected.anchor_mainstream]
    selected = selected.loc[selected._grade.isin(request['grades'])]
    if group.startswith('male'): selected = selected.loc[selected.anchor_gender.eq('0')]
    if group.endswith('primary'): selected = selected.loc[selected.anchor_school_stage.eq('primary')]
    values = {}
    for row in selected.to_dict('records'):
        value = row.get(variable)
        if row.get(variable+'__status', 'valid') != 'valid': value = None
        if value is not None and not math.isfinite(value): value = None
        values.setdefault(row['child_id'], {})[row['wave']] = value
    pairs = [(r.get('T0'), r.get('T1')) for r in values.values()
             if r.get('T0') is not None and r.get('T1') is not None]
    return pairs


def assert_wave_sd(result, frame, request):
    assert original_fields(result['view']) == result['old']
    for row in result['view']['changes']:
        pairs = selected_pairs(frame, request, row['variable_id'], row['group'])
        assert row['paired_valid_n'] == len(pairs)
        for wave, position in [('t0', 0), ('t1', 1)]:
            assert wave+'_sd' in row
            expected = raw_statistics.stdev([r[position] for r in pairs]) if len(pairs) > 1 else None
            assert row[wave+'_sd'] == pytest.approx(expected, rel=1e-12, abs=1e-12) if expected is not None else row[wave+'_sd'] is None


@pytest.mark.parametrize('role', ['student', 'parent'])
@pytest.mark.parametrize('packed', [False, True])
def test_all_single_unions_grades_and_named_all_use_same_raw_complete_pairs(role, packed):
    frame = example(role); snap = payload(frame, 'acbd', role)
    requests = [context(s, 'acbd', role, mainstream=m, grades=g)
                for s in [['all'], ['qualtrics'], ['paperform'], ['paperform', 'qualtrics'], list(CODES)]
                for g in [GRADES, ['P3', 'Unknown']] for m in (False, True)]
    for request, result in zip(requests, run_client(snap, requests, packed)):
        assert_wave_sd(result, frame, request)
        if result['old'].get('grade_custom'):
            assert all(r['p_value'] is None and r['cohen_dz'] is None for r in result['view']['changes'])
        if result['old']['source_status'] == 'pooled':
            assert not result['view']['source_capabilities']['inference']
    explicit, named = run_client(snap, [context(['all'], 'acbd', role), context(list(CODES), 'acbd', role)], packed)
    assert explicit['view']['changes'] == named['view']['changes']


def test_complete_pair_sd_is_not_wave_valid_sd_and_missingness_is_metric_specific():
    frame = example(); snap = payload(frame, 'acbd')
    result = run_client(snap, [context(['all'], 'acbd')])[0]
    assert_wave_sd(result, frame, context(['all'], 'acbd'))
    phq = next(r for r in result['view']['changes'] if r['variable_id'] == 'PHQ_total' and r['group'] == 'all')
    fq = next(r for r in result['view']['changes'] if r['variable_id'] == 'FQOL_total' and r['group'] == 'all')
    wave = next(r for r in result['view']['statistics'] if r['variable_id'] == 'PHQ_total' and r['group'] == 'all' and r['wave'] == 'T0')
    assert phq['paired_valid_n'] == 5 and fq['paired_valid_n'] == 6
    assert phq['t0_sd'] != pytest.approx(wave['sd'])
    assert phq['p_value'] == result['old']['changes'][0]['p_value']


def test_between_source_and_grade_variance_is_included():
    frame = example().iloc[:8].copy()
    for i, (a, b) in enumerate(zip([1., 3., 9., 11.], [2., 5., 10., 12.])):
        take = frame.child_id.eq('person-'+str(i))
        frame.loc[take, 'anchor_source_type'] = 'qualtrics' if i < 2 else 'paperform'
        frame.loc[take, '_grade'] = 'P3' if i < 2 else 'P4'
        frame.loc[take & frame.wave.eq('T0'), 'PHQ_total'] = a
        frame.loc[take & frame.wave.eq('T1'), 'PHQ_total'] = b
    snap = payload(frame, 'acbd'); req = context(['paperform', 'qualtrics'], 'acbd', grades=['P3', 'P4'])
    result = run_client(snap, [req])[0]; assert_wave_sd(result, frame, req)
    row = next(r for r in result['view']['changes'] if r['variable_id'] == 'PHQ_total' and r['group'] == 'all')
    assert row['t0_sd'] == pytest.approx(math.sqrt(68/3))
    assert row['t0_sd'] != pytest.approx(math.sqrt(2))


@pytest.mark.parametrize('n', [0, 1, 2])
def test_zero_one_pair_and_legitimate_zero_sample_sd(n):
    frame = example().iloc[:2*n].copy(); frame.attrs['mode'] = 'acbd'
    frame['PHQ_total'] = 2.
    snap = payload(frame, 'acbd', groups=('all',))
    result = run_client(snap, [context(['all'], 'acbd')])[0]
    assert_wave_sd(result, frame, context(['all'], 'acbd'))
    row = next(r for r in result['view']['changes'] if r['variable_id'] == 'PHQ_total')
    assert row['t0_sd'] == row['t1_sd'] == (0. if n > 1 else None)


@pytest.mark.parametrize('defect', ['missing', 'unavailable', 'release', 'anchor', 'negative_m2', 'count', 'mean_roundoff_exceeded', 'suppressed', 'detail'])
def test_invalid_optional_evidence_only_withholds_new_sd_and_keeps_old_summary(defect):
    snap = payload(example(), 'acbd', groups=('all',)); view = snap['views'][0]
    phq = next(r for r in view['changes'] if r['variable_id'] == 'PHQ_total')
    if defect == 'missing':
        snap.pop('grade'); view.pop('grade')
    elif defect == 'unavailable': view['grade'] = dict(status='unavailable', code='published_grade_fields_unavailable')
    elif defect == 'release': snap['grade']['release_id'] = 'wrong'
    elif defect == 'anchor': view['grade']['anchor'] = 'parent_report_T0'
    elif defect == 'negative_m2': next(c for c in view['grade']['cells'] if c['pairs'])['pairs'][0][7] = -1.
    elif defect == 'count': phq['paired_valid_n'] += 1
    elif defect == 'mean_roundoff_exceeded': phq['t0_mean'] += 1e-10
    elif defect == 'suppressed': phq['suppressed'] = True
    else:
        phq['pair_detail_status'] = 'not_provided'; phq['t0_mean'] = phq['t1_mean'] = None
    result = run_client(snap, [context(['all'], 'acbd')])[0]
    assert result['view']['source_status'] == 'all'
    assert original_fields(result['view']) == result['old']
    row = next(r for r in result['view']['changes'] if r['variable_id'] == 'PHQ_total')
    assert row['t0_sd'] is None and row['t1_sd'] is None


@pytest.mark.parametrize('mode', ['efmatched', 'independent_child'])
def test_parent_child_identity_does_not_create_phq_sd(mode):
    frame = example('parent', mode); snap = payload(frame, mode, 'parent')
    if mode.startswith('independent_'):
        for v in snap['views']: v['grade']['anchor'] = 'parent_report_T0'
    req = context(['all'], mode, 'parent')
    result = run_client(snap, [req])[0]
    assert_wave_sd(result, frame, req)
    assert not any(r['variable_id'].startswith('PHQ_') for r in result['view']['changes'])


def test_legacy_without_new_details_keeps_stored_pvalues_but_sd_unavailable():
    snap = payload(example(), 'acbd', groups=('all',)); snap.pop('grade'); snap.pop('source_selection')
    for view in snap['views']:
        view.pop('grade')
        for row in view['changes']:
            for key in ['pair_detail_status', 'only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n', 't0_mean', 't1_mean']:
                row.pop(key, None)
    for result in run_client(snap, [context(['all'], 'acbd'), context(['qualtrics'], 'acbd')]):
        assert original_fields(result['view']) == result['old']
        assert result['view']['source_capabilities']['paired_summaries']
        assert all(r['t0_sd'] is None and r['t1_sd'] is None for r in result['view']['changes'])


def test_grade_direct_opt_in_and_empty_source_keep_existing_behavior():
    frame = example(); snap = payload(frame, 'acbd', groups=('all',))
    req = context(['all'], 'acbd', grades=['P3', 'Unknown'])
    result = run_client(snap, [req], operation='grade')[0]
    assert_wave_sd(result, frame, req)
    assert all('t0_sd' not in r and 't1_sd' not in r for r in result['old']['changes'])
    empty = run_client(snap, [context([], 'acbd')])[0]
    assert empty['view'] == empty['old'] and empty['view']['source_status'] == 'empty'


def test_overflowing_optional_pair_variance_is_unavailable_not_infinite():
    snap = payload(example(), 'acbd', groups=('all',))
    cube = snap['views'][0]['grade']
    i = next(i for i, m in enumerate(cube['pairs_schema']) if m['variable_id'] == 'PHQ_total')
    for cell in cube['cells']:
        if cell['pairs'] and cell['pairs'][i][1] > 1: cell['pairs'][i][7] = 1e308
    result = run_client(snap, [context(['all'], 'acbd')], operation='grade')[0]
    assert original_fields(result['view']) == result['old']
    phq = next(r for r in result['view']['changes'] if r['variable_id'] == 'PHQ_total')
    assert phq['t0_sd'] is None and phq['t1_sd'] is None
