"""R2: positive-controlled closed ON lane; only frozen invented data."""
from collections import Counter
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path

import pandas as pd
import pytest

from study2.analysis_eligibility import EligibilityError, inventory_revision, manifest_revision, project_eligibility, projected_cohorts, sha
from study2.common import PipelineError, digest, plain
from study2.descriptive_spec import variables
from study2.manual_exclusion_export import _unpack, build_manual_export, validate_manual_export
from study2.static_export import build_views, english_snapshot, SCOPE_EXPORT_FORMAT
from study2.static_scope import ADULT_POLICY, build_scope_index, query_scope
from study2.static_sources import header as source_header

FROZEN = Path(os.environ['STUDY2_MANUAL_FIXTURE_ROOT']) if os.environ.get('STUDY2_MANUAL_FIXTURE_ROOT') else None


@pytest.fixture(scope='module')
def fixture():
    # Intentionally consume the already frozen actual core fixture, not a new
    # inferred catalogue. This is the reviewer's positive-control boundary.
    if FROZEN is None:
        pytest.skip('Set STUDY2_MANUAL_FIXTURE_ROOT to the revision-pinned synthetic r1 bundle.')
    for name, expected in {
        'SYNTHETIC_FIXTURE.json': '4a5558082f906344bab41c0ef0137e8f1360346534ac807305c576826552018a',
        'SYNTHETIC_INPUT_ORACLE.json': '759786029bf3545bb2a4b3a2f19ca5b98a49a1c3ed8e1185c09d9a5bad9190ef',
    }.items():
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == expected
    value = json.loads((FROZEN / 'SYNTHETIC_FIXTURE.json').read_text())
    return value, _unpack(value['snapshot'])


def keep_declared_catalogue(monkeypatch, snapshot):
    chosen = {role: {r['variable_id'] for v in snapshot['views'] if v['role'] == role
                     for r in v['statistics']} for role in ('student', 'parent')}
    monkeypatch.setattr('study2.static_sources.variables', lambda role, section=None:
                        [v for v in variables(role, section) if v.key in chosen[role]])


def test_frozen_fixture_positive_control_remains_valid(fixture, monkeypatch):
    value, snapshot = fixture
    keep_declared_catalogue(monkeypatch, snapshot)
    assert validate_manual_export(value['manual_exclusion'], snapshot, value['scope_export'])


@pytest.mark.parametrize('case', ['no_views', 'missing_one_projection', 'missing_one_source',
    'duplicate_projection', 'private_view', 'private_statistic', 'private_histogram',
    'private_trend', 'private_source_count', 'private_scope', 'identifier_value', 'missing_trends',
    'private_metric_label', 'private_transition_label', 'private_pair_schema_label'])
def test_on_payload_rejects_rehashed_incomplete_or_private_projection(fixture, monkeypatch, case):
    value, snapshot = fixture
    keep_declared_catalogue(monkeypatch, snapshot)
    wrapper = deepcopy(value['manual_exclusion'])
    on = wrapper['on']['snapshot']; views = on['views']
    if case == 'no_views': on['views'] = []
    elif case == 'missing_one_projection': on['views'] = [v for v in views if not (v['mode'] == 'acbd' and v['role'] == 'student')]
    elif case == 'missing_one_source': views.pop(1)
    elif case == 'duplicate_projection': views.append(deepcopy(views[0]))
    elif case == 'private_view': views[0]['private_response_ids'] = ['R_' + 'Q' * 14]
    elif case == 'private_statistic':
        views[0]['statistics']['columns'].append('private_response_ids')
        for row in views[0]['statistics']['rows']: row.append(['R_' + 'Q' * 14])
    elif case == 'private_histogram':
        table = views[0]['histograms']
        if isinstance(table, dict):
            table['columns'].append('private_response_ids')
            for row in table['rows']: row.append(['R_' + 'Q' * 14])
        else:
            table[0]['private_response_ids'] = ['R_' + 'Q' * 14]
    elif case == 'private_trend': views[0]['trends'][0]['private_response_ids'] = ['R_' + 'Q' * 14]
    elif case == 'private_source_count': on['sources']['all'][0]['private_response_ids'] = ['R_' + 'Q' * 14]
    elif case == 'private_scope': wrapper['on']['scope_export']['index']['records'][0]['private_response_ids'] = ['R_' + 'Q' * 14]
    elif case == 'identifier_value': views[0]['grouping_anchor'] = 'R_' + 'Q' * 14
    elif case == 'missing_trends': views[0].pop('trends')
    elif case == 'private_metric_label':
        table = views[0]['statistics']; table['rows'][0][table['columns'].index('variable')] = 'R_' + 'Q' * 14
    elif case == 'private_transition_label':
        view = next(v for v in views if v.get('transitions'))
        view['transitions']['rows'][0][view['transitions']['columns'].index('transition')] = 'R_' + 'Q' * 14
    elif case == 'private_pair_schema_label':
        views[0]['source_pairs']['groups'][0]['pairs_schema'][0]['variable'] = 'R_' + 'Q' * 14
    wrapper['on_revision'] = sha(wrapper['on'])  # Legitimate hash is not authorization.
    with pytest.raises((EligibilityError, PipelineError, ValueError)):
        validate_manual_export(wrapper, snapshot, value['scope_export'])


