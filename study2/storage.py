"""Versioned value storage. Shared bytes never imply shared participant identity."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .common import PipelineError, dumps


RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_schema(component TEXT PRIMARY KEY, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS record_values(
 value_hash TEXT PRIMARY KEY,
 payload_json TEXT,
 source_version TEXT REFERENCES submission_versions(version_id),
 source_field TEXT CHECK(source_field IN ('raw_json','standard_json')),
 CHECK((payload_json IS NOT NULL AND source_version IS NULL AND source_field IS NULL)
    OR (payload_json IS NULL AND source_version IS NOT NULL AND source_field IS NOT NULL)));
CREATE TABLE IF NOT EXISTS version_value_refs(
 version_id TEXT PRIMARY KEY REFERENCES submission_versions(version_id),
 raw_hash TEXT NOT NULL REFERENCES record_values(value_hash),
 answer_hash TEXT NOT NULL REFERENCES record_values(value_hash));
CREATE TABLE IF NOT EXISTS normalized_record_refs(
 run_id TEXT NOT NULL REFERENCES runs(run_id),
 submission_id TEXT NOT NULL REFERENCES submissions(submission_id),
 version_id TEXT REFERENCES submission_versions(version_id),
 record_hash TEXT NOT NULL REFERENCES record_values(value_hash),
 raw_hash TEXT REFERENCES record_values(value_hash),
 answer_hash TEXT REFERENCES record_values(value_hash),
 role TEXT, source_label TEXT, claimed_wave TEXT, selected_wave TEXT,
 observed_at TEXT, status TEXT, child_id TEXT,
 PRIMARY KEY(run_id,submission_id));
CREATE INDEX IF NOT EXISTS record_source_metadata ON normalized_record_refs(run_id,role,claimed_wave,source_label);
CREATE VIEW IF NOT EXISTS record_value_json AS
 SELECT o.value_hash, CASE WHEN o.payload_json IS NOT NULL THEN o.payload_json
    WHEN o.source_field='raw_json' THEN v.raw_json ELSE v.standard_json END AS payload_json
 FROM record_values o LEFT JOIN submission_versions v ON v.version_id=o.source_version;
CREATE VIEW IF NOT EXISTS normalized_records AS
 SELECT r.run_id,r.submission_id,
 CASE WHEN r.raw_hash IS NOT NULL AND r.answer_hash IS NOT NULL THEN
   json_set(CASE WHEN m.payload_json IS NOT NULL THEN m.payload_json WHEN m.source_field='raw_json' THEN mv.raw_json ELSE mv.standard_json END,
   '$.raw',json(CASE WHEN raw.payload_json IS NOT NULL THEN raw.payload_json WHEN raw.source_field='raw_json' THEN rv.raw_json ELSE rv.standard_json END),
   '$.answer',json(CASE WHEN a.payload_json IS NOT NULL THEN a.payload_json WHEN a.source_field='raw_json' THEN av.raw_json ELSE av.standard_json END))
 WHEN r.raw_hash IS NOT NULL THEN json_set(CASE WHEN m.payload_json IS NOT NULL THEN m.payload_json WHEN m.source_field='raw_json' THEN mv.raw_json ELSE mv.standard_json END,
   '$.raw',json(CASE WHEN raw.payload_json IS NOT NULL THEN raw.payload_json WHEN raw.source_field='raw_json' THEN rv.raw_json ELSE rv.standard_json END))
 WHEN r.answer_hash IS NOT NULL THEN json_set(CASE WHEN m.payload_json IS NOT NULL THEN m.payload_json WHEN m.source_field='raw_json' THEN mv.raw_json ELSE mv.standard_json END,
   '$.answer',json(CASE WHEN a.payload_json IS NOT NULL THEN a.payload_json WHEN a.source_field='raw_json' THEN av.raw_json ELSE av.standard_json END))
 ELSE CASE WHEN m.payload_json IS NOT NULL THEN m.payload_json WHEN m.source_field='raw_json' THEN mv.raw_json ELSE mv.standard_json END END AS payload_json
 FROM normalized_record_refs r JOIN record_values m ON m.value_hash=r.record_hash
 LEFT JOIN submission_versions mv ON mv.version_id=m.source_version
 LEFT JOIN record_values raw ON raw.value_hash=r.raw_hash
 LEFT JOIN submission_versions rv ON rv.version_id=raw.source_version
 LEFT JOIN record_values a ON a.value_hash=r.answer_hash
 LEFT JOIN submission_versions av ON av.version_id=a.source_version;
CREATE TRIGGER IF NOT EXISTS normalized_records_insert INSTEAD OF INSERT ON normalized_records
 BEGIN SELECT study2_store_record(NEW.run_id,NEW.submission_id,NEW.payload_json,0); END;
CREATE TRIGGER IF NOT EXISTS normalized_records_update INSTEAD OF UPDATE ON normalized_records
 BEGIN
 SELECT CASE WHEN NEW.run_id!=OLD.run_id OR NEW.submission_id!=OLD.submission_id
 THEN RAISE(ABORT,'Normalized record identity is immutable') END;
 SELECT study2_store_record(NEW.run_id,NEW.submission_id,NEW.payload_json,1);
 END;
CREATE TRIGGER IF NOT EXISTS normalized_records_delete INSTEAD OF DELETE ON normalized_records
 BEGIN DELETE FROM normalized_record_refs WHERE run_id=OLD.run_id AND submission_id=OLD.submission_id; END;
CREATE TRIGGER IF NOT EXISTS record_values_immutable BEFORE UPDATE ON record_values
 BEGIN SELECT RAISE(ABORT,'Stored record values are immutable'); END;
INSERT OR IGNORE INTO storage_schema VALUES('records',2);
INSERT OR IGNORE INTO storage_schema VALUES('record_view',3);
"""


