"""Optional protected ON aggregates. Canonical OFF assets are never duplicated."""
from copy import deepcopy
import math
import re

from .analysis_eligibility import (EligibilityError, POLICY, HASH_SCHEME, inventory_revision,
    project_eligibility, projected_cohorts, scope_overlay, sha, _need, _hash)
from .common import digest, plain

FORMAT = 'study2_manual_exclusion_v1'
ASSET = 'manual-exclusion.js'
GLOBAL = 'STUDY2_MANUAL_EXCLUSION'


def _base(snapshot, scope_export):
    from .static_export import pack_snapshot
    return dict(format=FORMAT, hash_scheme=HASH_SCHEME, status='unavailable', code='accepted_manifest_required',
                release_id=snapshot['release_id'], revision=None, inventory_revision=None,
                policy=POLICY, off=dict(snapshot_revision=sha(plain(pack_snapshot(snapshot))),
                                       scope_revision=sha(plain(scope_export))),
                on=None, on_revision=None, impact=None)


def build_manual_export(snapshot, scope_export, records, analysis, parents, measurements,
                        summary, imported, manifest, *, panel=None, progress=None):
    """Pure recomputation from explicitly supplied private inputs; no file reads.

    Invalid optional inputs disable only ON, without exposing exception details.
    OFF is still the original snapshot/scope pair supplied separately.
    """
    from .static_export import (build_views, count_table, pack_snapshot, english_snapshot, validate_snapshot,
                               validate_scope_export)
    from .dashboard_views import source_wave_counts
    from .static_sources import header as source_header
    wrapper = _base(snapshot, scope_export)
    if manifest is None:
        return wrapper
    try:
        _sample_catalogue(snapshot)
        validate_snapshot(snapshot)
        validate_scope_export(scope_export, snapshot)
        _need(scope_export['status'] == 'available', 'complete_scope_evidence_required')
        _need(snapshot['release_id'] == summary['release_id'], 'canonical_release_mismatch')
        _need(not snapshot.get('encoding'), 'unpacked_canonical_snapshot_required')
        _need(bool(summary.get('independent_parent')) == (panel is not None),
              'independent_parent_evidence_required')
        if panel is not None:
            from .parent_panel_views import verify_panel
            verify_panel(panel, summary['independent_parent'])
            by_id = {r['submission_id']: r for r in records}
            for row in panel['analysis'].to_dict('records'):
                _need(row['submission_id'] in by_id and
                      row.get('version_id') == by_id[row['submission_id']]['version_id'],
                      'independent_version_mismatch')
        projection = project_eligibility(records, analysis, parents, manifest,
                                         snapshot['release_id'], panel=panel)
        revision, inventory = manifest['revision'], inventory_revision(records)
        scopes = projected_cohorts(records, analysis, parents, measurements, projection, panel=panel)
        active = deepcopy(snapshot)
        # build_views does not open its folder when exact prepared scopes are given.
        active['views'] = build_views(analysis, parents, measurements, summary, '.',
            snapshot['minimum_cell_n'], progress, prepared_scopes=scopes,
            retain_residual=snapshot.get('source_selection', {}).get('residual_present', False))
        from .bd_pairing import POLICY as CHILD_BD_POLICY
        if summary.get('bd_pairing_policy') == CHILD_BD_POLICY:
            # An exclusion can empty an independent-parent subgroup. An empty
            # ON cube cannot establish grade fields absent in canonical OFF.
            originals = {(v['mode'], v['role'], v['mainstream'], v['source']): v
                         for v in snapshot['views']}
            for view in active['views']:
                original = originals.get((view['mode'], view['role'], view['mainstream'], view['source']), {})
                before, after = original.get('grade'), view.get('grade')
                if (before == {'status': 'unavailable', 'code': 'published_grade_fields_unavailable'} and
                        isinstance(after, dict) and after.get('status') == 'available' and
                        all(not any(cell.get('counts', {}).values()) for cell in after.get('cells', []))):
                    view['grade'] = deepcopy(before)
        for row in projection.impact['samples']:
            if row['baseline'] is not None:
                _need(snapshot['counts'].get(row['code']) == row['baseline'],
                      'canonical_sample_mismatch')
            active['counts'][row['code']] = row['active']
        for key, mask in [('analysis_mainstream_rows', projection.frame.mainstream.fillna(False)),
                          ('analysis_other_or_unknown_rows', ~projection.frame.mainstream.fillna(False))]:
            if key in active['counts']:
                active['counts'][key] = int(mask.sum())
        if 'parent_child_longitudinal' in active['counts']:
            canonical = analysis.loc[analysis.role.eq('parent')]
            _need(snapshot['counts']['parent_child_longitudinal'] == sum(set(g.wave) == {'T0', 'T1'}
                      for _, g in canonical.groupby('child_id')), 'canonical_supplementary_sample_mismatch')
            p = projection.frame.loc[projection.frame.role.eq('parent')]
            active['counts']['parent_child_longitudinal'] = sum(set(g.wave) == {'T0', 'T1'}
                                                               for _, g in p.groupby('child_id'))
        for row in active['samples']:
            # The default SAMPLE_NAMES includes one supported supplementary
            # same-child parent sample in addition to the nine native impacts.
            row['count'] = active['counts'][row['sample']]
        if 'BD_alternative_followups' in active['counts']:
            by_id = {r['submission_id']: r for r in records}
            active['counts']['BD_alternative_followups'] = sum(
                by_id[m[1]].get('selected_wave') != 'T1' for m in projection.members['BD'])
        active['sources'] = {role: count_table(source_wave_counts(imported, projection.frame,
                             None if role == 'all' else role).to_dict('records'), snapshot['minimum_cell_n'])
                             for role in ('all', 'student', 'parent')}
        if panel is not None:
            for key, value in projection.impact['independent'].items():
                active['independent_counts'][key] = value['active']
            pairs = panel['pairs']
            adult = pairs.loc[pairs.panel_branch.eq('same_adult') &
                              ~pairs.t0.isin(projection.excluded) & ~pairs.t1.isin(projection.excluded)]
            if 'same_adult_alternative_T1' in active['independent_counts']:
                child_t1 = dict(zip(pairs.loc[pairs.panel_branch.eq('child_report'), 'child_id'],
                                   pairs.loc[pairs.panel_branch.eq('child_report'), 't1']))
                active['independent_counts']['same_adult_alternative_T1'] = sum(
                    child_t1.get(row['child_id']) is not None and child_t1[row['child_id']] != row['t1']
                    for row in adult.to_dict('records'))
        if 'source_selection' in active:
            active['source_selection'] = source_header(active['release_id'], active['views'])
        active['eligibility_context'] = dict(mode='on', revision=revision,
                                            inventory_revision=inventory, policy=POLICY)
        english_snapshot(active, summary)
        # Source-table rows are a catalogue too. Retain baseline labels when a
        # category loses its final selected record; original intake stays fixed.
        for role, baseline in snapshot['sources'].items():
            by_label = {r['來源']: r for r in active['sources'][role]}
            active['sources'][role] = [by_label.get(r['來源'], {**r, '最終 T0': 0,
                '最終 T1': 0, '最終合計': 0}) for r in baseline]
        validate_snapshot(active)
        scope = deepcopy(scope_export)
        scope['index'] = scope_overlay(scope['index'], records, projection, revision, inventory)
        scope['index_revision'] = digest(scope['index'])
        scope['reconciliation'] = scope['index']['meta']['reconciliation']
        validate_scope_export(scope, active)
        wrapper.update(status='available', code=None, revision=revision,
                       inventory_revision=inventory, impact=projection.impact,
                       on=dict(snapshot=plain(pack_snapshot(active)), scope_export=scope))
        wrapper['on_revision'] = sha(wrapper['on'])
        validate_manual_export(wrapper, snapshot, scope_export)
    except EligibilityError as error:
        wrapper = _base(snapshot, scope_export)
        wrapper['code'] = str(error)
    return wrapper


