"""Read-only presentation of an explicitly supplied, exactly bound summary.

Supplied administrative closures are checked against read-only review state.
This module never changes scientific decisions or manufactures missing counts.
"""
import json
import os
from pathlib import Path
import re

ENVIRONMENT_KEY = 'STUDY2_CURRENT_REVIEW_WORKLOAD'
FORMAT = 'study2_current_review_workload_v1'


class WorkloadUnavailable(ValueError):
    """No verified workload can be displayed for the selected state."""


def _count(value):
    if type(value) is not int or value < 0:
        raise WorkloadUnavailable('invalid_count')
    return value


def _native_counts(value, prefix=''):
    if not isinstance(value, dict) or not value:
        raise WorkloadUnavailable('native_workload_counts_required')
    rows = []
    for key, count in value.items():
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', key):
            raise WorkloadUnavailable('invalid_native_count_name')
        label = prefix + key.replace('_', ' ').capitalize()
        if isinstance(count, dict):
            rows.extend(_native_counts(count, label + ' / '))
        else:
            rows.append({'Active review category': label, 'Count': _count(count)})
    return rows


def validate_summary(value, *, release_id, decision_revision, exclusion_revision=None):
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        raise WorkloadUnavailable('summary_format_required')
    if not isinstance(release_id, str) or not release_id or value.get('release_id') != release_id:
        raise WorkloadUnavailable('release_binding_mismatch')
    if not isinstance(decision_revision, str) or not decision_revision or value.get('decision_revision') != decision_revision:
        raise WorkloadUnavailable('decision_binding_mismatch')
    if 'exclusion_manifest_revision' not in value:
        raise WorkloadUnavailable('exclusion_binding_required')
    exclusion = value['exclusion_manifest_revision']
    if exclusion is not None and (not isinstance(exclusion, str) or not exclusion):
        raise WorkloadUnavailable('invalid_exclusion_revision')
    if exclusion != exclusion_revision:
        raise WorkloadUnavailable('exclusion_binding_mismatch')
    native_rows = _native_counts(value.get('native_workload'))
    for field in ('correction_bundles', 'source_groups_resolved', 'accepted_historical_policy_closures'):
        if field not in value:
            raise WorkloadUnavailable('required_count_missing')
        _count(value[field])
    answers = value.get('original_answers')
    if not isinstance(answers, dict) or set(answers) != {'total', 'same_child', 'different_children'}:
        raise WorkloadUnavailable('original_answer_counts_required')
    for count in answers.values():
        _count(count)
    if answers['same_child'] + answers['different_children'] != answers['total']:
        raise WorkloadUnavailable('original_answer_counts_mismatch')
    if value.get('administrative_disposition') is not None:
        if not isinstance(value['administrative_disposition'], dict):
            raise WorkloadUnavailable('invalid_administrative_block')
        _count(value.get('field_decisions_in_this_followup'))
    return native_rows


def load_summary(*, release_id, decision_revision, exclusion_revision=None, path=None, review_state=None,cfg=None,inventory=None,historical_read=False):
    state_value = review_state if review_state is not None else os.environ.get('STUDY2_REVIEW_STATE_DIR')
    if state_value is not None:
        from .coordinated_update import require_available
        require_available(state_value)
    # No discovery or fallback to queue_snapshot. Read afresh on each rerun.
    supplied = path if path is not None else os.environ.get(ENVIRONMENT_KEY)
    if not supplied:
        raise WorkloadUnavailable('summary_not_supplied')
    try:
        raw = Path(supplied).read_bytes()
        value = json.loads(raw)
        if historical_read:
            from .compatibility_profiles import administrative_read_contract
            import hashlib
            trust = administrative_read_contract()
            if trust is None or hashlib.sha256(raw).hexdigest() != trust['workload_pin']['sha256']:
                raise ValueError('historical_workload_changed')
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise WorkloadUnavailable('summary_unreadable') from None
    try:
        rows = validate_summary(value, release_id=release_id,
            decision_revision=decision_revision, exclusion_revision=exclusion_revision)
        rows = _verify_admin_projection(value, rows, release_id, decision_revision, review_state=review_state,cfg=cfg,inventory=inventory,historical_read=historical_read)
    except (RecursionError, KeyError, TypeError, ValueError):
        raise WorkloadUnavailable('summary_invalid') from None
    return value, rows


