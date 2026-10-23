"""Reversible analytical eligibility over exact, already selected members.

No I/O, matching, survey selection, scoring or administrative mutations. Private
accepted manifests never form part of the browser projection.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import math
import struct

import pandas as pd

from .common import PipelineError
from .static_scope import SLOTS

MANIFEST_FORMAT = 'study2_manual_exclusion_manifest_v1'
SCOPE_FORMAT = 'study2_scope_eligibility_v1'
POLICY = 'fixed_original_members_no_reselection'
COPY_POLICY = 'all_byte_identical_copies'
HASH_SCHEME = 'typed_f64_utf16_v1'


class EligibilityError(PipelineError):
    """Only stable, non-identifying codes may escape the private validator."""


def _need(ok, code):
    if not ok:
        raise EligibilityError(code)


def sha(value):
    """Hash JSON meaning without changing scientific values or float precision.

    Every numeric leaf hashes its IEEE754 bits; object keys sort as UTF16 code
    units. Python/JS decimal formatting (and 1 versus 1.0) cannot affect binding.
    Type tags prevent a supplied string/array from masquerading as a number.
    """
    def typed(v):
        if v is None:
            return ['null']
        if type(v) is bool:
            return ['bool', v]
        if isinstance(v, (int, float)):
            _need(math.isfinite(float(v)), 'nonfinite_revision_value')
            return ['f64', struct.pack('>d', float(v)).hex()]
        if isinstance(v, str):
            _need(not any(0xD800 <= ord(c) <= 0xDFFF for c in v), 'invalid_unicode_revision_value')
            return ['str', v]
        if isinstance(v, (list, tuple)):
            return ['array', [typed(x) for x in v]]
        _need(isinstance(v, dict) and all(isinstance(k, str) for k in v), 'invalid_revision_type')
        return ['object', [[typed(k), typed(v[k])] for k in sorted(v, key=lambda k: k.encode('utf-16-be'))]]
    return hashlib.sha256(json.dumps(typed(value), separators=(',', ':'), ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _records(records):
    rows = records.to_dict('records') if isinstance(records, pd.DataFrame) else list(records)
    by_id = {}
    for r in rows:
        sid = r.get('submission_id')
        _need(isinstance(sid, str) and sid and sid not in by_id, 'invalid_inventory_identity')
        _need(isinstance(r.get('version_id'), str) and r['version_id'] and
              isinstance(r.get('role'), str) and r['role'] in {'student', 'parent'}, 'invalid_inventory_version_or_role')
        _need(_hash(r.get('raw_hash')), 'inventory_content_hash_required')
        by_id[sid] = r
    return rows, by_id


def inventory_revision(records):
    rows, _ = _records(records)
    return sha(sorted([[r['submission_id'], r['version_id'], r['role'], r['raw_hash']]
                       for r in rows]))


def manifest_revision(manifest):
    return sha({k: v for k, v in manifest.items() if k != 'revision'})


def validate_manifest(manifest, records, release_id):
    rows, by_id = _records(records)
    _need(isinstance(manifest, dict) and set(manifest) == {
        'format', 'release_id', 'inventory_revision', 'revision', 'status',
        'approved_by', 'approved_at', 'copy_policy', 'entries'}, 'invalid_manifest_shape')
    _need(manifest['format'] == MANIFEST_FORMAT and manifest['status'] == 'accepted',
          'accepted_manifest_required')
    _need(manifest['release_id'] == release_id, 'manifest_release_mismatch')
    _need(_hash(manifest['inventory_revision']) and
          manifest['inventory_revision'] == inventory_revision(rows), 'manifest_inventory_mismatch')
    _need(_hash(manifest['revision']) and manifest['revision'] == manifest_revision(manifest),
          'manifest_revision_mismatch')
    _need(isinstance(manifest['approved_by'], str) and manifest['approved_by'].strip(),
          'manifest_approval_required')
    try:
        approved = datetime.fromisoformat(manifest['approved_at'].replace('Z', '+00:00'))
        _need(approved.tzinfo is not None, 'manifest_approval_date_invalid')
    except (ValueError, TypeError, AttributeError):
        raise EligibilityError('manifest_approval_date_invalid') from None
    _need(manifest['copy_policy'] == COPY_POLICY and isinstance(manifest['entries'], list),
          'manifest_copy_policy_invalid')
    excluded = set()
    for entry in manifest['entries']:
        _need(isinstance(entry, dict) and set(entry) == {'submission_id', 'version_id'},
              'invalid_manifest_entry')
        sid = entry['submission_id']
        _need(isinstance(sid, str) and sid in by_id, 'manifest_unknown_identity')
        _need(sid not in excluded, 'manifest_duplicate_identity')
        _need(entry['version_id'] == by_id[sid]['version_id'], 'manifest_version_mismatch')
        excluded.add(sid)
    copies = defaultdict(set)
    for r in rows:
        copies[r['role'], r['raw_hash']].add(r['submission_id'])
    _need(all(not (ids & excluded) or ids <= excluded for ids in copies.values()),
          'manifest_incomplete_identical_copies')
    return frozenset(excluded)


def _members(records, analysis, parents):
    _, by_id = _records(records)
    slots, seen = {}, set()
    for r in analysis.to_dict('records'):
        sid = r['submission_id']
        _need(sid in by_id and sid not in seen, 'analysis_identity_mismatch')
        original = by_id[sid]
        key = r['child_id'], r['role'], r['wave']
        _need(key not in slots and r['wave'] in {'T0', 'T1'} and
              original.get('child_id') == r['child_id'] and original['role'] == r['role'] and
              original.get('selected_wave') == r['wave'] and original.get('status') == 'eligible',
              'analysis_slot_mismatch')
        if 'version_id' in r:
            _need(r['version_id'] == original['version_id'], 'analysis_version_mismatch')
        slots[key] = sid
        seen.add(sid)
    _need(seen == {r['submission_id'] for r in by_id.values() if r.get('selected_wave')},
          'analysis_incomplete_membership')
    adult = {}
    if parents is not None:
        used = set()
        for r in parents.to_dict('records'):
            key = r['child_id'], r['role'], r['wave']
            sid = r['submission_id']
            _need(sid in by_id and sid not in used and key not in adult and r['role'] == 'parent'
                  and r['wave'] in {'T0', 'T1'} and by_id[sid].get('child_id') == r['child_id']
                  and by_id[sid]['role'] == 'parent' and by_id[sid].get('status') in {
                      'eligible', 'extra_followup', 'short_interval_followup'},
                  'formal_adult_slot_mismatch')
            if 'version_id' in r:
                _need(r['version_id'] == by_id[sid]['version_id'], 'formal_adult_version_mismatch')
            adult[key] = sid
            used.add(sid)
        for child in {k[0] for k in adult}:
            _need((child, 'parent', 'T0') in adult and (child, 'parent', 'T1') in adult and
                  adult[child, 'parent', 'T0'] == slots.get((child, 'parent', 'T0')),
                  'formal_adult_incomplete_pair')
    members = {}
    for code, required in SLOTS.items():
        lookup = adult if code == 'BD' and parents is not None else slots
        members[code] = tuple(tuple(lookup[child, role, wave] for role, wave in required)
                              for child in sorted({k[0] for k in slots})
                              if all((child, role, wave) in lookup for role, wave in required))
    return members


def _delta(before, after):
    return dict(baseline=before, active=after, excluded=before-after)


@dataclass(frozen=True)
class Projection:
    enabled: bool
    excluded: frozenset
    members: dict
    canonical_members: dict
    frame: pd.DataFrame
    parents: pd.DataFrame | None
    impact: dict


def project_eligibility(records, analysis, parent_longitudinal, manifest, release_id, *,
                        enabled=True, panel=None):
    """OFF does not inspect an optional manifest; no in-place changes or reselection."""
    rows, by_id = _records(records)
    original = _members(rows, analysis, parent_longitudinal)
    excluded = validate_manifest(manifest, rows, release_id) if enabled else frozenset()
    retained = {code: tuple(m for m in members if not excluded.intersection(m))
                for code, members in original.items()}
    frame = analysis.loc[~analysis.submission_id.isin(excluded)].copy(deep=True)
    parents = (parent_longitudinal.loc[parent_longitudinal.submission_id.isin(
        {sid for m in retained['BD'] for sid in m})].copy(deep=True)
               if parent_longitudinal is not None else None)
    if enabled:
        native_ids = lambda code: {sid for m in retained[code] for sid in m}
        for flag, codes in [('longitudinal', ('AC', 'BD')), ('dyad', ('E', 'F')),
                            ('longitudinal_dyad', ('EF',))]:
            if flag in frame:
                allowed = set().union(*(native_ids(c) for c in codes))
                frame[flag] = frame.submission_id.isin(allowed)
        if 'child_report_longitudinal' in frame:
            complete = {child for child, g in frame.loc[frame.role.eq('parent')].groupby('child_id')
                        if set(g.wave) == {'T0', 'T1'}}
            frame['child_report_longitudinal'] = [
                (child in complete if role == 'parent' else sid in native_ids('AC'))
                for child, role, sid in zip(frame.child_id, frame.role, frame.submission_id)]
    intake = {}
    for role in ('student', 'parent'):
        baseline = sum(r['role'] == role for r in rows)
        lost = sum(by_id[sid]['role'] == role for sid in excluded)
        intake[role] = dict(baseline=baseline, excluded=lost, retained=baseline-lost)
    samples = [dict(code=code, **(_delta(len(original[code]), len(retained[code]))
                                if code != 'BD' or parent_longitudinal is not None else
                                dict(baseline=None, active=None, excluded=None))) for code in SLOTS]
    independent = independent_impact(panel, excluded) if panel is not None else None
    return Projection(enabled, excluded, retained, original, frame, parents,
                      dict(intake=intake, samples=samples, independent=independent))


def independent_impact(panel, excluded):
    analysis, pairs = panel['analysis'], panel['pairs']
    base = analysis.loc[analysis.panel_branch.eq('child_report') & analysis.panel_wave.eq('T0')]
    out = {'baselines': _delta(len(base), int((~base.submission_id.isin(excluded)).sum()))}
    for branch, code in [('child_report', 'child_report_pairs'), ('same_adult', 'same_adult_pairs')]:
        group = pairs.loc[pairs.panel_branch.eq(branch)]
        keep = ~group.t0.isin(excluded) & ~group.t1.isin(excluded)
        out[code] = _delta(len(group), int(keep.sum()))
    return out


def projected_cohorts(records, analysis, parents, measurements, projection, *, panel=None):
    """Attach original anchors first; mask each native cohort by exact members."""
    from .descriptives import cohort, independent_cohort
    from .descriptive_spec import MODES
    out = []
    for mode in MODES:
        for role in ('student', 'parent'):
            if mode == 'acbd' and role == 'parent' and parents is None:
                continue
            base = cohort(analysis, parents, measurements, mode, role)
            code = ({'student': 'AC', 'parent': 'BD'}[role] if mode == 'acbd' else
                    'EF' if mode == 'efmatched' else None)
            allowed = ({sid for member in projection.members[code] for sid in member} if code else
                       {sid for c in (('A', 'B', 'C', 'D') if mode == 'abcd' else ('E', 'F'))
                        for member in projection.members[c] for sid in member})
            selected = base.loc[base.submission_id.isin(allowed)].copy()
            selected.attrs = base.attrs.copy()
            out.append((mode, role, selected))
    if panel is not None:
        for mode, branch, paired in [('independent_all', 'child_report', False),
                                     ('independent_child', 'child_report', True),
                                     ('independent_adult', 'same_adult', True)]:
            base = independent_cohort(panel['analysis'], measurements, branch, paired)
            pairs = panel['pairs'].loc[panel['pairs'].panel_branch.eq(branch)]
            keep = pairs.loc[~pairs.t0.isin(projection.excluded) & ~pairs.t1.isin(projection.excluded)]
            allowed = set(keep.t0) | set(keep.t1)
            selected = base.loc[base.submission_id.isin(allowed) if paired else
                                ~base.submission_id.isin(projection.excluded)].copy()
            if 'panel_longitudinal' in selected:
                selected['panel_longitudinal'] = selected.submission_id.isin(allowed)
            selected.attrs = base.attrs.copy()
            out.append((mode, 'parent', selected))
    return out


def scope_overlay(index, records, projection, revision, inventory):
    """Retain exact member/profile correlation, including same-profile copies."""
    from .static_scope import _catalogue_profile, canonical_json, validate_index
    validate_index(index)
    out = deepcopy(index)
    refs = {canonical_json(p): i for i, p in enumerate(index['profiles'])}
    profile = {r['submission_id']: refs[canonical_json(_catalogue_profile(r)[2])] for r in records}
    def samples(members):
        counts = Counter((c, tuple(profile[sid] for sid in member)) for c, group in members.items()
                         for member in group)
        return [dict(code=c, profiles=list(ps), count=n) for (c, ps), n in sorted(counts.items())]
    canonical = samples(projection.canonical_members)
    # A missing formal artifact is unavailable, not a reconstructed child pair.
    if index['meta']['adult']['status'] != 'available':
        canonical = [r for r in canonical if r['code'] != 'BD']
    _need(canonical == sorted(index['samples'], key=lambda r: (r['code'], tuple(r['profiles']))),
          'scope_canonical_membership_mismatch')
    out['samples'] = samples(projection.members)
    if index['meta']['adult']['status'] != 'available':
        out['samples'] = [r for r in out['samples'] if r['code'] != 'BD']
    def counts(ids):
        return [dict(profile=p, count=n) for p, n in sorted(Counter(profile[s] for s in ids).items())]
    selected = {r['submission_id'] for r in records if r.get('selected_wave')}
    out['eligibility'] = dict(format=SCOPE_FORMAT, revision=revision, inventory_revision=inventory,
                              baseline_samples=deepcopy(index['samples']),
                              excluded_records=counts(projection.excluded),
                              excluded_selected=counts(projection.excluded & selected))
    validate_index(out)
    return out


def validate_scope_eligibility(index):
    """Validate the new lane against the complete unchanged canonical index."""
    from .static_scope import validate_index
    e = index['eligibility']
    _need(isinstance(e, dict) and set(e) == {'format', 'revision', 'inventory_revision',
          'baseline_samples', 'excluded_records', 'excluded_selected'} and
          e['format'] == SCOPE_FORMAT and _hash(e['revision']) and _hash(e['inventory_revision']),
          'invalid_scope_eligibility')
    canonical = {k: deepcopy(v) for k, v in index.items() if k != 'eligibility'}
    canonical['samples'] = deepcopy(e['baseline_samples'])
    validate_index(canonical)
    totals, selected = Counter(), Counter()
    for r in index['records']:
        totals[r['profile']] += r['count']
        if r['exit_stage'] == 'selected':
            selected[r['profile']] += r['count']
    counts = []
    for field, limit in [('excluded_records', totals), ('excluded_selected', selected)]:
        _need(isinstance(e[field], list), 'invalid_scope_exclusion_counts')
        seen, values = set(), Counter()
        for r in e[field]:
            _need(isinstance(r, dict) and set(r) == {'profile', 'count'} and
                  type(r['profile']) is int and r['profile'] in totals and r['profile'] not in seen
                  and type(r['count']) is int and 0 < r['count'] <= limit[r['profile']],
                  'invalid_scope_exclusion_counts')
            seen.add(r['profile'])
            values[r['profile']] = r['count']
        counts.append(values)
    flagged, removed_selected = counts
    _need(all(n <= flagged[p] for p, n in removed_selected.items()), 'excluded_selected_exceeds_flags')
    before = {(r['code'], tuple(r['profiles'])): r['count'] for r in canonical['samples']}
    after = {(r['code'], tuple(r['profiles'])): r['count'] for r in index['samples']}
    _need(all(k in before and n <= before[k] for k, n in after.items()), 'eligibility_added_members')
    # Each original record can occur at most once in a native sample. A max-flow
    # allocation proves removed tuples can be covered by flagged profile counts.
    for code in SLOTS:
        lost = [(ps, n-after.get((c, ps), 0)) for (c, ps), n in before.items()
                if c == code and n > after.get((c, ps), 0)]
        graph = defaultdict(Counter)
        def edge(a, b, n):
            graph[a][b] += n
            graph[b][a] += 0
        for p, n in flagged.items():
            edge('start', ('p', p), n)
        required = 0
        for i, (ps, n) in enumerate(lost):
            required += n
            edge(('m', i), 'end', n)
            for p in set(ps):
                edge(('p', p), ('m', i), n)
        covered = 0
        while True:
            prev, queue = {'start': None}, ['start']
            for a in queue:
                for b, n in graph[a].items():
                    if n and b not in prev:
                        prev[b] = a
                        queue.append(b)
                if 'end' in prev:
                    break
            if 'end' not in prev:
                break
            b, amount = 'end', required
            while prev[b] is not None:
                amount = min(amount, graph[prev[b]][b]); b = prev[b]
            b = 'end'
            while prev[b] is not None:
                a = prev[b]; graph[a][b] -= amount; graph[b][a] += amount; b = a
            covered += amount
        _need(covered == required, 'removed_members_not_supported_by_flags')
    return removed_selected


def query_scope_eligibility(index, mask):
    e = index['eligibility']
    intake = {}
    for role in ('student', 'parent'):
        baseline = sum(r['count'] for r in index['records'] if mask[r['profile']] and
                       index['profiles'][r['profile']]['role'] == role)
        excluded = sum(r['count'] for r in e['excluded_records'] if mask[r['profile']] and
                       index['profiles'][r['profile']]['role'] == role)
        intake[role] = dict(baseline=baseline, excluded=excluded, retained=baseline-excluded)
    def count(rows, code):
        return sum(r['count'] for r in rows if r['code'] == code and all(mask[p] for p in r['profiles']))
    samples = [dict(code=c, **(_delta(count(e['baseline_samples'], c), count(index['samples'], c))
               if c != 'BD' or index['meta']['adult']['status'] == 'available' else
               dict(baseline=None, active=None, excluded=None))) for c in SLOTS]
    return dict(format=SCOPE_FORMAT, mode='on', revision=e['revision'],
                inventory_revision=e['inventory_revision'], intake=intake, samples=samples)