def _unpack(snapshot):
    result = deepcopy(snapshot)
    def table(value):
        if isinstance(value, list):
            return value
        _need(isinstance(value, dict) and set(value) == {'columns', 'rows'} and
              isinstance(value['columns'], list) and len(set(value['columns'])) == len(value['columns'])
              and isinstance(value['rows'], list), 'invalid_packed_table')
        _need(all(isinstance(r, list) and len(r) == len(value['columns']) for r in value['rows']),
              'invalid_packed_table')
        return [dict(zip(value['columns'], r)) for r in value['rows']]
    for view in result['views']:
        for field in ('statistics', 'changes', 'histograms', 'paired_histograms', 'transitions'):
            if field in view:
                view[field] = table(view[field])
        if 'trends' in view:
            for row in view['trends']:
                row['statistics'] = table(row['statistics'])
    result.pop('encoding', None)
    return result


def _sample_catalogue(snapshot):
    """Only supported published rows, including the optional parent-child row."""
    from .dashboard_views import SAMPLE_NAMES
    _need(isinstance(snapshot.get('samples'), list), 'unsupported_manual_sample_catalogue')
    rows = {}
    for row in snapshot['samples']:
        _need(isinstance(row, dict) and set(row) == {'sample', 'label', 'count'} and
              isinstance(row['sample'], str) and row['sample'] in SAMPLE_NAMES and
              row['sample'] not in rows and row['sample'] in snapshot['counts'] and
              row['count'] == snapshot['counts'][row['sample']], 'unsupported_manual_sample_catalogue')
        rows[row['sample']] = row
    _need(all(key in rows for key, value in snapshot['counts'].items()
              if key in SAMPLE_NAMES and value is not None), 'incomplete_manual_sample_catalogue')
    return rows


