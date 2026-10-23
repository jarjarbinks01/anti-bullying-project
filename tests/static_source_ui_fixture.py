"""Small synthetic UI contract, with expected results independent of source pooling.

The tuples are the specification: baseline source, baseline grade, T0/T1 PHQ,
mainstream eligibility, and an optional different T1 questionnaire source.
No input is read from a research publication, database or local configuration.
"""
from math import fsum
from statistics import stdev
import pandas as pd

SOURCE_CODES = ('legacy_online', 'paperform', 'qualtrics', 'school_batch', 'socialworkdream')
SOURCE_LABELS = dict(zip(SOURCE_CODES, ('Legacy online', 'Paperform', 'Qualtrics', 'School batch', 'Social Work Dream')))
SPEC = (
    ('legacy_online','P3',0.,1.,True,None),
    ('legacy_online','P4',4.,6.,True,None),
    ('legacy_online','Unknown',None,8.,False,'socialworkdream'),
    ('paperform','P3',2.,4.,True,None),
    ('paperform','P4',6.,None,True,None),
    ('qualtrics','P3',1.,2.,True,None),
    ('qualtrics','P4',2.,4.,True,None),
    ('qualtrics','P5',10.,11.,False,None),
    ('school_batch','P6',3.,5.,True,None),
    ('socialworkdream','S1',7.,8.,True,None),
    ('unknown','S3',12.,10.,False,'paperform'),
)
FORMAL = {'acbd','efmatched','independent_child','independent_adult'}


def records(mode='abcd', role='student', *, include_residual=True):
    result=[]
    for i,(source,grade,a,b,mainstream,changed) in enumerate(SPEC):
        if source=='unknown' and not include_residual:continue
        for wave,value in [('T0',a),('T1',b)]:
            response_source=changed if wave=='T1' and changed else source
            anchored=source if mode in FORMAL or mode.startswith('independent') else response_source
            row=dict(child_id=f'source-ui-unit-{i}',submission_id=f'source-ui-form-{i}-{wave}',
                version_id=f'source-ui-version-{i}-{wave}',role=role,wave=wave,
                report_mode={'independent_all':'independent_child_report','independent_adult':'independent_same_adult','independent_child':'independent_child_report'}.get(mode,mode),
                grouping_anchor='synthetic_baseline',anchor_gender=str(i%2),
                anchor_school_stage='secondary' if grade.startswith('S') else 'primary',
                anchor_source_type=anchored,source_type=response_source,
                observed_at='2025-01-02T00:00:00Z' if wave=='T0' else '2025-05-02T00:00:00Z',
                date_basis='system_creation',time_confidence='observed',
                adult_continuity_confirmed=not(role=='parent' and mode in {'efmatched','independent_child'}),
                PHQ_total=value,FQOL_total=2.+i%3/4,SEC_total=1.+i%2,
                TBV_mean=1.,TBP_mean=1.,CBV_mean=1.,CBP_mean=1.,
                _grade=grade,_mainstream=mainstream)
            row.update({domain+'_prevalence'+str(threshold):float(i%2) for domain in ('TBV','TBP','CBV','CBP') for threshold in (1,2)})
            result.append(row)
    frame=pd.DataFrame(result);frame.attrs['mode']={'independent_all':'independent_child_report','independent_child':'independent_child_report','independent_adult':'independent_same_adult'}.get(mode,mode)
    return frame


def expected_phq(mode, selected, *, grades=None, mainstream=False):
    """Loop the hand-written specification, not an exported cube or its sums."""
    result={}
    for wave,index in [('T0',2),('T1',3)]:
        cells=[]
        for item in SPEC:
            source,grade,_,_,eligible,changed=item
            if wave=='T1' and changed and mode not in FORMAL and not mode.startswith('independent'):source=changed
            if selected is not None and source not in selected:continue
            if grades is not None and grade not in grades:continue
            if mainstream and not eligible:continue
            cells.append(item[index])
        valid=[x for x in cells if x is not None]
        result[wave]={'sample_n':len(cells),'valid_n':len(valid),'missing_n':len(cells)-len(valid),
            'mean':fsum(valid)/len(valid) if valid else None,'sd':stdev(valid) if len(valid)>1 else None}
    return result


