"""Hand-checkable synthetic grade partitions and the actual client pooler."""
from copy import deepcopy
import json
import subprocess

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.descriptives import statistics,wave_counts
from study2.static_export import pair_details,safe_statistics,safe_changes,pack_snapshot
from study2.static_grade import (CODES,JS_SOURCE,attach_grade,build_cube,grade_code,header,validate_grade)
from test_static_g12 import panel


def example(a=(2.,10.,10.,10.),b=(4.,10.,10.,10.),mode='acbd',role='student'):
    rows=panel(a,b,role=role,mode=mode)
    rows['grade']=[3 if i<2 else 4 for i in range(len(rows))]
    rows['school_stage']='primary';rows['school_stage_status']='valid'
    rows['_grade']=['P3' if i<2 else 'P4' for i in range(len(rows))]
    return rows


def payload(rows,role='student',mode='acbd'):
    stats=safe_statistics(statistics(rows,role))
    changes=safe_changes(pair_details(rows,role,('all',)))
    view=dict(mode=mode,role=role,source='all',mainstream=False,counts={'all':wave_counts(rows)},statistics=stats,changes=changes)
    view['grade']=build_cube(rows,role,view,('all',),'student_T0' if mode=='acbd' else 'student_wave')
    snap=dict(release_id='synthetic-grade',report_version=header('synthetic-grade')['report_version'],
        dictionary_version=header('synthetic-grade')['dictionary_version'],minimum_cell_n=0,small_sample_policy='none',grade=header('synthetic-grade'),views=[view])
    validate_grade(snap);return snap


def js_pool(snap,codes):
    driver=JS_SOURCE+"\nconst x=JSON.parse(require('fs').readFileSync(0,'utf8'));try{console.log(JSON.stringify({value:Grade.pool(x.snapshot,x.snapshot.views[0],x.codes)}));}catch(error){console.log(JSON.stringify({error:error.message}));}"
    run=subprocess.run(['node','-e',driver],input=json.dumps(dict(snapshot=snap,codes=codes)),text=True,capture_output=True,check=True)
    return json.loads(run.stdout)


def phq(view,wave='T0'):
    return next(r for r in view['statistics'] if r['variable_id']=='PHQ_total' and r['wave']==wave)


def test_union_weighted_moments_singletons_and_duplicate_selection():
    snap=payload(example())
    result=js_pool(snap,['P3','P4','P4'])['value']
    assert phq(result)['mean']==8. and phq(result)['sd']==4. and phq(result)['valid_n']==4
    one=js_pool(snap,['P3'])['value']
    assert phq(one)['mean']==2. and phq(one)['valid_n']==1 and phq(one)['sd'] is None and not phq(one)['suppressed']
    assert js_pool(snap,['P3','P4'])==js_pool(snap,['P4','P3','P4'])
    union=js_pool(snap,['P3','P4','P5','P6'])['value']
    direct=statistics(example().loc[lambda r:r._grade.isin(['P3','P4','P5','P6'])],'student').query("variable_id=='PHQ_total' and wave=='T0'").iloc[0]
    assert phq(union)['mean']==direct['mean'] and phq(union)['sd']==direct['sd']


def test_metric_specific_pairs_use_same_complete_people_and_no_custom_inference():
    rows=example((2.,10.,6.),(4.,None,5.));rows.loc[rows.child_id.eq('person-2'),'_grade']='P5'
    rows.loc[(rows.child_id.eq('person-0'))&rows.wave.eq('T0'),'FQOL_total']=None
    result=js_pool(payload(rows),['P3','P4','P5'])['value']
    row=next(r for r in result['changes'] if r['variable_id']=='PHQ_total')
    assert [row[k] for k in ['pairs_n','paired_valid_n','only_t0_valid_n','only_t1_valid_n','both_missing_n']]==[3,2,1,0,0]
    assert row['t0_mean']==4 and row['t1_mean']==4.5 and row['mean_change']==.5
    assert phq(result)['mean']==6 and phq(result,'T1')['mean']==4.5
    assert row['p_value'] is None and row['cohen_dz'] is None and row['inference_status']=='custom_grade_inference_unavailable'
    fq=next(r for r in result['changes'] if r['variable_id']=='FQOL_total')
    assert fq['paired_valid_n']==2 and fq['only_t1_valid_n']==1


