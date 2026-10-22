"""G1/G2 synthetic oracles: exact slots, four states, safe numeric projection."""
import json

import numpy as np
import pandas as pd
import pytest

from study2.common import PipelineError
from study2.descriptive_spec import GROUPS
from study2.descriptives import filter_cohort, group_rows, paired_changes, statistics
from study2.static_export import (CHANGE_FIELDS, PAIR_DETAIL_FIELDS, build_views,
                                 overview_changes, pack_snapshot, pair_details, safe_changes)
from test_static_export import rows, snapshot


def panel(a, b, role='student', mode='acbd', adult=True):
    frame = rows(role, mode, adult).iloc[:2*len(a)].copy()
    frame.loc[frame.wave.eq('T0'), 'PHQ_total'] = np.asarray(a, dtype=float)
    frame.loc[frame.wave.eq('T1'), 'PHQ_total'] = np.asarray(b, dtype=float)
    return frame


def detail(frame, role='student'):
    return next(r for r in safe_changes(pair_details(frame, role, ('all',)))
                if r['variable_id'] == 'PHQ_total')


def test_g12_two_bases_have_different_means_without_changing_inference():
    frame = panel([2., 10., 6.], [4., None, 5.])
    row = detail(frame)
    assert [row[k] for k in ('pairs_n', 'paired_valid_n', 'only_t0_valid_n',
                            'only_t1_valid_n', 'both_missing_n')] == [3, 2, 1, 0, 0]
    wave = statistics(frame, 'student').query("variable_id == 'PHQ_total'").set_index('wave')
    assert wave.loc['T0', 'mean'] == 6 and wave.loc['T1', 'mean'] == 4.5
    assert row['t0_mean'] == 4 and row['t1_mean'] == 4.5 and row['mean_change'] == .5
    original = paired_changes(frame, 'student').query("variable_id == 'PHQ_total'").iloc[0]
    for field in ('mean_change', 'sd_change', 'p_value', 'cohen_dz', 'inference_status'):
        assert row[field] == original[field]


def test_g12_four_states_and_independent_metric_missingness_are_not_combined():
    frame = panel([0., 2., 10., None, None], [2., 4., None, 8., None])
    row = detail(frame)
    assert [row[k] for k in ('pairs_n', 'paired_valid_n', 'only_t0_valid_n',
                            'only_t1_valid_n', 'both_missing_n', 'paired_missing_n')] == [5, 2, 1, 1, 1, 3]
    assert row['t0_mean'] == 1 and row['t1_mean'] == 3
    other = pair_details(frame, 'student', ('all',)).query("variable_id == 'SEC_total'").iloc[0]
    assert other.paired_valid_n == 5 and other.both_missing_n == 0


@pytest.mark.parametrize('a,b,status', [([1.], [2.], 'insufficient_pairs'),
    ([1., 2.], [1., 2.], 'zero_change_variance'), ([None], [None], 'insufficient_pairs')])
def test_g12_undefined_tests_keep_means_and_states_without_invented_pvalues(a, b, status):
    row = detail(panel(a, b))
    assert row['inference_status'] == status and row['p_value'] is None and row['cohen_dz'] is None
    if a == [None]:
        assert row['t0_mean'] is None and row['t1_mean'] is None and row['both_missing_n'] == 1
    else:
        assert row['t0_mean'] == np.mean(a) and row['t1_mean'] == np.mean(b)


@pytest.mark.parametrize('corrupt', ['duplicate', 'missing_slot', 'submission_duplicate'])
def test_g12_formal_pair_corruption_is_not_silently_repaired(corrupt):
    frame = panel([1., 2.], [2., 4.])
    if corrupt == 'duplicate': frame = pd.concat([frame, frame.iloc[:1]])
    if corrupt == 'missing_slot': frame = frame.iloc[:-1]
    if corrupt == 'submission_duplicate': frame.loc[1, 'submission_id'] = frame.loc[0, 'submission_id']
    with pytest.raises(PipelineError): pair_details(frame, 'student', ('all',))


def test_g12_overview_uses_actual_bd_slots_versions_and_group_intersections():
    reference = panel([2., 3., 4., 5.], [4., 4., 3., 6.], 'parent')
    selected = reference.copy()
    selected.loc[1, 'submission_id'] = 'alternative-adult-followup'
    selected.loc[3, 'version_id'] = 'a-different-source-version'
    selected.loc[5, 'anchor_school_stage'] = 'secondary'
    result = safe_changes(overview_changes(selected, reference, 'parent', ('all', 'primary', 'secondary')))
    phq = {r['group']: r for r in result if r['variable_id'] == 'PHQ_total'}
    assert phq['all']['pairs_n'] == 2 and phq['all']['t0_mean'] == 4.5
    assert phq['all']['t1_mean'] == 4.5 and phq['primary']['pairs_n'] == 1
    assert phq['primary']['t0_mean'] == 5 and phq['secondary']['pairs_n'] == 0
    assert phq['secondary']['paired_valid_n'] == 0 and phq['secondary']['t0_mean'] is None
    assert set(reference['submission_id']) == set(panel([2., 3., 4., 5.], [4., 4., 3., 6.], 'parent')['submission_id'])


