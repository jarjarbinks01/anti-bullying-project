"""Pure extension for an already-validated candidate proposal preview.

The caller must first use the existing preview loader and proposal revision
validator.  This function does not load files, inspect stores, change flags,
approve a policy, or combine burst holds with identity or intent holds.
"""

from collections import Counter
import re

from study2.analysis_eligibility import sha


REASONS = {
    'unestablished_child_identity': 'Child identity is not established',
    'source_evidence_revision_invalid_or_missing': 'Source evidence is missing or invalid',
    'source_proof_shape_or_membership': 'A member lacks the required source proof',
    'source_proof_version_drift': 'A source proof no longer matches the record',
    'source_record_raw_hash_invalid': 'A record does not match its raw-data hash',
    'source_cell_provenance_invalid': 'A source-cell reference is incomplete',
    'timestamp_not_proven_genuine_precise_submission': 'The source time is not sufficiently established',
    'timestamp_or_source_binding_invalid': 'The source time or source binding needs review',
}


def burst_hold_view(proposal, *, validated_revision):
    """Return scope-only rows for the existing pinned preview, with no I/O.

    ``validated_revision`` must be supplied by the upstream reviewed loader,
    after it verifies the complete proposal and its externally recorded hash.
    The return value is an advisory view, never an acceptance or disposition.
    """
    if (not isinstance(proposal, dict) or
            proposal.get('format') != 'study2_group_cleaning_proposal_v1' or
            not isinstance(validated_revision, str) or
            re.fullmatch(r'[0-9a-f]{64}', validated_revision) is None or
            proposal.get('revision') != validated_revision or
            sha({key: value for key, value in proposal.items() if key != 'revision'}) != validated_revision):
        raise ValueError('verified_proposal_required')
    holds = proposal.get('burst_holds')
    if not isinstance(holds, list):
        raise ValueError('burst_hold_inventory_unavailable')

    seen_scopes, member_versions, rows = set(), {}, []
    reasons_by_scope = Counter()
    for hold in holds:
        if not isinstance(hold, dict) or hold.get('outcome') != 'hold':
            raise ValueError('invalid_burst_hold')
        scope = hold.get('group_id')
        if not isinstance(scope, str) or not scope or scope in seen_scopes:
            raise ValueError('invalid_or_duplicate_burst_scope')
        seen_scopes.add(scope)
        pins, reasons = hold.get('member_pins'), hold.get('reasons')
        if not isinstance(pins, list) or not pins or not isinstance(reasons, list) or not reasons:
            raise ValueError('incomplete_burst_hold')
        if any(not isinstance(reason, str) or reason not in REASONS for reason in reasons):
            raise ValueError('unknown_burst_hold_reason')
        scope_members = set()
        for pin in pins:
            if (not isinstance(pin, dict) or set(pin) != {'submission_id', 'version_id'} or
                    not all(isinstance(pin[k], str) and pin[k] for k in ('submission_id', 'version_id'))):
                raise ValueError('invalid_burst_member_pin')
            subject, version = pin['submission_id'], pin['version_id']
            if subject in scope_members or (subject in member_versions and member_versions[subject] != version):
                raise ValueError('duplicate_or_conflicting_burst_member')
            scope_members.add(subject)
            member_versions[subject] = version
        codes = sorted(set(reasons))
        reasons_by_scope.update(codes)
        rows.append({'Scope': scope, 'Submission records': len(scope_members),
                     'Evidence needed': '; '.join(REASONS[code] for code in codes)})

    return {'scope_count': len(rows), 'distinct_submission_count': len(member_versions),
            'reason_scope_counts': dict(sorted(reasons_by_scope.items())),
            'rows': sorted(rows, key=lambda row: row['Scope']),
            'proposal_revision': validated_revision}
