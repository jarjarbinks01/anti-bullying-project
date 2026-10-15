import json
import sqlite3

import pytest

from study2.common import dumps
from study2.storage import (imported_source_counts, migrate_records, read_records,
                            record_metadata, records_v2, store_record)
from study2.store import SCHEMA, connect, ingest
from test_identity_and_time import rec
from test_store_and_review import database, source


def test_shared_values_preserve_distinct_submissions_and_historical_runs(tmp_path):
    db=database(tmp_path)
    rows=[source(rec('synthetic-a')),source(rec('synthetic-b'))]
    with db:
        ingest(db,'run',rows)
        for row in rows:store_record(db,'run',row['submission_id'],row)
    count=db.execute('SELECT count(*) FROM record_values').fetchone()[0]
    with db:
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('second','fp','later','validated','{}',None,None))
        ingest(db,'second',rows)
        for row in rows:store_record(db,'second',row['submission_id'],row)
    assert db.execute('SELECT count(*) FROM record_values').fetchone()[0]==count
    assert db.execute('SELECT count(*) FROM submissions').fetchone()[0]==2
    assert db.execute('SELECT count(*) FROM normalized_records').fetchone()[0]==4
    assert list(read_records(db,'run'))==[json.loads(dumps(r)) for r in rows]
    assert list(read_records(db,'second'))==[json.loads(dumps(r)) for r in rows]
    # Raw and unchanged standard answers reference their original versions,
    # rather than adding another large JSON copy to the object table.
    assert db.execute('SELECT count(*) FROM record_values WHERE source_version IS NOT NULL').fetchone()[0]>=1
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()


def test_legacy_sql_updates_and_corrected_answers_preserve_original_source(tmp_path):
    db=database(tmp_path);row=source(rec('synthetic'))
    with db:
        ingest(db,'run',[row]);db.execute('INSERT INTO normalized_records VALUES(?,?,?)',('run',row['submission_id'],dumps(row)))
    before=tuple(db.execute('SELECT raw_json,standard_json FROM submission_versions').fetchone())
    corrected=json.loads(dumps(row));corrected['answer']['student_PHQ_01']=2
    with db:
        db.execute('UPDATE normalized_records SET payload_json=? WHERE submission_id=?',(dumps(corrected),row['submission_id']))
    assert list(read_records(db,'run'))==[corrected]
    assert tuple(db.execute('SELECT raw_json,standard_json FROM submission_versions').fetchone())==before
    with pytest.raises(sqlite3.IntegrityError,match='immutable'):
        db.execute('UPDATE record_values SET payload_json=payload_json')
    db.rollback();db.close()


def test_metadata_projections_match_legacy_json_null_and_fallback_semantics(tmp_path):
    db=database(tmp_path);row=source(rec('synthetic'))
    row.update(claimed_wave='T0',selected_wave=None,source_label=None)
    row['answer']['Survey']='synthetic-source'
    with db:ingest(db,'run',[row]);store_record(db,'run',row['submission_id'],row)
    assert record_metadata(db,'run')==[{'submission_id':row['submission_id'],'observed_at':row['observed_at'],'claimed_wave':'T0'}]
    assert imported_source_counts(db,'run')==[{'source_label':'synthetic-source','role':row['role'],'wave':'T0','submissions':1}]
    compact=list(read_records(db,'run',include_raw=False))[0]
    assert 'raw' not in compact and compact['answer']==row['answer']
    db.close()


def test_offline_migration_preserves_legacy_raw_override_and_nullable_fields(tmp_path):
    path=tmp_path/'study2.sqlite';db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('run','fp','now','published','{}',None,None))
    row=source(rec('synthetic'));ingest(db,'run',[row])
    # Legacy QA and historical callers may have frozen raw data that differs
    # from the source-version representation. Preserve it rather than assume.
    row['raw']={'original':'繁體中文','null':None,'empty':'','number':1.0}
    db.execute('INSERT INTO normalized_records VALUES(?,?,?)',('run',row['submission_id'],dumps(row)))
    db.commit();source_before=tuple(db.execute('SELECT raw_json,standard_json FROM submission_versions').fetchone())
    result=migrate_records(db)
    assert result['before']==result['after'] and result['after']['rows']==1
    assert records_v2(db)
    assert list(read_records(db,'run'))==[json.loads(dumps(row))]
    assert tuple(db.execute('SELECT raw_json,standard_json FROM submission_versions').fetchone())==source_before
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_records_legacy'").fetchone()
    assert migrate_records(db)['already_migrated']
    db.close()


def test_interrupted_migration_resumes_and_verifies_all_records(tmp_path):
    db=sqlite3.connect(tmp_path/'study2.sqlite');db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('run','fp','now','published','{}',None,None))
    rows=[source(rec('synthetic-'+str(i))) for i in range(3)]
    ingest(db,'run',rows)
    for row in rows:db.execute('INSERT INTO normalized_records VALUES(?,?,?)',('run',row['submission_id'],dumps(row)))
    db.commit()
    from unittest.mock import patch
    import study2.storage as storage
    original=storage.store_record;calls=[]
    def fail_after_first(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise OSError('synthetic migration interruption')
        original(*args,**kwargs);db.commit()
    with patch('study2.storage.store_record',side_effect=fail_after_first),pytest.raises(OSError):migrate_records(db)
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_records_legacy'").fetchone()
    result=migrate_records(db)
    assert result['after']['rows']==3
    assert list(read_records(db,'run'))==[json.loads(dumps(r)) for r in rows]
    db.close()


@pytest.mark.parametrize('phase',['renamed','schema_installed','references_copied','legacy_dropped'])
def test_resume_compaction_from_committed_legacy_intermediate_states(tmp_path,phase):
    from study2 import compact_storage
    from study2.storage import RECORD_SCHEMA
    path=tmp_path/'study2.sqlite';db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.executescript(SCHEMA)
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('run','fp','now','published','{}',None,None))
    rows=[source(rec('synthetic-'+str(i))) for i in range(3)]
    ingest(db,'run',rows)
    for row in rows:db.execute('INSERT INTO normalized_records VALUES(?,?,?)',('run',row['submission_id'],dumps(row)))
    db.execute('ALTER TABLE normalized_records RENAME TO normalized_records_legacy');db.commit()
    db.executescript(RECORD_SCHEMA)
    store_record(db,'run',rows[0]['submission_id'],rows[0]);db.commit()
    original=[tuple(r) for r in db.execute('SELECT * FROM submission_versions ORDER BY version_id')]
    db.execute('DROP VIEW normalized_records')
    db.execute('ALTER TABLE normalized_record_refs RENAME TO normalized_record_refs_legacy');db.commit()
    if phase!='renamed':
        db.executescript(compact_storage.SCHEMA)
    if phase in {'references_copied','legacy_dropped'}:
        for row in db.execute('SELECT * FROM normalized_record_refs_legacy'):compact_storage.store(db,tuple(row))
        db.commit()
    if phase=='legacy_dropped':db.execute('DROP TABLE normalized_record_refs_legacy');db.commit()
    db.close()
    # Reopen the actual persisted layout, without relying on in-memory phase state.
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    result=migrate_records(db)
    assert result['before']==result['after'] and result['after']['rows']==3
    assert list(read_records(db,'run'))==[json.loads(dumps(r)) for r in rows]
    assert [tuple(r) for r in db.execute('SELECT * FROM submission_versions ORDER BY version_id')]==original
    assert db.execute("SELECT version FROM storage_schema WHERE component='record_view'").fetchone()[0]==5
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_record_refs_legacy'").fetchone()
    db.close()
