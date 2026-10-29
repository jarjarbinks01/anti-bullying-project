from copy import deepcopy
import pandas as pd
import pytest

from study2.bd_pairing import POLICY, selected_parent_pairs, selected_parent_rows
from study2.common import PipelineError


def fixture():
    frame=pd.DataFrame([
        ('child-a','a-b','parent','T0'),('child-a','a-d','parent','T1'),
        ('child-b','b-b','parent','T0'),('child-b','b-d','parent','T1'),
        ('child-c','c-b','parent','T0'),('child-c','c-d','parent','T1'),
        ('child-d','d-b','parent','T0'),('child-e','e-d','parent','T1'),
        ('child-a','a-s0','student','T0'),('child-a','a-s1','student','T1'),
    ],columns=['child_id','submission_id','role','wave'])
    tracking=pd.DataFrame([
        ('child-a','a-b','a-d','same','reviewer_confirmed_same_adult'),
        ('child-b','b-b','b-d','different','reviewer_rejected_same_adult'),
        ('child-c','c-b','other-followup','same','reviewer_confirmed_same_adult'),
    ],columns=['child_id','parent_t0_id','parent_t1_id','adult_status','adult_rule'])
    return frame,tracking


def test_selected_waves_define_pair_and_tracking_does_not_reselect():
    frame,tracking=fixture();before=frame.copy(deep=True);old=tracking.copy(deep=True)
    pairs=selected_parent_pairs(frame,tracking=tracking)
    assert POLICY=='selected_parent_waves_same_child_v1'
    assert pairs[['child_id','t0','t1']].to_records(index=False).tolist()==[
        ('child-a','a-b','a-d'),('child-b','b-b','b-d'),('child-c','c-b','c-d')]
    assert pairs.adult_status.tolist()==['same','different','unconfirmed']
    assert pairs.adult_rule.tolist()==['reviewer_confirmed_same_adult','reviewer_rejected_same_adult','']
    pd.testing.assert_frame_equal(frame,before);pd.testing.assert_frame_equal(tracking,old)


def test_excluded_member_removes_pair_without_replacement():
    frame,tracking=fixture()
    for removed in ({'a-b'},{'a-d'}):
        result=selected_parent_pairs(frame,tracking=tracking,excluded=removed)
        assert set(result.child_id)=={'child-b','child-c'}
        assert 'other-followup' not in set(result.t1)
    with pytest.raises(PipelineError,match='invalid_exclusion_set'):
        selected_parent_pairs(frame,excluded='a-b')


def test_pair_rows_keep_exact_slots_and_explicit_continuity():
    frame,tracking=fixture();pairs=selected_parent_pairs(frame,tracking=tracking)
    rows=selected_parent_rows(frame,pairs)
    assert len(rows)==6 and rows.longitudinal.all()
    assert rows.groupby('child_id').adult_continuity_confirmed.first().to_dict()=={
        'child-a':True,'child-b':False,'child-c':False}
    assert rows.groupby('child_id').bd_adult_status.first().to_dict()=={
        'child-a':'same','child-b':'different','child-c':'unconfirmed'}
    assert rows.bd_pairing_policy.eq(POLICY).all()


def test_unlinked_tracking_rows_do_not_supply_adult_evidence():
    frame,tracking=fixture()
    unlinked=pd.DataFrame([(None,'c-b','c-d','same','reviewer_confirmed_same_adult')],columns=tracking.columns)
    result=selected_parent_pairs(frame,tracking=pd.concat([tracking,unlinked],ignore_index=True))
    assert result.set_index('child_id').loc['child-c','adult_status']=='unconfirmed'


def test_exact_case_evidence_survives_without_a_registered_dyad():
    from study2.bd_pairing import selected_pairs_with_case_evidence
    frame,tracking=fixture()
    cases=[dict(kind='respondent',record_a='c-b',record_b='c-d',status='confirmed',
                rule='reviewer_confirmed_same_adult')]
    result=selected_pairs_with_case_evidence(frame,tracking,cases).set_index('child_id')
    assert result.loc['child-c','adult_status']=='same'
    # Conflicting exact cases do not establish continuity.
    cases.append(dict(kind='respondent',record_a='c-b',record_b='c-d',status='rejected',
                      rule='reviewer_rejected_same_adult'))
    result=selected_pairs_with_case_evidence(frame,tracking,cases).set_index('child_id')
    assert result.loc['child-c','adult_status']=='unconfirmed'


def test_ambiguous_or_fabricated_inputs_fail_closed():
    frame,tracking=fixture()
    with pytest.raises(PipelineError,match='duplicate_selected_parent_slot'):
        selected_parent_pairs(pd.concat([frame,frame.iloc[[0]]],ignore_index=True))
    with pytest.raises(PipelineError,match='invalid_tracking_child'):
        selected_parent_pairs(frame,tracking=pd.concat([tracking,tracking.iloc[[0]]],ignore_index=True))
    invalid=tracking.copy();invalid.loc[0,'adult_status']='maybe'
    with pytest.raises(PipelineError,match='invalid_adult_status'):
        selected_parent_pairs(frame,tracking=invalid)
    pairs=selected_parent_pairs(frame);pairs.loc[0,'t1']='invented-followup'
    with pytest.raises(PipelineError,match='pair_members_missing'):
        selected_parent_rows(frame,pairs)


def test_mixed_adult_evidence_keeps_per_wave_phq_and_child_report_changes():
    from study2.descriptives import cohort, paired_changes, statistics
    frame,tracking=fixture()
    frame=frame.assign(gender='0',school_stage='primary',school='synthetic',mainstream=True,
                       source_type='paperform',identity_rules='',PHQ_total=2.,SEC_total=3.)
    frame.loc[frame.wave.eq('T1'),'PHQ_total']=4.
    frame.loc[frame.wave.eq('T1'),'SEC_total']=4.
    pairs=selected_parent_pairs(frame,tracking=tracking)
    parents=selected_parent_rows(frame,pairs)
    measurements=pd.DataFrame({'submission_id':frame.submission_id,
                               'descriptive_dictionary_version':'synthetic'})
    rows=cohort(frame,parents,measurements,'acbd','parent')
    assert rows.groupby('child_id').adult_continuity_confirmed.first().to_dict()=={
        'child-a':True,'child-b':False,'child-c':False}
    stats=statistics(rows,'parent')
    phq=stats.loc[stats.variable_id.eq('PHQ_total')]
    assert set(phq.wave)=={'T0','T1'} and phq.valid_n.tolist()==[3,3]
    changes=paired_changes(rows,'parent')
    assert 'PHQ_total' not in set(changes.variable_id)
    assert changes.loc[changes.variable_id.eq('SEC_total'),'paired_valid_n'].tolist()==[3]


def test_partial_or_contradictory_bd_evidence_never_implies_same_adult():
    from study2.descriptives import cohort
    frame,tracking=fixture()
    frame=frame.assign(gender='0',school_stage='primary',school='synthetic',mainstream=True,
                       source_type='paperform',identity_rules='')
    parents=selected_parent_rows(frame,selected_parent_pairs(frame,tracking=tracking))
    measurements=pd.DataFrame({'submission_id':frame.submission_id,
                               'descriptive_dictionary_version':'synthetic'})
    with pytest.raises(PipelineError,match='evidence is incomplete'):
        cohort(frame,parents.drop(columns='bd_adult_status'),measurements,'acbd','parent')
    parents.loc[parents.bd_adult_status.eq('different'),'adult_continuity_confirmed']=True
    with pytest.raises(PipelineError,match='evidence is incomplete'):
        cohort(frame,parents,measurements,'acbd','parent')
