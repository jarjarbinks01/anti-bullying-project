"""Permanent child-family registration, independent of scientific identity rules.

Planning is read-only. Staging reserves IDs; only published memberships are
eligible for invitation. Historical anchors and issued IDs are never deleted.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .common import PipelineError, digest, dumps, text, timestamp, utcnow
from .matching import identity_evidence

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS dyad_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dyad_registry(
 dyad_id TEXT PRIMARY KEY, first_student_id TEXT NOT NULL, first_parent_id TEXT NOT NULL,
 first_run_id TEXT NOT NULL, created_at TEXT NOT NULL, first_evidence TEXT NOT NULL,
 lifecycle TEXT NOT NULL DEFAULT 'reserved' CHECK(lifecycle IN ('reserved','active','suspended','retired')),
 first_published_run_id TEXT);
DROP INDEX IF EXISTS dyad_first_pair;
CREATE TABLE IF NOT EXISTS dyad_lineage(
 dyad_id TEXT NOT NULL REFERENCES dyad_registry, submission_id TEXT NOT NULL,
 evidence_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(dyad_id,submission_id,evidence_hash));
CREATE TABLE IF NOT EXISTS dyad_memberships(
 run_id TEXT NOT NULL REFERENCES runs, membership_key TEXT NOT NULL,
 dyad_id TEXT REFERENCES dyad_registry, child_id TEXT, state TEXT NOT NULL,
 payload_json TEXT NOT NULL, PRIMARY KEY(run_id,membership_key));
CREATE UNIQUE INDEX IF NOT EXISTS dyad_one_child_per_run ON dyad_memberships(run_id,child_id) WHERE child_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS dyad_one_mapping_per_run ON dyad_memberships(run_id,dyad_id) WHERE dyad_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS dyad_events(
 event_id TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, dyad_id TEXT,
 actor TEXT NOT NULL, reason TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dyad_resolutions(
 operation_id TEXT PRIMARY KEY, at TEXT NOT NULL, release_id TEXT NOT NULL,
 payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dyad_aliases(
 alias_id TEXT PRIMARY KEY REFERENCES dyad_registry,
 canonical_id TEXT NOT NULL REFERENCES dyad_registry, operation_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dyad_invitation_events(
 operation_id TEXT PRIMARY KEY, at TEXT NOT NULL, release_id TEXT NOT NULL,
 dyad_id TEXT NOT NULL REFERENCES dyad_registry, role TEXT NOT NULL,
 payload_json TEXT NOT NULL, event_key TEXT UNIQUE NOT NULL);
CREATE INDEX IF NOT EXISTS dyad_invitation_lookup ON dyad_invitation_events(dyad_id,role,at);
CREATE TRIGGER IF NOT EXISTS dyad_immutable_registration BEFORE UPDATE OF
 first_student_id,first_parent_id,first_run_id,created_at,first_evidence ON dyad_registry
 BEGIN SELECT RAISE(ABORT,'Permanent registration anchors are immutable'); END;
CREATE TRIGGER IF NOT EXISTS dyad_no_delete BEFORE DELETE ON dyad_registry
 BEGIN SELECT RAISE(ABORT,'Issued permanent IDs cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS dyad_first_publication_immutable BEFORE UPDATE OF first_published_run_id ON dyad_registry
 WHEN OLD.first_published_run_id IS NOT NULL AND NEW.first_published_run_id IS NOT OLD.first_published_run_id
 BEGIN SELECT RAISE(ABORT,'First publication is immutable'); END;
"""