def test_public_release_hash_and_numeric_display_metadata_are_not_masked(fixture, monkeypatch):
    from study2.static_export import pack_snapshot
    value, original = fixture
    off = deepcopy(original); scope = deepcopy(value['scope_export'])
    wrapper = deepcopy(value['manual_exclusion'])
    release = 'RUN_' + 'a' * 32
    note = ['Academic survey 2025/2026', 'Public N=12345; 1e-06; revision ' + 'b' * 64]
    for snap in (off, wrapper['on']['snapshot']):
        snap['release_id'] = release
        snap['grade']['release_id'] = release
        snap['source_selection']['release_id'] = release
        snap['notes'].append(note)
    for export in (scope, wrapper['on']['scope_export']):
        export['release_id'] = release
        export['index']['meta']['release_id'] = release
        export['index_revision'] = digest(export['index'])
    wrapper['release_id'] = release
    wrapper['off'] = dict(snapshot_revision=sha(plain(pack_snapshot(off))), scope_revision=sha(scope))
    wrapper['on_revision'] = sha(wrapper['on'])
    keep_declared_catalogue(monkeypatch, off)
    assert validate_manual_export(wrapper, off, scope)


def residual_inputs(monkeypatch, fixture):
    value, old_snapshot = fixture
    data = json.loads((FROZEN / 'SYNTHETIC_INPUT_ORACLE.json').read_text())
    records = deepcopy(data['records'])
    frame = pd.DataFrame(data['analysis']); parents = pd.DataFrame(data['parents'])
    measurements = pd.DataFrame(data['measurements'])
    panel = {k: pd.DataFrame(rows) for k, rows in data['panel'].items()}
    panel['candidates'] = pd.DataFrame(columns=['one_digit_candidate'])
    panel['sensitivity'] = pd.DataFrame(columns=['experiment'])
    residual_ids = {'toy-record-ls0', 'toy-record-ls1'}
    for r in records:
        if r['submission_id'] in residual_ids: r['source_type'] = 'unknown'
    frame.loc[frame.submission_id.isin(residual_ids), 'source_type'] = 'unknown'
    chosen = {'PHQ_total', 'FQOL_total', 'TBV_prevalence1'}
    for module in ['study2.static_export', 'study2.descriptives', 'study2.static_grade',
                   'study2.static_sources', 'study2.descriptive_exploration']:
        monkeypatch.setattr(module + '.variables', lambda role, section=None:
                            [v for v in variables(role, section) if v.key in chosen])
    monkeypatch.setattr('study2.static_export.GROUPS', {'all': 'All'})
    summary = dict(release_id=old_snapshot['release_id'], adult_identity_policy=ADULT_POLICY,
        submissions=len(records), status_counts=dict(Counter(r['status'] for r in records)),
        **{r['code']: r['baseline'] for r in value['manual_exclusion']['impact']['samples']},
        stage_counts={'1.1': 23, '2.1.3': 21, '2.1.4': {'eligible_submissions': 19, 'child_groups': 3},
                      '2.1.6': 17, '3.1.1': dict(A=3, B=3, C=3, D=3), '3.1.2/3.1.3': dict(E=3, F=3, EF=3)},
        independent_parent=dict(parent_submissions=12, baselines=1, child_report_pairs=1,
            same_adult_pairs=1, same_adult_alternative_T1=1, minimum_followup_days=90, one_digit_candidates=0))
    summary['parent_child_longitudinal'] = 3
    original = project_eligibility(records, frame, parents, None, summary['release_id'], enabled=False, panel=panel)
    scopes = projected_cohorts(records, frame, parents, measurements, original, panel=panel)
    snapshot = deepcopy(old_snapshot)
    from study2.dashboard_views import SAMPLE_NAMES
    snapshot['counts']['parent_child_longitudinal'] = 3
    snapshot['samples'] = [dict(sample=k, label=v, count=snapshot['counts'][k]) for k, v in SAMPLE_NAMES.items()]
    snapshot['views'] = build_views(frame, parents, measurements, summary, '.', 0, prepared_scopes=scopes)
    snapshot['source_selection'] = source_header(snapshot['release_id'], snapshot['views'])
    from study2.dashboard_views import source_wave_counts
    from study2.static_export import count_table
    imported = pd.DataFrame([dict(source_type=r['source_type'], role=r['role'],
                                  wave=r['claimed_wave'], submissions=1) for r in records])
    snapshot['sources'] = {role: count_table(source_wave_counts(imported, frame,
        None if role == 'all' else role).to_dict('records')) for role in ('all', 'student', 'parent')}
    # Keep only stages whose actual values are declared by this invented oracle.
    snapshot['stages'] = [r for r in snapshot['stages'] if r['階段'] in summary['stage_counts']]
    english_snapshot(snapshot, summary)
    index = build_scope_index(records, frame, parents, summary)
    scope = dict(format=SCOPE_EXPORT_FORMAT, status='available', release_id=summary['release_id'],
                 index_revision=digest(index), index=index, school_bindings=[], reconciliation=index['meta']['reconciliation'])
    return records, frame, parents, measurements, panel, summary, snapshot, scope, imported, residual_ids


