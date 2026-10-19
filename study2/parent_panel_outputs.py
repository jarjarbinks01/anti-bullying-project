"""Versioned independent-parent outputs; measurement scores are shared."""
import json

import pandas as pd

from .artifacts import write_json_lines
from .common import dumps, timestamp
from .parent_panel import ADULT, CHILD, POLICY


def write_parent_panel(folder, panel, by_id, analysis_row, labels):
    from .outputs import write_excel

    child_by_id = {p['child_id']: p for p in panel.child_pairs}
    adult_by_id = {p['child_id']: p for p in panel.adult_pairs}
    comparisons = []
    for item in panel.comparisons:
        row = dict(item)
        first, last = by_id[row['t0']], by_id[row['t1']]
        canonical = sorted([first, last], key=lambda r: r['submission_id'])
        label = labels.get(row['case_id'])
        payload = json.loads(label['payload_json']) if label else {}
        current = bool(label and all(payload.get('version_' + side) == r['version_id']
                                     for side, r in zip(('a', 'b'), canonical)))
        row.update(verification_label=label['label'] if current else 'NOT_REVIEWED_CURRENT_VERSIONS',
                   manual_decision=row['exact_rule'] in {'reviewer_confirmed_same_adult', 'reviewer_rejected_same_adult'},
                   selected_exact=adult_by_id.get(row['child_id'], {}).get('t1') == row['t1'],
                   interval_days=(timestamp(last['observed_at']) - timestamp(first['observed_at'])).total_seconds() / 86400)
        for wave, record in [('T0', first), ('T1', last)]:
            row.update({wave + '_' + k: record.get(k) for k in
                        ('version_id', 'observed_at', 'time_confidence', 'date_basis', 'school', 'claimed_wave')})
        comparisons.append(row)
    comparison_columns = ['case_id', 'child_id', 't0', 't1', 'exact_status', 'exact_rule', 'exact_reason',
                          'experiment_status', 'experiment_rule', 'experiment_reason', 'experiment_selection_issue',
                          'one_digit_candidate', 'verification_label', 'manual_decision', 'selected_exact', 'interval_days']
    comparison_columns += [w + '_' + k for w in ('T0', 'T1') for k in
                           ('version_id', 'observed_at', 'time_confidence', 'date_basis', 'school', 'claimed_wave')]
    comparison_frame = pd.DataFrame(comparisons, columns=comparison_columns)
    comparison_lookup = {(r['t0'], r['t1']): r for r in comparisons}
    pair_rows, analysis_rows = [], []

    def measurement(record, branch, wave, longitudinal):
        row = analysis_row(record, wave)
        for key in ('longitudinal', 'child_report_longitudinal', 'dyad', 'longitudinal_dyad'):
            row.pop(key, None)
        row.update(panel_branch=branch, panel_wave=wave, panel_longitudinal=longitudinal,
                   version_id=record.get('version_id'), observed_at=record.get('observed_at'),
                   claimed_wave=record.get('claimed_wave'), anchored_wave=record.get('selected_wave'),
                   policy=POLICY)
        return row

    for baseline in panel.baselines:
        analysis_rows.append(measurement(by_id[baseline['t0']], CHILD, 'T0', baseline['child_id'] in child_by_id))
    for branch, pairs in [(CHILD, panel.child_pairs), (ADULT, panel.adult_pairs)]:
        for pair in pairs:
            first, last = by_id[pair['t0']], by_id[pair['t1']]
            comparison = comparison_lookup[(pair['t0'], pair['t1'])]
            row = {**pair, 'panel_branch': branch, 'policy': POLICY,
                   'interval_days': comparison['interval_days'],
                   'adult_status': comparison['exact_status'], 'adult_rule': comparison['exact_rule'],
                   'verification_label': comparison['verification_label']}
            for wave, record in [('T0', first), ('T1', last)]:
                row.update({wave + '_' + k: record.get(k) for k in
                            ('version_id', 'observed_at', 'school', 'grade', 'time_confidence', 'date_basis', 'claimed_wave',
                             'adult_birth_year_status')})
                row[wave + '_adult_identity_exception'] = (record.get('adult_identity_exception') or {}).get('type')
                row[wave + '_anchored_wave'] = record.get('selected_wave')
                row[wave + '_submission_id'] = record['submission_id']
            pair_rows.append(row)
            if branch == ADULT:
                analysis_rows.append(measurement(first, branch, 'T0', True))
            analysis_rows.append(measurement(last, branch, 'T1', True))
    # Empty releases retain a usable, safe schema for the dashboard and exports.
    analysis_columns = list(dict.fromkeys([k for r in analysis_rows for k in r])) or [
        'submission_id', 'child_id', 'role', 'wave', 'panel_branch', 'panel_wave', 'panel_longitudinal',
        'mainstream', 'gender', 'school', 'school_type', 'source_type', 'age_at_observation']
    analysis = pd.DataFrame(analysis_rows, columns=analysis_columns)
    pair_columns = list(dict.fromkeys([k for r in pair_rows for k in r])) or [
        'child_id', 't0', 't1', 'panel_branch', 'interval_days', 'adult_status', 'adult_rule',
        'T0_submission_id', 'T1_submission_id']
    pairs = pd.DataFrame(pair_rows, columns=pair_columns)
    audit_rows = []
    for entry in panel.audit:
        record = by_id[entry['submission_id']]
        row = {**entry, 'policy': POLICY,
               **{k: record.get(k) for k in ('source_id', 'source_label', 'source_key', 'claimed_wave',
                                             'observed_at', 'time_confidence', 'date_basis', 'selected_wave', 'status')},
               'source_location': dumps(record.get('location', {}))}
        row['adult_birth_year_status'] = record.get('adult_birth_year_status', '')
        row['adult_identity_exception_type'] = (record.get('adult_identity_exception') or {}).get('type', '')
        row['adult_identity_exception_json'] = dumps(record.get('adult_identity_exception'))
        for field in ('t0_id', 'child_report_T1_id', 'same_adult_T1_id'):
            row[field + '_selected'] = entry[field] == entry['submission_id']
        audit_rows.append(row)
    audit = pd.DataFrame(audit_rows, columns=list(audit_rows[0]) if audit_rows else
                         ['submission_id', 'panel_status', 'child_id', 't0_id'])
    experiment = {p['child_id']: p for p in panel.shadow_pairs}
    sensitivity = []
    for child in sorted(experiment.keys() | adult_by_id.keys()):
        exact, alternative = adult_by_id.get(child, {}), experiment.get(child, {})
        category = ('experiment_added_child' if not exact else 'experiment_held_exact_child' if not alternative else
                    'different_T1' if exact['t1'] != alternative['t1'] else 'identical_pair')
        sensitivity.append({'child_id': child, 't0': exact.get('t0', alternative.get('t0')),
                            'exact_T1': exact.get('t1'), 'experiment_T1': alternative.get('t1'),
                            'experiment_rule': alternative.get('rule'), 'comparison': category,
                            'experimental_only': True})
    sensitivity = pd.DataFrame(sensitivity, columns=['child_id', 't0', 'exact_T1', 'experiment_T1',
                                                     'experiment_rule', 'comparison', 'experimental_only'])
    result = panel.summary()
    result['verification_label_counts'] = comparison_frame['verification_label'].value_counts().to_dict()
    for name, frame in [('analysis', analysis), ('pairs', pairs), ('audit', audit),
                        ('candidates', comparison_frame), ('sensitivity', sensitivity)]:
        frame.to_parquet(folder / ('independent_parent_' + name + '.parquet'), index=False)
    from .parent_panel_views import read_panel, verify_panel
    verify_panel(read_panel(folder), result)
    write_json_lines(folder / 'independent_parent_guard.jsonl.gz', panel.guard_cases)
    write_excel(folder / 'independent_parent.xlsx', {
        '數量及規則': [{'metric': k, 'value': dumps(v) if isinstance(v, dict) else v} for k, v in result.items()],
        '正式跨期樣本': pairs, '選定回應及描述資料': analysis, '全部家長處理追查': audit,
        '成人候選與核實': comparison_frame, '電話差一位試算': sensitivity})
    return result