def migrate(db):
    """Idempotent, explicit schema migration; callers hold the writer lock."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dyad_schema'").fetchone():
        prior = [r[0] for r in db.execute('SELECT version FROM dyad_schema')]
        if prior and max(prior) != SCHEMA_VERSION:
            raise PipelineError('Unsupported permanent registration schema version')
    kind=db.execute("SELECT type FROM sqlite_master WHERE name='dyad_memberships'").fetchone()
    shared=(kind and kind[0]=='view') or (not kind and db.execute("SELECT 1 FROM sqlite_master WHERE name='release_candidate_refs'").fetchone())
    schema=SCHEMA
    if shared:
        start=schema.index('CREATE TABLE IF NOT EXISTS dyad_memberships(')
        end=schema.index('CREATE TABLE IF NOT EXISTS dyad_events(')
        schema=schema[:start]+schema[end:]
    db.executescript(schema)
    if shared:
        from .run_storage import install_memberships
        install_memberships(db)
    versions = [r[0] for r in db.execute('SELECT version FROM dyad_schema')]
    if versions and max(versions) != SCHEMA_VERSION:
        raise PipelineError('Unsupported permanent registration schema version')
    with db:
        db.execute('INSERT OR IGNORE INTO dyad_schema VALUES(?,?)', (SCHEMA_VERSION, utcnow()))


def exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dyad_registry'").fetchone())


def canonical_id(did, aliases):
    seen = set()
    while did in aliases:
        if did in seen:
            raise PipelineError('Conflicting cyclic permanent-ID aliases')
        seen.add(did)
        did = aliases[did]
    return did


def related_ids(db, did):
    aliases = {r[0]:r[1] for r in db.execute('SELECT alias_id,canonical_id FROM dyad_aliases')}
    root = canonical_id(did, aliases)
    return sorted({root} | {old for old in aliases if canonical_id(old, aliases) == root})


def scientific_records(db, run_id):
    from .storage import read_records
    return list(read_records(db, run_id, include_raw=False))


def scientific_cases(db, release_id):
    return [json.loads(r[0]) for r in db.execute(
        'SELECT payload_json FROM release_candidates WHERE release_id=? ORDER BY case_id', (release_id,))]


def administrative_fingerprint(db):
    if not exists(db):
        return digest({})
    return digest({'resolutions': [dict(r) for r in db.execute('SELECT * FROM dyad_resolutions ORDER BY operation_id')],
                   'registry': [{k: r[k] for k in r.keys() if k not in {'lifecycle','first_published_run_id'}}
                                for r in db.execute('SELECT * FROM dyad_registry ORDER BY dyad_id')],
                   'lineage': [dict(r) for r in db.execute('SELECT * FROM dyad_lineage ORDER BY 1,2,3')]})


def evidence_hash(record):
    return digest(identity_evidence(record))


def group_signature(rows, cases, cfg):
    ids = {r['submission_id'] for r in rows}
    relevant = [c for c in cases if ids & {c.get('record_a'), c.get('record_b')} and
                c.get('kind') in {'identity', 'family'}]
    return digest({'records': [{'id': r['submission_id'], 'evidence': identity_evidence(r),
                               'status': r.get('status'), 'wave': r.get('selected_wave')}
                              for r in sorted(rows, key=lambda r: r['submission_id'])],
                   'cases': sorted([{'id': c['case_id'], 'status': c['status'], 'rule': c['rule'],
                                     'reason': c['reason']} for c in relevant], key=lambda c: c['id']),
                   'rules': {k: cfg.get(k) for k in ('matching_policy', 'date_policy', 'duplicate_days',
                                                    'minimum_followup_days', 'bd_requires_same_adult')},
                   'identity_code': cfg.get('_dyad_identity_code')})


def identity_code(cfg=None):
    from .common import file_hash
    hashes={n:file_hash(Path(__file__).parent/n) for n in ('matching.py','respondents.py','review_core.py')}
    if cfg and cfg.get('state_dir'):
        compatibility=Path(cfg['state_dir'])/'review_rule_compatibility.json'
        if compatibility.is_file():
            proof=json.loads(compatibility.read_text())
            complete={**hashes,'review_hints.py':file_hash(Path(__file__).parent/'review_hints.py')}
            if proof.get('format_version')==1 and proof.get('verified') is True and proof.get('current_code')==complete:
                hashes={n:proof['original_code'][n] for n in hashes}
    return hashes


def _tracking(child, rows, cells, cases, cfg):
    """Safe published view. Contact values stay in controlled exports only."""
    row = {'child_id': child, 'dyad_id': None, 'registration_state': 'awaiting_registration',
           'registration_reason': '', 'adult_status': 'unconfirmed', 'adult_rule': '',
           'member_ids': sorted(r['submission_id'] for r in rows)}
    ids = set(row['member_ids'])
    pending = [c for c in cases if c.get('status') == 'pending' and
               c.get('kind') in {'identity', 'family'} and ids & {c.get('record_a'), c.get('record_b')}]
    row['identity_candidate_pending'] = len(pending)
    row['contradictory_candidates'] = sorted(c['case_id'] for c in pending
        if c.get('reason') == 'Competing or contradictory candidate component' or c.get('rule') == 'manual_decision_reopened')
    dates = []
    for role in ('student', 'parent'):
        a, b = cells.get((child, role, 'T0')), cells.get((child, role, 'T1'))
        for wave, record in (('t0', a), ('t1', b)):
            row[role + '_' + wave + '_id'] = record['submission_id'] if record else None
            row[role + '_' + wave + '_at'] = record.get('observed_at') if record else None
        row[role + '_school'] = a.get('school') if a else None
        row[role + '_date_basis'] = a.get('date_basis') if a else None
        row[role + '_time_confidence'] = a.get('time_confidence') if a else None
        t = timestamp(a.get('observed_at')) if a else None
        reliable = a and a.get('time_confidence') in {'observed', 'manual_verified', 'accepted_creation_time'}
        due = (t + timedelta(days=cfg.get('minimum_followup_days', 90))).isoformat() if t and reliable else None
        row[role + '_due_at'] = due
        if due:
            dates.append(due)
        followups = [r for r in rows if r['role'] == role and a and r['submission_id'] != a['submission_id']]
        row[role + '_received_count'] = len(followups)
        row[role + '_short_interval_count'] = sum(r.get('status') == 'short_interval_followup' for r in followups)
        row[role + '_other_count'] = sum(r.get('status') in {'extra_followup', 'short_repeat'} for r in followups)
        row[role + '_complete'] = bool(b)
    row['family_due_at'] = max(dates) if len(dates) == 2 else None
    s, p = row['student_complete'], row['parent_complete']
    row['followup_status'] = 'both_complete' if s and p else 'student_only' if s else 'parent_only' if p else 'neither_complete'
    p0, p1 = row['parent_t0_id'], row['parent_t1_id']
    if p0 and p1:
        adult = next((c for c in cases if c['kind'] == 'respondent' and
                      {c.get('record_a'), c.get('record_b')} == {p0, p1}), None)
        if adult:
            row['adult_rule'] = adult['rule']
            row['adult_status'] = ('same' if adult['status'] == 'confirmed' else 'different'
                if adult['rule'] in {'reviewer_rejected_same_adult', 'reported_relationship_changed'} else 'unconfirmed')
    return row


def plan(db, run_id, records, cases, cfg):
    """No mutations or random allocation. Preview IDs for new rows stay blank."""
    cfg = {**cfg, '_dyad_identity_code': identity_code(cfg)}
    by_id = {r['submission_id']: r for r in records}
    groups = defaultdict(list)
    cells = {}
    for r in records:
        if r.get('child_id'):
            groups[r['child_id']].append(r)
        if r.get('selected_wave'):
            key = (r['child_id'], r['role'], r['selected_wave'])
            if key in cells:
                raise PipelineError('Non-unique scientific role/wave before permanent registration')
            cells[key] = r
    e_children = {c for c, role, wave in cells if role == 'student' and wave == 'T0' and (c, 'parent', 'T0') in cells}
    registry = [dict(r) for r in db.execute('SELECT * FROM dyad_registry ORDER BY dyad_id')] if exists(db) else []
    cases_by_child = defaultdict(list)
    for case in cases:
        children = {by_id[s].get('child_id') for s in (case.get('record_a'), case.get('record_b')) if s in by_id}
        for child in children:
            cases_by_child[child].append(case)
    lineage_all = [dict(r) for r in db.execute('SELECT * FROM dyad_lineage')] if exists(db) else []
    lineage = [r for r in lineage_all if r['active']]
    retired = {r['dyad_id'] for r in registry if r['lifecycle'] == 'retired'}
    aliases = {r[0]:r[1] for r in db.execute('SELECT alias_id,canonical_id FROM dyad_aliases')} if exists(db) else {}
    retired_groups = defaultdict(set)
    for entry in lineage_all:
        if entry['dyad_id'] in retired and entry['submission_id'] in by_id:
            child = by_id[entry['submission_id']].get('child_id')
            if child:
                retired_groups[child].add(entry['dyad_id'])
    members = defaultdict(list)
    for entry in lineage:
        members[entry['dyad_id']].append(entry)
    targets = defaultdict(set)
    problems = defaultdict(set)
    owners = defaultdict(set)
    for reg in registry:
        did = reg['dyad_id']
        if reg['lifecycle'] == 'retired':
            continue
        for entry in members[did]:
            r = by_id.get(entry['submission_id'])
            if not r:
                problems[did].add('missing_registered_submission')
                continue
            if r.get('child_id'):
                targets[did].add(r['child_id'])
                owners[r['child_id']].add(did)
            else:
                problems[did].add('registered_submission_not_assigned')
            if evidence_hash(r) != entry['evidence_hash']:
                problems[did].add('registered_identity_evidence_changed')
        if len(targets[did]) != 1:
            problems[did].add('registered_group_split_or_missing')
    result = []
    assigned = set()
    for child in sorted(e_children | set(owners)):
        if child not in groups:
            continue
        row = _tracking(child, groups[child], cells, cases_by_child[child], cfg)
        row['evidence_signature'] = group_signature(groups[child], cases_by_child[child], cfg)
        candidates = sorted(owners[child])
        row['candidate_dyad_ids'] = candidates
        row['retired_dyad_ids'] = sorted(retired_groups[child])
        issues = set()
        if any(canonical_id(d, aliases) not in owners[child] for d in retired_groups[child]):
            issues.add('retired_registration_without_canonical_mapping')
        if child not in e_children:
            issues.add('no_current_confirmed_t0_pair')
        if row['contradictory_candidates']:
            issues.add('contradictory_identity_component')
        for did in candidates:
            issues.update(problems[did])
        if len(candidates) > 1:
            issues.add('multiple_registered_families_merged')
        if candidates and any(len(targets[d]) != 1 for d in candidates):
            issues.add('registered_group_split_or_missing')
        if len(candidates) == 1 and len(targets[candidates[0]]) == 1 and candidates[0] not in assigned:
            row['dyad_id'] = candidates[0]
            assigned.add(candidates[0])
        elif candidates:
            issues.add('registered_id_claimed_by_multiple_groups')
        if issues:
            row['registration_state'] = 'suspended' if candidates else 'awaiting_registration'
            row['registration_reason'] = ';'.join(sorted(issues))
        else:
            row['registration_state'] = 'active' if candidates else 'new'
        result.append(row)
    for reg in registry:
        if reg['dyad_id'] not in assigned and reg['lifecycle'] != 'retired':
            result.append({'child_id': None, 'dyad_id': reg['dyad_id'], 'registration_state': 'suspended',
                           'registration_reason': ';'.join(sorted(problems[reg['dyad_id']])) or 'no_current_confirmed_t0_pair',
                           'candidate_dyad_ids': [reg['dyad_id']], 'member_ids': [],
                           'evidence_signature': None, 'followup_status': 'unconfirmed'})
    return result


def stage(db, run_id, records, cases, cfg):
    rows = plan(db, run_id, records, cases, cfg)
    if db.execute('SELECT 1 FROM dyad_memberships WHERE run_id=?', (run_id,)).fetchone():
        raise PipelineError('Permanent registration already staged for this run')
    by_id = {r['submission_id']: r for r in records}
    with db:
        for row in rows:
            if row['registration_state'] == 'new':
                did = 'DYAD_' + uuid.uuid4().hex
                row.update(dyad_id=did, registration_state='active')
                anchors = [row['student_t0_id'], row['parent_t0_id']]
                db.execute('INSERT INTO dyad_registry(dyad_id,first_student_id,first_parent_id,first_run_id,created_at,first_evidence,lifecycle) VALUES(?,?,?,?,?,?,?)',
                    (did, *anchors, run_id, utcnow(), dumps({sid: identity_evidence(by_id[sid]) for sid in anchors}), 'reserved'))
                _event(db, 'registered', did, 'pipeline', 'Confirmed T0 child-family registration',
                       {'run_id': run_id, 'anchors': anchors})
            did = row.get('dyad_id')
            if did:
                reg = db.execute('SELECT * FROM dyad_registry WHERE dyad_id=?', (did,)).fetchone()
                row.update(registered_student_id=reg['first_student_id'], registered_parent_id=reg['first_parent_id'],
                           registered_at=reg['created_at'], first_published_run_id=reg['first_published_run_id'] or run_id)
            if did and row['registration_state'] == 'active':
                for sid in row['member_ids']:
                    db.execute('INSERT OR IGNORE INTO dyad_lineage VALUES(?,?,?,1)', (did, sid, evidence_hash(by_id[sid])))
            key = row.get('child_id') or row['dyad_id']
            db.execute('INSERT INTO dyad_memberships VALUES(?,?,?,?,?,?)',
                       (run_id, key, did, row.get('child_id'), row['registration_state'], dumps(row)))
            if did:
                _event(db, 'staged_mapping', did, 'pipeline', row.get('registration_reason') or 'Unambiguous child lineage',
                       {'run_id': run_id, 'child_id': row.get('child_id'), 'state': row['registration_state'],
                        'signature': row.get('evidence_signature')})
    return rows


def _event(db, kind, did, actor, reason, payload, operation_id=None):
    eid = operation_id or 'DEVENT_' + digest([kind, did, payload])
    db.execute('INSERT OR IGNORE INTO dyad_events VALUES(?,?,?,?,?,?,?)',
               (eid, utcnow(), kind, did, actor, reason, dumps(payload)))


def staged_rows(db, run_id):
    if not exists(db):
        return []
    return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM dyad_memberships WHERE run_id=? ORDER BY membership_key', (run_id,))]


def validate_staging(db, run_id, records, cases, cfg):
    rows = staged_rows(db, run_id)
    active = [r for r in rows if r['registration_state'] == 'active']
    if len({r['dyad_id'] for r in active}) != len(active) or any(not r['dyad_id'] for r in active):
        raise PipelineError('Permanent IDs do not reconcile')
    # Replan after reservations; evidence and all current conflicts must still agree.
    replanned = {r.get('child_id'): r for r in plan(db, run_id, records, cases, cfg) if r.get('child_id')}
    for row in active:
        current = replanned.get(row['child_id'])
        if not current or current['registration_state'] != 'active' or current['dyad_id'] != row['dyad_id']:
            raise PipelineError('Permanent registration lineage changed before publication')
        if current['evidence_signature'] != row['evidence_signature']:
            raise PipelineError('Permanent registration evidence changed before publication')
    return {'active': len(active), 'suspended': sum(r['registration_state'] == 'suspended' for r in rows),
            'awaiting_registration': sum(r['registration_state'] == 'awaiting_registration' for r in rows),
            'schema_version': SCHEMA_VERSION}


def publish_memberships(db, run_id):
    """Called in the publication transaction. Retired IDs remain retired."""
    if not exists(db):
        return
    for row in staged_rows(db, run_id):
        did = row.get('dyad_id')
        if not did:
            continue
        reg = db.execute('SELECT lifecycle FROM dyad_registry WHERE dyad_id=?', (did,)).fetchone()
        if reg['lifecycle'] != 'retired':
            db.execute('UPDATE dyad_registry SET lifecycle=? WHERE dyad_id=?', (row['registration_state'], did))
            db.execute('UPDATE dyad_registry SET first_published_run_id=? WHERE dyad_id=? AND first_published_run_id IS NULL', (run_id, did))
        _event(db, 'published_mapping', did, 'pipeline', 'Published version membership',
               {'run_id': run_id, 'state': row['registration_state'], 'child_id': row.get('child_id')})


def safe_tracking_rows(rows):
    # JSON arrays are explicit text in Excel/parquet, avoiding mixed nested data.
    return [{k: dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()} for r in rows]


def summary(rows):
    return {'states': dict(Counter(r['registration_state'] for r in rows)),
            'followup': dict(Counter(r.get('followup_status') for r in rows)),
            'registered_ids': len({r['dyad_id'] for r in rows if r.get('dyad_id')})}
