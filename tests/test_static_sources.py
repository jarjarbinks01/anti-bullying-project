"""Synthetic independent row-filter oracles for all 31 source combinations."""
from copy import deepcopy
from itertools import combinations
import json
import subprocess

import pandas as pd
import pytest

from study2.common import PipelineError, plain
from study2.descriptive_spec import GROUPS, variables
from study2.descriptives import filter_cohort, group_rows, statistics, wave_counts
from study2.static_export import overview_changes, pack_snapshot, pair_details, safe_changes, safe_statistics
from study2.static_grade import CODES as GRADES, JS_SOURCE as GRADE_JS, build_cube, header as grade_header
from study2.static_sources import CODES, JS_SOURCE, build_pairs, header, validate_sources
from test_static_export import rows

SUBSETS = [list(c) for size in range(1, 6) for c in combinations(CODES, size)]
SMALL_GROUPS = ('all', 'male', 'primary', 'male_primary')
CHOSEN = {'PHQ_total', 'FQOL_total', 'SEC_total', 'TBV_prevalence1', 'phq_band',
          'dem_birthplace', 'dem_sen_types'}


@pytest.fixture(autouse=True)
def compact_metrics(monkeypatch):
    # Use unchanged Variable objects and validity rules, reducing the cross-product
    # only in these synthetic fixtures. Export integration below uses the full catalogue.
    def selected(role, section=None):
        return [v for v in variables(role, section) if v.key in CHOSEN]
    for name in ['study2.descriptives', 'study2.static_grade', 'study2.static_sources',
                 'study2.descriptive_exploration']:
        monkeypatch.setattr(name+'.variables', selected)


