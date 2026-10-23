"""Invented records only: native tuple oracle, binding, parity and export."""
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from study2.analysis_eligibility import (COPY_POLICY, MANIFEST_FORMAT, EligibilityError,
    inventory_revision, manifest_revision, project_eligibility, projected_cohorts,
    query_scope_eligibility, scope_overlay, sha, validate_manifest)
from study2.static_scope import SLOTS, build_scope_index, default_selection, query_scope, validate_index
from study2.static_scope_client import JS_SOURCE as SCOPE_JS
from study2.manual_exclusion_export import JS_HASH, _unpack, build_manual_export, validate_manual_export
from static_scope_cases import synthetic_inputs


def accepted(records, ids=(), release='synthetic-mm-r02'):
    by_id = {r['submission_id']: r for r in records}
    value = dict(format=MANIFEST_FORMAT, release_id=release,
        inventory_revision=inventory_revision(records), status='accepted', approved_by='Synthetic reviewer',
        approved_at='2026-10-23T10:00:00+08:00', copy_policy=COPY_POLICY,
        entries=[dict(submission_id=s, version_id=by_id[s]['version_id']) for s in ids])
    value['revision'] = manifest_revision(value)
    return value


def inputs():
    records, analysis, parents, summary = synthetic_inputs()
    for r in records:
        r['raw_hash'] = sha(r['submission_id'])
    return records, pd.DataFrame(analysis), pd.DataFrame(parents), summary


