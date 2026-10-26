"""Synthetic native calendar-response oracles and actual JS engine checks."""
from copy import deepcopy
from datetime import date
import json
import subprocess

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.descriptive_spec import DICTIONARY_VERSION, GROUPS
from study2.descriptive_trends import calendar_trends
from study2.descriptives import cohort, filter_cohort, independent_cohort
from study2.static_grade import CODES as GRADES, attach_grade
from study2.static_period import FORMAT, JS, METRICS, build_cube, validate_cube
from study2.static_sources import source_code


def response(sid, observed='2025-09-03T01:00:00Z', wave='T0', **extra):
    row = dict(submission_id=sid, version_id='version-'+sid, child_id=sid,
        wave=wave, role='student', observed_at=observed, date_basis='system_creation',
        time_confidence='observed', report_mode='abcd', grouping_anchor='該輪回應',
        anchor_gender='0', anchor_school_stage='primary', anchor_mainstream=True,
        anchor_source_type='qualtrics', _grade='P3', PHQ_total=2., FQOL_total=None,
        SEC_total=3., TBV_mean=.5, TBP_mean=.25, CBV_mean=0., CBP_mean=1.)
    row.update({domain+'_prevalence'+str(t): 1 if t == 1 else 0
                for domain in ('TBV','TBP','CBV','CBP') for t in (1,2)})
    row.update(extra)
    return row


def frame():
    rows = [response('a', PHQ_total=1.), response('b', PHQ_total=3.),
        response('c','2025-10-02T12:00:00Z',PHQ_total=9.,_grade='P4',anchor_source_type='paperform'),
        response('d','2025-10-03T12:00:00Z','T1',PHQ_total=None,_grade='S1',anchor_gender='1',anchor_school_stage='secondary'),
        response('e','2025-09-05T12:00:00Z','T1',PHQ_total=4.,_grade='Unknown',anchor_source_type='unrecognized',anchor_mainstream=False),
        response('batch', time_confidence='accepted_creation_time',date_basis='batch_assigned_creation',PHQ_total=7.),
        response('manual',time_confidence='manual_verified',date_basis='batch_assigned_creation',PHQ_total=5.),
        response('bad','not a date',PHQ_total=10.),response('unknown',time_confidence='unknown',PHQ_total=11.),
        response('before','2025-09-02T15:59:59.999999Z',PHQ_total=8.),
        response('end','2025-10-30T15:59:59.999999Z','T1',PHQ_total=6.),
        response('after','2025-10-30T16:00:00Z','T1',PHQ_total=12.)]
    result=pd.DataFrame(rows)
    result['SEC_total__status']='valid'
    result.loc[1,'SEC_total__status']='outside_report_range'
    result.loc[2,'TBV_prevalence2']=5
    result.loc[3,'TBV_prevalence2']=None
    return result


def cube(rows=None, role='student', mode='abcd', **anchors):
    options=dict(grade_anchor='student_wave',grouping_anchor='wave_response',source_filter_anchor='wave_response')
    options.update(anchors)
    return build_cube(frame() if rows is None else rows,role,mode=mode,release_id='synthetic-period',**options)


def selection(**overrides):
    result=dict(group='all',grades=list(GRADES),sources=['all'],mainstream=False,include_batch=False,
                **{'from':'2025-09-03','to':'2025-10-30'})
    result.update(overrides)
    return result


def client(value, selections=None, validate_only=False):
    driver=JS+'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8')),before=JSON.stringify(input);
const attempt=fn=>{try{return {value:fn()};}catch(error){return {error:error.message};}};
const out=input.validate_only?attempt(()=>Period.validate(input.cube)):
 input.selections.map(s=>attempt(()=>Period.query(input.cube,s)));
