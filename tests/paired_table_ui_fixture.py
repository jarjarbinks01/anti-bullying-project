"""Synthetic paired-table cases; expected wave summaries use raw tuples only."""
from copy import deepcopy
from math import fsum
from statistics import stdev

from static_source_ui_fixture import records, ui_snapshot, legacy_summary_snapshot

GRADES = ['P1','P2','P3','P4','P5','P6','S1','S2','S3','S4','S5','S6','Unknown']
CASES = [
    dict(name='all', sources=['all']),
    dict(name='single', sources=['qualtrics']),
    dict(name='union', sources=['legacy_online','qualtrics']),
    dict(name='grades', sources=['all'], grades=['P3','P4','P5']),
    dict(name='union-grades', sources=['legacy_online','qualtrics'], grades=['P3','P4']),
    dict(name='metric-one-pair', sources=['paperform']),
    dict(name='one-pair', sources=['all'], grades=['P6']),
    dict(name='zero-pairs', sources=['all'], grades=['P1']),
    dict(name='parent-all', sources=['all'], role='parent'),
    dict(name='parent-union', sources=['legacy_online','qualtrics'], role='parent'),
    dict(name='ef-adult-block', sources=['all'], role='parent', mode='efmatched'),
    dict(name='legacy-all', variant='legacy', sources=['all']),
    dict(name='legacy-single', variant='legacy', sources=['qualtrics']),
    dict(name='legacy-parent', variant='legacy', sources=['all'], role='parent'),
    dict(name='legacy-paired-means', variant='mean_only', sources=['all']),
    dict(name='suppressed', variant='suppressed', sources=['all']),
]


def snapshot_bundle():
    normal = ui_snapshot(projections=[('abcd','student'),('acbd','student'),
                                     ('acbd','parent'),('efmatched','parent')])
    legacy = legacy_summary_snapshot()
    suppressed = deepcopy(legacy)
    suppressed['minimum_cell_n'] = 5
    suppressed['small_sample_policy'] = 'threshold'
    # A renderer-only disclosure case follows safe_changes' exact null contract.
    # The old-format fixture has no optional moment evidence to bypass the gate.
    for view in suppressed['views']:
        for row in view['changes']:
            if row['variable_id'] != 'PHQ_total':
                continue
            for key in list(row):
                if key not in {'group','variable_id','variable','unit','suppressed',
                               'inference_status','pair_detail_status'}:
                    row[key] = None
            row.update(suppressed=True, inference_status='suppressed',
                       pair_detail_status='suppressed')
    mean_only = deepcopy(normal)
    mean_only.pop('grade');mean_only.pop('source_selection')
    for view in mean_only['views']:
        view.pop('grade',None);view.pop('source_pairs',None)
    variants = dict(normal=normal, legacy=legacy, mean_only=mean_only, suppressed=suppressed)
    cases = []
    for item in CASES:
        case = dict(variant='normal', role='student', mode='acbd', grades=GRADES)
        case.update(item)
        snap = variants[case['variant']]
        view = next(v for v in snap['views'] if v['mode']==case['mode'] and
                    v['role']==case['role'] and v['source']=='all' and not v['mainstream'])
        case['metrics'] = {r['variable_id']:dict(label=r['variable'], **raw_summary(case, r['variable_id']))
                           for r in view['changes'] if r['group']=='all'}
        cases.append(case)
    return variants, cases


def raw_summary(case, variable):
    """No adapter, cube, histogram or exported statistics provide expected SD."""
    if case['variant'] not in {'normal','mean_only'}:
        return dict(legacy=True, suppressed=case['variant']=='suppressed' and variable=='PHQ_total')
    frame = records(case['mode'], case['role'])
    units = {}
    for row in frame.to_dict('records'):
        if case['sources'] != ['all'] and row['anchor_source_type'] not in case['sources']:
            continue
        if row['_grade'] not in case['grades']:
            continue
        units.setdefault(row['child_id'], {})[row['wave']] = row.get(variable)
    import math
    valid = lambda v: isinstance(v,(int,float)) and math.isfinite(v)
    pairs = [(r.get('T0'),r.get('T1')) for r in units.values()
             if valid(r.get('T0')) and valid(r.get('T1'))]
    a = [x for x,y in pairs]; b = [y for x,y in pairs]
    return dict(paired_valid_n=len(pairs),
                t0_mean=fsum(a)/len(a) if a else None,
                t1_mean=fsum(b)/len(b) if b else None,
                t0_sd=stdev(a) if len(a)>1 and case['variant']=='normal' else None,
                t1_sd=stdev(b) if len(b)>1 and case['variant']=='normal' else None)
