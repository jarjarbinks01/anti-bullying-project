"""Synthetic T0/T1 fixtures only. No production paths, IDs, or databases."""
from copy import deepcopy

import pytest

from study2 import group_cleaning as policy
from study2 import group_decision_intents as intents
from study2.analysis_eligibility import sha
from study2.common import digest


def record(sid, *, role='student', child=None, contact='91230001', wave='T0'):
    raw={'synthetic':sid,'contact_01':contact}
    return dict(submission_id=sid,version_id='v-'+sid,role=role,raw_hash=digest(raw),raw=raw,
                answer={'contact_01':contact},child_id=child or 'CHILD_SYNTHETIC_'+sid,
                selected_wave=wave,status='eligible',dob='2010-01-01',gender='0',
                school='SYNTHETIC SCHOOL',source_id='synthetic_only')


def case(cid,a,b):
    return dict(case_id=cid,record_a=a,record_b=b,kind='identity',status='pending',
                rule='fuzzy_contact_child_demo')


def scope(gid,members,comparison_ids):
    return {gid:dict(case_id=gid,group_review=dict(members=members,comparison_ids=comparison_ids,
                  passed_pairs=[],conflicts=[],manual_restrictions=[]))}


def options(records,rid,*,partitions=None):
    return dict(release_id=rid,main_revision='a'*64,rules_hash='b'*64,
                eric_manifest=policy.exclusion_manifest(list(records.values()),rid,[],operator='SYNTHETIC',at='2026-01-01T00:00:00+00:00'),
                source_evidence={},partitions=partitions or {},user_exclusions={},
                authorization=dict(workbook_sha256='c'*64,request_sha256='d'*64,
                                   partition_groups=sorted(partitions or {}),user_exclusion_groups=[]))


@pytest.fixture
def original():
    records={'SYN_A':record('SYN_A'),'SYN_B':record('SYN_B',contact='91230002',wave='T1')}
    cases={'AB':case('AB','SYN_A','SYN_B')}
    groups=scope('GROUP_OLD',list(records),list(cases))
    proposal=policy.make_proposal(records,cases,groups,[],**options(records,'RUN_SYN_OLD',partitions={'GROUP_OLD':[['SYN_A'],['SYN_B']]}))
    receipt=dict(reason='SYNTHETIC explicit boundary answer',operation_id='synthetic-operation',
                 review=dict(accepted=True,proposal_revision=proposal['revision'],
                             reviewer='SYNTHETIC REVIEWER',reason='SYNTHETIC accepted answer'))
    collection=intents.migrate(proposal,records,cases,groups,receipt)
    return records,cases,groups,proposal,receipt,collection


def project(records,cases,groups,collection):
    return policy.make_proposal(records,cases,groups,[],decision_intents=collection,
                                **options(records,'RUN_SYN_NEW'))


def test_append_and_generated_group_change_preserve_full_intent_and_ids(original):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    before=deepcopy((records,cases,collection))
    records['SYN_UNRELATED']=record('SYN_UNRELATED',wave='T1')
    groups=scope('GROUP_NEW',['SYN_A','SYN_B'],['AB'])
    p=project(records,cases,groups,collection)
    assert p['decision_application']['entries'][0]['status']=='carried'
    assert p['projection']['pending_comparison_ids']==[]
    assert p['decision_intents']==collection
    assert collection['intents'][0]['origin']['receipt']==receipt
    assert collection['intents'][0]['subjects']==[intents.full_pin(before[0][s]) for s in ['SYN_A','SYN_B']]
    assert {s:records[s] for s in before[0]}==before[0]
    assert cases==before[1] and collection==before[2]
    assert project(records,cases,groups,collection)==p


def test_two_students_plus_parent_does_not_extend_answer(original):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    records['SYN_P']=record('SYN_P',role='parent',child=records['SYN_A']['child_id'])
    cases['PB']=case('PB','SYN_P','SYN_B')
    groups=scope('GROUP_THREE',list(records),['AB','PB'])
    p=project(records,cases,groups,collection)
    assert {c for row in p['projection']['closures'] for c in row['comparison_ids']}=={'AB'}
    assert p['projection']['pending_comparison_ids']==['PB']
    closure=next(row for row in p['projection']['closures'] if 'AB' in row['comparison_ids'])
    assert {pin['submission_id'] for pin in closure['member_pins']}=={'SYN_A','SYN_B'}
    assert 'SYN_P' not in closure['contact_evidence']
    assert p['decision_intents']==collection
    assert records['SYN_P']['child_id']==records['SYN_A']['child_id']


