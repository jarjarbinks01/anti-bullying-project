"""Explicit, audited creation-time version transitions; ordinary guards stay strict."""
import json
from .common import PipelineError, digest, dumps, plain, timestamp, utcnow

TABLE = "approved_source_time_transitions"

def effective_registry(db, source_id, known):
    rows = [dict(r) for r in known]
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
        return rows
    by_slot = {r['slot']: r for r in rows}
    for t in db.execute("SELECT * FROM "+TABLE+" WHERE source_id=? ORDER BY sequence", (source_id,)):
        row = by_slot.get(t['slot'])
        if not row or row['raw_hash'] != t['old_raw_hash']:
            raise PipelineError("Approved source transition chain does not match registered lineage")
        row['raw_hash'] = t['new_raw_hash']
    return rows

def prior_creation_times(db, record):
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
        return []
    entries = list(db.execute("SELECT * FROM "+TABLE+" WHERE submission_id=? ORDER BY sequence", (record['submission_id'],)))
    if not entries:
        return []
    if entries[-1]['new_raw_hash'] != record['raw_hash']:
        raise PipelineError("Approved source transition does not match current raw version")
    return list(dict.fromkeys(t['old_observed_at'] for t in entries))

def install(db, operation_id, candidates, *, baseline_run, input_hashes, authorizer, reason):
    """One transaction: immutable transitions only, no registry deletion or mutation."""
    if not operation_id or not authorizer or not reason:
        raise PipelineError("Explicit source transition approval required")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS approved_source_time_transitions(
      sequence INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, source_id TEXT NOT NULL,
      slot INTEGER NOT NULL, submission_id TEXT NOT NULL, old_version TEXT NOT NULL,
      new_version TEXT NOT NULL, old_raw_hash TEXT NOT NULL, new_raw_hash TEXT NOT NULL,
      old_observed_at TEXT, new_observed_at TEXT, input_sha256 TEXT NOT NULL,
      approved_at TEXT NOT NULL, authorizer TEXT NOT NULL, reason TEXT NOT NULL,
      UNIQUE(operation_id,submission_id));
    CREATE INDEX IF NOT EXISTS source_time_transition_sid ON approved_source_time_transitions(submission_id,sequence);
    CREATE INDEX IF NOT EXISTS source_time_transition_source ON approved_source_time_transitions(source_id,sequence);
    CREATE TRIGGER IF NOT EXISTS immutable_source_time_transition_update
      BEFORE UPDATE ON approved_source_time_transitions
      BEGIN SELECT RAISE(ABORT,'Approved source transitions are append-only'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_source_time_transition_delete
      BEFORE DELETE ON approved_source_time_transitions
      BEGIN SELECT RAISE(ABORT,'Approved source transitions are append-only'); END;
    """)
    checked=[]
    seen=set()
    registries={source_id: {r['slot']:r for r in effective_registry(db,source_id,
        db.execute('SELECT * FROM paper_registry WHERE source_id=?',(source_id,)).fetchall())}
        for source_id in input_hashes}
    for c in candidates:
        sid=c['submission_id']
        if sid in seen:raise PipelineError("Duplicate approved source identity")
        seen.add(sid)
        old=db.execute("""SELECT s.source_id,s.source_key,v.* FROM run_records rr
          JOIN submissions s ON s.submission_id=rr.submission_id
          JOIN submission_versions v ON v.version_id=rr.version_id
          WHERE rr.run_id=? AND rr.submission_id=?""", (baseline_run,sid)).fetchone()
        raw=plain(c['new_raw'])
        if not old or old['source_id']!=c['source_id'] or old['version_id']!=c['old_version'] or old['raw_hash']!=c['old_raw_hash']:
            raise PipelineError("Stale approved source transition")
        previous=json.loads(old['raw_json'])
        if digest({k:v for k,v in previous.items() if k!='建立時間'}) != digest({k:v for k,v in raw.items() if k!='建立時間'}):
            raise PipelineError("Source transition includes an unapproved non-date change")
        new_hash=digest(raw)
        if new_hash!=c['new_raw_hash'] or digest([sid,new_hash])!=c['new_version'] or new_hash==old['raw_hash']:
            raise PipelineError("Source transition hash/version mismatch")
        new_time=timestamp(raw.get('建立時間')); old_time=timestamp(previous.get('建立時間'))
        if new_time is None:raise PipelineError("Updated authoritative creation time is missing or invalid")
        slot=int(old['source_key'].rsplit(':',1)[1])
        registered=registries[c['source_id']].get(slot)
        existing=db.execute("SELECT * FROM "+TABLE+" WHERE operation_id=? AND submission_id=?",(operation_id,sid)).fetchone()
        if existing:
            if existing['old_raw_hash']!=old['raw_hash'] or existing['new_raw_hash']!=new_hash:
                raise PipelineError("Operation ID reused for another transition")
            continue
        if not registered or registered['raw_hash']!=old['raw_hash']:
            raise PipelineError("Registered source transition is stale")
        checked.append((operation_id,c['source_id'],slot,sid,old['version_id'],c['new_version'],
          old['raw_hash'],new_hash,old_time.isoformat() if old_time else None,new_time.isoformat(),
          input_hashes[c['source_id']],utcnow(),authorizer,reason))
    with db:
        db.executemany("INSERT INTO "+TABLE+"(operation_id,source_id,slot,submission_id,old_version,new_version,old_raw_hash,new_raw_hash,old_observed_at,new_observed_at,input_sha256,approved_at,authorizer,reason) VALUES("+",".join("?" for _ in range(14))+")",checked)
    return len(checked)
