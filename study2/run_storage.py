"""Immutable candidate and family payloads with complete per-run associations."""
import hashlib
import sqlite3

from .common import PipelineError,dumps

BASE="""
CREATE TABLE IF NOT EXISTS run_payload_values(value_hash TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS run_payload_immutable BEFORE UPDATE ON run_payload_values
 BEGIN SELECT RAISE(ABORT,'Run payload values are immutable'); END;
"""
CANDIDATES="""
CREATE TABLE IF NOT EXISTS release_candidate_refs(
 release_id TEXT REFERENCES releases,case_id TEXT,value_hash TEXT NOT NULL REFERENCES run_payload_values,
 PRIMARY KEY(release_id,case_id)) WITHOUT ROWID;
CREATE VIEW IF NOT EXISTS release_candidates AS
 SELECT r.release_id,r.case_id,v.payload_json FROM release_candidate_refs r
 JOIN run_payload_values v ON v.value_hash=r.value_hash;
CREATE TRIGGER IF NOT EXISTS candidate_insert INSTEAD OF INSERT ON release_candidates
 BEGIN INSERT INTO release_candidate_refs VALUES(NEW.release_id,NEW.case_id,study2_run_value(NEW.payload_json)); END;
CREATE TRIGGER IF NOT EXISTS candidate_update INSTEAD OF UPDATE ON release_candidates
 BEGIN
 SELECT CASE WHEN NEW.release_id IS NOT OLD.release_id OR NEW.case_id IS NOT OLD.case_id
 THEN RAISE(ABORT,'Candidate run identity is immutable') END;
 UPDATE release_candidate_refs SET value_hash=study2_run_value(NEW.payload_json)
 WHERE release_id=OLD.release_id AND case_id=OLD.case_id;
 END;
CREATE TRIGGER IF NOT EXISTS candidate_delete INSTEAD OF DELETE ON release_candidates
 BEGIN DELETE FROM release_candidate_refs WHERE release_id=OLD.release_id AND case_id=OLD.case_id; END;
"""
MEMBERSHIPS="""
CREATE TABLE IF NOT EXISTS dyad_membership_refs(
 run_id TEXT NOT NULL REFERENCES runs,membership_key TEXT NOT NULL,
 dyad_id TEXT REFERENCES dyad_registry,child_id TEXT,state TEXT NOT NULL,
 value_hash TEXT NOT NULL REFERENCES run_payload_values,PRIMARY KEY(run_id,membership_key));
CREATE UNIQUE INDEX IF NOT EXISTS dyad_one_child_per_run ON dyad_membership_refs(run_id,child_id) WHERE child_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS dyad_one_mapping_per_run ON dyad_membership_refs(run_id,dyad_id) WHERE dyad_id IS NOT NULL;
CREATE VIEW IF NOT EXISTS dyad_memberships AS
 SELECT r.run_id,r.membership_key,r.dyad_id,r.child_id,r.state,v.payload_json
 FROM dyad_membership_refs r JOIN run_payload_values v ON v.value_hash=r.value_hash;
CREATE TRIGGER IF NOT EXISTS membership_insert INSTEAD OF INSERT ON dyad_memberships
 BEGIN INSERT INTO dyad_membership_refs VALUES(NEW.run_id,NEW.membership_key,NEW.dyad_id,NEW.child_id,NEW.state,study2_run_value(NEW.payload_json)); END;
CREATE TRIGGER IF NOT EXISTS membership_update INSTEAD OF UPDATE ON dyad_memberships
 BEGIN
 SELECT CASE WHEN NEW.run_id IS NOT OLD.run_id OR NEW.membership_key IS NOT OLD.membership_key
 THEN RAISE(ABORT,'Family run identity is immutable') END;
 UPDATE dyad_membership_refs SET dyad_id=NEW.dyad_id,child_id=NEW.child_id,state=NEW.state,value_hash=study2_run_value(NEW.payload_json)
 WHERE run_id=OLD.run_id AND membership_key=OLD.membership_key;
 END;
CREATE TRIGGER IF NOT EXISTS membership_delete INSTEAD OF DELETE ON dyad_memberships
 BEGIN DELETE FROM dyad_membership_refs WHERE run_id=OLD.run_id AND membership_key=OLD.membership_key; END;
"""


def register(db):
    def value(payload):
        h=hashlib.sha256(payload.encode()).hexdigest()
        old=db.execute('SELECT payload_json FROM run_payload_values WHERE value_hash=?',(h,)).fetchone()
        if old and old[0]!=payload:raise PipelineError('Run payload hash collision or corruption')
        if not old:db.execute('INSERT INTO run_payload_values VALUES(?,?)',(h,payload))
        return h
    db.create_function('study2_run_value',1,value)


def install_candidates(db):
    register(db)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='release_candidate_refs'").fetchone():return
    db.executescript(BASE+CANDIDATES)


def install_memberships(db):
    register(db)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='dyad_membership_refs'").fetchone():return
    db.executescript(BASE+MEMBERSHIPS)


def table_digest(db,table,columns):
    h=hashlib.sha256();n=0
    for row in db.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+','.join(columns)):
        h.update((dumps(list(row))+'\n').encode());n+=1
    return {'rows':n,'sha256':h.hexdigest()}


def migrate(db,progress=None):
    """Resume a private conversion, dropping old bytes only after exact row proof."""
    register(db);report={}
    for table,installer in [('release_candidates',install_candidates),('dyad_memberships',install_memberships)]:
        legacy=table+'_legacy';kind=db.execute('SELECT type FROM sqlite_master WHERE name=?',(table,)).fetchone()
        if kind and kind[0]=='table':
            db.execute('ALTER TABLE '+table+' RENAME TO '+legacy);db.commit()
            for index in ['dyad_one_child_per_run','dyad_one_mapping_per_run']:
                if table=='dyad_memberships':db.execute('DROP INDEX IF EXISTS '+index)
            db.commit();installer(db)
        if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(legacy,)).fetchone():continue
        columns=[r[1] for r in db.execute('PRAGMA table_info('+legacy+')')]
        before=table_digest(db,legacy,columns)
        keys=columns[:2]
        query='SELECT o.* FROM '+legacy+' o WHERE NOT EXISTS(SELECT 1 FROM '+table+' n WHERE '+ ' AND '.join('n.'+k+'=o.'+k for k in keys)+')'
        n=0
        for row in db.execute(query):
            db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in columns)+')',tuple(row));n+=1
            if n%5000==0:db.commit()
        db.commit();after=table_digest(db,table,columns)
        if before!=after:raise PipelineError('Run payload conversion differs; original table retained')
        db.execute('DROP TABLE '+legacy);db.commit();report[table]={'before':before,'after':after}
        if progress:progress(report)
    return report
