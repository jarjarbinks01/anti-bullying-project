import copy
import json
from pathlib import Path

import pytest

from study2 import review_core as core
from study2.common import PipelineError, dumps
from study2.matching import candidate, identity_evidence
from study2.review_dispatch import Router, summary
from study2.respondents import adult_evidence
from study2.store import connect
from test_identity_and_time import rec
from test_review_cards import project


def child_pair(**changes):
    a, b = rec('a', child_id='a-child'), rec('b', 120, child_id='b-child', **changes)
    return a, b, candidate(a,b,'identity','synthetic','pending','synthetic')


@pytest.mark.parametrize('changes,route,reason', [
    ({'dob':'2011-01-01'},'background','child_birthdate_conflict'),
    ({'gender':'1'},'background','child_gender_conflict'),
    ({'dob':None},'correction','child_birthdate_missing_or_invalid'),
    ({'dob':'2012'},'correction','child_birthdate_missing_or_invalid'),
    ({'gender':None},'correction','child_gender_missing_or_invalid'),
    ({'gender':'9'},'correction','child_gender_missing_or_invalid'),
    ({'school':None},'correction','child_school_missing'),
    ({'status':'excluded_school'},'background','excluded_submission'),
    ({'status':'exact_input_repeat'},'background','excluded_submission'),
    ({'status':'manual_excluded'},'background','excluded_submission'),
])
def test_known_contradictions_and_missing_basics_are_not_identity_tasks(changes,route,reason):
    a,b,c=child_pair(**changes)
    router=Router({'a':a,'b':b})
    assert router.classify(c)=={'route':route,'reasons':[reason]}
    assert not router.eligible(c) and not router.eligible(c,'validation')
    assert not router.eligible(c,'adjudication')


@pytest.mark.parametrize('value', ['',None,'6123456','invalid','61234567；62345678'])
def test_missing_or_unusable_contact_is_not_a_data_collection_task(value):
    a,b,c=child_pair(dob=None)
    b['answer']['contact_01']=value
    assert Router({'a':a,'b':b}).classify(c)=={'route':'untraceable','reasons':['no_usable_contact']}


def test_email_is_traceable_when_phone_is_omitted():
    a,b,c=child_pair()
    a['answer']['contact_01']='A@example.org'
    b['answer']['contact_01']='b@example.org'
    assert Router({'a':a,'b':b}).classify(c)['route']=='awaiting_evidence'
    b['dob']=None
    assert Router({'a':a,'b':b}).classify(c)['route']=='correction'


@pytest.mark.parametrize('changes', [
    {'school':'New School'}, {'grade':4}, {'grade':None},
    {'observed_at':None}, {'observed_at':rec('x',1)['observed_at']},
    {'grade_raw':'F.1','grade':1,'school_type':'secondary'},
    {'phone_value':'61234568'}, {'phone_value':'62345678'},
])
def test_accepted_variation_and_uncertain_contacts_remain_reviewable(changes):
    a,b,c=child_pair(**changes)
    b['answer']['student_demographics_02']='99'
    expected='awaiting_evidence' if 'phone_value' in changes else 'review'
    assert Router({'a':a,'b':b}).classify(c)['route']==expected


def test_conflict_is_not_hidden_by_common_contacts_or_a_third_record():
    a,b,c=child_pair(dob='2011-01-01')
    third=rec('third',child_id='third-child')
    router=Router({'a':a,'b':b,'third':third})
    assert not router.eligible(c)
    assert router.eligible(candidate(a,third,'identity','synthetic','pending','Competing or contradictory candidate component'))


def decision(a,b,action):
    adult=action.endswith('_ADULT')
    evidence=adult_evidence if adult else identity_evidence
    return {'payload':{'action':action,'record_a':a['submission_id'],'record_b':b['submission_id'],
        'version_a':a['version_id'],'version_b':b['version_id'],
        'evidence_a':evidence(a),'evidence_b':evidence(b)}}


def test_manual_nonmatch_blocks_transitive_dispatch_without_rewriting_records():
    a,b,c=child_pair();third=rec('third',child_id='third-child')
    records={'a':a,'b':b,'third':third};before=copy.deepcopy(records)
    router=Router(records,[decision(a,third,'LINK'),decision(third,b,'UNLINK')])
    assert router.classify(c)=={'route':'operator','reasons':['manual_nonmatch']}
    assert not router.eligible(c)
    assert router.eligible(c,'adjudication')
    assert records==before


