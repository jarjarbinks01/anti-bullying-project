"""Durable, scoped administrative intent; never an identity or flag writer.

Only an accepted existing partition is migrated. Its full original subjects,
evidence and receipt survive. A release application closes only the original
concrete comparison semantics, never a transitive or newly added relationship.
"""
from copy import deepcopy

from .analysis_eligibility import sha
from .common import PipelineError

FORMAT = 'study2_group_decision_intents_v1'
APPLICATION = 'study2_group_decision_application_v1'
KIND = 'preserve_existing_subgroups'
PIN_FIELDS = ('submission_id', 'version_id', 'role', 'raw_hash')
CONTACT_FIELDS = ('contact_01', 'contact_02', 'contact_03.1', 'contact_03.2', 'contact_03.3', 'contact_03.4')


def need(ok, reason):
    if not ok:
        raise PipelineError(reason)


def sealed(value):
    return {**value, 'revision': sha(value)}


def full_pin(record):
    need(all(isinstance(record.get(k), str) and record[k] for k in PIN_FIELDS),
         'intent_full_subject_pin_required')
    return {k: record[k] for k in PIN_FIELDS}


def evidence(record):
    """Identity/routing context; scores and unrelated answers are not interpreted."""
    fields = ('role', 'source_id', 'dob', 'gender', 'school', 'child_id', 'status', 'selected_wave')
    return sha({'fields': {k: record.get(k) for k in fields},
                'contacts': {k: record.get('answer', {}).get(k) for k in CONTACT_FIELDS}})


def comparison(case):
    return {'subjects': sorted((case['record_a'], case['record_b'])),
            'kind': case.get('kind'), 'rule': case.get('rule')}


def validate(collection):
    need(isinstance(collection, dict) and set(collection) == {'format', 'intents', 'revision'}
         and collection['format'] == FORMAT and isinstance(collection['intents'], list),
         'intent_collection_shape')
    need(collection['revision'] == sha({k: v for k, v in collection.items() if k != 'revision'}),
         'intent_collection_revision')
    ids = set()
    for item in collection['intents']:
        need(isinstance(item, dict) and item.get('revision') ==
             sha({k: v for k, v in item.items() if k != 'revision'}), 'intent_revision')
        need(isinstance(item.get('decision_id'), str) and item['decision_id'] not in ids,
             'intent_duplicate_decision')
        ids.add(item['decision_id'])
        pins = item.get('subjects')
        need(isinstance(pins, list) and pins and all(set(p) == set(PIN_FIELDS) for p in pins),
             'intent_subject_scope')
        subjects = [p['submission_id'] for p in pins]
        need(len(subjects) == len(set(subjects)), 'intent_duplicate_subject')
        blocks = item.get('boundary')
        need(isinstance(blocks, list) and all(isinstance(b, list) and b for b in blocks)
             and sorted(s for b in blocks for s in b) == sorted(subjects), 'intent_boundary_scope')
        need(set(item.get('evidence', {})) == set(subjects), 'intent_evidence_scope')
        need(isinstance(item.get('comparisons'), list), 'intent_comparison_scope')
        where = {s: n for n, block in enumerate(blocks) for s in block}
        for c in item['comparisons']:
            need(set(c) == {'subjects', 'kind', 'rule'} and len(c['subjects']) == 2
                 and all(s in where for s in c['subjects'])
                 and where[c['subjects'][0]] != where[c['subjects'][1]], 'intent_comparison_scope')
    return collection


def migrate(proposal, records, cases, groups, receipt):
    """Called with the checksum-verified accepted generation and its pinned inputs."""
    need(proposal.get('revision') == sha({k: v for k, v in proposal.items() if k != 'revision'}),
         'intent_origin_proposal_revision')
    review = receipt.get('review', {})
    need(review.get('accepted') is True and review.get('proposal_revision') == proposal['revision'],
         'intent_origin_not_accepted')
    auth = proposal.get('authorization', {})
    need(set(proposal.get('partitions', {})) == set(auth.get('partition_groups', [])),
         'intent_origin_authorization_scope')
    items = []
    for gid, boundary in sorted(proposal.get('partitions', {}).items()):
        need(gid in groups, 'intent_origin_group_missing')
        members = sorted(groups[gid]['group_review']['members'])
        need(sorted(s for b in boundary for s in b) == members, 'intent_origin_members_changed')
        pins = [full_pin(records[s]) for s in members]
        where = {s: n for n, block in enumerate(boundary) for s in block}
        concrete = []
        for cid in groups[gid]['group_review']['comparison_ids']:
            c = cases[cid]
            a, b = c.get('record_a'), c.get('record_b')
            if a in where and b in where and where[a] != where[b]:
                concrete.append(comparison(c))
        canonical = sorted((sorted(b) for b in boundary))
        identity = {'kind': KIND, 'boundary': canonical, 'authorization': auth,
                    'origin_group_id': gid}
        item = {'decision_id': 'GI_' + sha(identity), 'kind': KIND,
                'subjects': pins, 'boundary': canonical,
                'evidence': {s: evidence(records[s]) for s in members},
                'comparisons': sorted({sha(c): c for c in concrete}.values(), key=sha),
                'reason': receipt.get('reason'), 'supersedes': None,
                'origin': {'release_id': proposal['base']['release_id'], 'group_id': gid,
                           'proposal_revision': proposal['revision'],
                           'authorization': deepcopy(auth), 'receipt': deepcopy(receipt)},
                'scientific_identity_changed': False, 'permanent_nonmatch': False}
        items.append(sealed(item))
    return validate(sealed({'format': FORMAT, 'intents': items}))


