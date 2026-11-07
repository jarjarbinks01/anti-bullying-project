"""Release-pinned enforcement of one historical pairwise policy constraint.

No publication, approval, I/O, or pointer mutation is performed by this module.  Trust anchors are independently reviewed
inputs; payloads are private and do not grant any new user decision.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from pathlib import Path

from .analysis_eligibility import sha
from .group_cleaning import implementation_revision, make_proposal, need
from .manual_flags import _read_pinned
from .pair_continuity import ContinuityError, build_continuity

from .compatibility_profiles import CONTINUITY_PROFILES as PROFILES, accepts_historical_implementation
PAYLOAD_FORMAT = 'study2_pair_continuity_private_inputs_v1'
BOUND_FORMAT = 'study2_reviewed_pair_continuity_binding_v1'


def _decode(value):
    try:
        need(isinstance(value, str), 'continuity_input_not_base64')
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError('continuity_input_not_base64') from exc


def _payload(payload):
    required = {'format', 'history', 'transition_export', 'prior_run_manifest',
                'prior_records', 'prior_cases', 'prior_group', 'prior_manual_manifest', 'prior_policy_manifest'}
    need(isinstance(payload, dict) and set(payload) == required and payload['format'] == PAYLOAD_FORMAT,
         'continuity_input_shape')
    history = payload['history']
    need(isinstance(history, dict) and set(history) == {'bundle', 'files', 'manifest', 'generation'} and
         set(history['files']) == {'authorization', 'partitions', 'groups', 'records'} and
         set(history['generation']) == {'proposal.json', 'policy.json', 'receipt.json'}, 'continuity_history_shape')
    decoded = {'bundle': _decode(history['bundle']), 'manifest': _decode(history['manifest']),
               'files': {k: _decode(v) for k, v in history['files'].items()},
               'generation': {k: _decode(v) for k, v in history['generation'].items()}}
    return decoded


def bound_proposal(data, options):
    """Recompute native proposal plus mandatory exact-target continuity."""
    base = make_proposal(data['records'], data['cases'], data['groups'], data['decisions'], **options)
    profile = PROFILES.get(options['release_id'])
    if profile is None:
        need('continuity' not in data, 'continuity_release_not_reviewed')
        return base
    need('continuity' in data, 'continuity_evidence_required')
    payload = data['continuity']
    history = _payload(payload)
    need(base['base']['inventory_revision'] == profile['target_inventory_revision'], 'continuity_target_inventory_changed')
    try:
        proof = build_continuity(history=history, trusted=profile,
            transition_export=_decode(payload['transition_export']), prior_run_manifest=_decode(payload['prior_run_manifest']),
            prior_records=payload['prior_records'], prior_cases=payload['prior_cases'], prior_group=payload['prior_group'],
            prior_manual_manifest=payload['prior_manual_manifest'], prior_policy_manifest=payload['prior_policy_manifest'],
            records=data['records'], cases=data['cases'], groups=data['groups'], decisions=data['decisions'],
            proposal=base, options=options)
    except ContinuityError as exc:
        raise ValueError('continuity_evidence_invalid:' + str(exc)) from exc
    _check_intent_continuity(base,proof,profile)
    binding = {'format': BOUND_FORMAT, 'profile_revision': sha(profile), 'proof': proof}
    if 'decision_intents' in base:
        binding['intent_lineage'] = _bind_intent_lineage(base, history, profile, proof, data['records'])
    binding['revision'] = sha(binding)
    result = copy.deepcopy(base)
    result['historical_continuity'] = binding
    result['revision'] = sha({k: v for k, v in result.items() if k != 'revision'})
    return result


def _bind_intent_lineage(proposal, history, profile, proof, records):
    """Describe existing proof coverage; never turn a held intent into a carry.

    The unchanged native verifier has already checked every changed historical
    partition member. Bind each intent's original subjects and boundary to that
    exact history, for both the special pair and retained groups. Comparison
    routing and held statuses remain the compiler's separate responsibility.
    """
    from .pair_continuity import _history, full_pin
    from .group_decision_intents import evidence
    _, _, _, original, old, _ = _history(history, profile)
    collection = proposal['decision_intents']
    expected_groups = set(original['partitions'])
    need(len(collection['intents']) == len(expected_groups) and
         {i['origin']['group_id'] for i in collection['intents']} == expected_groups,
         'intent_lineage_historical_scope_changed')
    entries = []
    receipt = json.loads(history['generation']['receipt.json'])
    for item in collection['intents']:
        gid = item['origin']['group_id']
        boundary = sorted(sorted(b) for b in original['partitions'][gid])
        subjects = sorted(s for b in boundary for s in b)
        old_pins = [full_pin(old[s]) for s in subjects]
        identity = {'kind':'preserve_existing_subgroups', 'boundary':boundary,
                    'authorization':original['authorization'], 'origin_group_id':gid}
        need(item['decision_id'] == 'GI_' + sha(identity) and
             item['kind'] == 'preserve_existing_subgroups' and item['boundary'] == boundary and
             item['subjects'] == old_pins and
             item['evidence'] == {s:evidence(old[s]) for s in subjects} and
             item['origin']['authorization'] == original['authorization'] and
             item['origin']['proposal_revision'] == original['revision'] and
             item['origin']['release_id'] == original['base']['release_id'] and
             item['origin']['receipt'] == receipt and
             item['reason'] == receipt.get('reason') and item['supersedes'] is None and
             item['scientific_identity_changed'] is False and item['permanent_nonmatch'] is False,
             'intent_lineage_historical_decision_changed')
        current = [full_pin(records[s]) for s in subjects]
        entries.append({'decision_id':item['decision_id'], 'intent_revision':item['revision'],
            'original_subject_pins':old_pins, 'current_subject_pins':current,
            'changed_subjects':sum(a != b for a,b in zip(old_pins,current)),
            'relevant_evidence_unchanged':all(evidence(records[s]) == item['evidence'][s] for s in subjects)})
    result = {'format':'study2_intent_lineage_evidence_v1',
        'intent_revision':collection['revision'],
        'application_revision':proposal['decision_application']['revision'],
        'proof_revision':proof['revision'], 'entries':entries, 'approval_granted':False}
    result['revision'] = sha(result)
    return result


def check_intent_lineage(proposal):
    """Check a stored evidence description without granting operational approval."""
    binding = proposal.get('historical_continuity') or {}
    lineage = binding.get('intent_lineage')
    collection = proposal.get('decision_intents')
    if collection is None:
        need(lineage is None, 'unexpected_intent_lineage')
        return {}
    need(isinstance(lineage,dict) and lineage.get('format') == 'study2_intent_lineage_evidence_v1' and
         lineage.get('revision') == sha({k:v for k,v in lineage.items() if k != 'revision'}) and
         lineage.get('intent_revision') == collection['revision'] and
         lineage.get('application_revision') == proposal['decision_application']['revision'] and
         lineage.get('proof_revision') == binding['proof']['revision'] and
         lineage.get('approval_granted') is False, 'intent_lineage_binding_changed')
    items = {i['decision_id']:i for i in collection['intents']}
    rows = lineage.get('entries',[])
    need(len(rows) == len(items) and {r['decision_id'] for r in rows} == set(items),
         'intent_lineage_scope_changed')
    for row in rows:
        item = items[row['decision_id']]
        old, current = row['original_subject_pins'], row['current_subject_pins']
        need(row['intent_revision'] == item['revision'] and old == item['subjects'] and
             len(current) == len(old) and all(set(p) == set(old[0]) and
                 all(isinstance(v,str) and v for v in p.values()) for p in current) and
             [(p['submission_id'],p['role']) for p in old] ==
             [(p['submission_id'],p['role']) for p in current] and
             type(row['changed_subjects']) is int and
             row['changed_subjects'] == sum(a != b for a,b in zip(old,current)) and
             type(row['relevant_evidence_unchanged']) is bool, 'intent_lineage_subjects_changed')
    return {r['decision_id']:r for r in rows}


def check_intent_inventory(proposal, records):
    for row in check_intent_lineage(proposal).values():
        need(all(p['submission_id'] in records and
             {k:records[p['submission_id']].get(k) for k in ('submission_id','version_id','role','raw_hash')} == p
             for p in row['current_subject_pins']), 'intent_lineage_inventory_changed')


def _check_intent_continuity(proposal,proof,profile):
    """A deferred intent must be the original two-student approval in this proof.

    No parent edge is routed and no historical verifier condition is removed.
    The native proof's target proposal revision also binds this exact collection
    and application. Raw/unbound proposals cannot activate through validate_bound.
    """
    application=proposal.get('decision_application') or {}
    entries=[e for e in application.get('entries',[])
             if e['status']=='requires_existing_continuity_proof']
    if not entries:return
    auth=proof.get('historical_authorization') or {}
    expected=sorted(auth.get('authorized_student_pins',[]),key=lambda p:p['submission_id'])
    items={x['decision_id']:x for x in proposal['decision_intents']['intents']}
    for entry in entries:
        item=items[entry['decision_id']]
        need(len(expected)==2 and all(p['role']=='student' for p in expected) and
             sorted(item['subjects'],key=lambda p:p['submission_id'])==expected and
             item['kind']=='preserve_existing_subgroups' and
             item['scientific_identity_changed'] is False and item['permanent_nonmatch'] is False and
             item['boundary']==sorted([[p['submission_id']] for p in expected]) and
             item['origin']['group_id']==auth.get('group_id')==profile['historical_group_id'] and
             item['origin']['authorization'].get('workbook_sha256')==auth.get('workbook_sha256') and
             item['origin']['authorization'].get('request_sha256')==auth.get('request_sha256') and
             entry['group_id']==profile['target_group_id'] and
             entry['subjects']==sorted(p['submission_id'] for p in expected) and
             entry['reasons']==['existing_continuity_guard_required'],
             'intent_continuity_subjects_or_authorization_changed')


def validate_bound(proposal, data, options):
    need(proposal == bound_proposal(data, options), 'continuity_proposal_or_context_changed')


def guard_transition(current, proposal, release_id, *, data=None):
    """Apply, stage and undo must not bypass the prior pairwise authorization."""
    profile = PROFILES.get(release_id)
    current_head = current['pointer']['manifest_sha256'] if current else None
    if profile is not None:
        need(current is not None and current_head == profile['historical_policy_head_sha256'],
             'continuity_prior_head_changed')
        need(proposal is not None and proposal.get('historical_continuity'), 'continuity_constraint_required')
    elif current and current['policy'].get('historical_continuity_revision'):
        need(False, 'continuity_future_release_requires_reviewed_transition')
    elif current and any(current_head == p['historical_policy_head_sha256'] or
                         p['historical_group_id'] in current['policy'].get('partitions', {})
                         for p in PROFILES.values()):
        if proposal is not None and proposal.get('partitions') == current['policy'].get('partitions'):
            return
        # One bounded legacy-to-intent transition. The existing source-bundle
        # verifier reconstructs every original authority from the active generation;
        # ordinary acceptance or caller-supplied claims cannot waive this check.
        need(any(current_head == p['historical_policy_head_sha256'] for p in PROFILES.values()) and
             isinstance(data, dict) and 'intent_origin' in data and 'carry' in data and
             proposal is not None and proposal.get('partitions') == {},
             'historical_partition_cannot_be_dropped')
        from .group_cleaning_operator import _carry_from_active
        verified = _carry_from_active(current, data, data['_proposal_options'])
        need(data['carry'] == verified and
             proposal.get('decision_intents') == verified.get('decision_intents') and
             bool(verified.get('decision_intents', {}).get('intents')) and
             proposal['base'].get('prior_policy_head') == current_head and
             proposal['base'].get('prior_policy_origin_revision') == current['policy_manifest']['revision'],
             'historical_intent_migration_changed')


def check_generation(policy, proposal, receipt):
    """Consumers reject missing or inconsistent target proof before use."""
    profile = PROFILES.get(policy.get('release_id'))
    if profile is None:
        need(not policy.get('historical_continuity_revision'), 'unrecognized_continuity_generation')
        return
    need(isinstance(proposal, dict) and isinstance(proposal.get('historical_continuity'), dict),
         'continuity_generation_missing')
    binding = proposal['historical_continuity']; proof = binding.get('proof') or {}
    expected_keys = {'format', 'profile_revision', 'proof', 'revision'}
    if 'decision_intents' in proposal:expected_keys.add('intent_lineage')
    need(set(binding) == expected_keys and
         binding['format'] == BOUND_FORMAT and binding['profile_revision'] == sha(profile) and
         binding['revision'] == sha({k: v for k, v in binding.items() if k != 'revision'}) and
         proof.get('revision') == sha({k: v for k, v in proof.items() if k != 'revision'}) and
         policy.get('policy_active') is True and
         policy.get('historical_continuity_revision') == binding['revision'] and
         policy.get('proposal_revision') == proposal.get('revision') and
         policy.get('partitions') == proposal.get('partitions') and
         policy.get('inventory_revision') == profile['target_inventory_revision'] and
         policy.get('main_revision') == proposal.get('base', {}).get('main_revision') and
         proposal.get('base', {}).get('inventory_revision') == profile['target_inventory_revision'] and
         accepts_historical_implementation(profile, proposal.get('base', {}).get('implementation_revision'), implementation_revision()) and
         proposal.get('revision') == sha({k: v for k, v in proposal.items() if k != 'revision'}),
         'continuity_generation_binding_changed')
    check_intent_lineage(proposal)
    native = {k: v for k, v in proposal.items() if k not in {'historical_continuity', 'revision'}}
    _check_intent_continuity(native,proof,profile)
    auth = proof.get('historical_authorization') or {}; target = proof.get('target') or {}
    pins = auth.get('authorized_student_pins') or []; existing = target.get('existing_parent_atom') or {}
    member_pins = target.get('scope_member_pins') or []
    need(proof.get('format') == 'study2_two_student_continuity_evidence_v1' and
         proof.get('status') == 'evidence_only_not_approval' and
         proof.get('scientific_identity_changed') is False and proof.get('permanent_nonmatch') is False and
         target.get('proposal_revision') == sha(native) and target.get('release_id') == profile['target_release_id'] and
         target.get('inventory_revision') == profile['target_inventory_revision'] and
         target.get('group_id') == profile['target_group_id'] and target.get('scope_sha256') == profile['target_scope_sha256'] and
         target.get('scope_binding') == proposal.get('group_bindings', {}).get(profile['target_group_id']) and
         proof.get('prior_scope_sha256') == profile['prior_scope_sha256'] and
         proof.get('source_time_export_sha256') == profile['transition_export_sha256'] and
         proof.get('prior_run_manifest_sha256') == profile['prior_run_manifest_sha256'] and
         auth.get('bundle_sha256') == profile['historical_bundle_sha256'] and
         auth.get('authorization_sha256') == profile['historical_authorization_sha256'] and
         auth.get('partitions_sha256') == profile['historical_partitions_sha256'] and
         auth.get('workbook_sha256') == profile['historical_workbook_sha256'] and
         auth.get('request_sha256') == profile['historical_request_sha256'] and
         auth.get('policy_head_sha256') == profile['historical_policy_head_sha256'] and
         auth.get('decision') == 'keep_original_students_in_separate_existing_atoms' and
         auth.get('group_id') == profile['historical_group_id'] and len(pins) == 2 and
         all(isinstance(p, dict) and p.get('role') == 'student' for p in pins) and
         len({p.get('submission_id') for p in pins}) == 2 and
         existing.get('parent') not in {p.get('submission_id') for p in pins} and
         existing.get('student') in {p.get('submission_id') for p in pins} and
         existing.get('rule') == 'exact_school_contact_child_demo' and
         len(member_pins) == 3 and all(isinstance(p, dict) and
             set(p) == {'submission_id','version_id','role','raw_hash'} for p in member_pins) and
         {p['submission_id'] for p in member_pins} ==
             ({p.get('submission_id') for p in pins} | {existing.get('parent')}) and
         {p['submission_id']:p['role'] for p in member_pins}.get(existing.get('parent')) == 'parent' and
         all({p['submission_id']:p['role'] for p in member_pins}.get(p.get('submission_id')) == 'student' for p in pins) and
         re.fullmatch('[0-9a-f]{64}', str(target.get('scope_member_records_sha256'))) is not None and
         profile['target_group_id'] not in proposal.get('partitions', {}) and len(proposal.get('partitions', {})) == 7,
         'continuity_generation_scope_changed')
    review = receipt.get('review') or {}
    need(review.get('accepted') is True and review.get('proposal_revision') == proposal['revision'],
         'continuity_generation_review_missing')


def check_inventory_binding(active, inventory):
    """Recheck reviewed target member content when the flag/publication guard loads it."""
    profile = PROFILES.get(inventory.release_id)
    if profile is None:
        need(not active['policy'].get('historical_continuity_revision'), 'continuity_inventory_release_changed')
        return
    check_generation(active['policy'], active['proposal'], active['receipt'])
    provenance = inventory.provenance
    need(isinstance(provenance, dict) and set(provenance) == {'summary','records'} and
         all(isinstance(provenance[k], dict) and set(provenance[k]) == {'path','sha256'}
             for k in ('summary','records')), 'continuity_release_provenance_required')
    record_path = Path(provenance['records']['path'])
    root = record_path.parent
    need(record_path.is_absolute() and record_path.name == 'records.jsonl.gz' and
         root.is_dir() and not root.is_symlink() and
         Path(provenance['summary']['path']) == root/'summary.json', 'continuity_release_root_invalid')
    summary_blob, summary_pin = _read_pinned(root/'summary.json')
    _, records_pin = _read_pinned(record_path)
    _, cases_pin = _read_pinned(root/'cases.jsonl.gz')
    _, run_pin = _read_pinned(root/'run_manifest.json')
    need(summary_pin == provenance['summary'] and summary_pin['sha256'] == profile['target_summary_sha256'] and
         records_pin == provenance['records'] and
         json.loads(summary_blob).get('release_id') == inventory.release_id and
         records_pin['sha256'] == profile['target_records_sha256'], 'continuity_target_records_changed')
    need(cases_pin['sha256'] == profile['target_cases_sha256'], 'continuity_target_cases_changed')
    need(run_pin['sha256'] == profile['target_run_manifest_sha256'], 'continuity_target_run_manifest_changed')
    target = active['proposal']['historical_continuity']['proof']['target']
    pins = target['scope_member_pins']
    by_id = {r['submission_id']: r for r in inventory.records}
    check_intent_inventory(active['proposal'],by_id)
    need(inventory.revision == profile['target_inventory_revision'] and
         all(p['submission_id'] in by_id and
             {k: by_id[p['submission_id']].get(k) for k in ('submission_id','version_id','role','raw_hash')} == p
             for p in pins), 'continuity_inventory_member_pin_changed')
    need(sha({p['submission_id']: by_id[p['submission_id']] for p in sorted(pins, key=lambda x:x['submission_id'])}) ==
         target['scope_member_records_sha256'], 'continuity_inventory_member_evidence_changed')
