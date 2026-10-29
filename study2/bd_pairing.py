"""BD projection from already selected parent waves, without reselection.

The pairing unit is the established child. Adult-continuity evidence is a
separate property and is used only when it identifies these exact two selected
submissions. This module performs no matching, wave assignment or I/O.
"""
from __future__ import annotations

import pandas as pd
from copy import deepcopy

from .common import PipelineError

POLICY = 'selected_parent_waves_same_child_v1'
STATUSES = frozenset({'same', 'different', 'unconfirmed'})
PAIR_COLUMNS = ['child_id', 't0', 't1', 'adult_status', 'adult_rule']


def _need(ok, code):
    if not ok:
        raise PipelineError('BD pairing: ' + code)


def _identifier(value):
    return isinstance(value, str) and bool(value.strip())


def selected_parent_pairs(analysis, *, tracking=None, excluded=()):
    """Pair the fixed selected B and D slots for each established child.

    ``analysis`` contains the published selected submissions, not candidates.
    An excluded member removes its complete pair; no alternative is selected.
    Optional published tracking evidence is carried only when both referenced
    parent submissions exactly match the selected pair. Otherwise continuity is
    explicitly unconfirmed. Neither pair membership nor a shared child ID is
    evidence of a shared adult.
    """
    _need(isinstance(analysis, pd.DataFrame) and
          {'child_id', 'submission_id', 'role', 'wave'} <= set(analysis.columns), 'selected_fields_required')
    _need(not isinstance(excluded, (str, bytes)), 'invalid_exclusion_set')
    try:
        removed = frozenset(excluded)
    except TypeError:
        raise PipelineError('BD pairing: invalid_exclusion_set') from None
    _need(all(_identifier(x) for x in removed), 'invalid_exclusion_set')
    parents = analysis.loc[analysis.role.eq('parent'), ['child_id', 'submission_id', 'wave']].copy()
    _need(parents.child_id.map(_identifier).all() and parents.submission_id.map(_identifier).all() and
          parents.wave.isin(['T0', 'T1']).all(), 'invalid_selected_parent_slot')
    _need(not parents.duplicated(['child_id', 'wave']).any() and
          not parents.submission_id.duplicated().any(), 'duplicate_selected_parent_slot')
    t0 = parents.loc[parents.wave.eq('T0'), ['child_id', 'submission_id']].rename(columns={'submission_id': 't0'})
    t1 = parents.loc[parents.wave.eq('T1'), ['child_id', 'submission_id']].rename(columns={'submission_id': 't1'})
    pairs = t0.merge(t1, on='child_id', how='inner', validate='one_to_one')
    pairs = pairs.loc[~pairs.t0.isin(removed) & ~pairs.t1.isin(removed)].copy()
    pairs['adult_status'] = 'unconfirmed'
    pairs['adult_rule'] = ''
    if tracking is not None:
        required = {'child_id', 'parent_t0_id', 'parent_t1_id', 'adult_status', 'adult_rule'}
        _need(isinstance(tracking, pd.DataFrame) and required <= set(tracking.columns), 'tracking_fields_required')
        # Tracking can contain retired/unlinked rows with no established
        # child. They cannot support evidence for a selected child pair.
        linked = tracking.loc[tracking.child_id.notna()].copy()
        _need(linked.child_id.map(_identifier).all() and not linked.child_id.duplicated().any(),
              'invalid_tracking_child')
        by_child = linked.set_index('child_id', verify_integrity=True)
        for i, pair in pairs.iterrows():
            if pair.child_id not in by_child.index:
                continue
            evidence = by_child.loc[pair.child_id]
            if (not _identifier(evidence.parent_t0_id) or not _identifier(evidence.parent_t1_id) or
                    evidence.parent_t0_id != pair.t0 or evidence.parent_t1_id != pair.t1):
                continue
            status = evidence.adult_status
            _need(isinstance(status, str) and status in STATUSES, 'invalid_adult_status')
            rule = evidence.adult_rule
            if status == 'unconfirmed' and not isinstance(rule, str):
                rule = ''
            _need(isinstance(rule, str) and (status == 'unconfirmed' or bool(rule.strip())), 'invalid_adult_rule')
            pairs.at[i, 'adult_status'] = status
            pairs.at[i, 'adult_rule'] = rule
    return pairs.reindex(columns=PAIR_COLUMNS).sort_values('child_id').reset_index(drop=True)


