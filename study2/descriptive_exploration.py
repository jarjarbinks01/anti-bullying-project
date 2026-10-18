"""Aggregate exploration of published answers. Never selects or repairs identities.

The existing 4.1 service owns availability and grouping. This layer owns fixed
quantiles, shared bins and the distinction between wave-valid and paired-valid
populations. Chart and export adapters consume only its aggregate frames.
"""
import json

import numpy as np
import pandas as pd

from .common import PipelineError
from .descriptive_spec import GROUPS, variables
from .descriptives import adult_continuity_confirmed, group_rows, values_and_status

VERSION = 'study2_exploration_v1'
PAIRED_MODES = {'acbd', 'efmatched', 'independent_same_adult', 'independent_child_report'}
METHODS = {'quantile': 'linear', 'whisker': 'farthest observation within 1.5 IQR',
           'bins': 'shared; integer-centred or at most 20 equal-width; last right-inclusive',
           'tie_tolerance': 1e-9, 'delta': 'T1 minus T0; original precision',
           'validity': 'existing values_and_status; per-variable complete pairs',
           'paired_missing_detail': 'own-wave reasons plus other_wave_missing_or_invalid for this-wave-only valid values'}
TABLES = ('distribution_summary', 'histograms', 'pair_summary', 'pair_transitions', 'categories')
EMPTY_COLUMNS = ['release_id','exploration_version','mode','role','group','group_label',
                 'variable_id','variable','unit','kind','basis','grouping_anchor','filters_json']
TABLE_COLUMNS = {
    'distribution_summary':['wave','sample_n','missing_n','valid_n','mean','sd','q1','median','q3','minimum','maximum'],
    'histograms':['wave','bin_index','bin_left','bin_right','right_inclusive','count','denominator','proportion'],
    'pair_summary':['pairs_n','paired_valid_n','only_t0_valid_n','only_t1_valid_n','both_missing_n'],
    'pair_transitions':['t0_value','t1_value','transition','count','denominator','proportion'],
    'categories':['wave','category_code','category','count','denominator','proportion'],
}


def mode_of(rows):
    return rows['report_mode'].iloc[0] if len(rows) else rows.attrs.get('mode', '')


def comparison_variables(mode, role, rows=None):
    if mode not in PAIRED_MODES:
        return []
    same_adult = adult_continuity_confirmed(rows)
    return [v for v in variables(role, 'scales')
            if not (role == 'parent' and not same_adult and (v.key.startswith('PHQ_') or v.key == 'phq_band'))]


def scale_display(variable):
    """Display bounds follow outputs.metrics; they never exclude a valid value."""
    key = variable.key
    if key.startswith('PHQ_'):
        return {'bounds': (0, 12 if key == 'PHQ_total' else 6), 'direction': '分數越高，回報症狀越多'}
    if key.startswith('FQOL_'):
        return {'bounds': (1, 5), 'direction': '分數越高，回報家庭生活質素越高'}
    if key.startswith('SEC_'):
        return {'bounds': (1, 4), 'direction': '分數越高，回報社交情緒能力越高'}
    if key.endswith('_mean'):
        return {'bounds': (0, 4), 'direction': '分數越高，回報發生頻率越高'}
    return {'bounds': None, 'direction': '只描述數值，不作好壞或臨床判斷'}


def numeric_summary(values):
    values = pd.Series(values, dtype=float).dropna()
    if not np.isfinite(values).all():
        raise PipelineError('Exploration received nonfinite valid values')
    result = dict(valid_n=len(values), mean=None, sd=None, minimum=None, q1=None,
                  median=None, q3=None, maximum=None, lower_whisker=None, upper_whisker=None, outside_whisker_n=0)
    if values.empty:
        return result
    q1, median, q3 = values.quantile([.25, .5, .75], interpolation='linear')
    inside = values[values.between(q1-1.5*(q3-q1), q3+1.5*(q3-q1))]
    result.update(mean=float(values.mean()), sd=float(values.std(ddof=1)) if len(values)>1 else None,
                  minimum=float(values.min()), maximum=float(values.max()), q1=float(q1), median=float(median), q3=float(q3),
                  lower_whisker=float(inside.min()), upper_whisker=float(inside.max()),
                  outside_whisker_n=int(len(values)-len(inside)))
    return result


def shared_bins(series):
    values = pd.concat([pd.Series(v, dtype=float).dropna() for v in series], ignore_index=True)
    if values.empty:
        return np.array([])
    lo, hi = float(values.min()), float(values.max())
    if np.all(np.isclose(values, np.rint(values), atol=1e-9, rtol=0)):
        # Integer scores retain their centres, including values outside expected bounds.
        return np.arange(np.floor(lo)-.5, np.ceil(hi)+1.5, 1.)
    if lo == hi:
        return np.array([lo-.5, hi+.5])
    return np.linspace(lo, hi, min(20, max(1, int(np.ceil(np.sqrt(len(values))))))+1)