def test_invalid_role_comparison_cannot_enter_review():
    a,b,c=child_pair();c['kind']='family'
    assert Router({'a':a,'b':b}).classify(c)['reasons']==['invalid_roles']


def test_adult_year_conflict_requires_explicit_operator_purpose():
    a,b=rec('a',role='parent',child_id='child'),rec('b',120,role='parent',child_id='child')
    for r,y in [(a,1980),(b,1981)]:r['answer']['adult_demographics_05']=y
    c=candidate(a,b,'respondent','synthetic','pending','synthetic')
    router=Router({'a':a,'b':b})
    assert router.classify(c)=={'route':'operator','reasons':['adult_birth_year_conflict']}
    assert not router.eligible(c) and not router.eligible(c,'validation')
    assert router.eligible(c,'adjudication')
    b['child_id']='another-child'
    assert not Router({'a':a,'b':b}).eligible(c,'adjudication')


def test_adult_relationship_and_personal_contact_differences_are_not_conflicts():
    a,b=rec('a',role='parent',child_id='child'),rec('b',120,role='parent',child_id='child')
    for r,relation,own in [(a,0,'62345678'),(b,1,'63456789')]:
        r['answer'].update(adult_demographics_05=1980,adult_demographics_06=relation,contact_02=own)
    c=candidate(a,b,'respondent','synthetic','pending','synthetic')
    assert Router({'a':a,'b':b}).eligible(c)
    b['answer']['adult_demographics_05']=''
    assert Router({'a':a,'b':b}).classify(c)['route']=='correction'


def test_default_exports_pending_only_and_validation_is_explicit(project):
    cfg,cases=project
    p=core.create_package(cfg,'helper')
    assert {t['snapshot']['case']['status'] for t in p['tasks']}=={'pending'}
    # All fixture child records already share a published child identity.
    # Ordinary dispatch no longer repeats their pair comparisons.
    assert {t['snapshot']['case']['kind'] for t in p['tasks']}=={'respondent'}
    with pytest.raises(PipelineError,match='不屬此用途'):
        core.create_package(cfg,'helper',case_ids=[cases[1]])
    qa=core.create_package(cfg,'QA',case_ids=[cases[1]],purpose='validation')
    assert qa['purpose']=='validation' and len(qa['tasks'])==1


@pytest.mark.parametrize('mode', ['review','validation','adjudication'])
@pytest.mark.parametrize('independent', [False,True])
def test_explicit_ids_and_independent_review_cannot_bypass_child_conflict(project,mode,independent):
    cfg,cases=project
    db=connect(Path(cfg['state_dir']))
    row=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='a'").fetchone()[0])
    row['dob']='2011-01-01'
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='a'",(dumps(row),));db.commit();db.close()
    with pytest.raises(PipelineError,match='完整孩子生日不同'):
        core.create_package(cfg,'Jarvis',case_ids=[cases[0]],independent=independent,purpose=mode)


def test_queue_counts_do_not_call_untraceable_cases_missing_data(project):
    cfg,cases=project
    db=connect(Path(cfg['state_dir']))
    r=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='a'").fetchone()[0])
    r['answer']['contact_01']='';r['dob']=None
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='a'",(dumps(r),));db.commit()
    result=summary(core.Context(db,cfg))
    assert result['pending_routes']=={'untraceable':1,'review':1}
    assert result['reviewable_pending']==1 and 'correction' not in result['pending_routes']
    db.close()


@pytest.mark.parametrize('limit',[0,500])
def test_legacy_export_cannot_reintroduce_conflicting_or_untraceable_identity_cards(project,limit):
    import pandas as pd
    from study2.review import export_review
    cfg,cases=project
    db=connect(Path(cfg['state_dir']))
    r=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='a'").fetchone()[0])
    r['dob']='2011-01-01'
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='a'",(dumps(r),));db.commit()
    path=Path(cfg['state_dir'])/'legacy-filtered.xlsx'
    export_review(db,cfg,path,limit=limit)
    sheets=pd.read_excel(path,sheet_name=None).copy()
    assert cases[0] not in set(sheets['cases']['case_id'])
    assert set(sheets['cases']['case_id'])=={cases[2]}
    assert not sheets['submissions'].empty and 'schools' in sheets
    r['dob']='2012-01-01';r['answer']['contact_01']=''
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='a'",(dumps(r),));db.commit()
    export_review(db,cfg,path,limit=limit)
    assert cases[0] not in set(pd.read_excel(path,sheet_name='cases')['case_id'])
    db.close()