def selected_parent_rows(analysis, pairs):
    """Return paired selected rows with explicit, pair-level adult evidence."""
    _need(isinstance(pairs, pd.DataFrame) and set(pairs.columns) == set(PAIR_COLUMNS), 'pair_fields_required')
    _need(not pairs.child_id.duplicated().any() and pairs.adult_status.isin(STATUSES).all(), 'invalid_pairs')
    _need(not {'bd_adult_status', 'bd_adult_rule', 'bd_pairing_policy', 'adult_continuity_confirmed'} & set(analysis.columns),
          'unexpected_existing_pair_metadata')
    parent = analysis.loc[analysis.role.eq('parent')].copy()
    _need(not parent.submission_id.duplicated().any(), 'duplicate_selected_parent_slot')
    ids = set(pairs.t0) | set(pairs.t1)
    selected = parent.loc[parent.submission_id.isin(ids)].copy()
    _need(len(selected) == 2 * len(pairs), 'pair_members_missing')
    metadata = pairs[['child_id', 'adult_status', 'adult_rule']].rename(
        columns={'adult_status': 'bd_adult_status', 'adult_rule': 'bd_adult_rule'})
    selected = selected.merge(metadata, on='child_id', how='left', validate='many_to_one')
    expected = {(r.child_id, 'T0', r.t0) for r in pairs.itertuples(index=False)} | {
                (r.child_id, 'T1', r.t1) for r in pairs.itertuples(index=False)}
    actual = set(zip(selected.child_id, selected.wave, selected.submission_id))
    _need(actual == expected, 'pair_slots_changed')
    selected['longitudinal'] = True
    selected['bd_pairing_policy'] = POLICY
    selected['adult_continuity_confirmed'] = selected.bd_adult_status.eq('same')
    return selected.sort_values(['child_id', 'wave']).reset_index(drop=True)


def selected_pairs_with_case_evidence(analysis, tracking, cases):
    """Use exact respondent cases when no matching tracking row exists.

    Some selected parent pairs have no registered student-parent dyad. A
    respondent case can still provide continuity evidence, but only for the
    exact selected submissions and only if the available cases agree.
    """
    pairs = selected_parent_pairs(analysis, tracking=tracking)
    linked = tracking.loc[tracking.child_id.notna()].set_index('child_id')
    by_pair = {}
    for case in cases:
        if case.get('kind') != 'respondent':
            continue
        a, b = case.get('record_a'), case.get('record_b')
        if not _identifier(a) or not _identifier(b) or a == b:
            continue
        rule, status = case.get('rule'), case.get('status')
        if not isinstance(rule, str) or status not in {'confirmed', 'pending', 'rejected', 'unmatched'}:
            continue
        adult = ('same' if status == 'confirmed' else 'different'
                 if rule in {'reviewer_rejected_same_adult', 'reported_relationship_changed'} else 'unconfirmed')
        if adult != 'unconfirmed' and not rule.strip():
            continue
        by_pair.setdefault(frozenset((a, b)), set()).add((adult, rule))
    for i, pair in pairs.iterrows():
        if pair.child_id in linked.index:
            row = linked.loc[pair.child_id]
            if (_identifier(row.parent_t0_id) and _identifier(row.parent_t1_id) and
                    row.parent_t0_id == pair.t0 and row.parent_t1_id == pair.t1):
                continue
        evidence = by_pair.get(frozenset((pair.t0, pair.t1)), set())
        if len(evidence) == 1:
            pairs.at[i, 'adult_status'], pairs.at[i, 'adult_rule'] = next(iter(evidence))
    return pairs


def project_published_selection(analysis, tracking, summary):
    """Project a legacy release into a same-child BD view without changing it.

    Only fixed, published selected slots may be used. The caller is responsible
    for authenticating and pinning all inputs and labelling this as a derived
    projection rather than a new analytical run.
    """
    _need(isinstance(summary, dict) and summary.get('bd_pairing_policy') is None and
          summary.get('bd_requires_same_adult') is True, 'legacy_source_policy_required')
    _need('longitudinal' in analysis.columns, 'published_membership_required')
    pairs = selected_parent_pairs(analysis, tracking=tracking)
    frame = analysis.copy(deep=True)
    paired_ids = set(pairs.t0) | set(pairs.t1)
    parent_mask = frame.role.eq('parent')
    frame.loc[parent_mask, 'longitudinal'] = frame.loc[parent_mask, 'submission_id'].isin(paired_ids)
    parents = selected_parent_rows(frame, pairs)
    projected = deepcopy(summary)
    projected.update(bd_pairing_policy=POLICY, bd_requires_same_adult=False,
                     BD=len(pairs), parent_child_longitudinal=len(pairs), BD_alternative_followups=0,
                     BD_general_contact_fallback=int(pairs.adult_rule.eq('same_adult_reported_birth_relationship_general_contact_fallback').sum()),
                     BD_any_exact_contact=int(pairs.adult_rule.eq('same_adult_reported_birth_any_exact_contact').sum()))
    # A legacy interval aggregate refers to the old same-adult sample.
    projected.pop('BD_parent_interval_under_90_days', None)
    return frame, parents, projected