def _histogram(values, edges, base):
    if not len(edges):
        return []
    values = pd.Series(values, dtype=float).dropna()
    counts, _ = np.histogram(values, bins=edges)
    if int(counts.sum()) != len(values):
        raise PipelineError('Exploration bins lost valid values')
    return [{**base, 'bin_index': i, 'bin_left': float(edges[i]), 'bin_right': float(edges[i+1]),
             'right_inclusive': i == len(counts)-1, 'count': int(n), 'denominator': len(values),
             'proportion': float(n/len(values)) if len(values) else None} for i,n in enumerate(counts)]


def _validate_pairs(rows):
    required = {'child_id', 'submission_id', 'wave'}
    if not required <= set(rows):
        raise PipelineError('Exploration pair structure is missing required keys')
    if rows[list(required)].isna().any().any() or not rows['wave'].isin(['T0','T1']).all():
        raise PipelineError('Exploration pair structure contains invalid keys or waves')
    if rows.duplicated(['child_id','wave']).any() or rows['submission_id'].duplicated().any():
        raise PipelineError('Exploration pair structure contains duplicate keys')
    first = rows[rows['wave'].eq('T0')].set_index('child_id').sort_index()
    last = rows[rows['wave'].eq('T1')].set_index('child_id').sort_index()
    if not first.index.equals(last.index):
        raise PipelineError('Exploration formal pair structure is incomplete')
    return first, last


def explore(rows, role, groups=('all',), release_id='', *, paired=False, selected_variables=None, metadata=None):
    mode = mode_of(rows)
    if not rows.empty and (rows['report_mode'].nunique()!=1 or rows['grouping_anchor'].nunique()!=1):
        raise PipelineError('Exploration cannot mix sample modes or grouping anchors')
    if paired and mode not in PAIRED_MODES:
        raise PipelineError('This sample is not a formal longitudinal cohort')
    allowed = comparison_variables(mode, role, rows) if paired else variables(role)
    requested = set(selected_variables) if selected_variables is not None else {v.key for v in allowed}
    if requested - {v.key for v in allowed}:
        raise PipelineError('Variable is unavailable for this role or paired sample')
    chosen = [v for v in allowed if v.key in requested]
    if paired:
        _validate_pairs(rows)
        required_columns={'PHQ_total' if v.key=='phq_band' else v.key for v in chosen}
        if not rows.empty and not required_columns<=set(rows):
            raise PipelineError('Exploration is missing required published score columns')
    output = {key: [] for key in TABLES}
    basis = 'paired_valid' if paired else 'wave_valid'
    settings = {**(metadata or {}), 'release_id': release_id, 'exploration_version': VERSION,
                'mode': mode, 'role': role, 'basis': basis, 'groups': list(groups), 'methods': METHODS}
    filters_json = json.dumps(settings, ensure_ascii=False, sort_keys=True)
    # Bins span every displayed group and both waves, rather than changing per panel.
    prepared = {}
    for group in groups:
        block = group_rows(rows, group)
        waves = _validate_pairs(block) if paired else tuple(block[block['wave'].eq(w)] for w in ('T0','T1'))
        for var in chosen:
            a, sa = values_and_status(waves[0], var); b, sb = values_and_status(waves[1], var)
            both = a.notna() & b.notna() if paired else None
            if paired:
                av, bv = a[both], b[both]
            else:
                av, bv = a.dropna(), b.dropna()
            prepared[group,var.key] = (av,bv,sa,sb,len(waves[0]),len(waves[1]),a,b)
    for var in chosen:
        numeric = var.kind == 'continuous'
        value_series = [v for g in groups for v in prepared[g,var.key][:2]]
        edges = shared_bins(value_series) if numeric else np.array([])
        delta_edges = shared_bins([prepared[g,var.key][1]-prepared[g,var.key][0] for g in groups]) if numeric and paired else np.array([])
        for group in groups:
            a,b,sa,sb,n0,n1,original_a,original_b = prepared[group,var.key]
            anchor = rows['grouping_anchor'].iloc[0] if len(rows) else settings.get('grouping_anchor','既定基線')
            base = dict(release_id=release_id, exploration_version=VERSION, mode=mode, role=role,
                        group=group, group_label=GROUPS[group], variable_id=var.key, variable=var.label,
                        unit=var.unit, kind=var.kind, basis=basis, grouping_anchor=anchor, filters_json=filters_json)
            for wave,values,status,n in [('T0',a,sa,n0),('T1',b,sb,n1)]:
                missing = status[status.ne('valid')].value_counts().to_dict()
                if paired:
                    other_missing=int(status.eq('valid').sum())-len(values)
                    if other_missing:
                        missing['other_wave_missing_or_invalid']=other_missing
                wb = {**base, 'wave':wave, 'sample_n':n, 'missing_n': n-len(values),
                      'wave_invalid_n':int(status.ne('valid').sum()), 'outside_range_n':int(status.eq('outside_report_range').sum()),
                      'missing_detail':json.dumps(missing,ensure_ascii=False,sort_keys=True)}
                if numeric:
                    bounds = scale_display(var)['bounds']
                    unexpected = int((~values.between(*bounds)).sum()) if bounds else 0
                    output['distribution_summary'].append({**wb, **numeric_summary(values), 'unexpected_display_range_n':unexpected})
                    output['histograms'] += _histogram(values, edges, wb)
                else:
                    cats = [('0','不符合門檻'),('1','符合門檻')] if var.kind=='binary' else var.categories
                    for code,label in cats:
                        count = int(values.eq(int(code) if var.kind=='binary' else code).sum()) if var.kind!='multi' else int(values.map(lambda v:code in str(v).split(';')).sum())
                        output['categories'].append({**wb,'category_code':code,'category':label,'count':count,
                            'denominator':len(values),'proportion':count/len(values) if len(values) else None})
            if not paired:
                continue
            valid0,valid1 = original_a.notna(),original_b.notna()
            pair = {**base, 'pairs_n':n0, 'paired_valid_n':len(a), 'only_t0_valid_n':int((valid0 & ~valid1).sum()),
                    'only_t1_valid_n':int((~valid0 & valid1).sum()), 'both_missing_n':int((~valid0 & ~valid1).sum()),
                    't0_missing_detail':json.dumps(sa[sa.ne('valid')].value_counts().to_dict(),ensure_ascii=False,sort_keys=True),
                    't1_missing_detail':json.dumps(sb[sb.ne('valid')].value_counts().to_dict(),ensure_ascii=False,sort_keys=True)}
            if numeric:
                delta = b-a
                pair.update(t0_mean=a.mean() if len(a) else None,t1_mean=b.mean() if len(b) else None,
                            mean_change=delta.mean() if len(delta) else None,sd_change=delta.std(ddof=1) if len(delta)>1 else None,
                            up_n=int((delta>1e-9).sum()),same_n=int((delta.abs()<=1e-9).sum()),down_n=int((delta < -1e-9).sum()))
                output['distribution_summary'].append({**base,'wave':'delta','sample_n':n0,'missing_n':n0-len(delta),
                    'missing_detail':json.dumps({'not_both_valid':n0-len(delta)}),**numeric_summary(delta)})
                output['histograms'] += _histogram(delta,delta_edges,{**base,'wave':'delta'})
            elif var.kind == 'binary':
                n=len(a);t0=int(a.eq(1).sum());t1=int(b.eq(1).sum())
                pair.update(t0_n=t0,t1_n=t1,t0_proportion=t0/n if n else None,t1_proportion=t1/n if n else None,
                            change_percentage_points=100*(t1-t0)/n if n else None)
                for x,y,title in [(0,0,'兩輪均不符合'),(1,0,'只 T0 符合'),(0,1,'只 T1 符合'),(1,1,'兩輪均符合')]:
                    count=int((a.eq(x)&b.eq(y)).sum())
                    output['pair_transitions'].append({**base,'t0_value':x,'t1_value':y,'transition':title,
                        'count':count,'denominator':n,'proportion':count/n if n else None})
            output['pair_summary'].append(pair)
    result = {key:(pd.DataFrame(records) if records else pd.DataFrame(columns=EMPTY_COLUMNS+TABLE_COLUMNS[key]))
              for key,records in output.items()}
    result['metadata'] = settings
    validate_exploration(result)
    return result


