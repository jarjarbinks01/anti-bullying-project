"""Read-only cohort selection and statistics shared by every report surface."""
import json
from collections import Counter

import numpy as np
import pandas as pd

from .common import PipelineError
from .dashboard_views import analysis_cohort
from .descriptive_data import attach_measurements
from .descriptive_spec import DICTIONARY_VERSION, GROUPS, MODES, VERSION, variables

COHORTS = {'abcd': '全部保留樣本', 'ef': '親子配對樣本',
           'acbd': '跨期配對樣本', 'efmatched': '跨期親子樣本'}
ANCHOR_FIELDS = ['gender', 'school_stage', 'school', 'mainstream', 'source_type', 'identity_rules']


def wave_counts(rows):
    return {w: int(rows['wave'].eq(w).sum()) for w in ('T0', 'T1')}


def _anchor_rows(rows, anchors, keys):
    names = {name: 'anchor_' + name for name in ANCHOR_FIELDS}
    if anchors.duplicated(keys).any():
        raise PipelineError('Report grouping anchor is not unique')
    result = rows.merge(anchors.reindex(columns=keys + ANCHOR_FIELDS).rename(columns=names),
                        on=keys, how='left', validate='many_to_one', indicator=True)
    if result['_merge'].ne('both').any():
        raise PipelineError('Published report sample is missing its grouping anchor')
    return result.drop(columns='_merge')


def cohort(frame, parent_frame, measurements, mode, role):
    """Use formal membership, then add a fixed anchor without choosing surveys."""
    if mode not in MODES or role not in {'student', 'parent'}:
        raise ValueError('Unknown descriptive mode or role')
    rows = pd.concat([analysis_cohort(frame, parent_frame, role, wave, COHORTS[mode])
                      for wave in ('T0', 'T1')], ignore_index=True)
    if rows.duplicated(['child_id', 'wave']).any():
        raise PipelineError('Report sample contains multiple submissions per child and wave')
    rows = attach_measurements(rows, measurements)
    if mode == 'abcd':
        result = _anchor_rows(rows, rows, ['submission_id'])
    elif mode == 'ef':
        students = frame[frame['role'].eq('student') & frame['dyad'].fillna(False)].copy()
        students = attach_measurements(students, measurements)
        result = _anchor_rows(rows, students, ['child_id', 'wave'])
        # School/gender come from the student; source/rule filters use this role.
        result['anchor_source_type'] = result['source_type']
        result['anchor_identity_rules'] = result['identity_rules']
    elif mode == 'acbd':
        result = _anchor_rows(rows, rows[rows['wave'].eq('T0')], ['child_id'])
    else:
        students = frame[frame['role'].eq('student') & frame['wave'].eq('T0')
                         & frame['longitudinal_dyad'].fillna(False)].copy()
        students = attach_measurements(students, measurements)
        result = _anchor_rows(rows, students, ['child_id'])
    result['report_mode'] = mode
    result['grouping_anchor'] = ('該輪回應' if mode == 'abcd' else '該輪學生' if mode == 'ef'
                                 else '學生T0' if mode == 'efmatched' or role == 'student' else 'BD家長T0所指孩子')
    result = result.sort_values(['child_id', 'wave']).reset_index(drop=True)
    result.attrs['mode'] = mode
    return result


def independent_cohort(frame, measurements, branch, paired_only=True):
    rows = frame[frame['panel_branch'].eq(branch)].copy()
    if paired_only:
        # Empty Parquet columns may have object dtype. Force a row mask so
        # pandas preserves the schema instead of treating it as column names.
        rows = rows.loc[rows['panel_longitudinal'].fillna(False).astype(bool)].copy()
    rows['wave'] = rows['panel_wave']
    rows = attach_measurements(rows, measurements)
    if rows.duplicated(['child_id', 'wave']).any():
        raise PipelineError('Independent report membership is not unique')
    result = _anchor_rows(rows, rows[rows['wave'].eq('T0')], ['child_id'])
    result['report_mode'] = 'independent_' + branch
    result['grouping_anchor'] = '獨立家長T0所指孩子'
    result = result.sort_values(['child_id', 'wave']).reset_index(drop=True)
    result.attrs['mode'] = 'independent_' + branch
    return result


