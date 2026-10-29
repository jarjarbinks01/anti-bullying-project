"""Synthetic semester filters, complete-domain roles and real JS query checks."""
from copy import deepcopy
import json
import subprocess

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.static_grade import CODES as GRADES
from study2.static_semester import FORMAT, JS, build_cube, validate_cube
from test_static_period import response

REV = 'a' * 64


def sample(sid, observed, wave='T0', **extra):
    return response(sid, observed, wave, **extra)


def make_cube(rows, role='student', mode='abcd', eligibility='on'):
    return build_cube(pd.DataFrame(rows), role, mode=mode, grade_anchor='student_wave',
        grouping_anchor='wave_response', source_filter_anchor='wave_response', release_id='synthetic-release',
        eligibility=eligibility, eligibility_revision=REV if eligibility == 'on' else None, active_on_revision=REV)


def choice(**extra):
    result = dict(academic_years=[2025], semesters=['S1', 'S2'], waves=['T0', 'T1'],
        group='all', grades=list(GRADES), sources=['all'], mainstream=False, include_batch=False,
        metric_id='PHQ_total', threshold='recurrent', ci='none')
    result.update({'from': '2025-09-01', 'to': '2026-08-31'})
    result.update(extra)
    return result


def client(cube, choices, *, validate_only=False):
    driver = JS + r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8')),before=JSON.stringify(input);
const attempt=fn=>{try{return {value:fn()};}catch(e){return {error:e.message};}};
const result=input.validate_only?attempt(()=>Study2Semester.validate(input.cube)):
  input.choices.map(x=>attempt(()=>Study2Semester.query(input.cube,x)));