def test_all_known_none_and_categories_have_correct_denominators():
    rows=example();rows.loc[rows.child_id.eq('person-3'),'_grade']='Unknown'
    snap=payload(rows)
    assert phq(js_pool(snap,CODES)['value'])['mean']==8
    known=js_pool(snap,CODES[:-1])['value'];assert phq(known)['valid_n']==3
    categories=[r for r in known['statistics'] if r['variable_id']=='phq_band' and r['wave']=='T0']
    assert sum(r['numerator'] for r in categories)==3 and all(r['denominator']==3 for r in categories)
    none=js_pool(snap,[])['value'];assert none['counts']['all']=={'T0':0,'T1':0}
    assert phq(none)['valid_n']==0 and phq(none)['mean'] is None and phq(none)['sd'] is None
    assert 'error' in js_pool(snap,['P9'])


@pytest.mark.parametrize('stage,status,n,expected', [('primary','valid',3,'P3'),('secondary','valid',3.,'S3'),
    ('primary','conflict',3,'Unknown'),('primary','valid',None,'Unknown'),(None,'valid',3,'Unknown'),
    ('primary','valid',True,'Unknown'),('primary','valid',7,'Unknown')])
def test_codes_do_not_infer_stage_or_repair_invalid_grade(stage,status,n,expected):
    assert grade_code(dict(grade=n,school_stage=stage,school_stage_status=status))==expected


def test_p6_s1_stays_at_baseline_but_per_wave_is_distinct():
    rows=example((2.,),(4.,));rows.loc[:,'grade']=[6,1];rows.loc[:,'school_stage']=['primary','secondary']
    measurements=pd.DataFrame({'submission_id':rows.submission_id,'descriptive_dictionary_version':'synthetic'})
    per,anchor=attach_grade(rows,rows,measurements,'abcd','student')
    assert list(per._grade)==['P6','S1'] and anchor=='student_wave'
    stable,anchor=attach_grade(rows,rows,measurements,'acbd','student')
    assert list(stable._grade)==['P6','P6'] and anchor=='student_T0'
    # A missing baseline is never filled by a known follow-up.
    rows.loc[rows.wave.eq('T0'),'grade']=None
    stable,_=attach_grade(rows,rows,measurements,'acbd','student');assert set(stable._grade)=={'Unknown'}


def test_parent_unique_student_link_preserves_actual_bd_and_never_falls_back():
    students=example((2.,),(4.,));students['grade']=[6,1];students['school_stage']=['primary','secondary']
    parent=students.copy();parent['role']='parent';parent['submission_id']=['formal-parent-baseline','actual-bd-alternative'];parent['grade']=3
    parent['version_id']=['formal-v0','actual-v1']
    measurements=pd.DataFrame({'submission_id':students.submission_id,'descriptive_dictionary_version':'synthetic'})
    out,_=attach_grade(parent,students,measurements,'acbd','parent')
    assert list(out._grade)==['P6','P6'] and list(out.submission_id)==list(parent.submission_id) and list(out.version_id)==list(parent.version_id)
    ambiguous=pd.concat([students,students.iloc[:1]],ignore_index=True)
    out,_=attach_grade(parent,ambiguous,measurements,'abcd','parent');assert list(out._grade)==['Unknown','S1']


def test_independent_parent_uses_own_grade_without_any_student_and_legacy_is_distinct():
    rows=example((2.,),(4.,),role='parent',mode='independent_same_adult');rows['grade']=[3,5]
    empty=rows.iloc[:0];measurements=pd.DataFrame()
    out,anchor=attach_grade(rows,empty,measurements,'independent_adult','parent')
    assert list(out._grade)==['P3','P3'] and anchor=='parent_report_T0'
    out,anchor=attach_grade(rows,empty,measurements,'independent_all','parent');assert list(out._grade)==['P3','P5']
    out,anchor=attach_grade(rows.drop(columns='school_stage_status'),empty,measurements,'independent_all','parent');assert anchor is None
    out,anchor=attach_grade(empty.drop(columns='grade'),empty,measurements,'independent_all','parent');assert anchor=='parent_report_wave' and out.empty


def test_whole_scope_parent_phq_gate_is_not_enabled_by_grade_partition():
    rows=example(role='parent');rows['adult_continuity_confirmed']=True;rows.loc[0,'adult_continuity_confirmed']=False
    snap=payload(rows,'parent');result=js_pool(snap,['P4'])['value']
    assert not any(r['variable_id'].startswith('PHQ') for r in result['changes'])
    assert any(r['variable_id']=='SEC_total' for r in result['changes'])