def filter_cohort(rows, *, mainstream=True, schools=(), sources=(), rules=(), group='all', school_types=()):
    """Apply each filter to the same anchor, preserving complete panel units."""
    counts = [{'stage': '未篩選', **wave_counts(rows)}]
    result = rows.copy()
    if mainstream:
        result = result[result['anchor_mainstream'].fillna(False).astype(bool)].copy()
    counts.append({'stage': '學校範圍後', **wave_counts(result)})
    for field, selected in [('anchor_school', schools), ('anchor_source_type', sources)]:
        if selected:
            result = result[result[field].isin(selected)].copy()
    if school_types:
        result = result[result['anchor_school_stage'].isin(school_types)].copy()
    if rules:
        selected = set(rules)
        result = result[result['anchor_identity_rules'].fillna('').map(lambda s: bool(set(s.split(';')) & selected))].copy()
    counts.append({'stage': '進階篩選後', **wave_counts(result)})
    result = group_rows(result, group)
    counts.append({'stage': '目前分組', **wave_counts(result)})
    return result, pd.DataFrame(counts)


def group_rows(rows, group):
    if group not in GROUPS:
        raise ValueError('Unknown report group')
    mask = pd.Series(True, index=rows.index)
    if group.startswith('male'):
        mask &= rows['anchor_gender'].fillna('').astype(str).eq('0')
    elif group.startswith('female'):
        mask &= rows['anchor_gender'].fillna('').astype(str).eq('1')
    if group.endswith('primary'):
        mask &= rows['anchor_school_stage'].eq('primary')
    elif group.endswith('secondary'):
        mask &= rows['anchor_school_stage'].eq('secondary')
    return rows[mask].copy()


def values_and_status(rows, variable):
    if variable.key == 'phq_band':
        total = pd.to_numeric(rows.get('PHQ_total', pd.Series(np.nan, index=rows.index)), errors='coerce')
        values = pd.cut(total, [-.01, 2, 5, 8, 12], labels=['0_2', '3_5', '6_8', '9_12']).astype(object)
        status = pd.Series(np.where(values.notna(), 'valid', 'missing'), index=rows.index)
        status.loc[total.notna() & values.isna()] = 'invalid'
    else:
        values = rows[variable.key] if variable.key in rows else pd.Series(None, index=rows.index, dtype=object)
        status_key = variable.key + '__status'
        status = (rows[status_key].fillna('missing') if status_key in rows
                  else pd.Series(np.where(values.notna(), 'valid', 'missing'), index=rows.index))
    values = values.copy()
    if variable.kind in {'continuous', 'binary'}:
        numeric = pd.to_numeric(values, errors='coerce')
        invalid = status.eq('valid') & (~np.isfinite(numeric) | (numeric.isin([0, 1]).eq(False) if variable.kind == 'binary' else False))
        status = status.copy(); status.loc[invalid] = 'invalid'
        values = numeric
    elif variable.kind == 'category':
        allowed = {code for code, _ in variable.categories}
        invalid = status.eq('valid') & ~values.isin(allowed)
        status = status.copy(); status.loc[invalid] = 'invalid'
    return values.where(status.eq('valid')), status


def statistics(rows, role, groups=('all',), release_id='', section=None):
    records = []
    mode = rows['report_mode'].iloc[0] if len(rows) else rows.attrs.get('mode', '')
    anchor = rows['grouping_anchor'].iloc[0] if len(rows) else ''
    for group in groups:
        grouped = group_rows(rows, group)
        for wave in ('T0', 'T1'):
            sample = grouped[grouped['wave'].eq(wave)]
            for var in variables(role, section):
                values, status = values_and_status(sample, var)
                valid = values.dropna()
                base = dict(release_id=release_id, report_version=VERSION, dictionary_version=DICTIONARY_VERSION,
                    mode=mode, role=role, wave=wave, group=group, group_label=GROUPS[group], grouping_anchor=anchor,
                    variable_id=var.key, variable=var.label, section=var.section, kind=var.kind, unit=var.unit,
                    sample_n=len(sample), valid_n=len(valid), missing_n=len(sample)-len(valid),
                    outside_range_n=int(status.eq('outside_report_range').sum()),
                    missing_detail=json.dumps(dict(Counter(status[status.ne('valid')])), ensure_ascii=False, sort_keys=True),
                    note=var.note, mean=None, sd=None, minimum=None, maximum=None,
                    numerator=None, denominator=len(valid), proportion=None)
                if var.kind == 'continuous':
                    records.append({**base, 'category_code': '', 'category': '',
                        'mean': valid.mean() if len(valid) else None,
                        'sd': valid.std(ddof=1) if len(valid) > 1 else None,
                        'minimum': valid.min() if len(valid) else None, 'maximum': valid.max() if len(valid) else None})
                elif var.kind == 'binary':
                    count = int(valid.eq(1).sum())
                    records.append({**base, 'category_code': '1', 'category': '符合門檻', 'numerator': count,
                                    'proportion': count/len(valid) if len(valid) else None})
                else:
                    for code, label in var.categories:
                        count = (int(valid.map(lambda v: code in str(v).split(';')).sum()) if var.kind == 'multi'
                                 else int(valid.eq(code).sum()))
                        records.append({**base, 'category_code': code, 'category': label, 'numerator': count,
                                        'proportion': count/len(valid) if len(valid) else None})
    result = pd.DataFrame(records)
    for key in ['mean', 'sd', 'minimum', 'maximum', 'numerator', 'proportion']:
        result[key] = pd.to_numeric(result[key], errors='coerce').astype(float)
    return result