@pytest.mark.parametrize('mode,adult', [('efmatched', True), ('independent_child_report', True),
    ('acbd', False), ('independent_same_adult', False)])
def test_g12_parent_phq_guard_is_not_inferred_from_mode_or_same_child(mode, adult):
    frame = panel([1., 2.], [2., 4.], 'parent', mode, adult)
    assert not pair_details(frame, 'parent', ('all',))['variable_id'].str.startswith('PHQ_').any()


def test_g12_removing_a_dangling_unconfirmed_adult_does_not_enable_phq():
    reference = panel([1., 2.], [2., 4.], 'parent')
    reference.loc[2, 'adult_continuity_confirmed'] = False
    selected = reference.loc[reference.index != 3].copy()
    result = overview_changes(selected, reference, 'parent', ('all',))
    assert not result['variable_id'].str.startswith('PHQ_').any()
    assert result.query("variable_id == 'SEC_total'").iloc[0]['pairs_n'] == 1


def test_g12_positive_threshold_hides_all_new_numeric_fields_and_pack_roundtrips():
    frame = panel([1.]*19+[2.], [2.]*19+[None])
    raw = pair_details(frame, 'student', ('all',))
    visible = next(r for r in safe_changes(raw, 0) if r['variable_id'] == 'PHQ_total')
    assert visible['only_t0_valid_n'] == 1 and visible['both_missing_n'] == 0
    hidden = next(r for r in safe_changes(raw, 10) if r['variable_id'] == 'PHQ_total')
    for field in CHANGE_FIELDS:
        if field not in {'group', 'variable_id', 'variable', 'unit', 'inference_status', 'pair_detail_status'}:
            assert hidden[field] is None, field
    assert hidden['pair_detail_status'] == hidden['inference_status'] == 'suppressed'
    value = {**snapshot(), 'views': [dict(statistics=[], changes=[visible, hidden])]}
    packed = pack_snapshot(value)['views'][0]['changes']
    assert [dict(zip(packed['columns'], r)) for r in packed['rows']] == [visible, hidden]
    assert value['views'][0]['changes'] == [visible, hidden]


def test_g12_absent_score_columns_remain_explicitly_unavailable():
    frame = panel([1., 2.], [2., 4.]).drop(columns='PHQ_total')
    raw = pair_details(frame, 'student', ('all',))
    row = next(r for r in safe_changes(raw) if r['variable_id'] == 'PHQ_total')
    assert row['pair_detail_status'] == 'not_provided'
    assert all(row[key] is None for key in PAIR_DETAIL_FIELDS)


def test_g12_legacy_minimal_inference_caller_has_no_invented_exploration_anchor():
    frame = panel([1., 2.], [2., 4.]).drop(columns='grouping_anchor')
    row = detail(frame)
    assert row['paired_valid_n'] == 2 and row['mean_change'] == 1.5
    assert row['pair_detail_status'] == 'not_provided' and row['t0_mean'] is None