def render_current_review_workload(st, *, release_id, decision_revision, exclusion_revision=None,cfg=None):
    st.subheader('Current review workload')
    try:
        value, rows = load_summary(release_id=release_id,
            decision_revision=decision_revision, exclusion_revision=exclusion_revision,cfg=cfg)
    except WorkloadUnavailable:
        st.warning('Current review workload is unavailable. A verified summary matching this release, '
                   'decision revision, exclusion revision and administrative revision is required. Missing or stale counts are not zero.')
        return False
    st.caption('Verified summary for the selected release and decision state, after accepted group and exclusion policy. '
               'Categories use different units; do not add them together.')
    st.dataframe(rows, hide_index=True, width='stretch')
    columns = st.columns(4)
    columns[0].metric('Correction bundles', f"{value['correction_bundles']:,}")
    columns[1].metric('Earlier child groups resolved', f"{value['source_groups_resolved']:,}")
    columns[2].metric('Earlier child-review answers', f"{value['original_answers']['total']:,}")
    columns[3].metric('Accepted earlier policy closures', f"{value['accepted_historical_policy_closures']:,}")
    st.caption(f"Original answers: {value['original_answers']['same_child']:,} Same child; "
               f"{value['original_answers']['different_children']:,} Different children. "
               'Resolved groups, recorded answers and earlier closures are completed work, not pending actions.')
    st.caption(f"Release: {release_id} | Decision revision: {decision_revision} | "
               f"Exclusion revision: {exclusion_revision if exclusion_revision is not None else 'none (no accepted manifest supplied)'}")
    block = value.get('administrative_disposition')
    if block is not None:
        projection = block['projection']
        st.caption(f"Field corrections applied: {value['field_decisions_in_this_followup']:,}. "
                   f"Closed unresolvable: {projection['projected_closed_questions']:,} questions across "
                   f"{projection['closed_unresolvable_comparisons']:,} comparisons. "
                   f"Raw correction inventory: {projection['raw_correction_comparisons']:,}; "
                   f"active correction comparisons: {projection['active_correction_comparisons']:,}. "
                   'Unresolvable closure changes work assignment, not missing values, identity or analysis eligibility.')
        st.caption(f"Administrative revision: {block['admin_revision']}")
        if block.get('carry_forward'):
            from .administrative_carry_current import HOLD_REASONS
            st.caption(f"Carried from original closure records: {projection['closed_unresolvable_comparisons']:,} comparisons. "
                       f"Separate administrative holds: {projection['held_comparisons']:,}, including "
                       f"{projection['source_only_hold_comparisons']:,} source-only comparisons outside the raw target inventory. "
                       'Original events are unchanged.')
            if block['carry_forward']['holds']:
                st.dataframe([{'Hold':f'Hold {i}','Reason':'; '.join(HOLD_REASONS.get(r,'Source evidence needs review.') for r in row['reasons'])}
                              for i,row in enumerate(block['carry_forward']['holds'],1)],hide_index=True,width='stretch')
    return True


def _verify_admin_projection(value, rows, release_id, decision_revision, *, review_state=None,cfg=None,inventory=None,historical_read=False):
    import sqlite3
    block = value.get('administrative_disposition')
    if block is None:
        return rows
    try:
        from .review_dispositions import administrative_revision, project_closures, DispositionError
        state = Path(review_state if review_state is not None else os.environ['STUDY2_REVIEW_STATE_DIR'])
        bindings = block['bindings']
        if bindings['release_id'] != release_id or bindings['decision_revision'] != decision_revision:
            raise WorkloadUnavailable('administrative_state_binding_mismatch')
        work = sqlite3.connect((state / 'review.sqlite').as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            work.execute('PRAGMA query_only=ON')
            if block.get('carry_forward'):
                from .administrative_carry_current import validate_workload
                if not isinstance(cfg,dict) or Path(cfg['state_dir']).resolve()!=state.resolve():
                    raise WorkloadUnavailable('current_carry_configuration_required')
                actual=validate_workload(cfg,work,block,inventory=inventory,historical_read=historical_read)
            else:actual = project_closures(work, bindings, block['case_inventory'])
            if (not actual['projection_ready'] or actual != block['projection'] or
                    administrative_revision(work) != block['admin_revision']):
                raise WorkloadUnavailable('administrative_revision_mismatch')
        finally:
            work.close()
        if (actual['raw_correction_comparisons'] != value['native_workload']['field_correction_comparisons'] or
                actual['active_correction_comparisons'] != value['active_workload']['field_correction_comparisons']):
            raise WorkloadUnavailable('administrative_count_mismatch')
        ignored={'field_correction_comparisons'}
        if block.get('carry_forward'):
            if value['active_workload'].get('administrative_carry_holds')!=actual['held_comparisons']:
                raise WorkloadUnavailable('administrative_hold_count_mismatch')
            ignored.add('administrative_carry_holds')
        if ({k: v for k, v in value['native_workload'].items() if k not in ignored} !=
                {k: v for k, v in value['active_workload'].items() if k not in ignored}):
            raise WorkloadUnavailable('unrelated_workload_changed')
        return _native_counts(value['active_workload'])
    except WorkloadUnavailable:
        raise
    except (KeyError, OSError, ValueError, TypeError, ImportError, sqlite3.Error):
        raise WorkloadUnavailable('administrative_projection_unavailable') from None