@pytest.mark.parametrize('defect',['duplicate','missing','negative_m2','count','header','policy','fields','pair','moment_total','schema_metadata'])
def test_invalid_or_legacy_grade_capabilities_fail_closed_in_python_and_client(defect):
    snap=payload(example());cube=snap['views'][0]['grade']
    if defect=='duplicate':cube['cells'].append(deepcopy(cube['cells'][0]))
    elif defect=='missing':cube['cells'].pop()
    elif defect=='negative_m2':next(c for c in cube['cells'] if c['statistics'])['statistics'][0][5]=-1
    elif defect=='count':cube['cells'][0]['counts']['T0']=1
    elif defect=='header':snap['grade']['format']='future'
    elif defect=='policy':snap['minimum_cell_n']=2
    elif defect=='fields':cube['statistic_fields']=[]
    elif defect=='pair':next(c for c in cube['cells'] if c['pairs'])['pairs'][0][1]=99
    elif defect=='moment_total':
        index=next(i for i,r in enumerate(cube['statistics_schema']) if r['wave']=='T0' and r['variable_id']=='PHQ_total')
        next(c for c in cube['cells'] if c['grade_code']=='P4')['statistics'][index][5]+=4
    else:cube['statistics_schema'][0]['variable']='incorrect metric'
    with pytest.raises(PipelineError):validate_grade(snap)
    assert 'error' in js_pool(snap,['P3'])


def test_packing_retains_grade_vectors_and_legacy_custom_is_unavailable():
    snap=payload(example());packed=pack_snapshot(snap)
    assert packed['views'][0]['grade']==snap['views'][0]['grade']
    legacy=deepcopy(snap);legacy.pop('grade');legacy['views'][0].pop('grade')
    assert 'error' in js_pool(legacy,['P3'])


def test_custom_per_wave_has_no_pair_fields_and_supported_empty_is_zero():
    rows=example((2.,),(4.,),mode='abcd');rows['_grade']=['P6','S1']
    result=js_pool(payload(rows,mode='abcd'),['P6'])['value']
    assert result['counts']['all']=={'T0':1,'T1':0} and result['changes']==[]
    empty=example().iloc[:0].copy();empty.attrs['mode']='acbd'
    result=js_pool(payload(empty),['P3'])['value']
    assert result['counts']['all']=={'T0':0,'T1':0} and phq(result)['mean'] is None


def test_contract_validation_remains_active_under_optimized_python():
    import sys
    snap=payload(example());snap['views'][0]['grade']['cells'].append(deepcopy(snap['views'][0]['grade']['cells'][0]))
    code="import json,sys;from study2.static_grade import validate_grade;from study2.common import PipelineError\ntry:validate_grade(json.load(sys.stdin))\nexcept PipelineError:print('invalid projection rejected')\nelse:raise RuntimeError('validation bypassed')"
    result=subprocess.run([sys.executable,'-O','-c',code],input=json.dumps(snap),text=True,capture_output=True,check=True)
    assert result.stdout.strip()=='invalid projection rejected'


@pytest.mark.parametrize('minimum',[0,2])
def test_real_export_has_grade_only_in_researcher_minimum_zero(tmp_path,monkeypatch,minimum):
    import study2.static_export as module
    from test_static_quality_integration import synthetic_publication,load_script
    monkeypatch.setattr(module,'GROUPS',{'all':'All'})
    monkeypatch.setattr(module,'SOURCE_NAMES',{'qualtrics':'Qualtrics'})
    monkeypatch.setattr(module,'MODES',{'abcd':'wave','acbd':'formal'})
    fixture=synthetic_publication(tmp_path/'inputs',independent=False)
    path=fixture['folder']/'descriptive_measurements.parquet'
    measurement=pd.read_parquet(path);measurement['school_stage_status']='valid';measurement.to_parquet(path,index=False)
    site=tmp_path/'site';module.export_static(fixture['cfg'],site,minimum)
    snapshot=load_script(site/'snapshot.js','window.STUDY2_SNAPSHOT=')
    if minimum:
        assert 'grade' not in snapshot and all('grade' not in v for v in snapshot['views'])
    else:
        assert snapshot['grade']==header(snapshot['release_id'])
        validate_grade(snapshot)
        assert all(v['grade']['status']=='available' for v in snapshot['views'])
        assert 'toy-record-' not in json.dumps([v['grade'] for v in snapshot['views']])
