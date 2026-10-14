import sqlite3
from unittest.mock import patch

import pytest

from study2.common import PipelineError
from study2.dense_storage import migrate
from study2.store import SCHEMA


def database(path):
    db=sqlite3.connect(path);db.executescript(SCHEMA)
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',('synthetic-run','fp','now','validated','{}',None,None))
    db.execute('INSERT INTO children VALUES(?,?,?)',('synthetic-child','now','synthetic'))
    db.execute('INSERT INTO identity_members VALUES(?,?,?)',('synthetic-run','synthetic','synthetic-child'))
    db.commit();return db


def test_dense_primary_keys_preserve_every_legacy_association_and_constraints(tmp_path):
    db=database(tmp_path/'main.sqlite');proof=migrate(db)
    assert all(p['before']==p['after'] for p in proof.values())
    assert list(db.execute('SELECT * FROM identity_members'))==[('synthetic-run','synthetic','synthetic-child')]
    assert 'WITHOUT ROWID' in db.execute("SELECT sql FROM sqlite_master WHERE name='identity_members'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT INTO identity_members VALUES(?,?,?)',('synthetic-run','synthetic','synthetic-child'))
    db.rollback();assert migrate(db)['already_dense'];db.close()


def test_failed_dense_copy_rolls_back_tables_and_views(tmp_path):
    db=database(tmp_path/'main.sqlite');db.execute('CREATE VIEW synthetic_view AS SELECT * FROM identity_members');db.commit()
    from study2.dense_storage import table_digest
    calls=[]
    def changed(*args):
        result=table_digest(*args);calls.append(1)
        if len(calls)==2:result['sha256']='synthetic mismatch'
        return result
    with patch('study2.dense_storage.table_digest',side_effect=changed),pytest.raises(PipelineError):migrate(db)
    assert list(db.execute('SELECT * FROM synthetic_view'))==[('synthetic-run','synthetic','synthetic-child')]
    assert 'WITHOUT ROWID' not in db.execute("SELECT sql FROM sqlite_master WHERE name='identity_members'").fetchone()[0]
    db.close()
