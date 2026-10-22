"""Independent manual expectations through Python and the pure Node engine.

Only the two package-owned test files define this oracle. No accepted R01 test
fixture/expected count is imported, copied, or used to calculate an expectation.
"""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from static_scope_cases import (ADULT_POLICY,CASE_SPECS,COUNT_COLUMNS,EXPECTED_COUNTS,
    FLOW_EXPECTED,LEDGER,VERSION_META,case_selection,synthetic_inputs,version_keys)
from study2.static_scope import (ScopeError,build_scope_index,canonical_json,
    catalogue_options,creation_day,default_selection,normalize_selection,query_scope,
    transition_selection)
from study2.static_scope_client import JS_SOURCE


def counts(result):
    samples={s['code']:s['count'] for s in result['samples']}
    return (result['raw']['student'],result['raw']['parent'],*(samples[k] for k in COUNT_COLUMNS[2:]))


def assert_manual(name,language,result):
    actual=counts(result);expected=EXPECTED_COUNTS[name]
    if actual!=expected and os.environ.get('MMR02_EVIDENCE_DIR'):
        folder=Path(os.environ['MMR02_EVIDENCE_DIR'])/'counterexamples'
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/f'{language}_{name}.json'
        number=1
        while target.exists():
            target=folder/f'{language}_{name}_{number}.json';number+=1
        target.write_text(json.dumps(dict(case=name,engine=language,columns=COUNT_COLUMNS,
            expected=expected,actual=actual,full_result=result),indent=2)+'\n')
    assert actual==expected,dict(case=name,engine=language,columns=COUNT_COLUMNS,expected=expected,actual=actual)


NODE_DRIVER=r'''
let input='';process.stdin.on('data',v=>input+=v);process.stdin.on('end',()=>{
  const data=JSON.parse(input),before=JSON.stringify(data);
  const results=data.operations.map(op=>{
    try{
      let result;
      if(op.method==='query')result=Study2Scope.query(data.index,op.selection);
      else if(op.method==='defaultSelection')result=Study2Scope.defaultSelection(data.index);
      else if(op.method==='transitionSelection')result=Study2Scope.transitionSelection(data.index,op.selection,op.patch);
      else if(op.method==='catalogueOptions')result=Study2Scope.catalogueOptions(data.index,op.facet,op.search||'');
      else throw Error('unsupported_test_operation');
      return {ok:true,result};
    }catch(e){return {ok:false,error:e.message};}
  });
  process.stdout.write(JSON.stringify({results,input_unchanged:before===JSON.stringify(data)}));
});
'''