def compile_application(collection, records, cases, groups, *, release_id, continuity_profile=None):
    """Pure release projection. Changed pins stay pending; no permissive defaults."""
    from .group_cleaning import classify_scope
    validate(collection)
    scopes = {gid: classify_scope(records, g, cases) for gid, g in groups.items()}
    entries = []
    for item in collection['intents']:
        subjects = {p['submission_id'] for p in item['subjects']}
        reasons = []
        if item['kind'] != KIND:
            reasons.append('unknown_decision_semantics')
        for p in item['subjects']:
            sid = p['submission_id']
            if sid not in records:
                reasons.append('subject_missing')
                continue
            row = records[sid]
            if full_pin(row) != p:
                reasons.append('source_pin_changed')
            if evidence(row) != item['evidence'][sid]:
                reasons.append('relevant_evidence_changed')
            if row.get('selected_wave') not in (None, 'T0', 'T1'):
                reasons.append('outside_t0_t1')
        allowed = {sha(c) for c in item['comparisons']}
        where = {s: n for n, block in enumerate(item['boundary']) for s in block}
        proof_candidate = bool(continuity_profile and item['kind']==KIND and
            item['origin']['group_id']==continuity_profile['historical_group_id'] and
            len(item['subjects'])==2 and all(p['role']=='student' for p in item['subjects']) and
            sorted(map(len,item['boundary']))==[1,1] and
            item['origin']['authorization'].get('workbook_sha256')==continuity_profile['historical_workbook_sha256'] and
            item['origin']['authorization'].get('request_sha256')==continuity_profile['historical_request_sha256'])
        found = False
        for gid, group in sorted(groups.items()):
            selected = [cid for cid in group['group_review']['comparison_ids']
                        if cases[cid].get('record_a') in subjects and cases[cid].get('record_b') in subjects
                        and where[cases[cid]['record_a']] != where[cases[cid]['record_b']]]
            if not selected:
                continue
            found = True
            scope = scopes[gid]
            merged = any(len({where[s] for s in atom if s in where}) > 1
                         for atom in scope['protected_atoms'])
            for cid in selected:
                why = list(reasons)
                if sha(comparison(cases[cid])) not in allowed:
                    why.append('comparison_not_in_original_authorized_scope')
                if merged:
                    why.append('supported_subgroup_boundary_changed')
                for held in scope['holds']:
                    if cid in held['comparison_ids'] and held['reasons'] != ['missing_invalid_or_uncertain_contact']:
                        why.append('native_scope_hold')
                # This is a request for the EXISTING proof, not a carry verdict.
                # The bound proposal and generation guards must verify it before
                # any accepted operation. Its native scope is left byte-for-byte.
                deferred = proof_candidate and gid==continuity_profile['target_group_id']
                entries.append({'decision_id': item['decision_id'], 'group_id': gid,
                                'comparison_ids': [cid], 'subjects': comparison(cases[cid])['subjects'],
                                'status': 'requires_existing_continuity_proof' if deferred else ('held' if why else 'carried'),
                                'reasons': ['existing_continuity_guard_required'] if deferred else sorted(set(why))})
        if not found:
            proof_group=continuity_profile['target_group_id'] if proof_candidate else None
            deferred=bool(proof_group in groups and subjects <= set(groups[proof_group]['group_review']['members']))
            entries.append({'decision_id': item['decision_id'], 'group_id': proof_group if deferred else None,
                            'comparison_ids': [], 'subjects': sorted(subjects),
                            'status': 'requires_existing_continuity_proof' if deferred else ('held' if reasons else 'not_applicable'),
                            'reasons': ['existing_continuity_guard_required'] if deferred else
                                       (sorted(set(reasons)) or ['no_current_concrete_comparison'])})
    return sealed({'format': APPLICATION, 'release_id': release_id,
                   'intent_revision': collection['revision'], 'entries': entries,
                   'scientific_identity_changed': False, 'permanent_nonmatch': False})


def apply_to_scopes(scopes, application):
    """Split concrete edges, so a student's decision cannot close a parent edge."""
    result = deepcopy(scopes)
    actions = {}
    for entry in application['entries']:
        if entry['status'] not in {'carried','held'}:
            continue
        for cid in entry['comparison_ids']:
            key = (entry['group_id'], cid)
            old = actions.get(key)
            if old is None or entry['status'] == 'held':
                actions[key] = entry
    for gid, scope in result.items():
        routed = {'questions': [], 'holds': [], 'closures': []}
        for lane in routed:
            for row in scope[lane]:
                remaining = []
                for cid in row['comparison_ids']:
                    entry = actions.get((gid, cid))
                    if entry is None:
                        remaining.append(cid)
                        continue
                    chosen = deepcopy(row)
                    subjects = set(entry['subjects'])
                    chosen.update(comparison_ids=[cid], decision_ids=[entry['decision_id']],
                                  reasons=entry['reasons'] if entry['status'] == 'held' else ['carried_explicit_subgroup_boundary'])
                    for key in ('atom_a', 'atom_b'):
                        chosen[key] = [s for s in row[key] if s in subjects]
                    chosen['member_pins'] = [p for p in row['member_pins'] if p['submission_id'] in subjects]
                    if 'contact_evidence' in chosen:
                        chosen['contact_evidence'] = {s: v for s, v in chosen['contact_evidence'].items() if s in subjects}
                    for key in ('similarity', 'exact_cross_contacts'):
                        chosen[key] = [p for p in chosen.get(key, []) if {p['a'], p['b']} <= subjects]
                    routed['holds' if entry['status'] == 'held' else 'closures'].append(chosen)
                if remaining:
                    routed[lane].append({**row, 'comparison_ids': remaining})
        scope.update(routed)
    return result
