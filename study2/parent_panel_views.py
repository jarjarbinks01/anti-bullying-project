"""Safe, reproducible dashboard views of one independent-parent release."""
from pathlib import Path

import pandas as pd

from .common import PipelineError
from .parent_panel import ADULT, CHILD


def read_panel(folder):
    return {name: pd.read_parquet(Path(folder) / ('independent_parent_' + name + '.parquet'))
            for name in ('analysis', 'pairs', 'audit', 'candidates', 'sensitivity')}


def reconcile_panel(data, summary):
    analysis, pairs, audit = data['analysis'], data['pairs'], data['audit']
    rows = []
    for key, title, actual in [
        ('parent_submissions', '家長提交追查', len(audit)),
        ('baselines', '獨立家長基線', int(((analysis['panel_branch'] == CHILD) & (analysis['panel_wave'] == 'T0')).sum())),
        ('child_report_pairs', '同一孩子跨期組數（可換填卷人）', int(pairs['panel_branch'].eq(CHILD).sum())),
        ('same_adult_pairs', '同一成人跨期組數', int(pairs['panel_branch'].eq(ADULT).sum())),
    ]:
        expected = summary[key]
        rows.append({'項目': title, '發布數量': expected, '明細數量': actual,
                     '核對': '一致' if expected == actual else '不一致'})
    return pd.DataFrame(rows)


def verify_panel(data, summary):
    """Validate counts, unique slots and exact selected IDs, not just totals."""
    report = reconcile_panel(data, summary)
    if not report['核對'].eq('一致').all():
        raise PipelineError('Independent parent summary and published rows do not reconcile')
    analysis, pairs, audit = data['analysis'], data['pairs'], data['audit']
    if analysis.duplicated(['panel_branch', 'child_id', 'panel_wave']).any():
        raise PipelineError('Independent parent measurement slots are not unique')
    if audit['submission_id'].duplicated().any():
        raise PipelineError('Independent parent audit counts one submission more than once')
    slots = {(r.panel_branch, r.child_id, r.panel_wave): r.submission_id
             for r in analysis.itertuples()}
    baseline_ids = {r.child_id: r.submission_id for r in analysis.itertuples()
                    if r.panel_branch == CHILD and r.panel_wave == 'T0'}
    if pairs.duplicated(['panel_branch', 'child_id']).any():
        raise PipelineError('Independent parent pairs are not unique')
    for pair in pairs.to_dict('records'):
        if pair['interval_days'] < summary['minimum_followup_days']:
            raise PipelineError('Independent parent followup is below the date threshold')
        if baseline_ids.get(pair['child_id']) != pair['t0']:
            raise PipelineError('Independent parent branches do not share the same baseline')
        for key, wave in [('t0', 'T0'), ('t1', 'T1')]:
            if slots.get((pair['panel_branch'], pair['child_id'], wave)) != pair[key]:
                raise PipelineError('Independent parent pair and analysis IDs disagree')
    for branch in (CHILD, ADULT):
        expected = pairs[pairs['panel_branch'] == branch]
        actual = analysis[(analysis['panel_branch'] == branch) & analysis['panel_longitudinal'].astype(bool)]
        if len(actual) != 2 * len(expected):
            raise PipelineError('Independent parent complete-panel membership disagrees')
    if summary['one_digit_candidates'] != int(data['candidates']['one_digit_candidate'].sum()):
        raise PipelineError('Independent parent experiment counts disagree')
    return report


def panel_cohort(frame, branch, wave, longitudinal=False, mainstream=False, gender=None,
                 schools=(), school_types=(), sources=()):
    rows = frame[(frame['panel_branch'] == branch) & (frame['panel_wave'] == wave)].copy()
    if longitudinal:
        rows = rows[rows['panel_longitudinal'].fillna(False).astype(bool)]
    if mainstream:
        rows = rows[rows['mainstream'].fillna(False).astype(bool)]
    if gender is not None:
        rows = rows[rows['gender'].fillna('').astype(str) == gender]
    for column, values in [('school', schools), ('school_type', school_types), ('source_type', sources)]:
        if values:
            rows = rows[rows[column].isin(values)]
    return rows


def pairs_for_cohort(pairs, cohort, branch, wave):
    key = 't0' if wave == 'T0' else 't1'
    return pairs[pairs['panel_branch'].eq(branch) & pairs[key].isin(cohort['submission_id'])].copy()
