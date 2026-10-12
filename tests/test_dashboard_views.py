import pandas as pd
import pytest

from study2.common import PipelineError
from study2.dashboard_views import analysis_cohort, selected_sample, sample_display, sample_reconciliation, source_wave_counts


@pytest.fixture
def samples():
    def row(sid, child, role, wave, mainstream=True, longitudinal=True):
        return {"submission_id": sid, "child_id": child, "role": role, "wave": wave,
                "mainstream": mainstream, "longitudinal": longitudinal,
                "dyad": child == 'x', "longitudinal_dyad": child == 'x',
                "child_report_longitudinal": child == 'x', "school": 'School', "grade": 3,
                "PHQ_total": 7, "raw": {"phone": 'synthetic'}, "dob": 'synthetic'}
    frame = pd.DataFrame([row('s0', 'x', 'student', 'T0'), row('s1', 'x', 'student', 'T1'),
                          row('mother0', 'x', 'parent', 'T0'), row('father_latest', 'x', 'parent', 'T1', longitudinal=False),
                          row('other_school_s0', 'y', 'student', 'T0', mainstream=False, longitudinal=False)])
    parents = pd.DataFrame([row('mother0', 'x', 'parent', 'T0'), row('mother_followup', 'x', 'parent', 'T1')])
    return frame, parents


def test_final_samples_count_groups_and_keep_bd_alternative_followup(samples):
    frame, parents = samples
    summary = dict(A=2, B=1, C=1, D=1, AC=1, BD=1, E=1, F=1, EF=1, parent_child_longitudinal=1)
    check = sample_reconciliation(frame, parents, summary)
    assert set(check['核對']) == {'一致'}
    bd = selected_sample(frame, parents, 'BD')
    family = selected_sample(frame, parents, 'EF')
    assert bd.iloc[0]['parent_T1_submission_id'] == 'mother_followup'
    assert family.iloc[0]['parent_T1_submission_id'] == 'father_latest'
    assert len([col for col in family if col.endswith('_submission_id')]) == 4


def test_analysis_all_schools_reproduces_overview_and_bd_uses_same_adult(samples):
    frame, parents = samples
    baseline = analysis_cohort(frame, parents, 'student', 'T0', '全部保留樣本')
    assert len(baseline) == 2 and baseline['mainstream'].sum() == 1
    bd = analysis_cohort(frame, parents, 'parent', 'T1', '跨期配對樣本')
    family = analysis_cohort(frame, parents, 'parent', 'T1', '親子配對樣本')
    assert bd['submission_id'].tolist() == ['mother_followup']
    assert family['submission_id'].tolist() == ['father_latest']


def test_display_only_contains_safe_selected_membership(samples):
    frame, parents = samples
    view = sample_display(selected_sample(frame, parents, 'EF'), 'EF')
    assert 'raw' not in str(view.columns) and 'PHQ_total' not in str(view.columns)
    assert 'dob' not in str(view.columns)
    assert set(c for c in view if c.endswith('_提交ID')) == {'學生T0_提交ID', '學生T1_提交ID', '家長T0_提交ID', '家長T1_提交ID'}


def test_duplicate_slot_cannot_silently_inflate_final_samples(samples):
    frame, parents = samples
    broken = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(PipelineError, match='不唯一'):
        selected_sample(broken, parents, 'AC')


def test_reconciliation_exposes_published_count_mismatch(samples):
    frame, parents = samples
    check = sample_reconciliation(frame, parents, {'AC': 3})
    assert check.iloc[0].to_dict() == {'樣本': 'AC｜學生 T0／T1', '首頁／版本組數': 3, '明細組數': 1, '核對': '不一致'}


def test_source_totals_use_original_and_final_waves_and_preserve_unknown_sources():
    imported = pd.DataFrame([
        {'source_type': 'legacy_online', 'role': 'student', 'wave': 'T0', 'submissions': 3},
        {'source_type': 'qualtrics', 'role': 'student', 'wave': 'T1', 'submissions': 2},
        {'source_type': 'paperform', 'role': 'parent', 'wave': 'T0', 'submissions': 4},
        {'source_type': None, 'role': 'parent', 'wave': 'T0', 'submissions': 1},
    ])
    selected = pd.DataFrame([
        {'source_type': 'qualtrics', 'role': 'student', 'wave': 'T0'},
        {'source_type': 'legacy_online', 'role': 'student', 'wave': 'T0'},
        {'source_type': 'legacy_online', 'role': 'student', 'wave': 'T1'},
        {'source_type': 'paperform', 'role': 'parent', 'wave': 'T0'},
        {'source_type': None, 'role': 'parent', 'wave': 'T0'},
    ])
    counts = source_wave_counts(imported, selected).set_index('來源')
    assert counts.loc['合計'].to_dict() == {'匯入 T0': 8, '匯入 T1': 2, '匯入合計': 10,
                                          '最終 T0': 4, '最終 T1': 1, '最終合計': 5}
    assert counts.loc['Qualtrics', '匯入 T1'] == 2
    assert counts.loc['Qualtrics', '最終 T0'] == 1
    assert counts.loc['其他／未識別來源', '匯入合計'] == counts.loc['其他／未識別來源', '最終合計'] == 1
    assert counts.loc['學校批次'].eq(0).all()
    student = source_wave_counts(imported, selected, 'student').iloc[-1]
    parent = source_wave_counts(imported, selected, 'parent').iloc[-1]
    assert student['匯入合計'] == parent['匯入合計'] == 5
    assert student['最終合計'] == 3 and parent['最終合計'] == 2


def test_source_totals_cannot_silently_drop_an_unknown_wave():
    imported = pd.DataFrame([{'source_type': 'paperform', 'role': 'student', 'wave': 'T2', 'submissions': 1}])
    selected = pd.DataFrame(columns=['source_type', 'role', 'wave'])
    with pytest.raises(PipelineError, match='未識別值'):
        source_wave_counts(imported, selected)