def node_batch(index,operations):
    node=shutil.which('node');assert node,'Existing Node runtime required'
    result=subprocess.run([node,'-e',JS_SOURCE+NODE_DRIVER],input=json.dumps(dict(index=index,operations=operations)),
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(result.stdout)
    assert data['input_unchanged'],'Browser API mutated index or operation/selection input'
    return data['results']


@pytest.fixture(scope='module')
def indexes():
    value={}
    for variant in ['base','absent','empty','unsupported']:
        inputs=synthetic_inputs(variant);original=deepcopy(inputs)
        value[variant]=build_scope_index(*inputs)
        assert inputs==original,'Builder changed synthetic input membership'
    return value


@pytest.fixture(scope='module')
def browser_results(indexes):
    output={}
    for variant,index in indexes.items():
        names=[name for name,spec in CASE_SPECS.items() if spec.get('variant','base')==variant]
        rows=node_batch(index,[dict(method='query',selection=case_selection(index,name)) for name in names])
        for name,row in zip(names,rows):
            assert row['ok'],(name,row)
            output[name]=row['result']
    return output


@pytest.mark.parametrize('name',list(CASE_SPECS))
def test_hand_calculated_case_in_both_engines(name,indexes,browser_results):
    index=indexes[CASE_SPECS[name].get('variant','base')]
    before=deepcopy(index);selection=case_selection(index,name);saved=deepcopy(selection)
    python=query_scope(index,selection);browser=browser_results[name]
    if os.environ.get('MMR02_EVIDENCE_DIR'):
        folder=Path(os.environ['MMR02_EVIDENCE_DIR'])/'case_results';folder.mkdir(parents=True,exist_ok=True)
        target=folder/f'{name}.json';number=1
        while target.exists():
            target=folder/f'{name}_{number}.json';number+=1
        target.write_text(json.dumps(dict(case=name,expected_columns=COUNT_COLUMNS,
            hand_calculated=EXPECTED_COUNTS[name],selection=selection,python=python,node=browser),indent=2)+'\n')
    assert_manual(name,'python',python)
    assert_manual(name,'node',browser)
    assert browser==python,'Full Python/browser result differs beyond manual counts'
    assert index==before and selection==saved
    assert len(python['samples'])==9
    assert python['date_policy']['timezone']=='Asia/Hong_Kong' and python['date_policy']['inclusive'] is True
    for s in python['samples']:
        assert s['unit']==('questionnaire_records' if s['code'] in ['A','B','C','D'] else 'longitudinal_cases' if s['code'] in ['AC','BD'] else 'dyads')
        assert s['status']==('unavailable' if s['count'] is None else 'available')
    for role in ['student','parent']:
        assert sum(row[role] for row in python['sources'])==python['raw'][role]
    if name in FLOW_EXPECTED:
        assert python['flow']['status']=='available'
        assert python['flow']['lanes']==FLOW_EXPECTED[name]
        assert browser['flow']['lanes']==FLOW_EXPECTED[name]
    if name in ['absent_adult_artifact','unsupported_adult_policy']:
        assert python['reconciliation']['status']=='partial'
    else:
        assert python['reconciliation']['status']=='checked'


def test_fixture_boundaries_and_exact_fixed_membership():
    records,analysis,adults,summary=synthetic_inputs()
    assert len(records)==23<=40 and len(analysis)==12 and len(adults)==4
    assert sum(r['role']=='student' for r in records)==11
    assert sum(r['role']=='parent' for r in records)==12
    assert {r['submission_id'] for r in adults}=={'toy-record-kp0','toy-record-kb1','toy-record-mp0','toy-record-mp1'}
    assert {r['submission_id'] for r in analysis if r['role']=='parent' and r['wave']=='T1'}=={'toy-record-kp1','toy-record-lp1','toy-record-mp1'}
    assert all('hk_creation_day' in r and 'fixture_version' in r and 'formal_sample_slots' in r for r in records)
    assert len(EXPECTED_COUNTS)==len(CASE_SPECS)==38
    assert set(EXPECTED_COUNTS)==set(CASE_SPECS)


def test_no_local_toy_ids_or_unrequested_phq_api_in_serialized_index(indexes):
    encoded=canonical_json(indexes['base'])
    for token in ['toy-record-','toy-child-','toy-input-revision-','submission_id','child_id','formal_sample_slots','hk_creation_day','observed_at','phq','PHQ','birth','contact','score']:
        # The published policy token includes birth/contact vocabulary. Its
        # presence is provenance, not participant values or a scoring API.
        if token in ['birth','contact']:
            continue
        assert token not in encoded,token
    assert set(indexes['base'])=={'format','meta','sources','surveys','profiles','records','samples','schools'}
    assert indexes['base']['meta']['adult']['policy']==ADULT_POLICY
    assert indexes['base']['meta']['adult']['evidence']=='formal_parent_longitudinal_artifact'


def test_catalogue_identity_search_and_zero_availability(indexes):
    index=indexes['base'];keys=version_keys(index)
    assert len(index['surveys'])==len(VERSION_META)==20
    common=[r for r in index['surveys'] if r['label']=='Common questionnaire']
    missing=[r for r in index['surveys'] if r['missing_name']]
    assert len(common)==18 and len(missing)==2
    assert {r['role'] for r in common}=={'student','parent'}
    assert len({r['source_key'] for r in common})==3
    assert keys['ks0']!=keys['extra_s'] and keys['kp1']!=keys['extra_p']
    assert all(r['label']=='Missing survey name' and r['form_id'] is None for r in missing)
    zero=query_scope(index,case_selection(index,'zero_availability'))
    assert_manual('zero_availability','python',zero)
    availability={r['key']:r['available'] for r in zero['facets']['surveys']}
    assert availability[keys['ks0']]==0
    assert keys['ks0'] in zero['scope']['surveys']
    assert keys['ks0'] in {r['key'] for r in catalogue_options(index,'surveys')}
    before=deepcopy(index);full=query_scope(index)
    assert catalogue_options(index,'surveys','not a matching name')==[]
    assert len(catalogue_options(index,'surveys','common'))==18
    rows=node_batch(index,[dict(method='catalogueOptions',facet='surveys'),
        dict(method='catalogueOptions',facet='surveys',search='not a matching name'),
        dict(method='catalogueOptions',facet='surveys',search='common'),dict(method='query',selection={})])
    assert all(r['ok'] for r in rows)
    assert rows[0]['result']==catalogue_options(index,'surveys') and rows[1]['result']==[] and len(rows[2]['result'])==18
    assert rows[3]['result']==full and index==before


def test_creation_dates_no_substitution_and_basis_markers(indexes,browser_results):
    records=synthetic_inputs()[0];by={r['submission_id'][11:]:r for r in records}
    assert creation_day(by['ks0'])==('2025-02-01','observed','usable')
    assert creation_day(by['pending_s'])==('2025-01-31','observed','usable')
    assert creation_day(by['ls1'])==(None,'unknown','missing')
    assert creation_day(by['invalid_s'])==(None,'observed','invalid')
    assert creation_day(by['naive_p'])==(None,'observed','naive')
    assert creation_day(by['repeat_s'])==('2025-05-01','accepted_batch','usable')
    assert creation_day(by['kb1'])==('2025-05-01','manual_verified','usable')
    for engine in [query_scope(indexes['base']),browser_results['all']]:
        assert engine['dates']['date_state']==dict(usable=20,missing=1,naive=1,invalid=1,untrusted=0)
        assert engine['dates']['timing_basis']==dict(observed=20,manual_verified=1,accepted_batch=1,unknown=1)
        assert engine['original_waves']=={'student':{'T0':9,'T1':2,'unknown':0},'parent':{'T0':7,'T1':5,'unknown':0}}
    for name in ['hk_day','known_only','from_may']:
        assert browser_results[name]['date_policy']['unknown_excluded']==dict(student=2,parent=1)
    assert browser_results['hk_day_unknown']['date_policy']['included_unknown_interval_unverified'] is True
    assert browser_results['bounded_unknown']['date_policy']['included_unknown_interval_unverified'] is True
    assert browser_results['all']['date_policy']['included_unknown_interval_unverified'] is False


def test_date_transitions_and_reset_use_supplied_apis(indexes):
    index=indexes['base'];initial=default_selection(index);snapshot=deepcopy(initial)
    patch=dict(start='2025-02-01',end='2025-02-01')
    activated=transition_selection(index,initial,patch)
    assert activated['include_unknown'] is False
    assert_manual('hk_day','python',query_scope(index,activated))
    explicit=transition_selection(index,activated,{'include_unknown':True})
    assert_manual('hk_day_unknown','python',query_scope(index,explicit))
    kept=transition_selection(index,explicit,{'end':'2025-06-30'})
    assert kept['include_unknown'] is True
    reset=default_selection(index)
    assert initial==snapshot and reset==initial and reset['include_unknown'] is True
    assert_manual('reset','python',query_scope(index,reset))
    rows=node_batch(index,[dict(method='transitionSelection',selection=initial,patch=patch),
        dict(method='transitionSelection',selection=activated,patch={'include_unknown':True}),
        dict(method='transitionSelection',selection=explicit,patch={'end':'2025-06-30'}),
        dict(method='defaultSelection'),dict(method='query',selection=reset)])
    assert all(r['ok'] for r in rows)
    assert [r['result'] for r in rows[:4]]==[activated,explicit,kept,reset]
    assert_manual('reset','node',rows[4]['result'])


@pytest.mark.parametrize('selection',[{'start':'2025-02-30'},{'start':'2025-05-01','end':'2025-02-01'},
    {'sources':['unknown-category']},{'surveys':['unknown-category']},{'include_unknown':1}])
def test_invalid_selection_errors_never_substitute_a_scope(selection,indexes):
    index=indexes['base'];before=deepcopy(index)
    with pytest.raises(ScopeError):
        query_scope(index,selection)
    row=node_batch(index,[dict(method='query',selection=selection)])[0]
    assert row['ok'] is False and row['error']
    assert index==before
    assert_manual('reset','python',query_scope(index,default_selection(index)))


def test_unanchored_retained_and_no_replacement_or_adult_inference(indexes,browser_results):
    alone=browser_results['unanchored_only'];parent=alone['flow']['lanes']['parent']
    assert parent['repeat_handling']['remaining']==1
    assert parent['selection']['entering']==1 and parent['selection']['remaining']==0
    assert parent['selection']['exits']['parent_no_reliable_student_baseline']==1
    assert all(s['count']==0 for s in alone['samples'])
    assert_manual('unconfirmed_adult','node',browser_results['unconfirmed_adult'])
    assert browser_results['unconfirmed_adult']['samples'][0]['policy']=='fixed_published_slots'
    # All three children have B and D, but only the two explicit formal adults
    # have BD. No PHQ measure is inferred from these memberships.
    for name in ['drop_student_t0','drop_student_t1','drop_parent_t0','drop_parent_t1','drop_formal_bd_t1','unselected_only']:
        assert_manual(name,'node',browser_results[name])


def test_shared_profile_slots_preserve_multiplicity(indexes,browser_results):
    index=indexes['base'];keys=version_keys(index)
    student=[i for i,p in enumerate(index['profiles']) if p['survey_key']==keys['ms']]
    parent=[i for i,p in enumerate(index['profiles']) if p['survey_key']==keys['mp']]
    assert len(student)==len(parent)==1
    s,p=student[0],parent[0]
    assert sum(r['count'] for r in index['records'] if r['profile']==s)==2
    assert sum(r['count'] for r in index['records'] if r['profile']==p)==2
    for code,profiles in [('AC',[s,s]),('BD',[p,p]),('EF',[s,p,s,p])]:
        assert any(r['code']==code and r['profiles']==profiles and r['count']==1 for r in index['samples'])
    assert_manual('shared_profiles','node',browser_results['shared_profiles'])


def test_repeated_reordered_inputs_and_selections_are_immutable(indexes):
    index=indexes['base'];before=deepcopy(index);inputs=synthetic_inputs();saved=deepcopy(inputs)
    rebuilt=build_scope_index(list(reversed(inputs[0])),list(reversed(inputs[1])),list(reversed(inputs[2])),inputs[3])
    assert rebuilt==index and inputs==saved
    operations=[];names=[]
    for name in reversed([n for n,s in CASE_SPECS.items() if 'variant' not in s]):
        selection=case_selection(index,name)
        for field in ['sources','surveys']:
            if field in selection:
                selection[field]=list(reversed(selection[field]))+selection[field]
        first=query_scope(index,selection);second=query_scope(index,selection)
        assert first==second
        assert_manual(name,'python',first)
        operations.extend([dict(method='query',selection=selection),dict(method='query',selection=selection)])
        names.extend([name,name])
    for name,row in zip(names,node_batch(index,operations)):
        assert row['ok'],row
        assert_manual(name,'node',row['result'])
    changed=query_scope(index);changed['raw']['student']=999
    assert_manual('all','python',query_scope(index))
    assert index==before and inputs==saved


def test_runtime_origins_are_inside_this_isolated_copy():
    root=Path(__file__).resolve().parents[1]
    for name in ['study2','study2.static_scope','study2.static_scope_client']:
        module=importlib.import_module(name)
        assert Path(module.__file__).resolve().is_relative_to(root)