def invent(mode='abcd', role='student', residual=False):
    formal = mode in {'acbd', 'efmatched', 'independent_child', 'independent_adult'}
    report = {'independent_all': 'independent_child_report',
              'independent_child': 'independent_child_report',
              'independent_adult': 'independent_same_adult'}.get(mode, mode)
    base = rows(role, report).iloc[:64].copy()
    base.attrs['mode'] = report
    for i in range(32):
        unit = base.child_id.eq(f'person-{i}')
        base.loc[unit, 'source_type'] = CODES[(i+3) % 5]
        base.loc[unit, 'anchor_source_type'] = CODES[i % 5]
        if not formal and mode != 'independent_all':
            base.loc[unit & base.wave.eq('T1'), 'anchor_source_type'] = CODES[(i//5) % 5]
        base.loc[unit, 'anchor_mainstream'] = i % 3 != 0
        base.loc[unit, 'anchor_gender'] = str(i % 2)
        base.loc[unit, 'anchor_school_stage'] = 'primary' if i % 4 < 2 else 'secondary'
        base.loc[unit, '_grade'] = ['P3', 'P4', 'S1', 'Unknown'][i % 4]
        for wave, plus in [('T0', 0), ('T1', 1)]:
            m = unit & base.wave.eq(wave)
            base.loc[m, 'PHQ_total'] = (i*3+plus*(i % 4)) % 13
            base.loc[m, 'FQOL_total'] = 1.+(i+plus) % 5
            base.loc[m, 'SEC_total'] = 1.+(i+plus) % 4
            base.loc[m, 'TBV_prevalence1'] = i % 2
            base.loc[m, 'dem_birthplace'] = str(i % 3)
            base.loc[m, 'dem_sen_types'] = '0;1' if i % 2 else '2'
    base.loc[0, 'PHQ_total'] = None
    base.loc[3, 'PHQ_total'] = None
    base.loc[4:5, 'FQOL_total'] = None
    base['SEC_total__status'] = 'valid'
    base.loc[8, 'SEC_total__status'] = 'outside_report_range'
    if residual:
        base.loc[base.child_id.eq('person-31'), 'anchor_source_type'] = 'unknown'
    if role == 'parent':
        base['adult_continuity_confirmed'] = report in {'acbd', 'independent_same_adult'}
    return base


def payload(base, mode='abcd', role='student', reference=None, groups=SMALL_GROUPS):
    sources = [*CODES, *(['unknown'] if base.anchor_source_type.eq('unknown').any() else [])]
    views = []
    formal = mode in {'acbd', 'efmatched', 'independent_child', 'independent_adult'}
    for mainstream in (False, True):
        for source in ['all', *sources]:
            selected, _ = filter_cohort(base, mainstream=mainstream,
                                        sources=() if source == 'all' else (source,))
            changes = overview_changes(selected, reference, role, groups) if reference is not None else pair_details(selected, role, groups)
            view = dict(mode=mode, role=role, mainstream=mainstream, source=source,
                        grouping_anchor='test-anchor', source_filter_anchor='test-source-anchor',
                        counts={g: wave_counts(group_rows(selected, g)) for g in groups},
                        statistics=safe_statistics(statistics(selected, role, groups)), changes=safe_changes(changes))
            view['grade'] = build_cube(selected, role, view, groups, 'student_T0' if formal else 'student_wave')
            if source == 'all' and reference is not None:
                view['source_pairs'] = build_pairs(selected, reference, role, groups, sources)
            if source == 'all':
                view['histograms'] = []; view['trends'] = []
            views.append(view)
    snap = dict(release_id='synthetic-source', report_version=grade_header('x')['report_version'],
                dictionary_version=grade_header('x')['dictionary_version'], minimum_cell_n=0,
                small_sample_policy='none', grade=grade_header('synthetic-source'), views=views)
    snap['source_selection'] = header(snap['release_id'], views)
    validate_sources(snap)
    return snap


def js_choose(snap, contexts):
    script = GRADE_JS+JS_SOURCE+"""
const x=JSON.parse(require('fs').readFileSync(0,'utf8'));
const before=JSON.stringify(x);
const result=x.contexts.map(c=>Source.choose(x.snapshot,c));
if(before!==JSON.stringify(x))throw Error('input mutated');
console.log(JSON.stringify(result));
"""
    run = subprocess.run(['node', '-e', script], input=json.dumps(dict(snapshot=pack_snapshot(snap), contexts=contexts)),
                         text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


def context(sources, mode='abcd', role='student', mainstream=False, grades=GRADES):
    return dict(sources=sources, mode=mode, role=role, mainstream=mainstream, grades=grades, group='all')


def assert_statistics(got, selected, role, groups=SMALL_GROUPS):
    expected = safe_statistics(statistics(selected, role, groups))
    assert len(got['statistics']) == len(expected)
    for a, b in zip(got['statistics'], expected):
        for key in b:
            if key in {'mean', 'sd', 'proportion'}:
                assert a[key] == pytest.approx(b[key]) if b[key] is not None else a[key] is None
            else:
                assert a[key] == b[key], (key, a, b)
    assert got['counts'] == {g: wave_counts(group_rows(selected, g)) for g in groups}


def assert_pairs(got, selected, role, reference=None, groups=SMALL_GROUPS):
    expected = safe_changes(overview_changes(selected, reference, role, groups) if reference is not None else pair_details(selected, role, groups))
    assert [(r['group'], r['variable_id']) for r in got['changes']] == [(r['group'], r['variable_id']) for r in expected]
    for a, b in zip(got['changes'], expected):
        for key in ['pairs_n', 'paired_valid_n', 'paired_missing_n', 'only_t0_valid_n',
                    'only_t1_valid_n', 'both_missing_n', 't0_mean', 't1_mean', 'mean_change', 'sd_change']:
            assert a[key] == pytest.approx(b[key]) if b[key] is not None else a[key] is None, (key, a, b)
        if got['source_status'] == 'pooled':
            assert a['p_value'] is None and a['cohen_dz'] is None
            assert a['inference_status'] == 'custom_source_inference_unavailable'


@pytest.mark.parametrize('mode,role', [('abcd', 'student'), ('ef', 'parent'), ('acbd', 'parent'),
    ('efmatched', 'parent'), ('independent_all', 'parent'), ('independent_child', 'parent'), ('independent_adult', 'parent')])
def test_all_31_subsets_and_empty_against_row_filter(mode, role):
    base = invent(mode, role)
    reference = None
    if mode in {'abcd', 'ef', 'independent_all'}:
        ref_mode = {'abcd': 'acbd', 'ef': 'efmatched', 'independent_all': 'independent_child'}[mode]
        reference = base.copy()
        reference['report_mode'] = {'independent_child': 'independent_child_report'}.get(ref_mode, ref_mode)
        reference.attrs['mode'] = reference.report_mode.iloc[0]
        # EF/adult attribution must not use this formal source anchor.
        reference['anchor_source_type'] = 'school_batch'
    snap = payload(base, mode, role, reference)
    requests = [context(s, mode, role, mainstream) for mainstream in (False, True) for s in [*SUBSETS, []]]
    results = js_choose(snap, requests)
    for request, got in zip(requests, results):
        subset = request['sources']
        if not subset:
            assert got['source_status'] == 'empty' and got['statistics'] == got['changes'] == []
            assert 'grade' not in got
            assert all(v == {'T0': 0, 'T1': 0} for v in got['counts'].values())
            continue
        assert got['source_status'] != 'unavailable', got
        selected, _ = filter_cohort(base, mainstream=request['mainstream'], sources=subset)
        assert_statistics(got, selected, role)
        assert_pairs(got, selected, role, reference)
        if len(subset) not in (1, 5):
            assert got['source_capabilities']['paired_summaries']
            assert not got['source_capabilities']['inference']
            assert all(k not in got for k in ['histograms', 'paired_histograms', 'transitions', 'trends'])


def test_source_grade_intersection_pools_disjoint_cells_not_groups():
    base = invent('acbd', 'student'); snap = payload(base, 'acbd')
    requests = [context(s, 'acbd', grades=['P3', 'P4']) for s in SUBSETS]
    for req, got in zip(requests, js_choose(snap, requests)):
        selected, _ = filter_cohort(base, mainstream=False, sources=req['sources'])
        selected = selected.loc[selected._grade.isin(req['grades'])].copy()
        assert_statistics(got, selected, 'student'); assert_pairs(got, selected, 'student')
        assert got['grade_custom'] and not got['source_capabilities']['inference']
    # Empty grade selection is distinct from All and from empty source selection.
    got = js_choose(snap, [context(['paperform', 'qualtrics'], 'acbd', grades=[])])[0]
    assert got['source_status'] == 'pooled' and got['counts']['all'] == {'T0': 0, 'T1': 0}
    assert all(r['mean'] is None for r in got['statistics'])


def test_unknown_residual_is_disclosed_not_silently_in_five_sources():
    base = invent('acbd', residual=True); snap = payload(base, 'acbd')
    all_five, reset, six = js_choose(snap, [context(list(CODES), 'acbd'), context(['all'], 'acbd'), context([*CODES, 'unknown'], 'acbd')])
    assert all_five['source_status'] == 'pooled' and all_five['counts']['all']['T0'] == 31
    assert reset['source_status'] == six['source_status'] == 'all'
    assert reset['statistics'] == six['statistics'] and reset['counts']['all']['T0'] == 32


def test_parent_phq_gate_keeps_dangling_unconfirmed_slot():
    base = invent('abcd', 'parent'); reference = base.copy()
    reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    reference['adult_continuity_confirmed'] = True
    reference.loc[2, 'adult_continuity_confirmed'] = False
    # A changed displayed version leaves a dangling bad slot in formal eligibility.
    base.loc[3, 'version_id'] = 'different-version'
    snap = payload(base, 'abcd', 'parent', reference)
    requests = [context(s, 'abcd', 'parent') for s in SUBSETS]
    for req, got in zip(requests, js_choose(snap, requests)):
        selected, _ = filter_cohort(base, mainstream=False, sources=req['sources'])
        assert_pairs(got, selected, 'parent', reference)
    cube = snap['views'][0]['source_pairs']
    for group in cube['groups']:
        for cell in group['cells']:
            if not cell['pairs_n']: continue
            if not all(group['source_eligibility'][cell[k]]['adult_confirmed'] for k in ('t0_source', 't1_source')):
                assert cell['pairs'][0] is None


def test_all_singleton_legacy_and_invalid_selections_are_explicit():
    base = invent('acbd'); snap = payload(base, 'acbd')
    legacy = deepcopy(snap); legacy.pop('source_selection')
    for v in legacy['views']: v.pop('source_pairs', None)
    requests = [context(s, 'acbd') for s in [['all'], ['qualtrics'], ['paperform', 'qualtrics'], [],
                ['all', 'paperform'], ['paperform', 'paperform'], ['unknown'], ['bogus']]]
    got = js_choose(legacy, requests)
    assert [v['source_status'] for v in got] == ['all', 'single', 'unavailable', 'empty', 'unavailable', 'unavailable', 'unavailable', 'unavailable']
    for s, out in zip(['all', 'qualtrics'], got):
        original = next(v for v in snap['views'] if v['source'] == s and not v['mainstream'])
        assert out['statistics'] == original['statistics'] and out['changes'] == original['changes']
    protected = deepcopy(legacy); protected['minimum_cell_n'] = 10; protected['small_sample_policy'] = 'threshold'
    out = js_choose(protected, requests[:3]); assert [x['source_status'] for x in out] == ['all', 'single', 'unavailable']


@pytest.mark.parametrize('defect', ['pin', 'counts', 'grade', 'duplicate', 'matrix_count', 'matrix_missing', 'matrix_moment', 'gate', 'payload'])
def test_malformed_contract_fails_closed_without_fallback(defect):
    base = invent(); reference = base.copy(); reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    snap = payload(base, reference=reference)
    if defect == 'pin': snap['source_selection']['release_id'] = 'wrong'
    elif defect == 'counts': snap['views'][1]['counts']['all']['T0'] += 1
    elif defect == 'grade': snap['views'][1]['grade']['cells'].pop()
    elif defect == 'duplicate': snap['views'].append(deepcopy(snap['views'][1]))
    else:
        cube = snap['views'][0]['source_pairs']; block = cube['groups'][0]
        cell = next(c for c in block['cells'] if c['pairs_n'])
        if defect == 'matrix_count': cell['pairs_n'] += 1
        elif defect == 'matrix_missing': block['cells'].pop()
        elif defect == 'matrix_moment': cell['pairs'][0][7] += 3
        elif defect == 'gate': block['source_eligibility']['paperform']['matched_n'] = -1
        else: cell['private_record'] = 'must-not-export'
    with pytest.raises(PipelineError): validate_sources(snap)
    got = js_choose(snap, [context(['paperform', 'qualtrics'])])[0]
    if defect in {'pin', 'counts', 'grade', 'duplicate'}:
        assert got['source_status'] == 'unavailable' and got['statistics'] == []
        assert 'grade' not in got
    else:
        assert got['source_status'] == 'pooled' and got['statistics']
        assert not got['source_capabilities']['paired_summaries'] and got['changes'] == []


def test_missing_joint_evidence_preserves_wave_summaries_not_unfiltered_pairs():
    base = invent(); reference = base.copy(); reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    snap = payload(base, reference=reference)
    snap['views'][0].pop('source_pairs')
    out = js_choose(snap, [context(['paperform', 'qualtrics']), context(['paperform', 'qualtrics'], grades=['P3'])])
    assert all(v['statistics'] and not v['changes'] and not v['source_capabilities']['paired_summaries'] for v in out)


def test_cross_source_adult_single_slot_keeps_original_missing_detail():
    base = invent('abcd', 'parent').iloc[:2].copy()
    base['anchor_source_type'] = ['paperform', 'qualtrics']
    reference = base.copy(); reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    reference['adult_continuity_confirmed'] = True
    snap = payload(base, 'abcd', 'parent', reference, groups=('all',))
    singleton = next(v for v in snap['views'] if v['source'] == 'paperform' and not v['mainstream'])
    phq = next(r for r in singleton['changes'] if r['variable_id'] == 'PHQ_total')
    assert phq['pair_detail_status'] == 'not_provided' and phq['pairs_n'] == 0
    result = js_choose(snap, [context(['paperform', 'qualtrics'], role='parent')])[0]
    assert result['source_capabilities']['paired_summaries']
    phq = next(r for r in result['changes'] if r['variable_id'] == 'PHQ_total')
    assert phq['pairs_n'] == 1 and phq['only_t1_valid_n'] == 1
    assert phq['t0_mean'] is None and phq['t1_mean'] is None


def test_packed_all_and_single_preserve_distribution_and_period_decoding():
    snap = payload(invent('acbd'), 'acbd')
    v = snap['views'][0]
    v['histograms'] = [dict(wave='T0', count=2, bin_left=0., bin_right=1.)]
    v['paired_histograms'] = [dict(wave='T0', count=1, bin_left=0., bin_right=1.)]
    v['transitions'] = [dict(count=3, transition='both')]
    v['trends'] = [dict(period='2025-01', include_batch=False, counts={'T0': 32, 'T1': 0}, statistics=v['statistics'][:1])]
    actual = js_choose(snap, [context(['all'], 'acbd')])[0]
    for k in ['statistics', 'changes', 'histograms', 'paired_histograms', 'transitions', 'trends']:
        assert actual[k] == v[k]
    assert actual['source_capabilities']['distributions'] and actual['source_capabilities']['monthly_trends']


def test_all_grade_source_statistics_reconcile_with_original_all_not_only_counts():
    snap = payload(invent('acbd'), 'acbd')
    v = snap['views'][1]
    # A consistently altered source cube and its own summary can validate alone,
    # but its moments must still reconcile to the untouched All partition.
    for r in v['statistics']:
        if r['variable_id'] == 'PHQ_total' and r['mean'] is not None: r['mean'] += 1
    ixs = [i for i, m in enumerate(v['grade']['statistics_schema']) if m['variable_id'] == 'PHQ_total']
    for cell in v['grade']['cells']:
        if cell['statistics']:
            for i in ixs:
                if cell['statistics'][i][4] is not None: cell['statistics'][i][4] += 1
    with pytest.raises(PipelineError): validate_sources(snap)
    assert js_choose(snap, [context(['paperform', 'qualtrics'], 'acbd')])[0]['source_status'] == 'unavailable'


def test_synthetic_export_roundtrip_uses_real_anchors_and_unchanged_source_tables(tmp_path, monkeypatch):
    import study2.static_export as export
    import study2.descriptives as desc
    from test_static_quality_integration import synthetic_publication
    # Real cohort/attach_measurements code; no research pipeline or live state.
    monkeypatch.setattr(export, 'GROUPS', {'all': 'All'})
    fixture = synthetic_publication(tmp_path/'published')
    path = fixture['folder']/'descriptive_measurements.parquet'
    measurement = pd.read_parquet(path); measurement['school_stage_status'] = 'valid'
    measurement.to_parquet(path, index=False)
    imported = fixture['frame'].groupby(['source_type', 'role', 'wave']).size().reset_index(name='submissions')
    snap = export.build_snapshot(fixture['folder'], fixture['summary'], imported)
    assert isinstance(snap['sources'], dict) and {'all', 'student', 'parent'} == set(snap['sources'])
    assert snap['source_selection']['format'] == 'study2_descriptive_sources_v1'
    assert len(snap['views']) == 11*2*6
    assert all('unknown' != v['source'] for v in snap['views'])
    validate_sources(pack_snapshot(snap))
    # Parent EF source is this respondent's source; matched EF stays on student T0.
    for mode in ['abcd', 'ef', 'acbd', 'efmatched']:
        for role in ['student', 'parent']:
            base = desc.cohort(fixture['frame'], fixture['parents'], measurement, mode, role)
            requests = [context(s, mode, role) for s in [['paperform', 'qualtrics'], ['all'], ['qualtrics']]]
            for request, got in zip(requests, js_choose(snap, requests)):
                assert got['source_status'] != 'unavailable', got
                selected, _ = filter_cohort(base, mainstream=False, sources=() if request['sources'] == ['all'] else request['sources'])
                assert got['counts']['all'] == wave_counts(selected)
                got_phq = next(r for r in got['statistics'] if r['variable_id'] == 'PHQ_total' and r['wave'] == 'T0')
                expected = statistics(selected, role).query("variable_id=='PHQ_total' and wave=='T0'").iloc[0]
                assert got_phq['valid_n'] == expected.valid_n
                assert got_phq['mean'] == pytest.approx(expected['mean']) if pd.notna(expected['mean']) else got_phq['mean'] is None


def test_empty_source_does_not_disable_confirmed_formal_parent_phq():
    base = invent('acbd', 'parent'); base['anchor_source_type'] = 'qualtrics'
    snap = payload(base, 'acbd', 'parent')
    got = js_choose(snap, [context(['paperform', 'qualtrics'], 'acbd', 'parent')])[0]
    assert any(r['variable_id'] == 'PHQ_total' for r in got['changes'])
    assert_pairs(got, base, 'parent')


def test_missing_bd_reference_retains_valid_wave_union():
    base = invent('abcd', 'parent')
    snap = payload(base, 'abcd', 'parent')
    assert not snap['views'][0]['changes'] and 'source_pairs' not in snap['views'][0]
    got = js_choose(snap, [context(['paperform', 'qualtrics'], role='parent')])[0]
    assert got['source_status'] == 'pooled' and got['source_capabilities']['statistics']
    assert not got['source_capabilities']['paired_summaries'] and got['changes'] == []


def test_overview_actual_slots_and_changing_wave_groups_are_intersections():
    base = invent('abcd', 'parent'); reference = base.copy()
    reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    reference['adult_continuity_confirmed'] = True
    base.loc[0, 'submission_id'] = 'alternative-displayed-baseline'
    base.loc[3, 'version_id'] = 'alternative-displayed-version'
    base.loc[5, 'anchor_school_stage'] = 'secondary'
    base.loc[7, 'anchor_mainstream'] = False
    snap = payload(base, 'abcd', 'parent', reference)
    requests = [context(['paperform', 'qualtrics'], role='parent', mainstream=m) for m in (False, True)]
    for req, got in zip(requests, js_choose(snap, requests)):
        selected, _ = filter_cohort(base, mainstream=req['mainstream'], sources=req['sources'])
        assert_statistics(got, selected, 'parent'); assert_pairs(got, selected, 'parent', reference)


def test_invalid_grade_selection_returns_unavailable_instead_of_throwing():
    snap = payload(invent('acbd'), 'acbd')
    got = js_choose(snap, [context(['paperform', 'qualtrics'], 'acbd', grades=['P99'])])[0]
    assert got['source_status'] == 'unavailable' and got['statistics'] == []
    assert 'grade' not in got


def test_absent_published_score_columns_keep_not_provided_details(monkeypatch):
    extra = next(v.key for v in variables('parent', 'scales') if v.kind == 'continuous' and v.key not in CHOSEN)
    def selected(role, section=None):
        return [v for v in variables(role, section) if v.key in CHOSEN | {extra}]
    for name in ['study2.descriptives', 'study2.static_grade', 'study2.static_sources', 'study2.descriptive_exploration']:
        monkeypatch.setattr(name+'.variables', selected)
    base = invent('abcd', 'parent'); reference = base.copy()
    reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    reference['adult_continuity_confirmed'] = True
    assert extra not in reference.columns
    snap = payload(base, 'abcd', 'parent', reference)
    got = js_choose(snap, [context(['paperform', 'qualtrics'], role='parent')])[0]
    selected_rows, _ = filter_cohort(base, mainstream=False, sources=['paperform', 'qualtrics'])
    assert_pairs(got, selected_rows, 'parent', reference)
    missing = next(r for r in got['changes'] if r['variable_id'] == extra and r['group'] == 'all')
    assert missing['pairs_n'] > 0 and missing['paired_valid_n'] == 0
    assert missing['pair_detail_status'] == 'not_provided' and missing['both_missing_n'] is None


def test_unknown_source_overview_matrix_has_complete_residual_partition():
    base = invent(residual=True); reference = base.copy()
    reference['report_mode'] = 'acbd'; reference.attrs['mode'] = 'acbd'
    snap = payload(base, reference=reference)
    requests = [context(s) for s in [['unknown', 'qualtrics'], list(CODES), [*CODES, 'unknown']]]
    for req, got in zip(requests, js_choose(snap, requests)):
        selected_rows, _ = filter_cohort(base, mainstream=False, sources=req['sources'])
        assert_statistics(got, selected_rows, 'student'); assert_pairs(got, selected_rows, 'student', reference)


# P2_LEGACY_SUMMARY_HIDDEN: stored summary and optional newer detail are distinct.
LEGACY_DETAIL_FIELDS = ('pair_detail_status', 'only_t0_valid_n', 'only_t1_valid_n',
                        'both_missing_n', 't0_mean', 't1_mean')


def legacy_summary_snapshot(role='student', mode='acbd', explicit_missing=False):
    from study2.static_export import validate_snapshot
    snap = payload(invent(mode, role), mode, role, groups=('all',))
    snap.pop('source_selection'); snap.pop('grade')
    for view in snap['views']:
        view.pop('grade'); view.pop('source_pairs', None)
        for row in view['changes']:
            for key in LEGACY_DETAIL_FIELDS:
                row.pop(key, None)
            if explicit_missing:
                row.update({key: 'not_provided' if key == 'pair_detail_status' else None
                            for key in LEGACY_DETAIL_FIELDS})
    validate_snapshot(snap)
    return snap


def render_legacy_summary(view, snap, request):
    """Execute the unchanged r2 renderer and CSV writer without a web server."""
    from pathlib import Path
    assets = (Path(__file__).resolve().parents[1]/'study2/static_assets.py').read_text()
    def function(name, end):
        return assets[assets.index('function '+name):assets.index('\nfunction '+end, assets.index('function '+name))]
    code = r'''
const x=JSON.parse(require('fs').readFileSync(0,'utf8'));
let buttons=[],tables=[],downloads=[],contentHost={append(){}};
const S=x.snapshot,state={...x.request,reading:'paired',section:'scales',family:'all'},parent=null,page=1;
const Source={choose:()=>x.view};
const el=(tag,cls,text)=>{const node={text,append(){}};if(tag==='button')buttons.push(node);return node;};
const section=()=>({append(){}}),notice=()=>{},select=()=>{},render=()=>{},distribution=()=>{};
const table=(host,rows,columns)=>tables.push({rows,columns});
const download=(text,name)=>downloads.push({text,name});
const num=v=>v===null||v===undefined?'—':Number(v).toFixed(2),n=v=>String(v);
const families={all:'All',PHQ:'PHQ',FQOL:'FQOL',SEC:'SEC',bullying:'Bullying'};
'''
    code += '\n'.join([function('statValue(', 'scoreMeaning('),
        function('scoreMeaning(', 'pValue('), function('pValue(', 'inferenceNote('),
        function('comparisonRows(', 'periodComparison('), function('csv(', 'table('),
        function('statisticsTable(', 'distribution('), function('paired(', 'trends(')])
    code += r'''
paired(x.view,state);
const pairedTables=tables.slice();
const pairedButton=buttons.find(b=>b.text==='Download all paired changes (CSV)');
if(pairedButton)pairedButton.onclick();
const pairedDownload=downloads.at(-1)||null;
tables=[];buttons=[];downloads=[];
state.reading='overview';statisticsTable(x.view,state);
const overviewButton=buttons.find(b=>b.text==='Download current category (CSV)');
if(overviewButton)overviewButton.onclick();
console.log(JSON.stringify({paired_download:pairedDownload,paired_tables:pairedTables,
 overview_download:downloads.at(-1)||null,overview_tables:tables}));
'''
    run = subprocess.run(['node', '-e', code], input=json.dumps(dict(view=view, snapshot=snap, request=request)),
                         text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


@pytest.mark.parametrize('source', ['all', 'qualtrics'])
@pytest.mark.parametrize('role', ['student', 'parent'])
@pytest.mark.parametrize('explicit_missing', [False, True])
def test_legacy_stored_summary_and_csv_survive_absent_complete_pair_detail(source, role, explicit_missing):
    import csv
    import io
    import math
    snap = legacy_summary_snapshot(role, explicit_missing=explicit_missing)
    original = next(v for v in snap['views'] if v['source'] == source and not v['mainstream'])
    req = context([source], 'acbd', role)
    out = js_choose(snap, [req])[0]
    assert out['statistics'] == original['statistics'] and out['changes'] == original['changes']
    phq = next(r for r in out['changes'] if r['variable_id'] == 'PHQ_total')
    assert phq['paired_valid_n'] > 1 and math.isfinite(phq['p_value']) and math.isfinite(phq['cohen_dz'])
    assert out['source_capabilities']['paired_summaries'] and out['source_capabilities']['inference']
    for row in out['changes']:
        if explicit_missing:
            assert row['pair_detail_status'] == 'not_provided'
            assert all(row[k] is None for k in LEGACY_DETAIL_FIELDS if k != 'pair_detail_status')
        else:
            assert not any(k in row for k in LEGACY_DETAIL_FIELDS)
    rendered = render_legacy_summary(out, snap, req)
    assert rendered['paired_download'] is not None
    paired_csv = list(csv.DictReader(io.StringIO(rendered['paired_download']['text'].lstrip('\ufeff'))))
    paired_phq = next(r for r in paired_csv if r['Variable ID'] == 'PHQ_total')
    assert float(paired_phq['p-value (raw)']) == phq['p_value']
    assert float(paired_phq['Cohen dz (raw)']) == phq['cohen_dz']
    assert paired_phq['T0 mean (raw, paired-valid)'] == paired_phq['T1 mean (raw, paired-valid)'] == ''
    assert paired_phq['Only T0 valid N'] == paired_phq['Only T1 valid N'] == paired_phq['Both missing N'] == ''
    overview = next(t for t in rendered['overview_tables'] if 'test_n' in t['columns'] and
                    any(r['variable_id'] == 'PHQ_total' for r in t['rows']))
    assert {'test_n', 'p', 'dz'} <= set(overview['columns'])
    overview_csv = list(csv.DictReader(io.StringIO(rendered['overview_download']['text'].lstrip('\ufeff'))))
    overview_phq = next(r for r in overview_csv if r['Variable ID'] == 'PHQ_total')
    assert float(overview_phq['p-value (raw)']) == phq['p_value']
    assert float(overview_phq['Cohen dz (raw)']) == phq['cohen_dz']
    assert overview_phq['Paired availability status'] == 'not_provided'


def test_legacy_empty_summary_remains_unavailable():
    snap = legacy_summary_snapshot()
    for view in snap['views']: view['changes'] = []
    for out in js_choose(snap, [context(['all'], 'acbd'), context(['qualtrics'], 'acbd')]):
        assert not out['source_capabilities']['paired_summaries']
        assert not out['source_capabilities']['inference'] and out['changes'] == []


def test_legacy_missing_contract_cannot_enable_union_or_custom_grade():
    snap = legacy_summary_snapshot()
    requests = [context(['paperform', 'qualtrics'], 'acbd'), context(['all'], 'acbd', grades=['P3'])]
    for out in js_choose(snap, requests):
        assert out['source_status'] == 'unavailable' and out['changes'] == []
        assert not out['source_capabilities']['paired_summaries'] and not out['source_capabilities']['inference']
        assert out['counts']['all'] == {'T0': None, 'T1': None}


def test_legacy_same_child_parent_summary_does_not_gain_adult_phq():
    snap = legacy_summary_snapshot('parent', 'independent_child')
    for out in js_choose(snap, [context(['all'], 'independent_child', 'parent'),
                               context(['qualtrics'], 'independent_child', 'parent')]):
        assert out['source_capabilities']['paired_summaries']
        assert out['changes'] and not any(r['variable_id'].startswith('PHQ_') for r in out['changes'])
