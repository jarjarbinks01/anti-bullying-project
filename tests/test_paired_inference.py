"""Synthetic paired tests, identity continuity and displayed-cohort intersections."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import ttest_rel

from study2.common import PipelineError
from study2.descriptives import paired_changes, paired_inference
from study2.static_export import overview_changes, safe_changes


def sample(role='student', mode='acbd'):
    before = [0., 1., 2., 3., 2., 1., 4., 2., 3., 0., 1., 2.]
    after = [1., 3., 1., 4., 2., 2., 6., 3., 4., 1., 3., 1.]
    records=[]
    for index, (a, b) in enumerate(zip(before, after)):
        for wave, value in [('T0', a), ('T1', b)]:
            records.append(dict(child_id=f'unit-{index}', submission_id=f'{index}-{wave}',
                version_id=f'v-{index}-{wave}', wave=wave, report_mode=mode,
                adult_continuity_confirmed=mode=='acbd', anchor_gender='0',
                anchor_school_stage='primary', PHQ_total=value, SEC_total=2+value/12))
    result=pd.DataFrame(records);result.attrs['mode']=mode
    return result


def phq(frame):
    return paired_changes(frame, 'student').query("variable_id == 'PHQ_total'").iloc[0]


def test_paired_test_and_dz_match_direct_scipy_on_jointly_valid_aligned_people():
    frame=sample()
    frame.loc[frame['submission_id'].eq('0-T0'), 'PHQ_total']=None
    frame.loc[frame['submission_id'].eq('1-T1'), 'PHQ_total']=None
    result=phq(frame.sample(frac=1, random_state=9))
    wide=frame.pivot(index='child_id', columns='wave', values='PHQ_total').dropna()
    delta=wide['T1']-wide['T0']
    assert result['paired_valid_n']==10 and result['paired_missing_n']==2
    assert result['p_value']==pytest.approx(ttest_rel(wide['T1'],wide['T0']).pvalue)
    assert result['cohen_dz']==pytest.approx(delta.mean()/delta.std(ddof=1))
    assert result['mean_change']==pytest.approx(delta.mean())
    assert result['inference_status']=='estimated'
    reversed_result=paired_inference(-delta)
    assert reversed_result['p_value']==pytest.approx(result['p_value'])
    assert reversed_result['cohen_dz']==pytest.approx(-result['cohen_dz'])


@pytest.mark.parametrize('values,status', [([], 'insufficient_pairs'), ([1.], 'insufficient_pairs'),
    ([0.]*12, 'zero_change_variance'), ([2.]*12, 'zero_change_variance')])
def test_degenerate_differences_do_not_create_infinite_effects_or_fake_pvalues(values,status):
    assert paired_inference(values)==dict(p_value=None,cohen_dz=None,inference_status=status)


def test_nonfinite_values_and_duplicate_pair_keys_fail_closed():
    with pytest.raises(PipelineError):paired_inference([0., np.inf])
    with pytest.raises(PipelineError):paired_changes(pd.concat([sample(),sample().iloc[:1]]),'student')


def test_inference_suppression_requires_explicit_positive_threshold():
    changes=paired_changes(sample().iloc[:18],'student')
    visible=next(row for row in safe_changes(changes) if row['variable_id']=='PHQ_total')
    assert not visible['suppressed'] and visible['paired_valid_n']==9
    assert visible['p_value'] is not None and visible['cohen_dz'] is not None
    row=next(row for row in safe_changes(changes, minimum=10) if row['variable_id']=='PHQ_total')
    assert row['suppressed'] and row['p_value'] is None and row['cohen_dz'] is None
    assert row['paired_valid_n'] is None and row['inference_status']=='suppressed'


def test_overview_intersection_requires_exact_selected_submissions_and_versions():
    reference=sample('parent')
    selected=reference.copy()
    # A different adult/follow-up must not replace the approved BD submission.
    selected.loc[selected['submission_id'].eq('0-T1'),'submission_id']='another-adult-form'
    selected.loc[selected['submission_id'].eq('1-T1'),'version_id']='changed-version'
    result=overview_changes(selected,reference,'parent',('all',))
    row=result.query("variable_id == 'PHQ_total'").iloc[0]
    assert row['pairs_n']==10
    expected=reference[~reference['child_id'].isin(['unit-0','unit-1'])]
    assert row['p_value']==pytest.approx(phq(expected)['p_value'])


def test_overview_subgroup_requires_both_displayed_waves_in_that_group():
    reference=sample()
    selected=reference.copy()
    # Moving to secondary is visible only in that wave in an each-wave view.
    selected.loc[selected['submission_id'].eq('0-T1'),'anchor_school_stage']='secondary'
    results=overview_changes(selected,reference,'student',('all','primary','secondary'))
    counts=results.query("variable_id == 'PHQ_total'").set_index('group')['pairs_n'].to_dict()
    assert counts=={'all':12,'primary':11,'secondary':0}


def test_same_child_parent_membership_never_authorises_adult_phq_inference():
    reference=sample('parent','efmatched')
    reference['adult_continuity_confirmed']=False
    result=overview_changes(reference,reference,'parent',('all',))
    assert not result['variable_id'].str.startswith('PHQ_').any()
    assert result.query("variable_id == 'SEC_total'")['paired_valid_n'].iloc[0]==12