def ui_snapshot(*,include_residual=True,projections=None):
    """Feed actual presentation/grade/source helpers from synthetic rows only."""
    from study2.descriptive_spec import GROUPS
    from study2.descriptives import group_rows,statistics,wave_counts
    from study2.static_export import safe_statistics,safe_changes,pair_details,overview_changes,_exploration,_trends
    from study2.static_grade import build_cube,header
    from study2.static_sources import build_pairs,header as source_header,validate_sources,PARTITIONS
    groups=('all','male_primary','female_secondary')
    modes={'abcd':'Each wave A–D','acbd':'Formal AC/BD','efmatched':'Formal EF',
        'independent_all':'Independent parent waves','independent_child':'Independent same child',
        'independent_adult':'Independent same adult'}
    projections=projections or [('abcd','student'),('abcd','parent'),('acbd','student'),('acbd','parent'),
        ('efmatched','parent'),('independent_all','parent'),('independent_child','parent'),('independent_adult','parent')]
    views=[]
    for mode,role in projections:
        base=records(mode,role,include_residual=include_residual)
        reference_mode={'abcd':'acbd','independent_all':'independent_child'}.get(mode)
        reference=records(reference_mode,role,include_residual=include_residual) if reference_mode else None
        grade_anchor=('parent_report_' if mode.startswith('independent') else 'student_')+('T0' if mode in FORMAL else 'wave')
        anchor='wave_response' if mode=='abcd' else 'independent_parent_T0' if mode.startswith('independent') else 'student_T0' if role=='student' or mode=='efmatched' else 'BD_parent_T0'
        for mainstream in [False,True]:
            full=base.loc[base._mainstream].copy() if mainstream else base.copy();full.attrs=base.attrs.copy()
            for source in ['all',*SOURCE_CODES,*(['unknown'] if include_residual else [])]:
                part=full.copy() if source=='all' else full.loc[full.anchor_source_type.eq(source)].copy();part.attrs=full.attrs.copy()
                view=dict(mode=mode,role=role,mainstream=mainstream,source=source,
                    grouping_anchor=anchor,source_filter_anchor=anchor,
                    counts={g:wave_counts(group_rows(part,g)) for g in groups},
                    statistics=safe_statistics(statistics(part,role,groups)),
                    changes=safe_changes(pair_details(part,role,groups)) if mode in FORMAL else safe_changes(overview_changes(part,reference,role,groups)))
                view['grade']=build_cube(part,role,view,groups,grade_anchor)
                if source=='all':
                    if reference is not None:view['source_pairs']=build_pairs(part,reference,role,groups,PARTITIONS if include_residual else SOURCE_CODES)
                    view.update(histograms=_exploration(part,role,'synthetic-source-ui',False,0),
                        paired_histograms=_exploration(part,role,'synthetic-source-ui',True,0) if mode in FORMAL else [],
                        trends=_trends(part,role,0))
                views.append(view)
    snap=dict(format='study2_static_v1',release_id='synthetic-source-ui',generated_at='2026-01-01T00:00:00Z',
        published_at='2026-01-01T00:00:00Z',report_version=header('synthetic-source-ui')['report_version'],
        dictionary_version=header('synthetic-source-ui')['dictionary_version'],inference_version='paired_t_dz_v1',
        descriptive_projection_version='study2_g12_v1',minimum_cell_n=0,small_sample_policy='none',
        grade=header('synthetic-source-ui'),views=views,modes=modes,groups={g:GROUPS[g] for g in groups},
        source_names={'all':'All sources',**SOURCE_LABELS,'unknown':'Unidentified source'},
        dictionary=[dict(variable_id='PHQ_total',label='PHQ_total')],notes=[],samples=[],evidence=[],tracking=[],stages=[],
        counts={},independent_counts=dict(baselines=11,child_report_pairs=11,same_adult_pairs=11,same_adult_alternative_T1=0))
    snap['source_selection']=source_header(snap['release_id'],views)
    snap['sources']=[]  # Existing first-tab count-table slot, never the new header.
    validate_sources(snap)
    return snap


def expected_pairs(selected, *, grades=None, mainstream=False):
    cells=[item for item in SPEC if (selected is None or item[0] in selected)
        and (grades is None or item[1] in grades) and (not mainstream or item[4])]
    complete=[item for item in cells if item[2] is not None and item[3] is not None]
    a=[item[2] for item in complete];b=[item[3] for item in complete];d=[y-x for x,y in zip(a,b)]
    return dict(pairs_n=len(cells),paired_valid_n=len(complete),
        only_t0_valid_n=sum(i[2] is not None and i[3] is None for i in cells),
        only_t1_valid_n=sum(i[2] is None and i[3] is not None for i in cells),
        both_missing_n=sum(i[2] is None and i[3] is None for i in cells),
        t0_mean=fsum(a)/len(a) if a else None,t1_mean=fsum(b)/len(b) if b else None,
        mean_change=fsum(d)/len(d) if d else None,sd_change=stdev(d) if len(d)>1 else None)


def expected_overview_pairs(selected, *, mainstream=False):
    """Both displayed source endpoints must be inside the chosen union."""
    eligible=[]
    for source,grade,a,b,main,changed in SPEC:
        if mainstream and not main:continue
        if selected is not None and (source not in selected or (changed or source) not in selected):continue
        eligible.append((a,b))
    complete=[(a,b) for a,b in eligible if a is not None and b is not None]
    return dict(pairs_n=len(eligible),paired_valid_n=len(complete),
        t0_mean=fsum(a for a,b in complete)/len(complete) if complete else None,
        t1_mean=fsum(b for a,b in complete)/len(complete) if complete else None)


