"""Aggregate-only static dashboard. Reads a publication, never a live review queue.

All selection/scoring/statistics remain in the existing research services. Only
explicitly projected aggregates reach the deployment directory. Researcher
exports retain small aggregate cells; identifiers and raw answers stay local.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import numpy as np

from .common import PipelineError, digest, file_hash, load_config, plain, utcnow
from .dashboard_views import (SAMPLE_NAMES, SOURCE_NAMES, STAGE_PURPOSES,
                              sample_reconciliation, source_wave_counts, stage_overview)
from .descriptive_spec import DICTIONARY_VERSION, GROUPS, MODES, VERSION, dictionary_rows, variables
from .descriptives import (cohort, filter_cohort, independent_cohort, paired_changes,
                           statistics, wave_counts)
from .store import connect, current
from .static_access import ACCESS_FILES, PUBLIC_FILES
from .static_period_assets import PERIOD_FILES
from .static_scope import (ADULT_POLICY, ScopeError, build_scope_index,
                           default_selection, normalize_selection, query_scope, validate_index)
from .static_english_catalog import (CATALOGUE_VERSION, bd_sample_text,
                                     stage_2_1_5_text, text as english)
from .static_grade import attach_grade, build_cube, header as grade_header, validate_grade
from .static_sources import (CODES as SOURCE_CODES, build_pairs as source_pairs,
                             header as source_header, source_code, validate_sources)

FORMAT = 'study2_static_v1'
DEPLOY_FILES = {'index.html', 'app.js', 'styles.css', 'snapshot.js', 'vercel.json',
                'scope-index.js', 'scope-engine.js', 'quality-ui.js', 'manual-exclusion.js',
                '.vercelignore', 'snapshot-manifest.json', *ACCESS_FILES, *PERIOD_FILES}
SCOPE_EXPORT_FORMAT = 'study2_static_scope_export_v1'
STAT_FIELDS = ['wave', 'group', 'variable_id', 'variable', 'section', 'kind', 'unit',
               'sample_n', 'valid_n', 'missing_n', 'outside_range_n', 'mean', 'sd',
               'numerator', 'denominator', 'proportion', 'category_code', 'category']
CHANGE_FIELDS = ['group', 'variable_id', 'variable', 'unit', 'pairs_n',
                 'paired_valid_n', 'paired_missing_n', 'mean_change', 'sd_change',
                 'p_value', 'cohen_dz', 'inference_status',
                 'only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n',
                 't0_mean', 't1_mean', 'pair_detail_status']
PAIR_DETAIL_FIELDS = ['only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n', 't0_mean', 't1_mean']
DESCRIPTIVE_PROJECTION_VERSION = 'study2_g12_v1'
FOCUS = ['PHQ_total', 'FQOL_total', 'SEC_total', 'TBV_mean', 'TBP_mean', 'CBV_mean', 'CBP_mean']
SUMMARY_COUNTS = ['submissions', 'A', 'B', 'C', 'D', 'AC', 'BD', 'E', 'F', 'EF',
                  'parent_child_longitudinal', 'BD_alternative_followups',
                  'batch_creation_time_submissions', 'school_names_pending',
                  'validation_cases_labelled', 'manual_decisions_reopened',
                  'analysis_mainstream_rows', 'analysis_other_or_unknown_rows']


def unavailable_scope(code, release_id=None):
    return dict(format=SCOPE_EXPORT_FORMAT, status='unavailable', code=code,
                release_id=release_id, index_revision=None, school_bindings=[])


def build_scope_export(folder, summary, minimum=0, *, school_binding=None):
    """Exact published membership only. No source aggregates or new selection.

    The optional school binding is a locally trusted, already supplied public
    projection, not a school query. Its real-data provenance/disclosure remains
    a separate gate; no such binding is discovered from private review state.
    """
    folder = Path(folder)
    if minimum > 0:
        return unavailable_scope('exact_scope_incompatible_with_suppression', summary['release_id'])
    path = folder / 'records.jsonl.gz'
    if not path.exists():
        return unavailable_scope('complete_published_records_required', summary['release_id'])
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        analysis = pd.read_parquet(folder / 'analysis.parquet')
        adult_path = folder / 'parent_longitudinal.parquet'
        adults = pd.read_parquet(adult_path) if adult_path.exists() else None
        ledger_path = folder / 'scope_flow_evidence.json'
        ledger = None
        if ledger_path.exists():
            wrapper = json.loads(ledger_path.read_text())
            if (set(wrapper) != {'format', 'release_id', 'records_sha256', 'evidence'} or
                    wrapper['format'] != 'study2_published_scope_flow_v1' or
                    wrapper['release_id'] != summary['release_id'] or
                    wrapper['records_sha256'] != file_hash(path)):
                raise ValueError('checkpoint_evidence_is_stale_or_unsupported')
            ledger = wrapper['evidence']
        index = build_scope_index(records, analysis, adults, summary, flow_evidence=ledger)
        result = query_scope(index)
    except (ScopeError, ValueError, OSError) as error:
        raise PipelineError('Exact scope inputs are invalid or unsupported: ' + str(error)) from error
    revision = digest(index)
    output = dict(format=SCOPE_EXPORT_FORMAT, status='available', release_id=summary['release_id'],
                  index_revision=revision, index=index, school_bindings=[])
    if school_binding is not None:
        # Invalid school evidence makes only that feature unavailable. Never
        # serialize an unvalidated wrapper/projection or its private fields.
        try:
            from .static_school_status import validate_public_projection
            if set(school_binding) != {'index_revision', 'scope', 'projection'}:
                raise ValueError('school_binding_shape')
            projection = school_binding['projection']
            validate_public_projection(projection)
            scope = normalize_selection(index, school_binding['scope'])
            if (school_binding['index_revision'] != revision or
                    projection['release_id'] != summary['release_id'] or
                    projection['availability'] != 'available' or
                    projection['current_scope']['raw'] != query_scope(index, scope)['raw']):
                raise ValueError('school_binding_mismatch')
            output['school_bindings'] = [dict(scope=scope, projection=plain(projection))]
        except (ValueError, TypeError, KeyError):
            output['school_code'] = 'supplied_school_projection_unavailable_or_incompatible'
    # This number is the accepted query's all-scope reconciliation, not a
    # claim that the school review or disclosure work has been completed.
    output['reconciliation'] = result['reconciliation']
    return output


def validate_scope_export(value, snapshot):
    if not isinstance(value, dict) or set(value) - {'format', 'status', 'code', 'release_id', 'index_revision',
                                                   'index', 'school_bindings', 'reconciliation', 'school_code'}:
        raise PipelineError('Scope export contains unsupported fields.')
    if value.get('format') != SCOPE_EXPORT_FORMAT or value.get('release_id') != snapshot['release_id']:
        raise PipelineError('Scope export and snapshot do not identify the same compatible release.')
    if value.get('status') == 'unavailable':
        if (set(value) != {'format', 'status', 'code', 'release_id', 'index_revision', 'school_bindings'} or
                value.get('code') not in {'exact_scope_incompatible_with_suppression', 'complete_published_records_required', 'compatible_scope_export_required'} or
                value.get('index_revision') is not None or value.get('school_bindings')):
            raise PipelineError('Unavailable scope export must not carry exact data.')
        return
    if value.get('status') != 'available' or snapshot.get('minimum_cell_n', 0) > 0:
        raise PipelineError('Exact filtering cannot bypass the configured suppression policy.')
    index = value['index']
    validate_index(index)
    if (index['meta']['release_id'] != snapshot['release_id'] or
            value.get('index_revision') != digest(index)):
        raise PipelineError('Scope index revision or release mismatch.')
    if value.get('reconciliation') != index['meta']['reconciliation']:
        raise PipelineError('Scope reconciliation metadata differs from its index.')
    if 'school_code' in value and value['school_code'] != 'supplied_school_projection_unavailable_or_incompatible':
        raise PipelineError('Unsupported school availability metadata.')
    from .static_school_status import validate_public_projection
    for binding in value.get('school_bindings', []):
        if set(binding) != {'scope', 'projection'}:
            raise PipelineError('Unsupported school binding fields.')
        projection = binding['projection']
        validate_public_projection(projection)
        scope = normalize_selection(index, binding['scope'])
        if (scope != binding['scope'] or projection['release_id'] != snapshot['release_id'] or
                projection['availability'] != 'available' or
                projection['current_scope']['raw'] != query_scope(index, scope)['raw']):
            raise PipelineError('School projection does not match its exact supplied scope.')


DISPLAY_GROUPS = dict(all='All', male='Male', female='Female', primary='Primary', secondary='Secondary',
    male_primary='Male, primary', female_primary='Female, primary',
    male_secondary='Male, secondary', female_secondary='Female, secondary')
DISPLAY_MODES = dict(abcd='Per-wave responses (A/B/C/D)', ef='Per-wave student-parent dyads (E/F)',
    acbd='Formal longitudinal samples (AC/BD)', efmatched='Longitudinal student-parent dyads (EF)',
    independent_all='All independent-parent responses', independent_child='Independent parent: same child',
    independent_adult='Independent parent: same adult')
DISPLAY_UNITS = {'分': 'points', '人': 'respondents', '比例': 'proportion', '歲': 'years', '位': 'people'}
DISPLAY_NOTES = [
    ('Scoring', 'Uses the published shared scores and their existing required-item rules. SEC uses 1-4; PHQ is a sum. Other scale scores retain the shared mean.'),
    ('Proportion denominator', 'Valid responses to each metric; missing N is separate. SEN can have multiple selections, so category proportions can exceed 100%.'),
    ('Groups', 'Nine overlapping groups must not be added. Parent groups refer to the child. Longitudinal grouping is fixed at T0; per-wave grouping uses that wave.'),
    ('Dates and age', 'Existing date/age confidence rules are unchanged. Adult age based only on birth year is an estimate; batch wave permission does not relax age confidence.'),
    ('Adult gender', 'Not independently collected. The respondent relationship is shown; adult gender is not inferred.'),
    ('Number of children', 'Only confirmed Qualtrics codes 1-4 are interpreted; 4 means four or more. Other-source coding remains unconfirmed. No mean is calculated.'),
    ('Respondent continuity', 'E/F may have different responding adults. Paired parent PHQ requires confirmed same-adult evidence. A BD label alone is not evidence. Independent-parent samples remain separate.'),
    ('Descriptive ranges', 'Approved inclusive ranges: child age 5-20, adult age 20-70, height 100-200 cm, weight 20-100 kg; each sibling count 0-5 and total 0-10. Outside-range values are missing only for that metric; records and membership remain unchanged.'),
    ('BMI', 'Computed as kg/m² only when both height and weight are valid. Adult cut-offs are not used to classify children.'),
    ('Interpretation', 'Descriptive values and distributions are not diagnoses or causal effects. Stable variable IDs are used where English scientific names remain unconfirmed.'),
]


def _display_note(row):
    from .descriptive_spec import REPORT_RANGES
    key = row['variable_id'].removeprefix('dem_')
    note = row.get('note', '')
    if key in REPORT_RANGES and REPORT_RANGES[key] is not None:
        low, high = REPORT_RANGES[key]
        extra = 'All four components must be valid; missing components are not zero. ' if key == 'siblings_total' else ''
        return extra + f'Inclusive descriptive range {low}-{high}. Outside-range values are missing for this metric only; membership is retained.'
    mapping = {
        '過去三個月；整域所需題目完整': 'Past three months; all required domain items must be complete.',
        '描述分數分布，不作臨床診斷': 'Describes score distribution; not a clinical diagnosis.',
        '身高及體重均在已確認範圍內才計算；不作兒童體重分類；分項超範圍亦列缺失': 'Requires valid height and weight; no child weight classification. An outside-range component makes BMI missing.',
        '年級數字須配合學校階段閱讀': 'Read the grade code together with school stage.',
        '不從父親／母親稱謂推定': 'Not inferred from the father/mother relationship label.',
        '不方便提供為有效選項': 'The prefer-not-to-disclose option is a valid response.',
        '只正式解讀已確認的 Qualtrics 1–4 編碼；其他來源編碼待核；不求平均': 'Only confirmed Qualtrics codes 1-4 are interpreted. Other-source coding is unconfirmed. No mean is calculated.',
        '缺失及矛盾選項不推定有／沒有': 'Missing or contradictory options are not inferred as yes or no.',
        '分母為該題有效回答人數，包含有效回答「沒有」；各類比例可合計超過 100%': 'Denominator: valid responses to this item, including a valid no response. Categories can exceed 100% in total.',
    }
    return mapping.get(note, note if not re.search(r'[\u3400-\u9fff]', note) else 'English wording is unconfirmed; consult the local dictionary.')


def english_snapshot(snapshot, summary):
    """Translate declared display fields only; never walk arbitrary data text."""
    snapshot['english_catalogue_version'] = CATALOGUE_VERSION
    snapshot['groups'] = DISPLAY_GROUPS
    snapshot['modes'] = DISPLAY_MODES
    source_labels = {'all': 'All sources', 'qualtrics': 'Qualtrics', 'paperform': 'Paperform',
        'legacy_online': 'Legacy online', 'unknown': 'Unidentified source',
        'school_batch': 'School batch', 'socialworkdream': 'Social Work Dream'}
    snapshot['source_names'] = {key: source_labels.get(key, key) for key in snapshot['source_names']}
    snapshot['notes'] = DISPLAY_NOTES
    for row in snapshot['dictionary']:
        row['label'] = row['variable_id']
        row['unit'] = DISPLAY_UNITS.get(row['unit'], row['unit'])
        row['note'] = _display_note(row)
    for view in snapshot['views']:
        for rows in [view.get('statistics', []), view.get('changes', []), view.get('transitions', []),
                     view.get('grade', {}).get('statistics_schema', []), view.get('grade', {}).get('pairs_schema', []),
                     *(group['pairs_schema'] for group in view.get('source_pairs', {}).get('groups', [])),
                     *(period['statistics'] for period in view.get('trends', []))]:
            for row in rows:
                if 'variable' in row:
                    row['variable'] = row['variable_id']
                if 'unit' in row:
                    row['unit'] = DISPLAY_UNITS.get(row['unit'], row['unit'])
                if row.get('kind') == 'binary' and row.get('category') == '符合門檻':
                    row['category'] = 'Meets threshold'
                if 'transition' in row:
                    row['transition'] = {'兩輪均不符合': 'Neither wave meets threshold',
                        '只 T0 符合': 'T0 only meets threshold', '只 T1 符合': 'T1 only meets threshold',
                        '兩輪均符合': 'Both waves meet threshold'}.get(row['transition'], row['transition'])
        # Original category codes/labels and every numeric value remain intact.
    for row in snapshot['samples']:
        code = row['sample']
        row['label'] = (bd_sample_text('same_adult' if summary.get('adult_identity_policy') == ADULT_POLICY
                                     and snapshot['counts'].get('BD') is not None else None)
                        if code == 'BD' else english('sample.' + code.lower()))
    stage_keys = {'1.1': '1_1', '1.3/2.1.1/2.1.2': '1_3_2_1_1_2_1_2',
        '2.1.3': '2_1_3', '2.1.4': '2_1_4', '2.1.5': '2_1_5', '2.1.6': '2_1_6',
        '3.1.1': '3_1_1', '3.1.2/3.1.3': '3_1_2_3_1_3'}
    for row in snapshot['stages']:
        stage = row['階段'];count = summary['stage_counts'][stage]
        row['主要目的'] = (stage_2_1_5_text(summary.get('parent_wave_policy')) if stage == '2.1.5'
                            else english('stage.' + stage_keys[stage]))
        row['數量／結果'] = ('; '.join(f'{key}: {value:,}' for key, value in count.items())
                            if isinstance(count, dict) else f'{count:,} questionnaire records')
    reverse_sources = {label: key for key, label in SOURCE_NAMES.items()}
    for rows in snapshot['sources'].values():
        for row in rows:
            label = row['來源']
            row['來源'] = ('Total' if label == '合計' else 'Unidentified source' if label == '其他／未識別來源'
                         else source_labels.get(reverse_sources.get(label), label))
    return snapshot


def _records(frame, fields):
    return plain(frame.reindex(columns=fields).to_dict('records'))


def _small(value, minimum):
    return value is not None and 0 < value < minimum


def safe_statistics(frame, minimum=0):
    """Suppress whole variable partitions, including binary complements.

    Keeping a denominator alongside one hidden small category would reveal it
    by subtraction. Suppress every numeric field in that variable/wave/group.
    The researcher export uses minimum=0, retaining small cells. An explicit
    positive threshold remains supported for older export callers.
    No raw extremes, missing-reason text or free-form notes are exported.
    """
    rows = _records(frame, STAT_FIELDS)
    partitions = {}
    for row in rows:
        partitions.setdefault((row['wave'], row['group'], row['variable_id']), []).append(row)
    labels = {'wave', 'group', 'variable_id', 'variable', 'section', 'kind', 'unit', 'category_code', 'category'}
    for block in partitions.values():
        # A few missing forms do not turn a large mean into a small-sample
        # statistic. Gate on the actual contributing N and substantive category
        # cells; retain aggregate quality denominators for interpretation.
        hide = any(_small(r.get(k), minimum) for r in block
                   for k in ('sample_n', 'valid_n', 'numerator'))
        hide |= any(r['numerator'] is not None and r['denominator'] is not None
                    and _small(r['denominator']-r['numerator'], minimum) for r in block)
        for row in block:
            row['suppressed'] = bool(hide)
            if hide:
                for key in STAT_FIELDS:
                    if key not in labels:
                        row[key] = None
    return rows


def safe_changes(frame, minimum=0):
    result = _records(frame, CHANGE_FIELDS)
    for row in result:
        hide = any(_small(row[k], minimum) for k in
                   ('pairs_n', 'paired_valid_n', 'paired_missing_n',
                    'only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n'))
        row['pair_detail_status'] = row.get('pair_detail_status') or 'not_provided'
        row['suppressed'] = bool(hide)
        if hide:
            for k in CHANGE_FIELDS:
                if k in {'group', 'variable_id', 'variable', 'unit', 'inference_status', 'pair_detail_status'}:
                    continue
                row[k] = None
            row['inference_status'] = 'suppressed'
            row['pair_detail_status'] = 'suppressed'
    return result


def pair_details(rows, role, groups=tuple(GROUPS), *, changes=None):
    """Project existing exploration results without changing formal inference.

    The caller supplies complete formal slots. For overview intersections the
    original inference/eligibility is supplied separately, before restricting
    exploration to units whose two exact slots are visible.
    """
    from .descriptive_exploration import comparison_variables, explore, mode_of

    changes = paired_changes(rows, role, groups) if changes is None else changes
    if changes.empty:
        return changes.copy()
    result = changes.copy()
    for field in PAIR_DETAIL_FIELDS:
        result[field] = None
    result['pair_detail_status'] = 'not_provided'
    if 'grouping_anchor' not in rows:
        # Legacy callers can request the original inference using a minimal
        # frame. Keep that behavior without inventing exploration metadata.
        return result
    # A subgroup can contain one original adult slot but no complete pairs.
    # Its original inference rows stay intact; never force PHQ eligibility on
    # the now-empty exploration cohort to fill in its new detail columns.
    permitted = {v.key for v in comparison_variables(mode_of(rows), role, rows)}
    chosen = [key for key in result['variable_id'].unique() if key in rows.columns and key in permitted]
    summary = explore(rows, role, tuple(groups), paired=True, selected_variables=chosen)['pair_summary']
    lookup = summary.set_index(['group', 'variable_id'])
    for index, item in result.iterrows():
        key = (item['group'], item['variable_id'])
        if key not in lookup.index:
            continue
        detail = lookup.loc[key]
        if (detail['pairs_n'] != item['pairs_n'] or
                detail['paired_valid_n'] != item['paired_valid_n']):
            raise PipelineError('Formal paired inference and availability do not reconcile.')
        for field in PAIR_DETAIL_FIELDS:
            result.at[index, field] = detail[field]
        result.at[index, 'pair_detail_status'] = 'available'
    return result


def overview_changes(selected, reference, role, groups=tuple(GROUPS)):
    """Intersect formal longitudinal membership with BOTH displayed submissions.

    Each-wave cohorts may use different source, school or demographic anchors
    in T0 and T1. Apply each displayed subgroup to the selected rows first, then
    retain only exact submission/version members from the formal pair artifact.
    Never join a parent baseline to another adult's follow-up by child ID alone.
    """
    from .descriptives import group_rows

    results = []
    for group in groups:
        visible = group_rows(selected, group)
        keys = pd.MultiIndex.from_frame(visible[['submission_id', 'version_id']])
        paired = reference.loc[pd.MultiIndex.from_frame(
            reference[['submission_id', 'version_id']]).isin(keys)].copy()
        paired.attrs = reference.attrs.copy()
        changes = paired_changes(paired, role, ('all',))
        if not changes.empty:
            # Exploration requires two exact formal slots; do not re-pair
            # overview records or loosen the original adult eligibility.
            first = set(paired.loc[paired['wave'].eq('T0'), 'child_id'])
            last = set(paired.loc[paired['wave'].eq('T1'), 'child_id'])
            complete = paired.loc[paired['child_id'].isin(first & last)].copy()
            complete.attrs = paired.attrs.copy()
            changes = pair_details(complete, role, ('all',), changes=changes)
            changes['group'] = group
            changes['group_label'] = GROUPS[group]
            results.append(changes)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def count_table(rows, minimum=0):
    """Conservative complement protection: suppress the entire numeric table
    if any positive cell is small, rather than expose a hidden cell via totals.
    """
    hide = any(_small(v, minimum) for row in rows for v in row.values()
               if isinstance(v, (int, float)) and not isinstance(v, bool))
    return [{k: None if hide and isinstance(v, (int, float)) else v for k, v in row.items()}
            for row in rows]


def _counts(rows, minimum=0):
    counts = wave_counts(rows)
    # T0/T1 may be the same people. Hide both counts if one is small.
    return {k: None if any(_small(n, minimum) for n in counts.values()) else v
            for k, v in counts.items()}


def _exploration(rows, role, release_id, paired, minimum):
    from .descriptive_exploration import _validate_pairs, comparison_variables, scale_display
    from .descriptives import group_rows, values_and_status
    allowed = comparison_variables(rows.attrs['mode'], role, rows) if paired else variables(role)
    hist = []
    for group in GROUPS:
        block = group_rows(rows, group)
        waves = _validate_pairs(block) if paired else tuple(block.loc[block['wave'].eq(w)] for w in ('T0', 'T1'))
        for var in [v for v in allowed if v.key in FOCUS]:
            a, _ = values_and_status(waves[0], var)
            b, _ = values_and_status(waves[1], var)
            if paired:
                mask = a.notna() & b.notna()
                a, b = a[mask], b[mask]
            values = [a.dropna().to_numpy(dtype=float), b.dropna().to_numpy(dtype=float)]
            lo, hi = scale_display(var)['bounds']
            if any(((v < lo) | (v > hi)).any() for v in values):
                raise PipelineError('量表超出靜態分箱範圍，請核對本機報表；不可靜默遺漏。')
            # Fixed, public scale bounds cannot reveal a participant's exact
            # minimum/maximum (data-derived histogram edges can do so).
            edges = np.arange(lo-.5, hi+1, 1.) if var.key.startswith('PHQ_') else np.linspace(lo, hi, int((hi-lo)*4)+1)
            counts = [np.histogram(v, bins=edges)[0] for v in values]
            if any(_small(len(v), minimum) for v in values):
                for wave in ('T0', 'T1'):
                    hist.append(dict(group=group, variable_id=var.key, wave=wave,
                                     bin_index=0, bin_left=None, bin_right=None, count=None))
                continue
            # Merge adjacent cells using the same bins for both waves; do not
            # expose rare tails or hide an otherwise useful large distribution.
            segments, start = [], 0
            for end in range(len(edges)-1):
                totals = [int(c[start:end+1].sum()) for c in counts]
                if all(not _small(n, minimum) for n in totals):
                    segments.append((start, end+1)); start = end+1
            if start < len(edges)-1:
                while segments and any(_small(int(c[start:].sum()), minimum) for c in counts):
                    start = segments.pop()[0]
                segments.append((start, len(edges)-1))
            for i, (left, right) in enumerate(segments):
                for wave, count in zip(('T0', 'T1'), counts):
                    hist.append(dict(group=group, variable_id=var.key, wave=wave, bin_index=i,
                                     bin_left=float(edges[left]), bin_right=float(edges[right]),
                                     count=int(count[left:right].sum())))
    return hist


def _trends(rows, role, minimum):
    """Aggregate the exact existing date-quality policy into complete HK months.

    Deliberately omit individual dates, school composition and partial-month
    endpoints. Each period's statistics still use the shared calculation layer.
    """
    from .descriptive_trends import date_mask, dated_rows
    dated = dated_rows(rows)
    records = []
    for include_batch in (False, True):
        selected = dated.loc[date_mask(dated, include_batch)].copy()
        if selected.empty:
            continue
        selected['_month'] = selected['_calendar_date'].map(lambda d: d.isoformat()[:7])
        first, last = selected['_month'].min(), selected['_month'].max()
        for period in pd.period_range(first, last, freq='M'):
            block = selected.loc[selected['_month'].eq(str(period))]
            stats = statistics(block, role)
            stats = stats.loc[stats['variable_id'].isin(FOCUS)]
            safe = safe_statistics(stats, minimum)
            counts = _counts(block, minimum)
            records.append(dict(period=str(period), include_batch=include_batch, counts=counts, statistics=safe))
    return records


def _binary_pairs(rows, role, release_id, minimum):
    from .descriptive_exploration import comparison_variables, explore
    chosen = [v.key for v in comparison_variables(rows.attrs['mode'], role, rows) if v.kind == 'binary']
    result = explore(rows, role, tuple(GROUPS), release_id, paired=True, selected_variables=chosen)
    partitions = {}
    for row in _records(result['pair_transitions'], ['group', 'variable_id', 'variable',
                         'transition', 'count', 'denominator', 'proportion']):
        partitions.setdefault((row['group'], row['variable_id']), []).append(row)
    for block in partitions.values():
        hide = any(_small(r[k], minimum) for r in block for k in ('count', 'denominator'))
        for row in block:
            row['suppressed'] = bool(hide)
            if hide:
                row.update(count=None, denominator=None, proportion=None)
    return [r for block in partitions.values() for r in block]


def build_views(frame, parents, measurements, summary, folder, minimum, progress=None, *, prepared_scopes=None,
                retain_residual=False):
    folder = Path(folder)
    views = []
    scopes = [(mode, role, cohort(frame, parents, measurements, mode, role))
              for mode in MODES for role in ('student', 'parent')
              if not (parents is None and mode == 'acbd' and role == 'parent')] if prepared_scopes is None else prepared_scopes
    parent_file = folder / 'independent_parent_analysis.parquet'
    if prepared_scopes is None and summary.get('independent_parent') and parent_file.exists():
        from .parent_panel_views import read_panel, verify_panel
        panel = read_panel(folder)
        verify_panel(panel, summary['independent_parent'])
        for key, branch, paired in [('independent_all', 'child_report', False),
                                    ('independent_child', 'child_report', True),
                                    ('independent_adult', 'same_adult', True)]:
            scopes.append((key, 'parent', independent_cohort(panel['analysis'], measurements, branch, paired)))
    source_capable = set(SOURCE_NAMES) == set(SOURCE_CODES)
    residual = minimum == 0 and (retain_residual or any(not rows['anchor_source_type'].isin(SOURCE_CODES).all()
                                                     for _, _, rows in scopes))
    for mode, role, base in scopes:
        if minimum == 0:
            base, grade_anchor = attach_grade(base, frame, measurements, mode, role)
            # Presentation-only partition key; unknown values must not vanish
            # when known source codes are pooled. Original sources stay intact.
            base['anchor_source_type'] = base['anchor_source_type'].map(source_code)
        reference = next((rows for key, who, rows in scopes
                          if key == {'abcd': 'acbd', 'ef': 'efmatched',
                                     'independent_all': 'independent_child'}.get(mode) and who == role), None)
        for mainstream in (False, True):
            if progress:
                progress(f'{mode} / {role} / {"mainstream" if mainstream else "all schools"}')
            for source in ('all', *SOURCE_NAMES, *(('unknown',) if residual else ())):
                selected, _ = filter_cohort(base, mainstream=mainstream, sources=() if source == 'all' else (source,))
                selected.attrs['mode'] = base.attrs['mode']
                stats = statistics(selected, role, tuple(GROUPS))
                changes = (overview_changes(selected, reference, role, tuple(GROUPS))
                           if reference is not None else pair_details(selected, role, tuple(GROUPS)))
                from .descriptives import group_rows
                view = dict(mode=mode, role=role, mainstream=mainstream, source=source,
                            grouping_anchor=('wave_response' if mode == 'abcd' else 'wave_student'
                                if mode == 'ef' else 'independent_parent_T0' if mode.startswith('independent')
                                else 'student_T0' if mode == 'efmatched' or role == 'student' else 'BD_parent_T0'),
                            source_filter_anchor=('wave_role_response' if mode == 'ef' else
                                'wave_response' if mode == 'abcd' else 'independent_parent_T0'
                                if mode.startswith('independent') else 'student_T0'
                                if mode == 'efmatched' or role == 'student' else 'BD_parent_T0'),
                            counts={g: _counts(group_rows(selected, g), minimum) for g in GROUPS},
                            statistics=safe_statistics(stats, minimum), changes=safe_changes(changes, minimum))
                if minimum == 0:
                    view['grade'] = build_cube(selected, role, view, tuple(GROUPS), grade_anchor)
                    if source_capable and source == 'all' and reference is not None:
                        view['source_pairs'] = source_pairs(selected, reference, role, tuple(GROUPS),
                            (*SOURCE_CODES, 'unknown') if residual else SOURCE_CODES)
                if source == 'all':
                    paired = mode in {'acbd', 'efmatched', 'independent_child', 'independent_adult'}
                    view['histograms'] = _exploration(selected, role, summary['release_id'], False, minimum)
                    view['trends'] = _trends(selected, role, minimum)
                    if paired:
                        view['paired_histograms'] = _exploration(selected, role, summary['release_id'], True, minimum)
                        # The new availability partition also protects its
                        # both-valid N and means. Do not disclose that same N
                        # again through the paired histogram download.
                        hidden = {(r['group'], r['variable_id']) for r in view['changes'] if r['suppressed']}
                        for row in view['paired_histograms']:
                            if (row['group'], row['variable_id']) in hidden:
                                row.update(bin_left=None, bin_right=None, count=None)
                        view['transitions'] = _binary_pairs(selected, role, summary['release_id'], minimum)
                views.append(view)
    return views


def build_snapshot(folder, summary, imported, minimum=0, progress=None):
    if minimum < 0:
        raise PipelineError('彙總人數門檻不可為負數。')
    folder = Path(folder)
    if summary.get('descriptive', {}).get('version') != VERSION:
        raise PipelineError('請先發布使用目前描述統計版本的資料，不能猜測舊版口徑。')
    frame = pd.read_parquet(folder / 'analysis.parquet')
    parent_file = folder / 'parent_longitudinal.parquet'
    parents = pd.read_parquet(parent_file) if parent_file.exists() else None
    measurements = pd.read_parquet(folder / 'descriptive_measurements.parquet')
    check = sample_reconciliation(frame, parents, {key: value for key, value in summary.items()
                                                   if parents is not None or key != 'BD'})
    if not check['核對'].eq('一致').all():
        raise PipelineError('首頁及正式樣本數不一致，停止靜態匯出。')
    # No arbitrary labels from source files are copied into the public object.
    frame = frame.copy()
    imported = imported.copy()
    for table in (frame, *([parents] if parents is not None else []), imported):
        table['source_type'] = table['source_type'].where(table['source_type'].isin(SOURCE_NAMES), 'unknown')
    source_tables = {}
    for role in ('all', 'student', 'parent'):
        rows = source_wave_counts(imported, frame, None if role == 'all' else role).to_dict('records')
        source_tables[role] = count_table(rows, minimum)
    counts = {key: int(summary[key]) for key in SUMMARY_COUNTS if key in summary}
    # Only known stages and their numeric counts are allowed into stage labels.
    clean = {key: summary['stage_counts'][key] for key in STAGE_PURPOSES if key in summary['stage_counts']}
    stages = stage_overview({'stage_counts': clean, 'parent_wave_policy': summary.get('parent_wave_policy')}).to_dict('records')
    samples = [dict(sample=key, label=SAMPLE_NAMES[key], count=int(summary[key]))
               for key in SAMPLE_NAMES if key in summary]
    if parents is None:
        counts['BD'] = None
        for row in samples:
            if row['sample'] == 'BD':
                row['count'] = None
    status_names = {'confirmed': 'Confirmed', 'pending': 'Pending', 'rejected': 'Rejected', 'unmatched': 'Unmatched'}
    evidence = [dict(status=label, count=int(summary.get('case_status_counts', {}).get(code, 0)))
                for code, label in status_names.items()]
    independent = summary.get('independent_parent', {})
    parent_counts = {key: int(independent[key]) for key in
                     ('baselines', 'child_report_pairs', 'same_adult_pairs', 'same_adult_alternative_T1') if key in independent}
    from .descriptive_reports import NOTES
    tracking = []
    path = folder / 'dyad_tracking.parquet'
    if path.exists():
        tracked = pd.read_parquet(path, columns=['registration_state', 'followup_status'])
        tracking = count_table([
            {'item': 'Active student-parent registrations', 'count': int(tracked['registration_state'].eq('active').sum())},
            {'item': 'Paused or awaiting registration', 'count': int(tracked['registration_state'].ne('active').sum())},
            {'item': 'Both roles completed eligible T1', 'count': int(tracked['followup_status'].eq('both_complete').sum())},
            {'item': 'At least one role incomplete', 'count': int(tracked['followup_status'].isin(['student_only', 'parent_only', 'neither_complete']).sum())},
        ], minimum)
    snapshot = dict(format=FORMAT, release_id=summary['release_id'], generated_at=utcnow(),
                    inference_version='paired_t_dz_v1',
                    dictionary_version=DICTIONARY_VERSION,
                    descriptive_projection_version=DESCRIPTIVE_PROJECTION_VERSION,
                    minimum_cell_n=minimum, small_sample_policy='none' if minimum==0 else 'threshold',
                    report_version=VERSION,
                    counts=counts, stages=stages, sources=source_tables,
                    samples=samples, evidence=count_table(evidence, minimum), tracking=tracking,
                    independent_counts=parent_counts, groups=GROUPS,
                    modes={**MODES, 'independent_all': '全部獨立家長基線及追蹤',
                           'independent_child': '獨立家長：同一孩子跨期', 'independent_adult': '獨立家長：同一成人跨期'},
                    source_names={'all': '全部來源', **SOURCE_NAMES, **({'unknown': 'Unidentified source'} if minimum == 0 else {})}, notes=NOTES,
                    dictionary=[{k: r[k] for k in ('variable_id', 'label', 'kind', 'role', 'section', 'unit', 'note')}
                                for r in dictionary_rows()],
                    parent_wave_policy=summary.get('parent_wave_policy', ''),
                    views=build_views(frame, parents, measurements, summary, folder, minimum, progress))
    if minimum == 0:
        snapshot['grade'] = grade_header(summary['release_id'])
        if set(SOURCE_NAMES) == set(SOURCE_CODES):
            snapshot['source_selection'] = source_header(summary['release_id'], snapshot['views'])
    english_snapshot(snapshot, summary)
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot):
    """Defence in depth after the explicit projections above."""
    private_keys = {'submission_id', 'child_id', 'respondent_id', 'version_id', 'case_id', 'dyad_id',
                    'school', 'school_a', 'phone', 'email', 'dob', 'raw', 'source_label', 'path', 'reason'}
    forbidden = re.compile(r'(?:\b(?:SUB|CHILD|CASE|REV|DYAD|PKG|DEC)_\w+|/(?:Users|home)/|'
                           r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:https?://|file://))')
    def visit(value):
        if isinstance(value, dict):
            if set(value) & private_keys:
                raise PipelineError('靜態快照含有禁止匯出的欄位。')
            for part in value.values():
                visit(part)
        elif isinstance(value, list):
            for part in value:
                visit(part)
        elif isinstance(value, str) and forbidden.search(value):
            raise PipelineError('靜態快照含有識別碼、個人聯絡或本機路徑。')
    visit(snapshot)
    if 'release_context' in snapshot:
        from .static_release_context import validate_release_context
        validate_release_context(snapshot['release_context'], public=True)
        if snapshot['release_context']['release_id'] != snapshot['release_id']:
            raise PipelineError('Dashboard release context identifies a different release.')
    validate_grade(snapshot)
    validate_sources(snapshot)
    if 'period_selection' in snapshot:
        from .static_period_assets import validate_catalog
        validate_catalog(snapshot['period_selection'], snapshot['release_id'])
        minimum = snapshot.get('minimum_cell_n', 0)
        if type(minimum) is not int or minimum < 0 or snapshot['period_selection']['minimum_cell_n'] != minimum:
            raise PipelineError('Period catalog and snapshot suppression thresholds differ.')
    json.dumps(plain(snapshot), allow_nan=False)


def pack_snapshot(snapshot):
    """Store field names once per table; browsers decode only the selected view.

    This changes representation only, never numeric precision or missingness.
    """
    def table(rows):
        if not rows:
            return []
        columns = list(rows[0])
        if any(set(r) != set(columns) for r in rows):
            raise PipelineError('彙總表欄位不一致，不能封裝。')
        return dict(columns=columns, rows=[[r[c] for c in columns] for r in rows])
    views = []
    for view in snapshot['views']:
        packed = dict(view)
        for key in ('statistics', 'changes', 'histograms', 'paired_histograms', 'transitions'):
            if key in packed:
                packed[key] = table(packed[key])
        if 'trends' in packed:
            packed['trends'] = [{**period, 'statistics': table(period['statistics'])} for period in packed['trends']]
        views.append(packed)
    return {**snapshot, 'encoding': 'column_tables_v1', 'views': views}


def _owned_deployment(destination):
    """Reject unrelated files before an export can replace this directory."""
    managed = {'.vercel', 'node_modules', 'public'}
    for path in destination.iterdir():
        if path.name == '.gitignore':
            if path.is_symlink() or not path.is_file():
                return False
            continue
        if path.name in managed:
            if path.is_symlink() or not path.is_dir():
                return False
            if path.name == 'public' and any(p.is_symlink() or not p.is_file() or
                                           p.name not in PUBLIC_FILES for p in path.iterdir()):
                return False
            continue
        if path.is_symlink():
            return False
        if path.is_dir():
            for part in path.rglob('*'):
                if part.is_symlink() or (part.is_file() and part.relative_to(destination).as_posix() not in DEPLOY_FILES):
                    return False
            if not any(name.startswith(path.name + '/') for name in DEPLOY_FILES):
                return False
        elif path.name not in DEPLOY_FILES:
            return False
    return True


def write_site(snapshot, destination, *, scope_export=None, manual_exclusion=None,
               verify_inputs=None, input_inventory=None, period_assets=None):
    from .static_assets import APP_JS, HTML, STYLES
    from .static_scope_client import JS_SOURCE as SCOPE_JS
    from .static_quality_ui import JS_SOURCE as QUALITY_JS
    validate_snapshot(snapshot)
    from .static_period_assets import empty_assets, validate_assets
    if 'period_selection' in snapshot:
        if period_assets is None:
            raise PipelineError('Combined period assets are required for their declared catalog.')
        validate_assets(snapshot['period_selection'], period_assets, snapshot['release_id'])
    else:
        period_assets = empty_assets(snapshot['release_id'])
    if scope_export is None:
        scope_export = unavailable_scope('compatible_scope_export_required', snapshot['release_id'])
    validate_scope_export(scope_export, snapshot)
    from .manual_exclusion_export import JS_HASH, validate_manual_export
    if manual_exclusion is not None:
        validate_manual_export(manual_exclusion, snapshot, scope_export)
    destination = Path(destination).absolute()
    if destination.is_symlink():
        raise PipelineError('匯出位置不可是捷徑。')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        manifest = destination / 'snapshot-manifest.json'
        try:
            owned = json.loads(manifest.read_text()).get('format') == FORMAT
        except (OSError, ValueError):
            owned = False
        if not owned or not _owned_deployment(destination):
            raise PipelineError('匯出位置含有其他檔案，請選擇新的空資料夾。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.study2-static-', dir=destination.parent))
    previous = stage.with_name(stage.name + '-previous')
    failed = stage.with_name(stage.name + '-discarded')
    initially_present = destination.exists()
    try:
        html = HTML if 'src="manual-exclusion.js"' in HTML else HTML.replace(
            '<script defer src="app.js">', '<script defer src="manual-exclusion.js"></script><script defer src="app.js">')
        contents = {**ACCESS_FILES, **period_assets, 'index.html': html, 'app.js': APP_JS, 'styles.css': STYLES,
                    'snapshot.js': 'window.STUDY2_SNAPSHOT=' + json.dumps(plain(pack_snapshot(snapshot)), ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c') + ';\n',
                    'scope-index.js': 'window.STUDY2_SCOPE_EXPORT=' + json.dumps(plain(scope_export), ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c') + ';\n',
                    'scope-engine.js': SCOPE_JS, 'quality-ui.js': QUALITY_JS,
                    'manual-exclusion.js': JS_HASH + '\nwindow.STUDY2_MANUAL_EXCLUSION=' + json.dumps(
                        plain(manual_exclusion), ensure_ascii=False, separators=(',', ':'),
                        allow_nan=False).replace('<', '\\u003c') + ';\n',
                    '.vercelignore': '*\n' + ''.join('!' + name + '\n' for name in sorted(
                        (DEPLOY_FILES - {'preview.mjs', 'DEPLOYMENT.md', '.vercelignore'}) | {'api', 'server'})),
                    'vercel.json': json.dumps({'framework': None, 'buildCommand': 'npm run build',
                        'installCommand': 'npm ci --ignore-scripts', 'outputDirectory': 'public',
                        'headers': [{'source': '/(.*)', 'headers': [
                            {'key': 'X-Content-Type-Options', 'value': 'nosniff'},
                            {'key': 'Referrer-Policy', 'value': 'no-referrer'},
                            {'key': 'X-Robots-Tag', 'value': 'noindex, nofollow'},
                            {'key': 'Content-Security-Policy', 'value': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"},
                            {'key': 'Cache-Control', 'value': 'private, no-store, max-age=0'},
                            {'key': 'CDN-Cache-Control', 'value': 'no-store'},
                            {'key': 'Vercel-CDN-Cache-Control', 'value': 'no-store'},
                            {'key': 'Cross-Origin-Resource-Policy', 'value': 'same-origin'}]}]}, indent=2)}
        for name, content in contents.items():
            (stage / name).parent.mkdir(parents=True, exist_ok=True)
            (stage / name).write_text(content, encoding='utf-8')
        manifest = dict(format=FORMAT, release_id=snapshot['release_id'], generated_at=snapshot['generated_at'],
                        snapshot_sha256=digest(snapshot), files={name: file_hash(stage / name) for name in contents})
        manifest.update(scope_format=SCOPE_EXPORT_FORMAT, index_revision=scope_export['index_revision'],
                        input_inventory=input_inventory or {}, input_revision=digest(input_inventory or {}))
        if manual_exclusion is not None:
            manifest['manual_exclusion'] = {k: manual_exclusion[k] for k in
                ('format', 'hash_scheme', 'status', 'revision', 'inventory_revision', 'on_revision')}
        if 'release_context' in snapshot:
            manifest['release_context'] = snapshot['release_context']
        (stage / 'snapshot-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        if verify_inputs:
            verify_inputs()
        if destination.exists():
            # Preserve local project association/dependencies without following
            # dependency symlinks. Neither directory enters the deployment ZIP.
            for name in ('.vercel', 'node_modules'):
                association = destination / name
                if association.exists():
                    shutil.copytree(association, stage / name, symlinks=True)
            local_ignore = destination / '.gitignore'
            if local_ignore.exists():
                shutil.copy2(local_ignore, stage / '.gitignore')
            os.replace(destination, previous)
        if verify_inputs:
            verify_inputs()
        os.replace(stage, destination)
        if verify_inputs:
            verify_inputs()
    except BaseException:
        # Check actual rename outcomes, not only flags set after a syscall:
        # interruption can occur immediately after a successful rename.
        if previous.exists():
            if destination.exists():
                os.replace(destination, failed)
            os.replace(previous, destination)
        elif not initially_present and not stage.exists() and destination.exists():
            os.replace(destination, failed)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if failed.exists():
            shutil.rmtree(failed)
    if previous.exists():
        shutil.rmtree(previous)
    return dict(output=str(destination), release_id=snapshot['release_id'], views=len(snapshot['views']),
                bytes=sum((destination / name).stat().st_size for name in DEPLOY_FILES),
                deployed=False)


PUBLICATION_INPUTS = (
    'summary.json', 'analysis.parquet', 'descriptive_measurements.parquet',
    'parent_longitudinal.parquet', 'records.jsonl.gz', 'scope_flow_evidence.json',
    'dyad_tracking.parquet', 'independent_parent_analysis.parquet',
    'independent_parent_pairs.parquet', 'independent_parent_audit.parquet',
    'independent_parent_candidates.parquet', 'independent_parent_sensitivity.parquet',
)


def _file_pin(path):
    if path.is_symlink() or path.exists() and not path.is_file():
        raise PipelineError('Publication inputs must be regular files, not links or directories.')
    return dict(sha256=file_hash(path), bytes=path.stat().st_size) if path.exists() else None


def _input_inventory(folder, state, release_root):
    return {**{name: _file_pin(folder / name) for name in PUBLICATION_INPUTS},
            'publication_pointer': _file_pin(release_root / 'CURRENT.json'),
            'release_location_mapping': _file_pin(state / 'release_locations.json')}


def export_static(cfg, destination, minimum=0, progress=None, *, school_binding=None, manual_manifest=None,
                  release_context=None, default_eligibility='off'):
    if default_eligibility not in {'off', 'on'} or default_eligibility == 'on' and release_context is None:
        raise PipelineError('Default ON requires an explicit validated dashboard release context.')
    state = Path(cfg['state_dir']).resolve()
    raw_destination = Path(destination).absolute()
    if raw_destination.is_symlink():
        raise PipelineError('匯出位置不可是捷徑。')
    destination = raw_destination.resolve()
    # Never replace any state, release, source folder or repository ancestor.
    protected = [state, Path(cfg['release_dir']).resolve(), Path(__file__).resolve().parent.parent,
                 Path(cfg['project_root']).resolve()]
    if any(destination == p or destination in p.parents or p == state and p in destination.parents
           or p == Path(cfg['release_dir']).resolve() and p in destination.parents for p in protected):
        raise PipelineError('靜態匯出必須與研究資料庫、發布及原始資料分開。')
    # Open only the published pointer/summary and aggregate source counts.
    # Do not trigger maintenance/recovery writes from an export reader.
    db = sqlite3.connect((state / 'study2.sqlite').as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    try:
        release = current(db)
        if not release:
            raise PipelineError('尚未發布資料，不能建立快照。')
        from .storage import imported_source_counts
        from .outputs import source_category
        source_counts = imported_source_counts(db, release['run_id'])
        source_counts = sorted(source_counts, key=lambda row: json.dumps(row, sort_keys=True))
        imported = pd.DataFrame(source_counts,
                                columns=['source_label', 'role', 'wave', 'submissions'])
        imported['source_type'] = imported.pop('source_label').map(lambda v: source_category(str(v)) if v else 'unknown')
        summary = json.loads(release['stats_json'])
        folder = Path(release['path'])
        release_root = Path(cfg['release_dir']).resolve()
        pins = _input_inventory(folder, state, release_root)
        if any(pins[name] is None for name in ('summary.json', 'analysis.parquet', 'descriptive_measurements.parquet', 'publication_pointer')):
            raise PipelineError('Required published inputs or pointer are missing; previous export retained.')
        pointer = json.loads((release_root / 'CURRENT.json').read_text())
        if pointer.get('release_id') != release['release_id']:
            raise PipelineError('Published file and database pointers disagree; previous export retained.')
        if json.loads((folder / 'summary.json').read_text()) != summary:
            raise PipelineError('Published summary file and frozen database summary disagree.')
        pins['published_summary'] = dict(sha256=digest(summary))
        pins['legacy_source_counts'] = dict(sha256=digest(source_counts))
        pins['supplied_school_binding'] = dict(sha256=digest(school_binding)) if school_binding is not None else None
        pins['supplied_manual_manifest'] = dict(sha256=digest(manual_manifest)) if manual_manifest is not None else None
        pins['supplied_release_context'] = dict(sha256=digest(release_context)) if release_context is not None else None
        run = None
        if release_context is not None:
            from .static_release_context import validate_release_context
            from .runner import program_hash
            validate_release_context(release_context)
            run = db.execute('SELECT run_id, fingerprint FROM runs WHERE run_id=?', (release['run_id'],)).fetchone()
            if run is None:
                raise PipelineError('Dashboard release context requires its recorded analytical run.')
            run = dict(run)
            pins['analytical_run'] = dict(sha256=digest(run))
            pins['export_program_hash'] = dict(sha256=program_hash())
        initial_files = {key: value for key, value in pins.items() if key not in {'published_summary', 'legacy_source_counts', 'supplied_school_binding', 'supplied_manual_manifest', 'supplied_release_context', 'analytical_run', 'export_program_hash'}}
        def verify():
            now = current(db)
            counts_now = sorted(imported_source_counts(db, release['run_id']), key=lambda row: json.dumps(row, sort_keys=True))
            if (now != release or _input_inventory(folder, state, release_root) != initial_files or
                    digest(counts_now) != pins['legacy_source_counts']['sha256'] or
                    (dict(sha256=digest(school_binding)) if school_binding is not None else None) != pins['supplied_school_binding'] or
                    (dict(sha256=digest(manual_manifest)) if manual_manifest is not None else None) != pins['supplied_manual_manifest'] or
                    (dict(sha256=digest(release_context)) if release_context is not None else None) != pins['supplied_release_context'] or
                    (run is not None and dict(db.execute('SELECT run_id, fingerprint FROM runs WHERE run_id=?',
                        (release['run_id'],)).fetchone() or {}) != run) or
                    (run is not None and program_hash() != pins['export_program_hash']['sha256'])):
                raise PipelineError('Published inputs or pointer changed during export; previous export retained.')
        scope = build_scope_export(folder, summary, minimum, school_binding=school_binding)
        snapshot = build_snapshot(folder, summary, imported, minimum, progress)
        snapshot['published_at'] = release['created_at']
        # Fine date/profile moments live only in separately lazy-loaded assets.
        # The same OFF/ON catalog is immutable in both snapshots, preserving the
        # existing exclusion wrapper's strict metadata comparison and hashes.
        analysis = pd.read_parquet(folder / 'analysis.parquet')
        parent_path = folder / 'parent_longitudinal.parquet'
        parents = pd.read_parquet(parent_path) if parent_path.exists() else None
        measurements = pd.read_parquet(folder / 'descriptive_measurements.parquet')
        panel = None
        if summary.get('independent_parent'):
            from .parent_panel_views import read_panel
            panel = read_panel(folder)
        records = None
        if manual_manifest is not None:
            with gzip.open(folder / 'records.jsonl.gz', 'rt', encoding='utf-8') as handle:
                records = [json.loads(line) for line in handle if line.strip()]
        manual_export = None
        if release_context is not None and manual_manifest is None:
            raise PipelineError('Dashboard release context requires an accepted composed manifest.')
        if manual_manifest is not None:
            from .manual_exclusion_export import build_manual_export
            if release_context is not None:
                from .static_release_context import bind_release_context
                snapshot['release_context'] = bind_release_context(release_context, release, summary,
                    run['fingerprint'], records, manual_manifest, default_eligibility=default_eligibility)
            manual_export = build_manual_export(snapshot, scope, records, analysis, parents,
                measurements, summary, imported, manual_manifest, panel=panel, progress=progress)
            if release_context is not None and manual_export['status'] != 'available':
                raise PipelineError('Dashboard release context requires a complete valid ON/OFF export.')
        from .static_period_assets import prepare_assets
        accepted_on = manual_export is not None and manual_export['status'] == 'available'
        period_catalog, period_assets = prepare_assets(analysis, parents, measurements, summary,
            records=records, manifest=manual_manifest if accepted_on else None,
            panel=panel, minimum=minimum, progress=progress)
        snapshot['period_selection'] = period_catalog
        if manual_export is not None:
            # Add the same validated lazy index to both immutable snapshots.
            # Only an already valid ON bundle can authorize an ON period cube.
            from .analysis_eligibility import sha
            from .manual_exclusion_export import validate_manual_export
            manual_export['off']['snapshot_revision'] = sha(plain(pack_snapshot(snapshot)))
            if accepted_on:
                manual_export['on']['snapshot']['period_selection'] = plain(period_catalog)
                manual_export['on_revision'] = sha(manual_export['on'])
            validate_manual_export(manual_export, snapshot, scope)
        verify()
        return write_site(snapshot, destination, scope_export=scope,
                          manual_exclusion=manual_export, verify_inputs=verify, input_inventory=pins,
                          period_assets=period_assets)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Study 2 aggregate-only static export')
    parser.add_argument('--config', type=Path, default=Path('config.local.json'))
    parser.add_argument('--output', type=Path, default=Path('static_dashboard'))
    parser.add_argument('--manual-manifest', type=Path, help='Exact accepted private composed exclusion manifest')
    parser.add_argument('--release-context', type=Path, help='Strict current-run aggregate control provenance')
    parser.add_argument('--default-eligibility', choices=('off', 'on'), default='off',
                        help='Explicit initial analytical mask; ON requires a validated release context')
    args = parser.parse_args()
    def supplied(path):
        if path is None:
            return None
        if path.is_symlink() or not path.is_file():
            raise PipelineError('Supplied export metadata must be a regular private JSON file.')
        return json.loads(path.read_bytes())
    print(json.dumps(export_static(load_config(args.config), args.output,
        manual_manifest=supplied(args.manual_manifest), release_context=supplied(args.release_context),
        default_eligibility=args.default_eligibility), ensure_ascii=False))


if __name__ == '__main__':
    main()