def _validate_on_shape(raw, baseline):
    """Close ONLY the new lane. Hashes are integrity, never content approval.

    Catalogue identity/metadata come from canonical OFF, not an assumed full
    metric list: the declared reduced synthetic catalogue remains valid.
    """
    from .static_export import STAT_FIELDS, CHANGE_FIELDS
    view_fields = {'mode', 'role', 'mainstream', 'source', 'grouping_anchor', 'source_filter_anchor',
                   'counts', 'statistics', 'changes', 'grade', 'source_pairs', 'histograms',
                   'trends', 'paired_histograms', 'transitions'}
    row_fields = {'statistics': set(STAT_FIELDS) | {'suppressed'},
                  'changes': set(CHANGE_FIELDS) | {'suppressed'},
                  'histograms': {'group', 'variable_id', 'wave', 'bin_index', 'bin_left', 'bin_right', 'count'},
                  'paired_histograms': {'group', 'variable_id', 'wave', 'bin_index', 'bin_left', 'bin_right', 'count'},
                  'transitions': {'group', 'variable_id', 'variable', 'transition', 'count', 'denominator', 'proportion', 'suppressed'}}
    _need(isinstance(raw, dict) and isinstance(raw.get('views'), list) and
          isinstance(baseline.get('views'), list) and baseline['views'], 'manual_view_catalogue_mismatch')
    def table_shape(value, fields):
        if isinstance(value, dict):
            _need(set(value) == {'columns', 'rows'} and isinstance(value['columns'], list) and
                  len(value['columns']) == len(fields) and set(value['columns']) == fields and
                  isinstance(value['rows'], list), 'manual_table_shape_mismatch')
        else:
            _need(isinstance(value, list) and all(isinstance(r, dict) and set(r) == fields for r in value),
                  'manual_table_shape_mismatch')
    for view in raw['views']:
        _need(isinstance(view, dict) and set(view) <= view_fields, 'manual_view_shape_mismatch')
        for field, fields in row_fields.items():
            if field in view: table_shape(view[field], fields)
        if 'trends' in view:
            _need(isinstance(view['trends'], list), 'manual_trend_shape_mismatch')
            for period in view['trends']:
                _need(isinstance(period, dict) and set(period) == {'period', 'include_batch', 'counts', 'statistics'},
                      'manual_trend_shape_mismatch')
                table_shape(period['statistics'], row_fields['statistics'])
    on = _unpack(raw)
    def catalogue(views):
        result = {}
        for view in views:
            _need(isinstance(view, dict) and set(view) <= view_fields and
                  {'mode', 'role', 'mainstream', 'source', 'counts', 'statistics', 'changes'} <= set(view) and
                  all(isinstance(view[k], str) for k in ('mode', 'role', 'source')) and
                  type(view['mainstream']) is bool, 'manual_view_shape_mismatch')
            key = view['mode'], view['role'], view['mainstream'], view['source']
            _need(key not in result, 'manual_duplicate_projection')
            result[key] = view
        return result
    original, current = catalogue(baseline['views']), catalogue(on['views'])
    _need(current.keys() == original.keys(), 'manual_view_catalogue_mismatch')
    def number(value, integer=False):
        # Pandas serializes nullable count columns (e.g. categorical numerator)
        # as integral floats. Validate meaning without rewriting their values.
        _need(value is None or (type(value) in (int, float) and math.isfinite(value) and
              (not integer or value >= 0 and value == int(value))), 'manual_numeric_shape_mismatch')
    def counts(value, expected):
        _need(isinstance(value, dict) and set(value) == set(expected), 'manual_count_shape_mismatch')
        for n in value.values(): number(n, True)
    meta = ('wave', 'group', 'variable_id', 'variable', 'section', 'kind', 'unit', 'category_code', 'category')
    def stats(rows, expected_meta=None, allowed_meta=None):
        signatures = []
        for r in rows:
            _need(isinstance(r, dict) and set(r) == row_fields['statistics'] and type(r['suppressed']) is bool,
                  'manual_table_shape_mismatch')
            signature = tuple(r[k] for k in meta)
            signatures.append(signature)
            if allowed_meta is not None:
                _need(signature in allowed_meta, 'manual_metric_catalogue_mismatch')
            for k in ('sample_n', 'valid_n', 'missing_n', 'outside_range_n', 'numerator', 'denominator'):
                number(r[k], True)
            for k in ('mean', 'sd', 'proportion'): number(r[k])
        if expected_meta is not None:
            _need(signatures == expected_meta, 'manual_metric_catalogue_mismatch')
    for key, view in current.items():
        old = original[key]
        _need(set(view) == set(old), 'manual_view_shape_mismatch')
        for name in ('grouping_anchor', 'source_filter_anchor'):
            _need(view.get(name) == old.get(name), 'manual_view_anchor_mismatch')
        _need(set(view['counts']) == set(old['counts']), 'manual_group_catalogue_mismatch')
        for g, c in view['counts'].items(): counts(c, old['counts'][g])
        old_meta = [tuple(r[k] for k in meta) for r in old['statistics']]
        stats(view['statistics'], expected_meta=old_meta)
        allowed = {(r['group'], r['variable_id'], r['variable'], r['unit']) for r in old['statistics']}
        for row in view['changes']:
            _need(set(row) == row_fields['changes'] and
                  (row['group'], row['variable_id'], row['variable'], row['unit']) in allowed and
                  type(row['suppressed']) is bool and row['inference_status'] in {
                      'estimated', 'insufficient_pairs', 'zero_change_variance', 'suppressed'} and
                  row['pair_detail_status'] in {'available', 'not_provided', 'suppressed'},
                  'manual_change_shape_mismatch')
            for name in ('pairs_n', 'paired_valid_n', 'paired_missing_n', 'only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n'):
                number(row[name], True)
            for name in ('mean_change', 'sd_change', 'p_value', 'cohen_dz', 't0_mean', 't1_mean'): number(row[name])
        for name in ('histograms', 'paired_histograms', 'transitions'):
            for row in view.get(name, []):
                _need(row['group'] in view['counts'] and row['variable_id'] in {m[1] for m in allowed},
                      'manual_distribution_catalogue_mismatch')
                for field in ('count', 'denominator', 'bin_index'):
                    if field in row: number(row[field], True)
                for field in ('bin_left', 'bin_right', 'proportion'):
                    if field in row: number(row[field])
                if 'wave' in row: _need(row['wave'] in {'T0', 'T1'}, 'manual_distribution_shape_mismatch')
                if 'suppressed' in row: _need(type(row['suppressed']) is bool, 'manual_distribution_shape_mismatch')
                if name == 'transitions':
                    allowed_transition = {(r['group'], r['variable_id'], r['variable'], r['transition'])
                                          for r in old.get('transitions', [])}
                    _need((row['group'], row['variable_id'], row['variable'], row['transition']) in
                          allowed_transition, 'manual_distribution_catalogue_mismatch')
        old_periods = {(r['period'], r['include_batch']) for r in old.get('trends', [])}
        seen = set()
        for period in view.get('trends', []):
            pair = period['period'], period['include_batch']
            _need(pair in old_periods and pair not in seen and type(pair[1]) is bool, 'manual_trend_catalogue_mismatch')
            seen.add(pair); counts(period['counts'], {'T0', 'T1'})
            stats(period['statistics'], allowed_meta=set(old_meta))
        if 'grade' in view:
            _need(view['grade'].get('status') == old['grade'].get('status') and
                  view['grade'].get('anchor') == old['grade'].get('anchor'), 'manual_grade_catalogue_mismatch')
            if view['grade'].get('status') == 'available':
                _need(view['grade']['statistics_schema'] == old['grade']['statistics_schema'], 'manual_metric_catalogue_mismatch')
        if 'source_pairs' in view:
            _need(view['source_pairs']['source_codes'] == old['source_pairs']['source_codes'], 'manual_source_catalogue_mismatch')
            _need([(g['group'], g['pairs_schema'], g['detail_variables']) for g in view['source_pairs']['groups']] ==
                  [(g['group'], g['pairs_schema'], g['detail_variables']) for g in old['source_pairs']['groups']],
                  'manual_source_catalogue_mismatch')
    counts(on['counts'], baseline['counts'])
    counts(on['independent_counts'], baseline['independent_counts'])
    original_samples, samples = _sample_catalogue(baseline), _sample_catalogue(on)
    _need(original_samples.keys() == samples.keys() and all(samples[k]['label'] == v['label']
          for k, v in original_samples.items()), 'manual_sample_catalogue_mismatch')
    _need(set(on['sources']) == set(baseline['sources']), 'manual_source_count_shape_mismatch')
    for role, rows in on['sources'].items():
        old = baseline['sources'][role]
        _need(len(rows) == len(old), 'manual_source_count_shape_mismatch')
        for row, previous in zip(rows, old):
            _need(isinstance(row, dict) and set(row) == set(previous) and row['來源'] == previous['來源'],
                  'manual_source_count_shape_mismatch')
            for field in set(row) - {'來源'}: number(row[field], True)
            for field in ('匯入 T0', '匯入 T1', '匯入合計'):
                _need(row[field] == previous[field], 'manual_raw_history_changed')
    return on


