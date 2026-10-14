import json
import sqlite3

import pytest

from study2.common import dumps
from study2.run_storage import migrate,table_digest
from study2.store import SCHEMA,connect


def legacy(db):
    db.executescript(SCHEMA)
    for rid in ['synthetic-first','synthetic-second']:
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(rid,'fp','now','published','{}',None,None))
        db.execute('INSERT INTO releases VALUES(?,?,?,?,?)',(rid,rid,'now','synthetic','{}'))
        db.execute('INSERT INTO release_candidates VALUES(?,?,?)',(rid,'synthetic-case',dumps({'unicode':'繁體中文','empty':'','null':None,'values':[1.0,1]})))
    db.commit()


def test_candidate_migration_preserves_every_value_and_shares_across_runs(tmp_path):
    db=sqlite3.connect(tmp_path/'old.sqlite');legacy(db)
    proof=migrate(db)
    assert proof['release_candidates']['before']==proof['release_candidates']['after']
    assert db.execute('SELECT count(*) FROM release_candidates').fetchone()[0]==2
    assert db.execute('SELECT count(*) FROM run_payload_values').fetchone()[0]==1
    assert json.loads(db.execute('SELECT payload_json FROM release_candidates').fetchone()[0])['values']==[1.0,1]
    with pytest.raises(sqlite3.IntegrityError,match='immutable'):db.execute('UPDATE run_payload_values SET payload_json=payload_json')
    db.rollback();db.close()


def test_interrupted_candidate_conversion_resumes_without_losing_original_rows(tmp_path):
    class Interrupting(sqlite3.Connection):
        calls=0;interrupted=False
        def execute(self,sql,*args,**kwargs):
            if sql.startswith('INSERT INTO release_candidates VALUES') and self.interrupted:
                self.calls+=1
                if self.calls==2:raise OSError('synthetic payload migration interruption')
                result=super().execute(sql,*args,**kwargs);self.commit();return result
            return super().execute(sql,*args,**kwargs)
    db=sqlite3.connect(tmp_path/'old.sqlite',factory=Interrupting);legacy(db);db.interrupted=True
    with pytest.raises(OSError):migrate(db)
    assert db.execute('SELECT count(*) FROM release_candidates_legacy').fetchone()[0]==2
    db.interrupted=False;proof=migrate(db)
    assert proof['release_candidates']['before']==proof['release_candidates']['after']
    assert db.execute('SELECT count(*) FROM release_candidates').fetchone()[0]==2
    db.close()


def test_compact_record_links_preserve_original_adapter_and_share_projections(tmp_path):
    from study2.storage import store_record
    from study2.store import ingest
    from test_identity_and_time import rec
    from test_store_and_review import source
    db=connect(tmp_path);row=source(rec('synthetic'))
    for rid in ['synthetic-first','synthetic-second']:
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(rid,'fp','now','published','{}',None,None))
        ingest(db,rid,[row]);store_record(db,rid,row['submission_id'],row)
    assert db.execute('SELECT count(*) FROM processed_run_refs').fetchone()[0]==2
    assert db.execute('SELECT count(*) FROM processed_record_values').fetchone()[0]==1
    rows=[json.loads(r[0]) for r in db.execute('SELECT payload_json FROM normalized_records ORDER BY run_id')]
    assert rows==[json.loads(dumps(row))]*2
    db.close()
