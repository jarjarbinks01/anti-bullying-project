"""Share unchanged record projections while retaining every source/run link."""
import hashlib

from .common import PipelineError,dumps

SCHEMA="""
CREATE TABLE IF NOT EXISTS processed_record_values(
 instance_hash TEXT PRIMARY KEY,version_id TEXT REFERENCES submission_versions,record_hash TEXT NOT NULL REFERENCES record_values,
 raw_hash TEXT REFERENCES record_values,answer_hash TEXT REFERENCES record_values,
 role TEXT,source_label TEXT,claimed_wave TEXT,selected_wave TEXT,observed_at TEXT,status TEXT,child_id TEXT);
CREATE TABLE IF NOT EXISTS processed_run_refs(
 run_id TEXT NOT NULL REFERENCES runs,submission_id TEXT NOT NULL REFERENCES submissions,
 instance_hash TEXT NOT NULL REFERENCES processed_record_values,
 PRIMARY KEY(run_id,submission_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS processed_source_metadata ON processed_record_values(role,claimed_wave,source_label);
CREATE VIEW IF NOT EXISTS normalized_record_refs AS
 SELECT r.run_id,r.submission_id,v.version_id,v.record_hash,v.raw_hash,v.answer_hash,
 v.role,v.source_label,v.claimed_wave,v.selected_wave,v.observed_at,v.status,v.child_id
 FROM processed_run_refs r JOIN processed_record_values v ON v.instance_hash=r.instance_hash;
CREATE TRIGGER IF NOT EXISTS compact_ref_insert INSTEAD OF INSERT ON normalized_record_refs
 BEGIN SELECT study2_compact_ref(NEW.run_id,NEW.submission_id,NEW.version_id,NEW.record_hash,NEW.raw_hash,NEW.answer_hash,
 NEW.role,NEW.source_label,NEW.claimed_wave,NEW.selected_wave,NEW.observed_at,NEW.status,NEW.child_id); END;
CREATE TRIGGER IF NOT EXISTS compact_ref_delete INSTEAD OF DELETE ON normalized_record_refs
 BEGIN DELETE FROM processed_run_refs WHERE run_id=OLD.run_id AND submission_id=OLD.submission_id; END;
CREATE TRIGGER IF NOT EXISTS processed_record_immutable BEFORE UPDATE ON processed_record_values
 BEGIN SELECT RAISE(ABORT,'Processed record projections are immutable'); END;
"""


def enabled(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='processed_run_refs'").fetchone() is not None


def store(db,parameters,replace=False):
    values=tuple(parameters[2:]);h=hashlib.sha256(dumps(list(values)).encode()).hexdigest()
    old=db.execute('SELECT version_id,record_hash,raw_hash,answer_hash,role,source_label,claimed_wave,selected_wave,observed_at,status,child_id FROM processed_record_values WHERE instance_hash=?',(h,)).fetchone()
    if old and tuple(old)!=values:raise PipelineError('Processed projection hash collision or corruption')
    if not old:db.execute('INSERT INTO processed_record_values VALUES('+','.join('?' for _ in range(12))+')',(h,*values))
    verb='INSERT OR REPLACE' if replace else 'INSERT'
    db.execute(verb+' INTO processed_run_refs VALUES(?,?,?)',(*parameters[:2],h))


def register(db):
    def write(*args):store(db,args);return 1
    db.create_function('study2_compact_ref',13,write)


def migrate(db):
    from .storage import RECORD_SCHEMA,register_record_writer
    from .run_storage import table_digest
    register(db)
    legacy='normalized_record_refs_legacy'
    if enabled(db) and 'version_id' in [r[1] for r in db.execute('PRAGMA table_info(processed_run_refs)')]:
        # Freeze the old adapter before moving the source version into values.
        db.execute('CREATE TABLE '+legacy+' AS SELECT * FROM normalized_record_refs');db.commit()
        db.execute('DROP VIEW normalized_records');db.execute('DROP VIEW normalized_record_refs')
        db.execute('DROP TABLE processed_run_refs');db.execute('DROP TABLE processed_record_values');db.commit()
        db.executescript(SCHEMA)
    kind=db.execute("SELECT type FROM sqlite_master WHERE name='normalized_record_refs'").fetchone()
    if kind and kind[0]=='table':
        db.execute('DROP VIEW IF EXISTS normalized_records')
        db.execute('ALTER TABLE normalized_record_refs RENAME TO '+legacy);db.commit()
        db.executescript(SCHEMA)
    if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(legacy,)).fetchone():return {'already_compact':True}
    columns=[r[1] for r in db.execute('PRAGMA table_info('+legacy+')')]
    before=table_digest(db,legacy,columns);n=0
    for row in db.execute('SELECT o.* FROM '+legacy+' o WHERE NOT EXISTS(SELECT 1 FROM processed_run_refs r WHERE r.run_id=o.run_id AND r.submission_id=o.submission_id)'):
        store(db,tuple(row));n+=1
        if n%5000==0:db.commit()
    db.commit();after=table_digest(db,'normalized_record_refs',columns)
    if before!=after:raise PipelineError('Compact run references differ; original references retained')
    db.execute('DROP TABLE '+legacy);db.commit()
    # Reuse the exact legacy reconstruction and writer contract.
    view=RECORD_SCHEMA[RECORD_SCHEMA.index('CREATE VIEW IF NOT EXISTS normalized_records'):]
    db.executescript(view)
    db.execute("INSERT OR REPLACE INTO storage_schema VALUES('record_view',5)");db.commit()
    register_record_writer(db)
    return {'before':before,'after':after}