# Pre-detail published summaries. These raw synthetic pairs are independent of
# Source/Grade and deliberately have finite, nonzero original inference.
LEGACY_SUMMARY_SPEC = (
    ('qualtrics',1.,3.,1.,2.),
    ('qualtrics',3.,4.,1.5,2.),
    ('qualtrics',7.,10.,2.,3.5),
    ('legacy_online',0.,1.,1.,1.5),
    ('legacy_online',4.,7.,2.,3.5),
    ('legacy_online',6.,8.,3.,4.),
)
LEGACY_ABSENT_DETAILS = ('pair_detail_status','only_t0_valid_n','only_t1_valid_n',
    'both_missing_n','t0_mean','t1_mean')


def expected_legacy_summary(role, source):
    """Original summary oracle from raw pairs, with explicit adult negative gate."""
    import numpy as np
    from scipy.stats import ttest_1samp
    cells=[x for x in LEGACY_SUMMARY_SPEC if source=='all' or x[0]==source]
    expected={}
    for key,start in [('PHQ_total',1),('SEC_total',3)]:
        if role=='parent' and key.startswith('PHQ_'):continue
        delta=np.asarray([x[start+1]-x[start] for x in cells],dtype=float)
        if not len(delta):continue
        mean=fsum(delta)/len(delta);sd=stdev(delta) if len(delta)>1 else None
        expected[key]=dict(pairs_n=len(cells),paired_valid_n=len(cells),paired_missing_n=0,
            mean_change=mean,sd_change=sd,p_value=float(ttest_1samp(delta,0).pvalue),cohen_dz=mean/sd)
    return expected


def legacy_summary_snapshot():
    """Valid pre-Grade/pre-Source snapshot with only original paired fields.

No complete-pair detail is filled. Parent PHQ is excluded by the original
scientific same-adult gate before serialization, and remains excluded in UI.
"""
    from study2.descriptives import statistics,paired_changes,wave_counts
    from study2.static_export import safe_statistics,safe_changes,validate_snapshot
    from study2.descriptive_spec import VERSION,DICTIONARY_VERSION
    views=[]
    for role in ['student','parent']:
        raw=[]
        for i,(source,a,b,sa,sb) in enumerate(LEGACY_SUMMARY_SPEC):
            for wave,phq,sec in [('T0',a,sa),('T1',b,sb)]:
                raw.append(dict(child_id=f'legacy-ui-unit-{i}',submission_id=f'legacy-ui-form-{i}-{wave}',
                    version_id=f'legacy-ui-version-{i}-{wave}',role=role,wave=wave,
                    report_mode='acbd',grouping_anchor='synthetic_baseline',
                    adult_continuity_confirmed=role=='student',anchor_source_type=source,
                    anchor_gender='0',anchor_school_stage='primary',PHQ_total=phq,SEC_total=sec))
        frame=pd.DataFrame(raw);frame.attrs['mode']='acbd'
        for source in ['all',*SOURCE_CODES]:
            part=frame.copy() if source=='all' else frame.loc[frame.anchor_source_type.eq(source)].copy();part.attrs=frame.attrs.copy()
            stats=safe_statistics(statistics(part,role,('all',)))
            changes=safe_changes(paired_changes(part,role,('all',)))
            for row in [*stats,*changes]:row['variable']=row['variable_id']
            for row in changes:
                for field in LEGACY_ABSENT_DETAILS:row.pop(field,None)
            for mode in ['abcd','acbd']:
                anchor='wave_response' if mode=='abcd' else 'student_T0' if role=='student' else 'BD_parent_T0'
                views.append(dict(mode=mode,role=role,mainstream=False,source=source,
                    grouping_anchor=anchor,source_filter_anchor=anchor,counts={'all':wave_counts(part)},
                    statistics=stats,changes=changes))
    snap=dict(format='study2_static_v1',release_id='synthetic-legacy-summary',
        generated_at='2026-01-01T00:00:00Z',published_at='2026-01-01T00:00:00Z',
        report_version=VERSION,dictionary_version=DICTIONARY_VERSION,inference_version='paired_t_dz_v1',
        descriptive_projection_version='study2_g12_v1',minimum_cell_n=0,small_sample_policy='none',
        views=views,modes={'abcd':'Each wave A–D','acbd':'Formal AC/BD'},groups={'all':'All children'},
        source_names={'all':'All sources',**SOURCE_LABELS},dictionary=[{'variable_id':k,'label':k} for k in ['PHQ_total','SEC_total']],
        notes=[],samples=[],evidence=[],tracking=[],stages=[],sources=[],counts={},independent_counts={})
    assert 'grade' not in snap and 'source_selection' not in snap
    for v in snap['views']:
        assert 'grade' not in v and 'source_pairs' not in v
        assert all(not any(k in row for k in LEGACY_ABSENT_DETAILS) for row in v['changes'])
        if v['role']=='parent':assert not any(row['variable_id'].startswith('PHQ_') for row in v['changes'])
    validate_snapshot(snap)
    return snap