def manifest_for(records, ids, release):
    manifest = dict(format='study2_manual_exclusion_manifest_v1', release_id=release,
        inventory_revision=inventory_revision(records), status='accepted', approved_by='Synthetic reviewer',
        approved_at='2026-10-23T10:00:00+08:00', copy_policy='all_byte_identical_copies',
        entries=[dict(submission_id=r['submission_id'], version_id=r['version_id']) for r in records if r['submission_id'] in ids])
    manifest['revision'] = manifest_revision(manifest)
    return manifest


def test_default_full_sample_names_updates_supplementary_parent_row(fixture, monkeypatch):
    from study2.dashboard_views import SAMPLE_NAMES
    records, frame, parents, measurements, panel, summary, off, scope, imported, residual = residual_inputs(monkeypatch, fixture)
    manifest = manifest_for(records, {'toy-record-kp1'}, summary['release_id'])
    wrapper = build_manual_export(off, scope, records, frame, parents, measurements, summary, imported, manifest, panel=panel)
    assert wrapper['status'] == 'available', wrapper['code']
    on = _unpack(wrapper['on']['snapshot'])
    assert [r['sample'] for r in on['samples']] == list(SAMPLE_NAMES)
    row = next(r for r in on['samples'] if r['sample'] == 'parent_child_longitudinal')
    assert on['counts']['parent_child_longitudinal'] == row['count'] == 2
    assert on['counts']['BD'] == 2 and on['counts']['D'] == 2
    assert len(wrapper['impact']['samples']) == 9
    assert wrapper['impact']['samples'] == query_scope(wrapper['on']['scope_export']['index'])['eligibility']['samples']


def test_unsupported_sample_name_is_explicitly_unavailable_without_mutating_off(fixture):
    value, snapshot = fixture
    off = deepcopy(snapshot)
    off['counts']['not_an_approved_sample'] = 1
    off['samples'].append(dict(sample='not_an_approved_sample', label='Unsupported synthetic sample', count=1))
    before = deepcopy(off)
    oracle = json.loads((FROZEN / 'SYNTHETIC_INPUT_ORACLE.json').read_text())
    wrapper = build_manual_export(off, value['scope_export'], oracle['records'], pd.DataFrame(oracle['analysis']),
        pd.DataFrame(oracle['parents']), pd.DataFrame(oracle['measurements']), {}, pd.DataFrame(),
        oracle['accepted_manifest'])
    assert wrapper['status'] == 'unavailable' and wrapper['code'] == 'unsupported_manual_sample_catalogue'
    assert wrapper['on'] is None and off == before


def test_static_source_header_preserves_existing_zero_residual_catalogue():
    assert source_header('synthetic-release', [dict(source='unknown', counts={'all': dict(T0=0, T1=0)})])['residual_present'] is True
    assert source_header('synthetic-release', [dict(source='qualtrics', counts={'all': dict(T0=0, T1=0)})])['residual_present'] is False


@pytest.mark.parametrize('all_rows', [False, True, None])
def test_zero_residual_and_zero_entire_analysis_preserve_baseline_options(fixture, monkeypatch, all_rows):
    records, frame, parents, measurements, panel, summary, off, scope, imported, residual = residual_inputs(monkeypatch, fixture)
    ids = set() if all_rows is None else {r['submission_id'] for r in records} if all_rows else residual
    manifest = manifest_for(records, ids, summary['release_id'])
    wrapper = build_manual_export(off, scope, records, frame, parents, measurements, summary, imported,
                                  manifest, panel=panel)
    assert wrapper['status'] == 'available', wrapper['code']
    on = _unpack(wrapper['on']['snapshot'])
    key = lambda v: (v['mode'], v['role'], v['mainstream'], v['source'])
    assert Counter(map(key, on['views'])) == Counter(map(key, off['views']))
    assert on['source_selection'] == off['source_selection']
    assert on['source_selection']['residual_present'] is True
    assert on['source_names'] == off['source_names']
    for view in on['views']:
        if all_rows is not None and (view['source'] == 'unknown' or all_rows):
            assert all(n == 0 for counts in view['counts'].values() for n in counts.values())
            assert all(r['sample_n'] == r['valid_n'] == r['missing_n'] == 0 for r in view['statistics'])
        assert view['grade']['anchor'] == next(v for v in off['views'] if key(v) == key(view))['grade']['anchor']
        assert len(view['grade']['cells']) == len(next(v for v in off['views'] if key(v) == key(view))['grade']['cells'])
    if all_rows:
        assert all(r['active'] == 0 for r in wrapper['impact']['samples'])
        assert all(r['active'] == 0 for r in wrapper['impact']['independent'].values())
    if all_rows is None:
        for field in ('counts', 'samples', 'sources', 'views', 'source_selection', 'independent_counts'):
            assert plain(on[field]) == plain(off[field])
    assert validate_manual_export(wrapper, off, scope)