if(before!==JSON.stringify(input))throw Error('mutated input');
console.log(JSON.stringify(result));
'''
    run = subprocess.run(['node', '-e', driver], input=json.dumps({'cube': cube, 'choices': choices, 'validate_only': validate_only}),
                         text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


def output(cube, selection):
    result = client(cube, [selection])[0]
    assert 'error' not in result, result
    return result['value']


def test_full_scale_catalogue_and_complete_joint_roles_with_threshold_comparison():
    a = sample('a', '2025-09-01T00:00:00Z', PHQ_total=1., TBP_prevalence1=1, TBP_prevalence2=1,
               TBV_prevalence1=0, TBV_prevalence2=0)
    b = sample('b', '2025-09-01T00:00:00Z', PHQ_total=3., TBP_prevalence1=1, TBP_prevalence2=0,
               TBV_prevalence1=1, TBV_prevalence2=0)
    c = sample('c', '2025-09-01T00:00:00Z', PHQ_total=6., TBP_prevalence1=None, TBP_prevalence2=None,
               TBV_prevalence1=1, TBV_prevalence2=1)
    value = make_cube([a,b,c]); assert value['format'] == FORMAT
    assert len(value['metrics']) == 27 and len(value['joint_metrics']) == 4
    result = output(value, choice(semesters=['S1'], waves=['T0'], metric_id='bullying_roles_traditional', threshold='both'))
    rows = result['rows'];assert len(rows) == 8
    by = {(r['threshold'], r['category_code']): r for r in rows}
    assert {key: by['any', key]['numerator'] for key in ('perpetrator_only','victim_only','both','neither')} == {
        'perpetrator_only':1,'victim_only':0,'both':1,'neither':0}
    assert {key: by['recurrent', key]['numerator'] for key in ('perpetrator_only','victim_only','both','neither')} == {
        'perpetrator_only':1,'victim_only':0,'both':0,'neither':1}
    assert all(r['sample_n']==3 and r['valid_n']==2 and r['missing_n']==1 and r['denominator']==2 for r in rows)
    assert all(r['ci_low'] is None for r in rows)
    bands = output(value, choice(semesters=['S1'], waves=['T0'], metric_id='phq_band'))['rows']
    assert [r['numerator'] for r in bands] == [1,1,1,0] and all(r['denominator']==3 for r in bands)
    assert next(m for m in value['metrics'] if m['variable_id']=='PHQ_anxiety')['available'] is False
    missing = output(value, choice(semesters=['S1'], waves=['T0'], metric_id='FQOL_total'))['rows'][0]
    assert missing['status']=='no_valid_scores' and missing['sample_n']==3 and missing['mean'] is None
    absent = output(value, choice(semesters=['S1'], waves=['T0'], metric_id='PHQ_anxiety'))['rows'][0]
    assert absent['status']=='metric_unavailable' and absent['valid_n'] is None


def test_hk_semester_boundaries_nonconsecutive_years_and_clipping():
    rows = [sample('s1start','2025-08-31T16:00:00Z',PHQ_total=1.),
            sample('s1end','2026-01-31T15:59:59Z',PHQ_total=3.),
            sample('s2start','2026-01-31T16:00:00Z','T1',PHQ_total=5.),
            sample('s2end','2026-08-31T15:59:59Z','T1',PHQ_total=7.),
            sample('next','2026-08-31T16:00:00Z',PHQ_total=9.),
            sample('later','2027-09-01T00:00:00Z',PHQ_total=11.)]
    value=make_cube(rows)
    r=output(value,choice(academic_years=[2027,2025,2025],semesters=['S2','S1','S1'],waves=['T1','T0','T0'],
                          **{'from':'2025-09-01','to':'2028-08-31'}))
    assert r['selection']['academic_years']==[2025,2027] and r['selection']['semesters']==['S1','S2'] and r['selection']['waves']==['T0','T1']
    points={(x['academic_year_start'],x['semester'],x['wave']):x for x in r['rows']}
    assert points[2025,'S1','T0']['sample_n']==2 and points[2025,'S1','T0']['mean']==2
    assert points[2025,'S2','T1']['sample_n']==2 and points[2025,'S2','T1']['mean']==6
    assert points[2027,'S1','T0']['sample_n']==1 and points[2027,'S1','T0']['mean']==11
    assert sum(x['sample_n'] or 0 for x in r['rows'])==5  # middle year was not selected
    clipped=output(value,choice(semesters=['S1','S2'],waves=['T0'],**{'from':'2025-10-01','to':'2026-01-31'}))['rows']
    assert clipped[0]['partial_period'] and clipped[0]['sample_n']==1
    assert clipped[1]['status']=='outside_date_range' and clipped[1]['sample_n'] is None


def test_date_provenance_filter_school_source_grade_and_zero_is_not_missing():
    rows=[sample('a','2025-09-03T01:00:00Z',TBV_prevalence2=0),
          sample('batch','2025-09-03T01:00:00Z',time_confidence='accepted_creation_time',date_basis='batch_assigned_creation',TBV_prevalence2=1),
          sample('manual','2025-09-03T01:00:00Z',time_confidence='manual_verified',date_basis='batch_assigned_creation',TBV_prevalence2=0),
          sample('other','2025-09-03T01:00:00Z',anchor_mainstream=False,anchor_source_type='paperform',_grade='P4',TBV_prevalence2=1),
          sample('invalid','not a date',TBV_prevalence2=1)]
    value=make_cube(rows);s=choice(semesters=['S1'],waves=['T0'],metric_id='TBV_prevalence2',
        grades=['P3','P3'],sources=['qualtrics','qualtrics'],mainstream=True,ci='wilson_95_unclustered')
    result=output(value,s);r=result['rows'][0]
    assert result['selection']['grades']==['P3'] and result['selection']['sources']==['qualtrics']
    assert (r['sample_n'],r['valid_n'],r['numerator'],r['denominator'],r['proportion'])==(2,2,0,2,0)
    assert r['ci_low']==pytest.approx(0,abs=1e-15) and 0<r['ci_high']<1
    assert {x['date_quality']:x['input_n'] for x in result['date_quality']}['invalid_date']==1
    assert {x['date_quality']:x['included_n'] for x in result['date_quality']}['manual_verified']==1
    with_batch=output(value,{**s,'include_batch':True})['rows'][0]
    assert (with_batch['sample_n'],with_batch['numerator'])==(3,1)
    no_sources=output(value,{**s,'sources':[]})['rows'][0]
    assert no_sources['sample_n']==0 and no_sources['status']=='no_responses' and no_sources['proportion'] is None
    empty=output(value,{**s,'waves':[]});assert empty['status']=='empty_selection' and empty['rows']==[]
    bad=client(value,[{**s,'grades':['invalid']}])[0];assert 'selection_grades' in bad['error']
    ambiguous=client(value,[{**s,'sources':['all','qualtrics']}])[0];assert 'selection_sources' in ambiguous['error']


def test_mean_pooling_and_independent_wave_outputs():
    value=make_cube([sample('a','2025-09-01T00:00:00Z',PHQ_total=1.),
                     sample('b','2025-10-01T00:00:00Z',PHQ_total=3.),
                     sample('c','2025-10-01T00:00:00Z',PHQ_total=5.),
                     sample('d','2025-10-01T00:00:00Z','T1',PHQ_total=10.)])
    rows=output(value,choice(semesters=['S1']))['rows']; by={r['wave']:r for r in rows}
    assert by['T0']['sample_n']==3 and by['T0']['mean']==pytest.approx(3) and by['T0']['sd']==pytest.approx(2)
    assert by['T1']['sample_n']==1 and by['T1']['mean']==10 and by['T1']['sd'] is None


def test_python_and_js_reject_tampering_and_private_data_never_enters_cube():
    r=sample('synthetic', '2025-09-01T00:00:00Z', contact='sensitive synthetic', school='private school')
    value=make_cube([r]);encoded=json.dumps(value)
    assert all(x not in encoded for x in ('submission_id','child_id','version_id','sensitive synthetic','private school','observed_at'))
    for change in ('revision','joint','denominator','extra_field'):
        bad=deepcopy(value)
        if change=='revision':bad['eligibility_revision']='b'*64
        if change=='joint':bad['cells'][0][10][0][1]+=1
        if change=='denominator':
            index=next(i for i,m in enumerate(bad['metrics']) if m['variable_id']=='PHQ_total')
            bad['cells'][0][9][index][0]=5
        if change=='extra_field':bad['school']='not allowed'
        with pytest.raises(PipelineError):validate_cube(bad)
        assert 'error' in client(bad,[],validate_only=True)


@pytest.mark.parametrize('joint_index,perp_key,victim_key,metric,threshold', [
    (0,'TBP_prevalence1','TBV_prevalence1','bullying_roles_traditional','any'),
    (1,'TBP_prevalence2','TBV_prevalence2','bullying_roles_traditional','recurrent'),
    (2,'CBP_prevalence1','CBV_prevalence1','bullying_roles_cyber','any'),
    (3,'CBP_prevalence2','CBV_prevalence2','bullying_roles_cyber','recurrent'),
])
@pytest.mark.parametrize('perp,victim,joint', [
    (None,1,[1,0,1,0,0]),  # no valid perpetrator domain
    (1,None,[1,1,0,0,0]),  # no valid victim domain
    (0,1,[1,0,0,1,0]),     # impossible perpetrator positive
    (1,1,[1,0,1,0,0]),     # impossible perpetrator negative
    (1,0,[1,0,0,1,0]),     # impossible victim positive
    (1,1,[1,1,0,0,0]),     # impossible victim negative
    (1,1,[0,0,0,0,0]),     # overlap smaller than required by both valid domains
])
def test_joint_roles_must_fit_each_domain_marginal(joint_index,perp_key,victim_key,metric,threshold,perp,victim,joint):
    row=sample('invalid-joint','2025-09-01T00:00:00Z',**{perp_key:perp,victim_key:victim})
    bad=make_cube([row])
    bad['cells'][0][10][joint_index]=joint
    with pytest.raises(PipelineError,match='joint_domain_mismatch'):
        validate_cube(bad)
    assert 'joint_domain_mismatch' in client(bad,[],validate_only=True)['error']
    query=client(bad,[choice(semesters=['S1'],waves=['T0'],metric_id=metric,threshold=threshold)])[0]
    assert 'joint_domain_mismatch' in query['error']


def test_joint_roles_allow_valid_partial_domain_overlap():
    rows=[sample('both','2025-09-01T00:00:00Z',TBP_prevalence1=1,TBV_prevalence1=1),
          sample('perp-only-valid','2025-09-01T00:00:00Z',TBP_prevalence1=1,TBV_prevalence1=None),
          sample('victim-only-valid','2025-09-01T00:00:00Z',TBP_prevalence1=None,TBV_prevalence1=0)]
    cube=make_cube(rows);validate_cube(cube)
    rows=output(cube,choice(semesters=['S1'],waves=['T0'],metric_id='bullying_roles_traditional',threshold='any'))['rows']
    assert all(row['status']=='available' and row['valid_n']==1 and row['missing_n']==2 for row in rows)
    assert next(row['proportion'] for row in rows if row['category_code']=='both')==1
    bad=deepcopy(cube);bad['cells'][0][10][0]=[0,0,0,0,0]
    with pytest.raises(PipelineError,match='joint_domain_mismatch'):validate_cube(bad)
    assert 'joint_domain_mismatch' in client(bad,[],validate_only=True)['error']
