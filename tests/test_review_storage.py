import copy
import json
import sqlite3

import pytest

from study2.common import dumps
from study2.review_core import SCHEMA
from study2.review_storage import migrate_reviews, prepare_workspace, task_heads


def task(tid,case):
    return {'task_id':tid,'revision':1,'reviewer':'synthetic-reviewer','independent':False,
            'snapshot':{'case':{'case_id':case},'records':{'synthetic':{'field':'繁體中文','empty':'','null':None}},
                        'candidates':[],'release_id':'synthetic-release','rules_hash':'synthetic-rules',
                        'signature':'synthetic-signature','original_manual_constraints':[]}}


def populate(db):
    tasks=[task('synthetic-first','first-case'),task('synthetic-second','second-case')]
    pkg={'package_id':'synthetic-package','tasks':tasks,'contract':{'hash':'original-contract'}}
    db.execute('INSERT INTO packages VALUES(?,?,?,?)',('synthetic-package','now','synthetic-reviewer',dumps({'tasks':[]})))
    for t in tasks:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(t['task_id'],'synthetic-package',t['snapshot']['case']['case_id'],
                   'synthetic-reviewer',1,'assigned',dumps(t)))
    db.execute('UPDATE packages SET payload=? WHERE id=?',(dumps(pkg),'synthetic-package'))
    db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',('synthetic-answer','synthetic-first',1,'now',dumps({'verdict':'資料不足'})))
    db.commit()
    return tasks,pkg


def database(tmp_path):
    db=sqlite3.connect(tmp_path/'review.sqlite');db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');prepare_workspace(db,SCHEMA)
    return db


def test_shared_component_preserves_task_identity_and_original_package_snapshot(tmp_path):
    db=database(tmp_path);tasks,pkg=populate(db)
    assert db.execute('SELECT count(*) FROM review_components').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM review_task_values').fetchone()[0]==2
    assert json.loads(db.execute('SELECT payload FROM packages').fetchone()[0])==pkg
    assert [json.loads(r[0]) for r in db.execute('SELECT payload FROM tasks ORDER BY id')]==tasks
    changed=copy.deepcopy(tasks[0]);changed['snapshot']['records']['synthetic']['field']='changed'
    with db:db.execute('UPDATE tasks SET payload=? WHERE id=?',(dumps(changed),'synthetic-first'))
    assert json.loads(db.execute('SELECT payload FROM packages').fetchone()[0])==pkg
    assert db.execute('SELECT count(*) FROM review_components').fetchone()[0]==2
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()


def test_task_state_updates_do_not_duplicate_evidence_and_heads_are_small(tmp_path):
    db=database(tmp_path);populate(db)
    count=db.execute('SELECT count(*) FROM review_task_values').fetchone()[0]
    with db:db.execute("UPDATE tasks SET state='submitted' WHERE id='synthetic-first'")
    assert db.execute('SELECT count(*) FROM review_task_values').fetchone()[0]==count
    heads=task_heads(db)
    assert all(set(row.keys())=={'id','case_id','signature'} for row in heads)
    with pytest.raises(sqlite3.IntegrityError,match='immutable'):
        db.execute('UPDATE review_components SET payload_json=payload_json')
    db.rollback();db.close()


def test_migration_preserves_all_payloads_reviews_and_states(tmp_path):
    db=sqlite3.connect(tmp_path/'review.sqlite');db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
    tasks,pkg=populate(db)
    db.execute("UPDATE tasks SET state='cancelled' WHERE id='synthetic-second'");db.commit()
    answer=tuple(db.execute('SELECT * FROM reviews').fetchone())
    result=migrate_reviews(db)
    assert result['before']==result['after']
    assert tuple(db.execute('SELECT * FROM reviews').fetchone())==answer
    assert json.loads(db.execute('SELECT payload FROM packages').fetchone()[0])==pkg
    assert db.execute("SELECT state FROM tasks WHERE id='synthetic-second'").fetchone()[0]=='cancelled'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert migrate_reviews(db)['already_migrated']
    db.close()


def test_empty_packages_and_literal_snapshots_roundtrip(tmp_path):
    db=database(tmp_path)
    with db:
        db.execute('INSERT INTO packages VALUES(?,?,?,?)',('empty','now','synthetic','{}'))
        for i,snapshot in enumerate([None,{}, {'case':None} ]):
            value={'task_id':'literal-'+str(i),'snapshot':snapshot}
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',('literal-'+str(i),'empty','case','synthetic',1,'assigned',dumps(value)))
    assert json.loads(db.execute('SELECT payload FROM packages').fetchone()[0])=={}
    payloads=[json.loads(r[0]) for r in db.execute('SELECT payload FROM tasks ORDER BY id')]
    assert [p['snapshot'] for p in payloads]==[None,{}, {'case':None}]
    db.close()