def validate_manual_export(wrapper, snapshot, scope_export):
    """Closed wrapper, full existing scientific validators and exact pair binding."""
    from .static_export import pack_snapshot, validate_snapshot, validate_scope_export
    from .static_scope import query_scope, SLOTS
    _need(isinstance(wrapper, dict) and set(wrapper) == {'format', 'hash_scheme', 'status', 'code', 'release_id',
        'revision', 'inventory_revision', 'policy', 'off', 'on', 'on_revision', 'impact'}, 'invalid_manual_wrapper')
    _need(wrapper['format'] == FORMAT and wrapper['hash_scheme'] == HASH_SCHEME and wrapper['release_id'] == snapshot['release_id']
          and wrapper['policy'] == POLICY and wrapper['off'] == {
              'snapshot_revision': sha(plain(pack_snapshot(snapshot))),
              'scope_revision': sha(plain(scope_export))}, 'manual_off_binding_mismatch')
    if wrapper['status'] == 'unavailable':
        _need(isinstance(wrapper['code'], str) and re_token(wrapper['code']) and
              all(wrapper[k] is None for k in ('revision', 'inventory_revision', 'on', 'on_revision', 'impact')),
              'invalid_unavailable_manual_wrapper')
        return wrapper
    _need(wrapper['status'] == 'available' and wrapper['code'] is None and
          _hash(wrapper['revision']) and _hash(wrapper['inventory_revision']) and
          isinstance(wrapper['on'], dict) and set(wrapper['on']) == {'snapshot', 'scope_export'} and
          wrapper['on_revision'] == sha(wrapper['on']), 'invalid_manual_on_binding')
    on = _validate_on_shape(wrapper['on']['snapshot'], snapshot)
    _need(set(on) == set(snapshot) | {'eligibility_context'} and on.get('release_id') == snapshot['release_id'],
          'manual_on_release_mismatch')
    context = dict(mode='on', revision=wrapper['revision'], inventory_revision=wrapper['inventory_revision'], policy=POLICY)
    _need(on.get('eligibility_context') == context, 'manual_context_mismatch')
    for field in ('format', 'generated_at', 'published_at', 'minimum_cell_n', 'small_sample_policy',
                  'report_version', 'dictionary_version', 'grade', 'stages', 'evidence', 'tracking',
                  'parent_wave_policy', 'notes', 'dictionary', 'modes', 'groups', 'source_selection',
                  'source_names', 'inference_version', 'descriptive_projection_version', 'english_catalogue_version'):
        _need(plain(on.get(field)) == plain(snapshot.get(field)), 'manual_reference_metadata_mismatch')
    # All display/schema/reference fields are immutable, including any legacy
    # metadata. Do not apply broad text/number masking to questionnaire labels.
    mutable = {'counts', 'sources', 'samples', 'independent_counts', 'views'}
    for field in set(snapshot) - mutable:
        _need(plain(on.get(field)) == plain(snapshot.get(field)), 'manual_reference_metadata_mismatch')
    active_counts = {'A', 'B', 'C', 'D', 'AC', 'BD', 'E', 'F', 'EF', 'parent_child_longitudinal',
                     'BD_alternative_followups', 'analysis_mainstream_rows', 'analysis_other_or_unknown_rows'}
    for field in set(snapshot['counts']) - active_counts:
        _need(on['counts'][field] == snapshot['counts'][field], 'manual_raw_history_changed')
    if 'parent_child_longitudinal' in on['counts']:
        _need(on['counts']['parent_child_longitudinal'] <= min(on['counts']['B'], on['counts']['D'],
              snapshot['counts']['parent_child_longitudinal']), 'manual_supplementary_sample_mismatch')
    validate_snapshot(on)
    scope = wrapper['on']['scope_export']
    validate_scope_export(scope, on)
    _need(scope['status'] == 'available' and scope['index'].get('eligibility', {}).get('revision') == wrapper['revision']
          and scope['index']['eligibility']['inventory_revision'] == wrapper['inventory_revision'],
          'manual_scope_binding_mismatch')
    before, after = query_scope(scope_export['index']), query_scope(scope['index'])
    _need({k: v for k, v in scope['index'].items() if k not in {'samples', 'eligibility'}} ==
          {k: v for k, v in scope_export['index'].items() if k != 'samples'}, 'manual_raw_history_changed')
    impact = wrapper['impact']
    _need(isinstance(impact, dict) and set(impact) == {'intake', 'samples', 'independent'} and
          impact['intake'] == after['eligibility']['intake'] and
          impact['samples'] == after['eligibility']['samples'], 'manual_impact_mismatch')
    for code in SLOTS:
        base = next(r['count'] for r in before['samples'] if r['code'] == code)
        active = next(r['count'] for r in after['samples'] if r['code'] == code)
        _need(snapshot['counts'].get(code) == base and on['counts'].get(code) == active,
              'manual_sample_counts_mismatch')
        rows = {r['sample']: r for r in on['samples']}
        if code in rows:
            _need(rows[code]['count'] == active, 'manual_sample_rows_mismatch')
    # Root sample totals and native unfiltered views must describe the same
    # fixed members, not merely two individually valid source/grade cubes.
    expected = {('abcd', 'student'): ('A', 'C'), ('abcd', 'parent'): ('B', 'D'),
                ('ef', 'student'): ('E', 'F'), ('ef', 'parent'): ('E', 'F'),
                ('acbd', 'student'): ('AC', 'AC'), ('acbd', 'parent'): ('BD', 'BD'),
                ('efmatched', 'student'): ('EF', 'EF'), ('efmatched', 'parent'): ('EF', 'EF')}
    for view in on['views']:
        if view['mainstream'] or view['source'] != 'all':
            continue
        codes = expected.get((view['mode'], view['role']))
        if codes is not None:
            _need(view['counts']['all'] == dict(zip(('T0', 'T1'), [on['counts'][c] for c in codes])),
                  'manual_view_counts_mismatch')
    independent = impact['independent']
    if independent is None:
        _need(not snapshot.get('independent_counts') and not on.get('independent_counts'),
              'manual_independent_mismatch')
    else:
        _need(isinstance(independent, dict) and set(independent) == {'baselines', 'child_report_pairs', 'same_adult_pairs'},
              'manual_independent_mismatch')
        for key, d in independent.items():
            _need(isinstance(d, dict) and set(d) == {'baseline', 'active', 'excluded'} and
                  all(type(v) is int and v >= 0 for v in d.values()) and
                  d['baseline'] == d['active'] + d['excluded'] and
                  d['baseline'] == snapshot['independent_counts'][key] and
                  d['active'] == on['independent_counts'][key], 'manual_independent_mismatch')
        for view in on['views']:
            if not view['mainstream'] and view['source'] == 'all' and view['mode'] in {
                    'independent_child', 'independent_adult'}:
                key = 'child_report_pairs' if view['mode'] == 'independent_child' else 'same_adult_pairs'
                _need(view['counts']['all'] == dict(T0=independent[key]['active'], T1=independent[key]['active']),
                      'manual_independent_view_counts_mismatch')
    return wrapper