def test_g12_existing_mode_role_school_source_group_projections(tmp_path, monkeypatch):
    import study2.static_export as module
    import study2.parent_panel_views as parent_views
    originals = {}
    def scope(role, mode):
        frame = panel([0., 2., 10., None, 2., 3., 4., 5.],
                      [2., 4., None, 8., 3., 2., 4., 6.], role, mode,
                      adult=mode in {'acbd', 'independent_same_adult'})
        for index in range(8):
            mask = frame['child_id'].eq('person-'+str(index))
            frame.loc[mask, 'anchor_gender'] = str(index % 2)
            frame.loc[mask, 'anchor_school_stage'] = 'primary' if index % 4 < 2 else 'secondary'
            frame.loc[mask, 'anchor_mainstream'] = index % 3 != 0
            frame.loc[mask, 'anchor_source_type'] = list(module.SOURCE_NAMES)[index % len(module.SOURCE_NAMES)]
        return frame
    for mode in module.MODES:
        for role in ('student', 'parent'):
            originals[mode, role] = scope(role, mode)
    def fake_cohort(frame, parents, measurements, mode, role):
        return originals[mode, role].copy()
    def fake_independent(frame, measurements, branch, paired):
        mode = 'independent_same_adult' if branch == 'same_adult' else 'independent_child_report'
        result = scope('parent', mode)
        if not paired:
            # An unpaired baseline belongs in the overview, not its paired block.
            extra = result.iloc[:1].copy()
            extra['child_id'] = 'unpaired-unit'; extra['submission_id'] = 'unpaired-form'
            extra['version_id'] = 'unpaired-version'
            result = pd.concat([result, extra], ignore_index=True)
        result.attrs['mode'] = mode
        return result
    monkeypatch.setattr(module, 'cohort', fake_cohort)
    monkeypatch.setattr(module, 'independent_cohort', fake_independent)
    monkeypatch.setattr(parent_views, 'read_panel', lambda folder: {'analysis': pd.DataFrame()})
    monkeypatch.setattr(parent_views, 'verify_panel', lambda *args: None)
    (tmp_path/'independent_parent_analysis.parquet').touch()
    # Only this test skips the unchanged histogram/date services. Actual bins
    # and date downloads have their own exporter and browser checks.
    monkeypatch.setattr(module, '_exploration', lambda *args: [])
    monkeypatch.setattr(module, '_trends', lambda *args: [])
    monkeypatch.setattr(module, '_binary_pairs', lambda *args: [])
    views = build_views(None, pd.DataFrame(), None, {'release_id': 'synthetic-release',
                        'independent_parent': True}, tmp_path, 0)
    assert len(views) == 11*2*(1+len(module.SOURCE_NAMES))
    for view in views:
        assert view['grouping_anchor'] and view['source_filter_anchor']
        if view['mode'] in {'abcd', 'ef', 'acbd', 'efmatched'}:
            base = originals[view['mode'], view['role']]
        else:
            branch = 'same_adult' if view['mode'] == 'independent_adult' else 'child_report'
            base = fake_independent(None, None, branch, view['mode'] != 'independent_all')
        selected, _ = filter_cohort(base, mainstream=view['mainstream'],
            sources=() if view['source'] == 'all' else (view['source'],))
        for row in view['changes']:
            assert set(CHANGE_FIELDS) <= set(row)
            if row['pair_detail_status'] != 'available': continue
            assert row['pairs_n'] == sum(row[key] for key in ('paired_valid_n',
                'only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n'))
            if row['paired_valid_n']:
                assert row['mean_change'] == pytest.approx(row['t1_mean']-row['t0_mean'])
            if row['variable_id'] == 'PHQ_total':
                block = group_rows(selected, row['group'])
                wide = block.pivot(index='child_id', columns='wave', values='PHQ_total').reindex(columns=['T0','T1'])
                # The invented overview-only baseline is not a formal pair.
                wide = wide.loc[wide.index != 'unpaired-unit']
                both = wide.dropna()
                assert row['paired_valid_n'] == len(both)
                if len(both):
                    assert row['t0_mean'] == both['T0'].mean() and row['t1_mean'] == both['T1'].mean()
        for group in GROUPS:
            rows_in_group = [r for r in view['changes'] if r['group'] == group]
            if view['mode'] in {'acbd', 'efmatched', 'independent_child', 'independent_adult'}:
                assert rows_in_group
        if view['mode'] == 'independent_all':
            assert view['counts']['all']['T0'] >= view['counts']['all']['T1']
            assert all(r['pairs_n'] <= view['counts'][r['group']]['T1'] for r in view['changes'])
        if view['role'] == 'parent' and view['mode'] in {'ef', 'efmatched', 'independent_all', 'independent_child'}:
            assert not any(r['variable_id'].startswith('PHQ_') for r in view['changes'])


def test_g12_hidden_paired_partition_cannot_reappear_as_histogram_n(tmp_path, monkeypatch):
    import study2.static_export as module
    frame = panel([1.]*19+[2.], [2.]*19+[None])
    frame['anchor_mainstream'] = True
    monkeypatch.setattr(module, 'cohort', lambda *args: frame.copy())
    monkeypatch.setattr(module, 'MODES', {'acbd': 'Formal pairs'})
    monkeypatch.setattr(module, 'SOURCE_NAMES', {})
    monkeypatch.setattr(module, 'GROUPS', {'all': 'All'})
    monkeypatch.setattr(module, '_trends', lambda *args: [])
    monkeypatch.setattr(module, '_binary_pairs', lambda *args: [])
    views = build_views(None, pd.DataFrame(), None, {'release_id': 'synthetic-release'}, tmp_path, 10)
    for view in views:
        phq = [r for r in view['paired_histograms'] if r['variable_id'] == 'PHQ_total']
        assert phq and all(r['count'] is None and r['bin_left'] is None for r in phq)
        assert all(r['count'] is not None for r in view['histograms'] if r['variable_id'] == 'PHQ_total')