@pytest.mark.parametrize('change,reason',[
    ('version','source_pin_changed'),('school','relevant_evidence_changed'),('merge','supported_subgroup_boundary_changed')])
def test_changed_evidence_and_conflict_hold_only_authorized_scope(original,change,reason):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    records['SYN_C']=record('SYN_C',contact='91230003')
    records['SYN_D']=record('SYN_D',contact='91230004')
    cases['CD']=case('CD','SYN_C','SYN_D')
    groups.update(scope('GROUP_UNRELATED',['SYN_C','SYN_D'],['CD']))
    if change=='version':records['SYN_A']['version_id']='v-changed'
    elif change=='school':records['SYN_A']['school']='CHANGED SYNTHETIC SCHOOL'
    else:records['SYN_B']['child_id']=records['SYN_A']['child_id']
    p=project(records,cases,groups,collection)
    entry=next(e for e in p['decision_application']['entries'] if e['group_id']=='GROUP_OLD')
    assert entry['status']=='held' and reason in entry['reasons']
    assert p['projection']['scopes']['GROUP_UNRELATED']==policy.classify_scope(records,groups['GROUP_UNRELATED'],cases)
    assert p['decision_intents']==collection
    assert p['projection']['counts']['pending_decision_intents']==1
    assert p['group_dispositions']['intent_review_required']==1
    if change=='merge':
        assert p['projection']['holds']==[]  # No fabricated scientific edge.
        assert p['projection']['counts']['decision_intent_hold_scopes']==1
        assert p['projection']['counts']['remaining_open_group_scopes']==2
        assert p['projection']['intent_holds'][0]['status']=='held'
        assert 'AB' in p['projection']['pending_comparison_ids']


def test_no_transitive_or_new_comparison_semantics(original):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    cases['AB']['rule']='new_unreviewed_rule'
    p=project(records,cases,groups,collection)
    assert p['decision_application']['entries'][0]['status']=='held'
    assert 'comparison_not_in_original_authorized_scope' in p['decision_application']['entries'][0]['reasons']
    assert p['decision_application']['scientific_identity_changed'] is False
    assert p['decision_application']['permanent_nonmatch'] is False


def test_collection_tampering_and_unknown_semantics_never_close(original):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    collection['intents'][0]['reason']='changed without revision'
    with pytest.raises(Exception,match='intent_.*revision'):project(records,cases,groups,collection)
    item={k:v for k,v in original[-1]['intents'][0].items() if k!='revision'}
    item['kind']='ambiguous_legacy_negative'
    unknown=intents.sealed({'format':intents.FORMAT,'intents':[intents.sealed(item)]})
    p=project(records,cases,groups,unknown)
    assert p['decision_application']['entries'][0]['status']=='held'
    assert 'unknown_decision_semantics' in p['decision_application']['entries'][0]['reasons']


def test_scores_waves_and_source_records_are_not_written(original):
    records,cases,groups,proposal,receipt,collection=deepcopy(original)
    records['SYN_A'].update(score_total=None,raw_date='2026-01-01',adopted_date='2026-01-01')
    records['SYN_B'].update(score_total=0,adult_continuity_confirmed=False)
    before=deepcopy(records)
    project(records,cases,groups,collection)
    assert records==before
    assert records['SYN_A']['selected_wave']=='T0' and records['SYN_B']['selected_wave']=='T1'


def test_no_transitive_closure_for_a_new_ac_comparison():
    records={s:record(s,contact=p) for s,p in [('A','91230001'),('B','91230002'),('C','91230003')]}
    cases={'AB':case('AB','A','B'),'BC':case('BC','B','C')}
    groups=scope('GROUP_OLD',list(records),list(cases))
    original=policy.make_proposal(records,cases,groups,[],
        **options(records,'RUN_SYN_OLD',partitions={'GROUP_OLD':[['A'],['B'],['C']]}))
    receipt={'reason':'SYNTHETIC scoped answers','review':{'accepted':True,'proposal_revision':original['revision']}}
    collection=intents.migrate(original,records,cases,groups,receipt)
    cases['AC']=case('AC','A','C');groups=scope('GROUP_NEW',list(records),list(cases))
    p=project(records,cases,groups,collection)
    assert {c for row in p['projection']['closures'] for c in row['comparison_ids']}=={'AB','BC'}
    assert p['projection']['pending_comparison_ids']==['AC']
    assert p['decision_application']['permanent_nonmatch'] is False