def re_token(value):
    import re
    return re.fullmatch('[a-z][a-z0-9_]{0,95}', value) is not None


JS_HASH = r'''
const Study2EligibilityHash=Object.freeze({
  canonical(value){
    function typed(v){
      if(v===null)return ['null'];
      if(typeof v==='boolean')return ['bool',v];
      if(typeof v==='number'){
        if(!Number.isFinite(v))throw Error('nonfinite_revision_value');
        const bytes=new Uint8Array(8);new DataView(bytes.buffer).setFloat64(0,v,false);
        return ['f64',Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('')];
      }
      if(typeof v==='string'){
        // Reject lone surrogates, while preserving legitimate astral text.
        for(let i=0;i<v.length;i++){const c=v.charCodeAt(i);if(c>=0xd800&&c<=0xdbff){const n=v.charCodeAt(++i);if(!(n>=0xdc00&&n<=0xdfff))throw Error('invalid_unicode_revision_value');}else if(c>=0xdc00&&c<=0xdfff)throw Error('invalid_unicode_revision_value');}
        return ['str',v];
      }
      if(Array.isArray(v))return ['array',v.map(typed)];
      if(!v||typeof v!=='object'||Object.getPrototypeOf(v)!==Object.prototype)throw Error('invalid_revision_type');
      return ['object',Object.keys(v).sort().map(k=>[typed(k),typed(v[k])])];
    }
    return JSON.stringify(typed(value));
  },
  async digest(value){const bytes=new TextEncoder().encode(this.canonical(value));const result=await crypto.subtle.digest('SHA-256',bytes);return Array.from(new Uint8Array(result),x=>x.toString(16).padStart(2,'0')).join('');}
});
'''
