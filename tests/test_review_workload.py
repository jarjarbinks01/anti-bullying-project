"""Synthetic checks that a durable reopen/stale binding cannot display false zero."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from study2 import review_dispositions as admin
from study2 import review_workload as runtime


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    work=sqlite3.connect(tmp_path/'review.sqlite')
    work.executescript('CREATE TABLE followups(case_id TEXT PRIMARY KEY,task_id TEXT,state TEXT,payload TEXT);'
                      'CREATE TABLE events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,target TEXT,payload TEXT);')
    bindings={'release_id':'RUN_TEST','decision_revision':'DECISION_TEST','rules_hash':'RULES_TEST',
              'source_bindings':{'source':'TEST'},'output_bindings':{'output':'TEST'}}
    cases=[{'case_id':f'CASE_{i}','route':'correction','record_a':f'A{i}','record_b':f'B{i}',
            'version_a':f'VA{i}','version_b':f'VB{i}','evidence_hash':str(i)*64,
            'reasons':['child_birthdate_missing_or_invalid']} for i in range(1,6)]
    refs=[[(i,1),(i,2)] for i in range(1,6)]
    questions=[{'case_index':c,'question_index':q,'record_id':f'A{i}','version_id':f'VA{i}',
                'field':'dob','comparison_ids':[f'CASE_{i}']}
               for i,pairs in enumerate(refs,1) for c,q in pairs]
    request={'operation_id':'CLOSE_TEST','bindings':bindings,
        'authorization':{'authorizer':'synthetic-operator','reference':'TEST','reason':'Synthetic test'},
        'questions':questions,'cases':cases}
    admin.apply_closed_unresolvable(work,request)
    projection=admin.project_closures(work,bindings,cases)
    value={'format':runtime.FORMAT,'release_id':'RUN_TEST','decision_revision':'DECISION_TEST',
        'exclusion_manifest_revision':None,'native_workload':{'field_correction_comparisons':5},
        'active_workload':{'field_correction_comparisons':0},'correction_bundles':0,
        'source_groups_resolved':3,'accepted_historical_policy_closures':7,
        'original_answers':{'total':4,'same_child':1,'different_children':3},'field_decisions_in_this_followup':2,
        'administrative_disposition':{'bindings':bindings,'case_inventory':cases,
            'projection':projection,'admin_revision':admin.administrative_revision(work)}}
    source=tmp_path/'workload.json';source.write_text(json.dumps(value))
    monkeypatch.setenv(runtime.ENVIRONMENT_KEY,str(source))
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR',str(tmp_path))
    yield work,bindings,value,source,tmp_path
    work.close()


def load():
    return runtime.load_summary(release_id='RUN_TEST',decision_revision='DECISION_TEST',exclusion_revision=None)


def test_closed_comparisons_are_active_zero_only_with_authoritative_rows(prepared):
    _,_,_,_,_=prepared
    value,rows=load()
    assert rows==[{'Active review category':'Field correction comparisons','Count':0}]
    assert value['native_workload']['field_correction_comparisons']==5


def test_reopen_invalidates_the_old_zero_summary(prepared):
    work,bindings,_,_,_=prepared
    admin.reopen_closed_unresolvable(work,{'operation_id':'REOPEN_TEST','closure_operation_id':'CLOSE_TEST',
        'bindings':bindings,'authorization':{'authorizer':'synthetic-operator','reference':'TEST','reason':'Reopen synthetic test'}})
    with pytest.raises(runtime.WorkloadUnavailable):load()


def test_missing_admin_state_never_falls_back_to_zero(prepared,monkeypatch):
    monkeypatch.delenv('STUDY2_REVIEW_STATE_DIR')
    with pytest.raises(runtime.WorkloadUnavailable):load()


def test_stale_case_evidence_does_not_suppress_work(prepared):
    _,_,value,source,_=prepared
    value['administrative_disposition']['case_inventory'][0]['evidence_hash']='f'*64
    source.write_text(json.dumps(value))
    with pytest.raises(runtime.WorkloadUnavailable):load()


def test_loading_admin_summary_never_mutates_review_database(prepared):
    _,_,_,_,directory=prepared
    before=hashlib.sha256((directory/'review.sqlite').read_bytes()).hexdigest()
    load()
    assert hashlib.sha256((directory/'review.sqlite').read_bytes()).hexdigest()==before


def test_unrelated_categories_cannot_be_zeroed_by_correction_closure(prepared):
    _, _, value, source, _ = prepared
    value['native_workload']['other_work'] = 2
    value['active_workload']['other_work'] = 0
    source.write_text(json.dumps(value))
    with pytest.raises(runtime.WorkloadUnavailable):
        load()


def test_missing_correction_count_fails_closed_before_render(prepared):
    _, _, value, source, _ = prepared
    del value['field_decisions_in_this_followup']
    source.write_text(json.dumps(value))
    with pytest.raises(runtime.WorkloadUnavailable):
        load()
