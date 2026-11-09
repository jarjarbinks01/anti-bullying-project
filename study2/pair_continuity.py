"""Synthetic-only proof of historical pairwise policy continuity.

Pure functions: no I/O, policy activation, approvals, or scientific decisions.
The caller must obtain and protect trusted anchors independently. The native
operator does not invoke this proof; see README before considering integration.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
from copy import deepcopy
from datetime import datetime

from study2.analysis_eligibility import inventory_revision, sha, validate_manifest
from study2.common import digest, timestamp
from study2.group_cleaning import PROPOSAL_FORMAT, classify_scope, validate_proposal


class ContinuityError(ValueError):
    """Only non-identifying error codes escape the proof."""


def need(condition, code):
    if not condition:
        raise ContinuityError(code)


def _bytes_sha(data):
    need(isinstance(data, bytes), 'expected_pinned_bytes')
    return hashlib.sha256(data).hexdigest()


def _json(data):
    try:
        return json.loads(data)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContinuityError('invalid_pinned_json') from exc


def full_pin(record):
    return {k: record[k] for k in ('submission_id', 'version_id', 'role', 'raw_hash')}


def _content_pin(record):
    need(isinstance(record.get('raw'), dict) and digest(record['raw']) == record['raw_hash'] and
         digest([record['submission_id'], record['raw_hash']]) == record['version_id'],
         'record_content_pin_mismatch')


def scope_fingerprint(release_id, records, group, cases):
    """Bind the native classification, complete group, cases, and full pins."""
    ids = group['group_review']['members']
    result = classify_scope(records, group, cases)
    snapshot = {
        'release_id': release_id,
        'inventory_revision': inventory_revision(records.values()),
        'group': group,
        'members': sorted((full_pin(records[s]) for s in ids), key=lambda p: p['submission_id']),
        'cases': [cases[c] for c in sorted(set(group['group_review']['comparison_ids']))],
        'classification_binding': result['binding'],
    }
    return sha(snapshot)


def _history(history, trusted):
    """Verify the original bundle and the already-accepted generation by hash."""
    need(_bytes_sha(history['bundle']) == trusted['historical_bundle_sha256'], 'historical_bundle_changed')
    bundle = _json(history['bundle'])
    need(bundle.get('format') == 'study2_group_cleaning_inputs_v1' and
         bundle.get('revision') == sha({k: v for k, v in bundle.items() if k != 'revision'}),
         'historical_bundle_revision')
    for name in ('authorization', 'partitions', 'groups', 'records'):
        need(_bytes_sha(history['files'][name]) == bundle['files'][name]['sha256'],
             'historical_input_changed')
    auth = _json(history['files']['authorization'])
    partitions = _json(history['files']['partitions'])
    groups = _json(history['files']['groups'])
    need(set(auth) == {'workbook_sha256', 'request_sha256', 'partition_groups', 'user_exclusion_groups'} and
         all(re.fullmatch('[0-9a-f]{64}', str(auth.get(k))) is not None for k in ('workbook_sha256', 'request_sha256')),
         'historical_authorization_invalid')
    gid = trusted['historical_group_id']
    need(gid in auth['partition_groups'] and gid in partitions and gid in groups,
         'historical_scope_not_authorized')
    need(len(partitions) == 8 and set(auth['partition_groups']) == set(partitions) and
         len(auth['partition_groups']) == len(set(auth['partition_groups'])),
         'historical_partition_inventory_changed')
    blocks = partitions[gid]
    need(isinstance(blocks, list) and len(blocks) == 2 and
         all(isinstance(x, list) and len(x) == 1 for x in blocks),
         'historical_decision_not_two_singletons')
    original = {b[0] for b in blocks}
    need(len(original) == 2, 'historical_group_membership_changed')
    historical_members = set()
    for group_id, group_blocks in partitions.items():
        need(group_id in groups and isinstance(group_blocks, list) and group_blocks and
             all(isinstance(block, list) and block for block in group_blocks), 'historical_partition_shape')
        members = [member for block in group_blocks for member in block]
        need(len(members) == len(set(members)) and set(groups[group_id]['group_review']['members']) == set(members) and
             group_id == 'GROUP_' + digest(['child_review_v1', sorted(members)])[:28],
             'historical_group_membership_changed')
        historical_members.update(members)
    old_records = {}
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(history['files']['records'])) as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    if row.get('submission_id') in historical_members:
                        need(row['submission_id'] not in old_records, 'historical_duplicate_member')
                        old_records[row['submission_id']] = row
    except (OSError, ValueError, UnicodeError) as exc:
        raise ContinuityError('historical_records_invalid') from exc
    need(set(old_records) == historical_members and all(old_records[s].get('role') == 'student' for s in original),
         'historical_members_not_students')
    for row in old_records.values():
        need(row.get('role') in {'student', 'parent'} and isinstance(row.get('raw'), dict) and
             digest(row['raw']) == row['raw_hash'] and
             digest([row['submission_id'], row['raw_hash']]) == row['version_id'],
             'historical_record_pin_invalid')

    need(_bytes_sha(history['manifest']) == trusted['historical_policy_head_sha256'],
         'historical_policy_head_changed')
    manifest = _json(history['manifest'])
    need(manifest.get('format') == 'study2_group_cleaning_generation_v1', 'historical_generation_format')
    for name in ('proposal.json', 'policy.json', 'receipt.json'):
        need(_bytes_sha(history['generation'][name]) == manifest['files'][name],
             'historical_generation_changed')
    proposal = _json(history['generation']['proposal.json'])
    policy = _json(history['generation']['policy.json'])
    receipt = _json(history['generation']['receipt.json'])
    review = receipt.get('review', {})
    need(proposal.get('format') == PROPOSAL_FORMAT and
         proposal.get('revision') == sha({k: v for k, v in proposal.items() if k != 'revision'}) and
         proposal.get('authorization') == auth and proposal.get('partitions') == partitions and
         policy.get('format') == 'study2_group_policy_control_v1' and
         policy.get('policy_active') is True and policy.get('partitions') == partitions and
         policy.get('proposal_revision') == proposal['revision'] and
         proposal.get('base', {}).get('release_id') == bundle.get('release_id') == policy.get('release_id') == receipt.get('release_id') and
         set(review) == {'format', 'proposal_revision', 'accepted', 'reviewer', 'reason', 'review_manifest_sha256'} and
         review.get('format') == 'study2_group_cleaning_acceptance_v1' and review.get('accepted') is True and
         review.get('proposal_revision') == proposal['revision'] and
         all(isinstance(review.get(x), str) and review[x].strip() for x in ('reviewer', 'reason')) and
         re.fullmatch('[0-9a-f]{64}', str(review.get('review_manifest_sha256'))) is not None,
         'historical_acceptance_binding_invalid')
    return bundle, auth, partitions, proposal, old_records, original


def _lineage(history_records, current, transition_export, prior_run_manifest, trusted):
    need(_bytes_sha(transition_export) == trusted['transition_export_sha256'], 'source_time_lineage_changed')
    need(_bytes_sha(prior_run_manifest) == trusted['prior_run_manifest_sha256'], 'prior_run_manifest_changed')
    export = _json(transition_export)
    manifest = _json(prior_run_manifest)
    need(export.get('format') == 'verified_source_time_export_v1' and
         export.get('prior_release_id') == trusted['prior_release_id'], 'source_time_export_unbound')
    sources = manifest.get('inputs', {}).get('sources', [])
    source_hash = {r['source_id']: r['sha256'] for r in sources}
    need(len(source_hash) == len(sources) and all(isinstance(k, str) and k and
         re.fullmatch('[0-9a-f]{64}', str(v)) is not None for k, v in source_hash.items()),
         'prior_source_manifest_ambiguous')
    need(set(history_records) <= set(current), 'historical_partition_member_missing')
    for sid in history_records:
        _content_pin(current[sid])
    changed = {sid for sid, row in history_records.items() if full_pin(row) != full_pin(current[sid])}
    rows = export.get('rows')
    need(isinstance(rows, list) and len(rows) == len(changed) and
         {r.get('submission_id') for r in rows} == changed and
         all(type(r.get('sequence')) is int and r['sequence'] > 0 for r in rows) and
         len({r.get('sequence') for r in rows}) == len(rows), 'source_time_transition_count')
    for t in rows:
        sid = t['submission_id']
        old, new = history_records[sid], current[sid]
        need(old.get('role') == new.get('role') and old.get('role') in {'student', 'parent'} and
             old.get('source_id') and old.get('source_id') == new.get('source_id') == t.get('source_id') and
             t['source_id'] in source_hash and source_hash[t['source_id']] == t.get('input_sha256'),
             'source_time_origin_mismatch')
        need(isinstance(new.get('raw'), dict) and digest(new['raw']) == new['raw_hash'] and
             digest([sid, new['raw_hash']]) == new['version_id'] and
             t.get('old_version') == old['version_id'] and t.get('new_version') == new['version_id'] and
             t.get('old_raw_hash') == old['raw_hash'] and t.get('new_raw_hash') == new['raw_hash'] and
             old['raw_hash'] != new['raw_hash'], 'source_time_pin_mismatch')
        old_raw, new_raw = old['raw'], new['raw']
        need({k: v for k, v in old_raw.items() if k != '建立時間'} ==
             {k: v for k, v in new_raw.items() if k != '建立時間'}, 'source_time_non_time_change')
        old_time, new_time = timestamp(old_raw.get('建立時間')), timestamp(new_raw.get('建立時間'))
        need(old_time is not None and new_time is not None and old_time != new_time and
             timestamp(t.get('old_observed_at')) == old_time and timestamp(t.get('new_observed_at')) == new_time,
             'source_time_value_mismatch')
        need(all(isinstance(t.get(k), str) and t[k].strip() for k in
                 ('operation_id', 'authorizer', 'reason', 'approved_at')) and
             type(t.get('slot')) is int and t['slot'] >= 0, 'source_time_approval_evidence_missing')
        try:
            when = datetime.fromisoformat(t['approved_at'].replace('Z', '+00:00'))
            need(when.tzinfo is not None, 'source_time_approval_date_invalid')
        except ValueError as exc:
            raise ContinuityError('source_time_approval_date_invalid') from exc


def _verify_scope(records, group, cases, original):
    ids = group['group_review']['members']
    need(len(ids) == 3 and len(set(ids)) == 3 and original < set(ids) and
         group['case_id'] == 'GROUP_' + digest(['child_review_v1', sorted(ids)])[:28],
         'scope_membership_changed')
    parent = next(iter(set(ids) - original))
    need(records[parent].get('role') == 'parent' and all(records[s].get('role') == 'student' for s in original),
         'scope_roles_changed')
    for sid in ids:
        _content_pin(records[sid])
    scope = classify_scope(records, group, cases)
    atoms = [set(a) for a in scope['protected_atoms']]
    need(len(atoms) == 2 and sorted(map(len, atoms)) == [1, 2] and
         len({next(i for i, a in enumerate(atoms) if s in a) for s in original}) == 2,
         'historical_students_not_separate')
    joined = next((s for s in original if any({s, parent} <= a for a in atoms)), None)
    need(joined is not None and records[joined].get('child_id') and
         records[joined].get('child_id') == records[parent].get('child_id'), 'existing_parent_atom_missing')
    edges = group['group_review'].get('passed_pairs', [])
    need(any({p.get('a'), p.get('b')} == {joined, parent} and
             p.get('rule') == 'exact_school_contact_child_demo' for p in edges), 'existing_direct_edge_missing')
    need(scope['partition'] is None and len(scope['closures']) == 1 and
         not scope['holds'] and not scope['questions'] and
         scope['closures'][0]['reasons'] == ['known_nonblank_contacts_without_phone_similarity_user_policy'] and
         scope['closures'][0]['scientific_identity_changed'] is False and
         scope['closures'][0]['permanent_nonmatch'] is False, 'generic_continuity_projection_changed')
    return parent, joined, scope


def build_continuity(*, history, trusted, transition_export, prior_run_manifest,
                     prior_records, prior_cases, prior_group, prior_manual_manifest, prior_policy_manifest,
                     records, cases, groups, decisions, proposal, options):
    """Return a private evidence envelope, or fail before an operator may proceed.

    All trust anchors are inputs from independent verification. No anchor, review,
    acceptance, policy, flag, registry, or release is created by this function.
    """
    try:
        return _build(history=history, trusted=trusted, transition_export=transition_export,
            prior_run_manifest=prior_run_manifest, prior_records=prior_records, prior_cases=prior_cases,
            prior_group=prior_group, prior_manual_manifest=prior_manual_manifest,
            prior_policy_manifest=prior_policy_manifest, records=records, cases=cases, groups=groups,
            decisions=decisions, proposal=proposal, options=options)
    except ContinuityError:
        raise
    except Exception as exc:
        raise ContinuityError('invalid_or_unavailable_evidence') from exc


def _build(*, history, trusted, transition_export, prior_run_manifest,
           prior_records, prior_cases, prior_group, prior_manual_manifest, prior_policy_manifest,
           records, cases, groups, decisions, proposal, options):
    bundle, auth, historical_parts, historical_proposal, old_records, original = _history(history, trusted)
    target_release = trusted['target_release_id']
    need(options.get('release_id') == target_release and proposal.get('base', {}).get('release_id') == target_release,
         'target_release_changed')
    try:
        validate_proposal(proposal, records, cases, groups, decisions, **options)
    except Exception as exc:
        raise ContinuityError('native_proposal_invalid') from exc
    _lineage(old_records, records, transition_export, prior_run_manifest, trusted)
    need(all(s in prior_records and full_pin(prior_records[s]) == full_pin(records[s])
             for s in old_records), 'prior_partition_pins_changed')
    for sid in old_records:
        _content_pin(prior_records[sid])

    prior_release = trusted['prior_release_id']
    need(prior_manual_manifest.get('revision') == trusted['prior_manual_revision'] and
         prior_policy_manifest.get('revision') == trusted['prior_policy_revision'], 'prior_exclusion_head_changed')
    old_manual = validate_manifest(prior_manual_manifest, list(prior_records.values()), prior_release)
    old_policy = validate_manifest(prior_policy_manifest, list(prior_records.values()), prior_release)
    new_manual = validate_manifest(options['eric_manifest'], list(records.values()), target_release)
    new_policy = validate_manifest(options['prior_policy_manifest'], list(records.values()), target_release)
    need(old_manual == new_manual and old_policy == new_policy and
         all(full_pin(prior_records[s]) == full_pin(records[s]) for s in old_manual | old_policy),
         'prior_exclusion_pins_changed')
    for sid in old_manual | old_policy:
        _content_pin(prior_records[sid])
        _content_pin(records[sid])
    expected_flags = {tuple(sorted({'submission_id': s, 'version_id': records[s]['version_id']}.items())) for s in old_policy}
    actual_flags = {tuple(sorted(p.items())) for p in proposal['flag_entries']}
    need(actual_flags == expected_flags and len(actual_flags) == len(proposal['flag_entries']), 'new_policy_exclusions')

    old_gid = trusted['historical_group_id']
    retained = {k: v for k, v in historical_parts.items() if k != old_gid}
    need(len(retained) == 7 and proposal['partitions'] == retained, 'retained_partitions_changed')
    target_gid = trusted['target_group_id']
    target_auth = proposal['authorization']
    need(target_gid not in proposal['partitions'] and
         set(target_auth['partition_groups']) == set(retained) and
         len(target_auth['partition_groups']) == 7 and
         set(target_auth['user_exclusion_groups']) == set(auth['user_exclusion_groups']) and
         len(target_auth['user_exclusion_groups']) == len(auth['user_exclusion_groups']) and
         all(target_auth[k] == auth[k] for k in ('workbook_sha256', 'request_sha256')) and
         proposal['user_directed_flags'] == historical_proposal['user_directed_flags'],
         'historical_authorization_scope_changed')
    need(target_gid in groups and prior_group['case_id'] == target_gid, 'target_group_missing')
    target_group = groups[target_gid]
    parent, joined, target_scope = _verify_scope(records, target_group, cases, original)
    old_parent, old_joined, old_scope = _verify_scope(prior_records, prior_group, prior_cases, original)
    need((parent, joined) == (old_parent, old_joined) and
         all(full_pin(prior_records[s]) == full_pin(records[s]) and
             prior_records[s].get('child_id') == records[s].get('child_id')
             for s in original | {parent}), 'prior_atom_correspondence_changed')
    need(not (original | {parent}) & (new_manual | new_policy), 'scope_member_excluded')
    need(proposal['projection']['scopes'].get(target_gid) == target_scope and
         proposal['group_bindings'].get(target_gid) == target_scope['binding'], 'proposal_scope_projection_changed')
    need(not any(parent in block for blocks in proposal['partitions'].values() for block in blocks),
         'parent_in_new_user_partition')
    need(scope_fingerprint(prior_release, prior_records, prior_group, prior_cases) == trusted['prior_scope_sha256'] and
         scope_fingerprint(target_release, records, target_group, cases) == trusted['target_scope_sha256'],
         'reviewed_scope_binding_changed')

    envelope = {
        'format': 'study2_two_student_continuity_evidence_v1',
        'status': 'evidence_only_not_approval',
        'historical_authorization': {
            'bundle_sha256': trusted['historical_bundle_sha256'],
            'authorization_sha256': bundle['files']['authorization']['sha256'],
            'partitions_sha256': bundle['files']['partitions']['sha256'],
            'policy_head_sha256': trusted['historical_policy_head_sha256'],
            'workbook_sha256': auth['workbook_sha256'], 'request_sha256': auth['request_sha256'],
            'group_id': old_gid,
            'authorized_student_pins': sorted((full_pin(old_records[s]) for s in original), key=lambda x: x['submission_id']),
            'decision': 'keep_original_students_in_separate_existing_atoms',
        },
        'source_time_export_sha256': trusted['transition_export_sha256'],
        'prior_run_manifest_sha256': trusted['prior_run_manifest_sha256'],
        'prior_scope_sha256': trusted['prior_scope_sha256'],
        'target': {
            'release_id': target_release, 'inventory_revision': proposal['base']['inventory_revision'],
            'proposal_revision': proposal['revision'], 'group_id': target_gid,
            'scope_binding': target_scope['binding'], 'scope_sha256': trusted['target_scope_sha256'],
            'scope_member_pins': sorted((full_pin(records[s]) for s in original | {parent}), key=lambda x: x['submission_id']),
            'scope_member_records_sha256': sha({s: records[s] for s in sorted(original | {parent})}),
            'existing_parent_atom': {'student': joined, 'parent': parent, 'rule': 'exact_school_contact_child_demo'},
        },
        'scientific_identity_changed': False, 'permanent_nonmatch': False,
    }
    envelope['revision'] = sha(envelope)
    return envelope


def verify_continuity(envelope, **context):
    """Recompute proof against live inputs; equality rejects stale evidence."""
    need(envelope == build_continuity(**context), 'continuity_envelope_stale')
    return True