if(JSON.stringify(input)!==before)throw Error('mutated cube or settings');
if(Period.FORMAT!==input.cube.format&&!input.validate_only)throw Error('format constant');
console.log(JSON.stringify(out));
'''
    run=subprocess.run(['node','-e',driver],input=json.dumps(dict(cube=value,selections=selections,validate_only=validate_only)),
        text=True,capture_output=True,check=True)
    return json.loads(run.stdout)


def oracle(rows, setting, role='student'):
    prepared=rows.copy()
    prepared['anchor_source_type']=prepared['anchor_source_type'].map(source_code)
    selected,_=filter_cohort(prepared,mainstream=setting['mainstream'],group=setting['group'],
        sources=() if setting['sources']==['all'] else setting['sources'])
    selected=selected.loc[selected['_grade'].isin(setting['grades'])].copy()
    if not setting['sources']:selected=selected.iloc[:0]
    return calendar_trends(selected,role,'synthetic-period',start=date.fromisoformat(setting['from']),
        end=date.fromisoformat(setting['to']),include_batch=setting['include_batch'],
        variable_ids=[setting['variable_id']] if 'variable_id' in setting else list(METRICS))


def assert_oracle(actual, native, available):
    for key in ('whole_period','statistics'):
        columns=['wave','variable_id']+(['period_id'] if key=='statistics' else [])
        expected={tuple(row[k] for k in columns):row for row in native[key].to_dict('records')}
        for row in actual[key]:
            if row['variable_id'] not in available:
                assert not row['available'] and row['valid_n'] is row['missing_n'] is None
                continue
            target=expected[tuple(row[k] for k in columns)]
            for field in ['sample_n','valid_n','missing_n','outside_range_n','denominator']:
                assert row[field]==target[field]
            for field in ['mean','sd','numerator','proportion']:
                value=target['proportion'] if field=='mean' and row['kind']=='binary' else target[field]
                value=None if pd.isna(value) else value
                assert row[field]==pytest.approx(value,rel=1e-12,abs=1e-12) if value is not None else row[field] is None
    for row,target in zip(actual['counts'],native['counts'].to_dict('records')):
        assert all(row[k]==target[k] for k in row)
    expected=native['date_quality'][['wave','date_quality','input_n','included_n']].to_dict('records')
    assert actual['date_quality']==expected
    target=native['exclusions'].groupby('wave',sort=False)
    for wave,block in target:
        selected=block.iloc[[0,2,3,4]]
        got=[r for r in actual['exclusions'] if r['wave']==wave]
        assert [r['remaining_n'] for r in got]==list(selected.remaining_n)
        assert [r['excluded_n'] for r in got]==list(selected.excluded_n)


def test_sparse_moments_all_metrics_native_combined_filters_and_privacy():
    rows=frame();before=rows.copy(deep=True)
    rows['contact']='private synthetic contact';rows['school']='private school';rows['dob']='private birth date'
    value=cube(rows)
    assert value['format']==FORMAT and len(value['metrics'])==15
    assert len(value['cells'])<len(rows) and sum(r[8] for r in value['cells'])==len(rows)
    encoded=json.dumps(value)
    assert all(secret not in encoded for secret in ['submission_id','child_id','version_id','private synthetic','private school','private birth','T01:00','not a date'])
    settings=[selection(),selection(group='male_primary',grades=['P3','P4'],sources=['qualtrics','paperform'],mainstream=True),
        selection(group='female_secondary',grades=['S1'],sources=['qualtrics']),
        selection(grades=['Unknown'],sources=['unknown']),selection(include_batch=True),
        selection(group='male',grades=['P4'],sources=['paperform'],variable_id='TBV_prevalence2')]
    results=client(value,settings)
    for setting,result in zip(settings,results):
        assert 'error' not in result
        assert_oracle(result['value'],oracle(rows,setting),set(rows.columns)&set(METRICS))
    pd.testing.assert_frame_equal(before,rows[before.columns])


def test_pooled_variance_not_mean_of_means_singletons_and_true_zero():
    rows=pd.DataFrame([response('one',PHQ_total=1.),response('two',PHQ_total=3.),
        response('three','2025-10-02T00:00Z',PHQ_total=9.,_grade='P4')])
    settings=[selection(variable_id='PHQ_total'),selection(grades=['P4'],variable_id='PHQ_total'),selection(grades=['S6'],variable_id='PHQ_total')]
    results=[r['value'] for r in client(cube(rows),settings)]
    whole=results[0]['whole_period'][0]
    assert whole['mean']==pytest.approx(13/3) and whole['sd']==pytest.approx(rows.PHQ_total.std(ddof=1))
    assert whole['mean']!=5.5
    assert results[1]['whole_period'][0]['valid_n']==1 and results[1]['whole_period'][0]['sd'] is None
    assert results[2]['status']=='empty' and results[2]['whole_period'][0]['sample_n']==0
    assert results[2]['whole_period'][0]['valid_n']==results[2]['whole_period'][0]['missing_n']==0


def test_hk_days_clipped_months_leap_day_manual_priority_and_binary():
    rows=pd.DataFrame([response('before','2024-02-28T15:59:59.999999Z'),
        response('start','2024-02-28T16:00:00Z',TBV_prevalence2=1),
        response('manual','2024-02-29T15:59:59.999999Z','T1',time_confidence='manual_verified',date_basis='batch_assigned_creation',TBV_prevalence2=0),
        response('after','2024-02-29T16:00:00Z','T1')])
    setting=selection(**{'from':'2024-02-29','to':'2024-02-29'},variable_id='TBV_prevalence2')
    result=client(cube(rows),[setting])[0]['value']
    assert_oracle(result,oracle(rows,setting),set(METRICS))
    assert result['counts'][0]['covered_start']==result['counts'][0]['covered_end']=='2024-02-29'
    assert result['counts'][0]['period_end']=='2024-02-29' and result['counts'][0]['partial_period']
    assert result['whole_period'][0]['mean']==result['whole_period'][0]['proportion']==1
    assert result['counts'][1]['manual_date_n']==1 and result['counts'][1]['batch_date_n']==0


def test_missing_capability_differs_from_all_missing_and_empty_controls():
    rows=frame().drop(columns='SEC_total');value=cube(rows)
    settings=[selection(variable_id='SEC_total'),selection(variable_id='FQOL_total'),selection(grades=[]),selection(sources=[])]
    result=[r['value'] for r in client(value,settings)]
    assert result[0]['whole_period'][0]['sample_n']>0
    assert not result[0]['whole_period'][0]['available'] and result[0]['whole_period'][0]['valid_n'] is None
    assert result[1]['whole_period'][0]['available'] and result[1]['whole_period'][0]['valid_n']==0
    assert result[1]['whole_period'][0]['missing_n']==result[1]['whole_period'][0]['sample_n']
    for setting,got in zip(settings[2:],result[2:]):
        assert got['status']=='empty' and len(got['counts'])==4
        assert got['metadata']['grades']==setting['grades'] and got['metadata']['sources']==setting['sources']
        assert all(r['sample_n']==0 for r in got['counts'])
    empty=client(cube(rows.iloc[:0]),[selection()])[0]['value']
    assert empty['status']=='empty' and len(empty['date_quality'])==10


def native_anchors(mode,role):
    frame_rows=[]
    for wave in ('T0','T1'):
        for who in ('student','parent'):
            row=response(who+'-'+wave,'2025-09-03T00:00Z' if wave=='T0' else '2026-09-03T00:00Z',wave,
                child_id='synthetic-child',role=who,grade=6 if wave=='T0' else 1,
                gender='0' if who=='student' else '1',school_stage='primary' if wave=='T0' else 'secondary',
                school_stage_status='valid',mainstream=who=='student',school='ignored synthetic school',
                source_type=('legacy_online' if who=='student' else 'paperform') if wave=='T0' else 'qualtrics',
                identity_rules='synthetic',dyad=True,longitudinal=True,longitudinal_dyad=True)
            frame_rows.append(row)
    original=pd.DataFrame(frame_rows).drop(columns=[c for c in frame_rows[0] if c.startswith('anchor_') or c=='_grade'])
    measurements=pd.DataFrame(dict(submission_id=original.submission_id,descriptive_dictionary_version=DICTIONARY_VERSION))
    prepared=cohort(original,original.loc[original.role.eq('parent')],measurements,mode,role)
    prepared,anchor=attach_grade(prepared,original,measurements,mode,role)
    return prepared,anchor


def test_formal_p6_s1_anchors_and_ef_parent_source_are_native():
    rows,anchor=native_anchors('acbd','student')
    assert list(rows._grade)==['P6','P6']
    value=cube(rows,mode='acbd',grade_anchor=anchor,grouping_anchor='student_T0',source_filter_anchor='student_T0')
    setting=selection(group='male_primary',grades=['P6'],sources=['legacy_online'],**{'to':'2026-09-03'})
    got=client(value,[setting])[0]['value'];assert_oracle(got,oracle(rows,setting),set(METRICS))
    assert [r['sample_n'] for r in got['whole_period'] if r['variable_id']=='PHQ_total']==[1,1]
    parents,anchor=native_anchors('ef','parent')
    assert list(parents._grade)==['P6','S1'] and list(parents.anchor_source_type)==['paperform','qualtrics']
    value=cube(parents,role='parent',mode='ef',grade_anchor=anchor,grouping_anchor='wave_student',source_filter_anchor='wave_role_response')
    setting=selection(group='male_primary',grades=['P6'],sources=['paperform'],mainstream=True,**{'to':'2026-09-03'})
    got=client(value,[setting])[0]['value'];assert_oracle(got,oracle(parents,setting,'parent'),set(METRICS))
    assert got['whole_period'][0]['sample_n']==1
    assert not any('p_value' in row or 'cohen_dz' in row for row in got['whole_period'])


@pytest.mark.parametrize('mode',['independent_all','independent_child','independent_adult'])
def test_independent_parent_native_baseline_and_wave_grade(mode):
    branch='same_adult' if mode=='independent_adult' else 'child_report'
    rows=pd.DataFrame([response('parent-0',child_id='unit',role='parent',grade=3,school_stage='primary',school_stage_status='valid',
        source_type='paperform',gender='0',mainstream=True,school='synthetic',identity_rules=''),
        response('parent-1','2025-10-03T00:00Z','T1',child_id='unit',role='parent',grade=5,school_stage='secondary',school_stage_status='valid',
        source_type='qualtrics',gender='1',mainstream=False,school='synthetic',identity_rules='')])
    rows['panel_branch']=branch;rows['panel_wave']=rows.wave;rows['panel_longitudinal']=True
    # independent_cohort attaches its own anchors to the original panel rows.
    # The generic response helper is already anchored, so remove that overlay.
    rows=rows.drop(columns=[k for k in rows if k.startswith('anchor_') or k=='_grade'])
    measurements=pd.DataFrame(dict(submission_id=rows.submission_id,descriptive_dictionary_version=DICTIONARY_VERSION))
    prepared=independent_cohort(rows,measurements,branch,mode!='independent_all')
    prepared,anchor=attach_grade(prepared,rows,measurements,mode,'parent')
    value=cube(prepared,role='parent',mode=mode,grade_anchor=anchor,
        grouping_anchor='independent_parent_T0',source_filter_anchor='independent_parent_T0')
    setting=selection(group='male_primary',grades=['P3'],sources=['paperform'],mainstream=True,variable_id='PHQ_total')
    got=client(value,[setting])[0]['value'];assert_oracle(got,oracle(prepared,setting,'parent'),set(METRICS))
    assert [r['sample_n'] for r in got['whole_period']]==([1,0] if mode=='independent_all' else [1,1])


def test_cube_schema_is_not_an_alias_and_pool_overflow_is_explicit():
    value=cube(pd.DataFrame([response('one')]))
    value['cell_fields'][0]='private timestamp'
    with pytest.raises(PipelineError):validate_cube(value)
    assert 'error' in client(value,validate_only=True)
    valid=cube(pd.DataFrame([response('large',PHQ_total=1e300),response('small','2025-10-01T00:00Z',PHQ_total=-1e300)]))
    assert 'pooled_moments_overflow' in client(valid,[selection(variable_id='PHQ_total')])[0]['error']


@pytest.mark.parametrize('fault',['extra_private','format','duplicate','negative_m2','single_m2','valid_count','outside','numerator','unavailable','date','quality','anchor','gender'])
def test_python_and_js_validation_reject_malformed_or_private_cells(fault):
    value=cube(pd.DataFrame([response('one')]))
    cell=value['cells'][0]
    if fault=='extra_private':value['submission_id']='private marker'
    elif fault=='format':value['format']='future'
    elif fault=='duplicate':value['cells'].append(deepcopy(cell))
    elif fault=='negative_m2':cell[9][0][3]=-1
    elif fault=='single_m2':cell[9][0][3]=1
    elif fault=='valid_count':cell[9][0][0]=2
    elif fault=='outside':cell[9][0][1]=1
    elif fault=='numerator':cell[9][7][2]=2
    elif fault=='unavailable':value['metrics'][0]['available']=False
    elif fault=='date':cell[0]='2025-02-30'
    elif fault=='quality':cell[7]='unknown_basis'
    elif fault=='anchor':value['source_filter_anchor']='wrong'
    else:cell[2]='private label'
    with pytest.raises(PipelineError):validate_cube(value)
    assert 'error' in client(value,validate_only=True)


@pytest.mark.parametrize('change',[{'grades':['P9']},{'sources':['made_up']},{'sources':['all','qualtrics']},
    {'grades':['P3','P3']},{'group':'unknown'},{'mainstream':1},{'include_batch':'true'},
    {'from':'2025-02-30'},{'to':'2025-09-02'},{'variable_id':'new_score'},{'extra':'not allowed'}])
def test_invalid_query_is_never_silently_broadened(change):
    assert 'error' in client(cube(),[selection(**change)])[0]