def js_queries(index, selections):
    result = subprocess.run(['node', '-e', SCOPE_JS + "\nconst x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(x.scopes.map(s=>Study2Scope.query(x.index,s))));"],
        input=json.dumps(dict(index=index, scopes=selections)), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('flag', ['ks0', 'ks1', 'kp0', 'kp1', 'kb1', 'ms0', 'mp1', 'exact_s'])
def test_every_native_required_component_and_scope_correlations(flag):
    records, frame, parents, summary = inputs()
    sid = 'toy-record-' + flag
    baseline = project_eligibility(records, frame, parents, None, summary['release_id'], enabled=False)
    p = project_eligibility(records, frame, parents, accepted(records, [sid]), summary['release_id'])
    # Independent oracle: remove an original tuple iff it explicitly contains sid.
    for code in SLOTS:
        assert p.members[code] == tuple(m for m in baseline.members[code] if sid not in m)
    assert set(p.frame.submission_id) == set(frame.submission_id) - {sid}
    index = build_scope_index(records, frame, parents, summary)
    on = scope_overlay(index, records, p, accepted(records, [sid])['revision'], inventory_revision(records))
    scope = default_selection(index)
    cases = [None, {**scope, 'sources': []}, {**scope, 'surveys': []},
             {**scope, 'start': '2025-02-01', 'end': '2025-02-01', 'include_unknown': False}]
    cases += [{**scope, 'sources': list(c)} for size in (1, 2, 3)
              for c in combinations(scope['sources'], size)]
    cases += [{**scope, 'surveys': scope['surveys'][::2]}, {**scope, 'include_unknown': False}]
    py = [query_scope(on, c) for c in cases]
    assert js_queries(on, cases) == py
    for selected, result in zip(cases, py):
        canonical = query_scope(index, selected)
        assert result['raw'] == canonical['raw'] and result['flow'] == canonical['flow']
        assert all(r['baseline'] is None or r['active'] + r['excluded'] == r['baseline']
                   for r in result['eligibility']['samples'])


def test_off_does_not_validate_or_mutate_optional_manifest_and_no_replacement():
    records, frame, parents, summary = inputs()
    original = deepcopy(records)
    before = frame.copy(deep=True)
    bad = {'status': 'draft'}
    off = project_eligibility(records, frame, parents, bad, summary['release_id'], enabled=False)
    on = project_eligibility(records, frame, parents,
        accepted(records, ['toy-record-ks0']), summary['release_id'])
    again = project_eligibility(records, frame, parents, bad, summary['release_id'], enabled=False)
    assert off.members == again.members
    assert not any('extra_s' in sid or 'repeat_s' in sid for m in on.members['A'] for sid in m)
    pd.testing.assert_frame_equal(off.frame, again.frame)
    pd.testing.assert_frame_equal(frame, before)
    assert records == original


@pytest.mark.parametrize('defect', ['draft', 'release', 'inventory', 'revision', 'version', 'unknown',
                                   'duplicate', 'extra', 'approval', 'date', 'copies'])
def test_manifest_fails_closed(defect):
    records, _, _, summary = inputs()
    m = accepted(records, ['toy-record-ks0'])
    if defect == 'draft': m['status'] = 'draft'
    elif defect == 'release': m['release_id'] = 'other'
    elif defect == 'inventory': m['inventory_revision'] = '0' * 64
    elif defect == 'revision': m['revision'] = '0' * 64
    elif defect == 'version': m['entries'][0]['version_id'] = 'old'
    elif defect == 'unknown': m['entries'][0]['submission_id'] = 'invented-unmatched'
    elif defect == 'duplicate': m['entries'] *= 2
    elif defect == 'extra': m['unverified_contact'] = 'unused'
    elif defect == 'approval': m['approved_by'] = ''
    elif defect == 'date': m['approved_at'] = '2026-10-23'
    elif defect == 'copies':
        records[1]['raw_hash'] = records[0]['raw_hash']; m['inventory_revision'] = inventory_revision(records)
    if defect != 'revision': m['revision'] = manifest_revision(m)
    with pytest.raises(EligibilityError): validate_manifest(m, records, summary['release_id'])


def test_both_identical_copies_empty_sets_and_inventory_order():
    records, _, _, summary = inputs()
    records[1]['raw_hash'] = records[0]['raw_hash']
    ids = [r['submission_id'] for r in records[:2]]
    assert validate_manifest(accepted(records, ids), records[::-1], summary['release_id']) == frozenset(ids)
    assert not validate_manifest(accepted(records), records, summary['release_id'])


@pytest.mark.parametrize('defect', ['adult_student', 'adult_excluded', 'selected_excluded', 'bad_hash'])
def test_private_inventory_and_formal_artifact_roles_fail_closed(defect):
    records, frame, parents, summary = inputs()
    if defect == 'adult_student':
        parents.loc[parents.submission_id.eq('toy-record-kb1'), 'submission_id'] = 'toy-record-ks1'
    elif defect == 'adult_excluded':
        next(r for r in records if r['submission_id'] == 'toy-record-kb1')['status'] = 'incomplete'
    elif defect == 'selected_excluded':
        next(r for r in records if r['submission_id'] == 'toy-record-ks0')['status'] = 'manual_excluded'
    else:
        records[0]['raw_hash'] = 'not-a-content-hash'
    with pytest.raises(EligibilityError):
        project_eligibility(records, frame, parents, None, summary['release_id'], enabled=False)


@pytest.mark.parametrize('value', [1, 1.0, -0.0, 1e-6, 1e21, 1e-7, 1e30, 5e-324,
    {'\U0001f600': 1e-6, '\ue000': [1.0, -0.0], '漢字': '\u2028\u2029\b\f\t'},
    {'num': ['f64', '0000000000000000'], 'n': 0.0}, {'n': 9007199254740991}])
def test_hash_matches_browser_numeric_and_unicode_bits(value):
    driver = JS_HASH + "\nconst crypto=require('node:crypto');const x=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(crypto.createHash('sha256').update(Study2EligibilityHash.canonical(x)).digest('hex'));"
    run = subprocess.run(['node', '-e', driver], input=json.dumps(value, ensure_ascii=False),
                          text=True, capture_output=True, check=True)
    assert sha(value) == run.stdout.strip()
    assert sha(1) == sha(1.0) and sha(0) != sha(-0.0)
    assert sha(['f64', '0000000000000000']) != sha(0.0)


@pytest.fixture(scope='module')
def full(tmp_path_factory):
    from test_static_quality_integration import synthetic_publication
    from study2.parent_panel_views import read_panel
    from study2.static_export import build_snapshot, build_scope_export
    from study2.static_grade import validate_grade
    from study2.descriptive_spec import variables
    # Keep original Variable/scoring objects and every mode/source. Smaller
    # catalogue/group cross-product exercises the adapter without repeating
    # hundreds of identical metadata rows; existing regressions use full specs.
    chosen = {'PHQ_total', 'PHQ_anxiety', 'PHQ_depression', 'FQOL_total', 'SEC_total',
              'TBV_mean', 'TBP_mean', 'CBV_mean', 'CBP_mean', 'TBV_prevalence1', 'phq_band'}
    patch = pytest.MonkeyPatch()
    for module in ['study2.static_export', 'study2.descriptives', 'study2.static_grade',
                   'study2.static_sources', 'study2.descriptive_exploration']:
        patch.setattr(module + '.variables', lambda role, section=None: [
            v for v in variables(role, section) if v.key in chosen])
    patch.setattr('study2.static_export.GROUPS', {'all': 'All', 'male': 'Male', 'female': 'Female'})
    root = tmp_path_factory.mktemp('manual-synthetic-only')
    f = synthetic_publication(root)
    records = f['records']
    for r in records:
        r['raw_hash'] = sha(r['submission_id'])
    measurements = pd.read_parquet(f['folder'] / 'descriptive_measurements.parquet')
    measurements['school_stage_status'] = 'valid'
    measurements.to_parquet(f['folder'] / 'descriptive_measurements.parquet', index=False)
    imported = pd.DataFrame([dict(source_type=r['source_type'], role=r['role'],
                                  wave=r['claimed_wave'], submissions=1) for r in records])
    snapshot = build_snapshot(f['folder'], f['summary'], imported)
    snapshot['published_at'] = '2026-10-23T00:00:00Z'
    scope = build_scope_export(f['folder'], f['summary'])
    panel = read_panel(f['folder'])
    yield {**f, 'measurements': measurements, 'imported': imported, 'snapshot': snapshot,
           'scope': scope, 'panel': panel}
    patch.undo()


def build(f, ids):
    key = tuple(ids)
    cache = f.setdefault('_wrapper_cache', {})
    if key in cache:
        return deepcopy(cache[key])
    result = build_manual_export(f['snapshot'], f['scope'], f['records'], f['frame'], f['parents'],
        f['measurements'], f['summary'], f['imported'],
        accepted(f['records'], ['toy-record-' + x for x in ids], f['summary']['release_id']), panel=f['panel'])
    cache[key] = deepcopy(result)
    return result


def test_full_on_recomputation_independent_and_raw_history(full):
    f = full
    wrapper = build(f, ['ks0', 'kp1'])
    assert wrapper['status'] == 'available', wrapper.get('code')
    on = _unpack(wrapper['on']['snapshot'])
    assert {k: on['counts'][k] for k in SLOTS} == dict(A=2, B=3, C=3, D=2, AC=2, BD=2, E=2, F=2, EF=2)
    assert on['independent_counts']['child_report_pairs'] == 0
    assert on['independent_counts']['same_adult_pairs'] == 1
    assert on['independent_counts']['same_adult_alternative_T1'] == 1
    assert on['stages'] == f['snapshot']['stages']
    assert on['tracking'] == f['snapshot']['tracking']
    assert wrapper['impact']['intake']['student'] == dict(baseline=11, excluded=1, retained=10)
    assert wrapper['impact']['intake']['parent'] == dict(baseline=12, excluded=1, retained=11)
    def view(mode, role):
        return next(v for v in on['views'] if v['mode'] == mode and v['role'] == role
                    and not v['mainstream'] and v['source'] == 'all')
    phq = next(r for r in view('acbd', 'student')['changes'] if r['variable_id'] == 'PHQ_total' and r['group'] == 'all')
    assert phq['paired_valid_n'] == 2 and phq['t0_mean'] == 1.5 and phq['t1_mean'] == 2.5
    assert phq['mean_change'] == 1.0 and phq['cohen_dz'] == pytest.approx(2**-.5)
    for mode in ['efmatched', 'independent_child']:
        assert not any(r['variable_id'].startswith('PHQ') for r in view(mode, 'parent')['changes'])
    assert view('abcd', 'student')['counts']['all'] == {'T0': 2, 'T1': 3}
    # New source/grade aggregates pass existing validators, not a UI subtraction.
    from study2.static_grade import validate_grade
    from study2.static_sources import validate_sources
    validate_grade(on); validate_sources(on)
    assert all(r['count'] >= 0 for r in view('abcd', 'student')['histograms'])
    json_text = json.dumps(wrapper, ensure_ascii=False)
    for private in ['toy-record-', 'toy-child-', 'Synthetic reviewer', '/Users/', 'raw_hash', 'submission_id']:
        assert private not in json_text


def test_empty_accepted_on_equals_every_existing_off_statistic_and_capability(full):
    from study2.static_export import pack_snapshot
    wrapper = build(full, [])
    assert wrapper['status'] == 'available', wrapper['code']
    on = deepcopy(wrapper['on']['snapshot'])
    on.pop('eligibility_context')
    assert on == json.loads(json.dumps(pack_snapshot(full['snapshot'])))
    before = query_scope(full['scope']['index'])
    after = query_scope(wrapper['on']['scope_export']['index'])
    after.pop('eligibility'); after['scope_notice'] = before['scope_notice']
    assert after == before


def test_independent_all_unflagged_singleton_keeps_original_anchor(full):
    m = accepted(full['records'], ['toy-record-kp0'], full['summary']['release_id'])
    p = project_eligibility(full['records'], full['frame'], full['parents'], m,
                            full['summary']['release_id'], panel=full['panel'])
    scopes = projected_cohorts(full['records'], full['frame'], full['parents'], full['measurements'], p, panel=full['panel'])
    single = next(rows for mode, role, rows in scopes if mode == 'independent_all')
    assert list(single.submission_id) == ['toy-record-kp1']
    assert single.wave.iloc[0] == 'T1' and not single.panel_longitudinal.iloc[0]
    assert single.anchor_source_type.iloc[0] == 'qualtrics'
    assert all(rows.empty for mode, role, rows in scopes if mode in {'independent_child', 'independent_adult'})


def test_optional_manifest_invalid_on_does_not_change_off(full):
    snapshot = deepcopy(full['snapshot'])
    bad = accepted(full['records'], [], full['summary']['release_id']); bad['status'] = 'draft'
    bad['revision'] = manifest_revision(bad)
    wrapper = build_manual_export(snapshot, full['scope'], full['records'], full['frame'], full['parents'],
        full['measurements'], full['summary'], full['imported'], bad, panel=full['panel'])
    assert wrapper['status'] == 'unavailable' and wrapper['on'] is None
    assert snapshot == full['snapshot']
    validate_manual_export(wrapper, snapshot, full['scope'])


def test_atomic_export_protected_asset_and_existing_auth_unchanged(full, tmp_path):
    from study2.static_export import write_site
    from study2.static_access import ACCESS_CORE, MIDDLEWARE, AUTH_API
    wrapper = build(full, ['kb1'])
    assert wrapper['status'] == 'available', wrapper['code']
    site = tmp_path / 'site'
    write_site(full['snapshot'], site, scope_export=full['scope'], manual_exclusion=wrapper)
    old = {p.relative_to(site).as_posix(): p.read_bytes() for p in site.rglob('*') if p.is_file()}
    assert (site/'server/access-core.js').read_text() == ACCESS_CORE
    assert (site/'middleware.js').read_text() == MIDDLEWARE
    assert (site/'api/auth.js').read_text() == AUTH_API
    assert 'manual-exclusion.js' in (site/'build.mjs').read_text()
    script = "import {gate} from './server/access-core.js';const r=gate(new Request('https://example.test/manual-exclusion.js'),{STUDY2_ACCESS_PASSWORD:'synthetic-password-only',STUDY2_SESSION_SECRET:'s'.repeat(40)});if(!r||r.status===200)throw Error('asset not gated');console.log(r.status);"
    run = subprocess.run(['node', '--input-type=module', '-e', script], cwd=site, capture_output=True, text=True, check=True)
    assert run.stdout.strip() in {'303', '401', '307'}
    def changed(): raise RuntimeError('Synthetic input change')
    with pytest.raises(RuntimeError):
        write_site(full['snapshot'], site, scope_export=full['scope'], manual_exclusion=wrapper, verify_inputs=changed)
    assert old == {p.relative_to(site).as_posix(): p.read_bytes() for p in site.rglob('*') if p.is_file()}


@pytest.mark.parametrize('defect', ['off', 'on_hash', 'release', 'context', 'impact', 'raw', 'selected_flags'])
def test_public_tampering_fails_closed(full, defect):
    wrapper = build(full, ['ks0'])
    assert wrapper['status'] == 'available', wrapper['code']
    if defect == 'off': wrapper['off']['snapshot_revision'] = '0'*64
    elif defect == 'on_hash': wrapper['on_revision'] = '0'*64
    elif defect == 'release': wrapper['on']['snapshot']['release_id'] = 'another-release'
    elif defect == 'context': wrapper['on']['snapshot']['eligibility_context']['revision'] = '0'*64
    elif defect == 'impact': wrapper['impact']['intake']['student']['excluded'] = 0
    elif defect == 'raw': wrapper['on']['scope_export']['index']['records'][0]['count'] += 1
    elif defect == 'selected_flags': wrapper['on']['scope_export']['index']['eligibility']['excluded_selected'] = []
    if defect not in {'off', 'on_hash'}: wrapper['on_revision'] = sha(wrapper['on'])
    with pytest.raises((EligibilityError, ValueError, PipelineError)):
        validate_manual_export(wrapper, full['snapshot'], full['scope'])


from study2.common import PipelineError