def records_v2(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name='normalized_record_refs'").fetchone() is not None


def register_record_writer(db):
    from .compact_storage import register
    register(db)
    def write(run_id, sid, payload, replace):
        store_record(db, run_id, sid, json.loads(payload), replace=bool(replace))
        return 1
    db.create_function('study2_store_record', 4, write)


def install_records(db):
    register_record_writer(db)
    from .compact_storage import migrate
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_record_refs_legacy' AND type='table'").fetchone():
        migrate(db)
        return
    marker=db.execute("SELECT 1 FROM sqlite_master WHERE name='storage_schema' AND type='table'").fetchone()
    current=db.execute("SELECT version FROM storage_schema WHERE component='record_view'").fetchone() if marker else None
    if current and current[0] in {3,4,5}:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_records' AND type='view'").fetchone():migrate(db)
        return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_records' AND type='view'").fetchone():
        db.execute('DROP VIEW normalized_records')
    db.executescript(RECORD_SCHEMA)
    migrate(db)


def _value(db, value, source_version=None, source_field=None):
    payload = dumps(value)
    h = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    old = db.execute('SELECT payload_json FROM record_value_json WHERE value_hash=?', (h,)).fetchone()
    if old:
        # Source JSON remains byte-exact in its original table. Legacy strings
        # may use different whitespace, so compare their canonical values.
        if old[0] != payload and dumps(json.loads(old[0])) != payload:
            raise PipelineError('Record value hash collision or corrupt stored content')
        return h
    if source_version:
        db.execute('INSERT INTO record_values VALUES(?,NULL,?,?)', (h, source_version, source_field))
    else:
        db.execute('INSERT INTO record_values VALUES(?,?,NULL,NULL)', (h, payload))
    return h


def _version_values(db, version_id):
    if not version_id:
        return None
    row = db.execute('SELECT raw_hash,answer_hash FROM version_value_refs WHERE version_id=?', (version_id,)).fetchone()
    if row:
        return tuple(row)
    source = db.execute('SELECT raw_json,standard_json FROM submission_versions WHERE version_id=?', (version_id,)).fetchone()
    if not source:
        return None
    raw = _value(db, json.loads(source[0]), version_id, 'raw_json')
    answer = _value(db, json.loads(source[1]), version_id, 'standard_json')
    db.execute('INSERT INTO version_value_refs VALUES(?,?,?)', (version_id,raw,answer))
    return raw, answer


def store_record(db, run_id, sid, record, replace=False):
    if not records_v2(db):
        verb = 'INSERT OR REPLACE' if replace else 'INSERT'
        db.execute(verb+' INTO normalized_records VALUES(?,?,?)', (run_id,sid,dumps(record)))
        return
    linked = db.execute('SELECT version_id FROM run_records WHERE run_id=? AND submission_id=?', (run_id,sid)).fetchone()
    version_id = linked[0] if linked else record.get('version_id')
    values = _version_values(db, version_id)
    if values is None:
        version_id = None
    # Original source values have already been registered as references. Values
    # changed by controlled corrections are stored independently and immutably.
    raw = _value(db, record['raw']) if 'raw' in record else None
    answer = _value(db, record['answer']) if 'answer' in record else None
    meta = _value(db, {k:v for k,v in record.items() if k not in {'raw','answer'}})
    source_label = record.get('source_label')
    if source_label is None and isinstance(record.get('answer'),dict):
        source_label = record['answer'].get('Survey')
    parameters = (run_id,sid,version_id,meta,raw,answer,record.get('role'),source_label,
                  record.get('claimed_wave'),record.get('selected_wave'),record.get('observed_at'),
                  record.get('status'),record.get('child_id'))
    from .compact_storage import enabled,store
    if enabled(db):store(db,parameters,replace)
    else:
        verb = 'INSERT OR REPLACE' if replace else 'INSERT'
        db.execute(verb+' INTO normalized_record_refs VALUES('+','.join('?' for _ in parameters)+')',parameters)


def read_records(db, run_id, include_raw=True):
    """Reconstruct legacy dictionaries without loading raw answers unnecessarily."""
    if not records_v2(db):
        value = "payload_json" if include_raw else "json_remove(payload_json,'$.raw')"
        for row in db.execute(f'SELECT {value} FROM normalized_records WHERE run_id=? ORDER BY submission_id', (run_id,)):
            yield json.loads(row[0])
        return
    def content(alias,version):
        return f"CASE WHEN {alias}.payload_json IS NOT NULL THEN {alias}.payload_json WHEN {alias}.source_field='raw_json' THEN {version}.raw_json ELSE {version}.standard_json END"
    raw_column = ','+content('raw','rv') if include_raw else ''
    raw_join = (' LEFT JOIN record_values raw ON raw.value_hash=r.raw_hash'
                ' LEFT JOIN submission_versions rv ON rv.version_id=raw.source_version') if include_raw else ''
    query = ('SELECT '+content('m','mv')+','+content('a','av')+',r.answer_hash'+raw_column+
             ' FROM normalized_record_refs r JOIN record_values m ON m.value_hash=r.record_hash'
             ' LEFT JOIN submission_versions mv ON mv.version_id=m.source_version'
             ' LEFT JOIN record_values a ON a.value_hash=r.answer_hash'
             ' LEFT JOIN submission_versions av ON av.version_id=a.source_version'+raw_join+
             ' WHERE r.run_id=? ORDER BY r.submission_id')
    for row in db.execute(query,(run_id,)):
        record = json.loads(row[0])
        if row[2] is not None:
            record['answer'] = json.loads(row[1])
        if include_raw and row[3] is not None:
            record['raw'] = json.loads(row[3])
        yield record


def record_metadata(db, run_id):
    if records_v2(db):
        sql='SELECT submission_id,observed_at,claimed_wave FROM normalized_record_refs WHERE run_id=? ORDER BY submission_id'
    else:
        sql=("SELECT submission_id,json_extract(payload_json,'$.observed_at') AS observed_at,"
             "json_extract(payload_json,'$.claimed_wave') AS claimed_wave FROM normalized_records WHERE run_id=? ORDER BY submission_id")
    return [dict(row) for row in db.execute(sql,(run_id,))]


def imported_source_counts(db, run_id):
    if records_v2(db):
        sql='SELECT source_label,role,claimed_wave AS wave,count(*) AS submissions FROM normalized_record_refs WHERE run_id=? GROUP BY 1,2,3'
    else:
        sql=("SELECT COALESCE(json_extract(payload_json,'$.source_label'),json_extract(payload_json,'$.answer.Survey')) AS source_label,"
             "json_extract(payload_json,'$.role') AS role,json_extract(payload_json,'$.claimed_wave') AS wave,count(*) AS submissions "
             "FROM normalized_records WHERE run_id=? GROUP BY 1,2,3")
    return [dict(row) for row in db.execute(sql,(run_id,))]


def _record_digest(db, table):
    h=hashlib.sha256();count=0
    for run_id,sid,payload in db.execute(f'SELECT run_id,submission_id,payload_json FROM {table} ORDER BY run_id,submission_id'):
        h.update((dumps([run_id,sid,json.loads(payload)])+'\n').encode('utf-8'));count+=1
    return {'rows':count,'sha256':h.hexdigest()}


def migrate_records(db, progress=None):
    """Run on an offline copy. Keep the legacy table until reconstruction proves equal."""
    legacy='normalized_records_legacy'
    kind=db.execute("SELECT type FROM sqlite_master WHERE name='normalized_records'").fetchone()
    saved=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(legacy,)).fetchone()
    if kind and kind[0]=='table':
        db.execute('ALTER TABLE normalized_records RENAME TO '+legacy);db.commit()
        saved=True
    if not saved:
        if records_v2(db):return {'already_migrated':True}
        raise PipelineError('Legacy record storage is missing')
    install_records(db)
    before=_record_digest(db,legacy)
    total=0
    cursor=db.execute('SELECT o.run_id,o.submission_id,o.payload_json FROM '+legacy+' o '
                      'LEFT JOIN normalized_record_refs r ON r.run_id=o.run_id AND r.submission_id=o.submission_id '
                      'WHERE r.run_id IS NULL ORDER BY o.run_id,o.submission_id')
    try:
        for run_id,sid,payload in cursor:
            store_record(db,run_id,sid,json.loads(payload));total+=1
            if total%5000==0:
                db.commit()
                if progress:progress({'migrated_records':total})
        db.commit()
    except BaseException:
        db.rollback();raise
    after=_record_digest(db,'normalized_records')
    if before!=after:
        raise PipelineError('Historical reconstructed records differ; legacy storage retained')
    db.execute('DROP TABLE '+legacy);db.commit()
    if progress:progress({'record_preservation':after})
    return {'before':before,'after':after,'records':total}