def validate_exploration(result):
    for table in ['distribution_summary','categories']:
        for row in result[table].to_dict('records'):
            if 'missing_detail' in row and sum(json.loads(row['missing_detail']).values())!=row['missing_n']:
                raise PipelineError('Exploration missing reasons do not reconcile')
    pairs = result['pair_summary']
    for r in pairs.to_dict('records'):
        if r['pairs_n'] != sum(r[k] for k in ['paired_valid_n','only_t0_valid_n','only_t1_valid_n','both_missing_n']):
            raise PipelineError('Exploration missing states do not reconcile')
        if r['kind']=='continuous':
            if sum(r[k] for k in ['up_n','same_n','down_n']) != r['paired_valid_n']:
                raise PipelineError('Exploration change states do not reconcile')
            if r['paired_valid_n'] and not np.isclose(r['mean_change'],r['t1_mean']-r['t0_mean'],atol=1e-10):
                raise PipelineError('Exploration paired means do not reconcile')
    keys=['mode','role','group','variable_id','basis','wave']
    hist=result['histograms']
    if not hist.empty:
        for _,block in hist.groupby(keys):
            if block['count'].sum()!=block['denominator'].iloc[0]:
                raise PipelineError('Exploration histogram denominator mismatch')
    transitions=result['pair_transitions']
    if not transitions.empty:
        for _,block in transitions.groupby(keys[:-1]):
            if len(block)!=4 or block['count'].sum()!=block['denominator'].iloc[0]:
                raise PipelineError('Exploration transition denominator mismatch')