def paired_changes(rows, role, groups=('all',), release_id=''):
    mode = rows['report_mode'].iloc[0] if len(rows) else rows.attrs.get('mode', '')
    permitted = mode in {'acbd', 'efmatched', 'independent_same_adult', 'independent_child_report'}
    if not permitted:
        return pd.DataFrame()
    records = []
    for group in groups:
        grouped = group_rows(rows, group)
        first, last = (grouped[grouped['wave'].eq(w)].set_index('child_id') for w in ('T0', 'T1'))
        units = first.index.intersection(last.index)
        for var in variables(role, 'scales'):
            if var.kind != 'continuous':
                continue
            if role == 'parent' and var.key.startswith('PHQ_') and mode != 'acbd' and mode != 'independent_same_adult':
                continue
            a, _ = values_and_status(first.loc[units], var)
            b, _ = values_and_status(last.loc[units], var)
            delta = (b-a).dropna()
            records.append(dict(release_id=release_id, report_version=VERSION, mode=mode, role=role,
                group=group, group_label=GROUPS[group], variable_id=var.key, variable=var.label, unit=var.unit,
                pairs_n=len(units), paired_valid_n=len(delta), paired_missing_n=len(units)-len(delta),
                mean_change=delta.mean() if len(delta) else None, sd_change=delta.std(ddof=1) if len(delta)>1 else None))
    result = pd.DataFrame(records)
    for key in ['mean_change', 'sd_change']:
        if key in result:
            result[key] = pd.to_numeric(result[key], errors='coerce').astype(float)
    return result


def formatted(row):
    if row['kind'] == 'continuous':
        if pd.isna(row['mean']):
            return '缺失'
        sd = '缺失' if pd.isna(row['sd']) else f"{row['sd']:.2f}"
        return f"{row['mean']:.2f} ({sd})"
    return ('缺失' if not row['denominator'] else
            f"{int(row['numerator']):,}/{int(row['denominator']):,} ({row['proportion']:.1%})")


def display_table(stats):
    """A presentation projection of numeric results; it does not calculate N."""
    rows = []
    for _, pair in stats.groupby(['variable_id', 'category_code', 'group'], sort=False, dropna=False):
        first = pair.iloc[0]
        row = {'指標': first['variable'], '分類': first['category'], '分組': first['group_label'], '單位': first['unit']}
        for item in pair.to_dict('records'):
            w = item['wave']
            row[w] = formatted(item)
            row[w+'有效N'] = item['valid_n']; row[w+'缺失N'] = item['missing_n']
        rows.append(row)
    return pd.DataFrame(rows)


def validate_statistics(stats):
    key = ['mode', 'role', 'wave', 'group', 'variable_id', 'category_code']
    if stats.duplicated(key).any():
        raise PipelineError('Duplicate variable/category keys in descriptive statistics')
    if not (stats['sample_n'] == stats['valid_n'] + stats['missing_n']).all():
        raise PipelineError('Descriptive valid and missing counts do not reconcile')
    if 'outside_range_n' in stats and ((stats['outside_range_n'] < 0) | (stats['outside_range_n'] > stats['missing_n'])).any():
        raise PipelineError('Out-of-range descriptive counts do not reconcile')
    cats = stats[stats['kind'].eq('category')]
    for _, block in cats.groupby(key[:-1], dropna=False):
        if block['numerator'].sum() != block['valid_n'].iloc[0]:
            raise PipelineError('Descriptive categorical denominator does not reconcile')
    binary = stats[stats['kind'].isin(['binary', 'category', 'multi'])]
    if ((binary['numerator'] < 0) | (binary['numerator'] > binary['denominator'])).any():
        raise PipelineError('Descriptive numerator exceeds its denominator')
