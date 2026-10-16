"""Exact row-preserving primary-key compaction for private migrations."""
import re

from .common import PipelineError
from .run_storage import table_digest


def migrate(db):
    """Views are temporarily rebuilt inside one transaction; no rows are dropped."""
    report={}
    targets=['run_records','identity_members','release_candidate_refs']
    definitions=db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('view','trigger') AND sql IS NOT NULL").fetchall()
    needed=[]
    for table in targets:
        row=db.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()
        if row and 'WITHOUT ROWID' not in row[0].upper():needed.append((table,row[0]))
    if not needed:return {'already_dense':True}
    db.commit();db.execute('BEGIN IMMEDIATE')
    try:
        for kind,name,_ in definitions:
            if kind=='view':db.execute('DROP VIEW "'+name+'"')
        for kind,name,_ in definitions:
            if kind=='trigger' and db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone():db.execute('DROP TRIGGER "'+name+'"')
        for table,sql in needed:
            columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
            before=table_digest(db,table,columns);temporary=table+'_dense'
            create=re.sub(r'^(CREATE TABLE)(?: IF NOT EXISTS)?\s+(?:"'+table+'"|'+table+r')',r'\1 '+temporary,sql,count=1)
            db.execute(create.rstrip().rstrip(';')+' WITHOUT ROWID')
            db.execute('INSERT INTO '+temporary+' SELECT * FROM '+table)
            after=table_digest(db,temporary,columns)
            if before!=after:raise PipelineError('Dense primary-key copy differs')
            db.execute('DROP TABLE '+table);db.execute('ALTER TABLE '+temporary+' RENAME TO '+table)
            report[table]={'before':before,'after':after}
        for kind,_,sql in definitions:
            if kind=='view':db.execute(sql)
        for kind,_,sql in definitions:
            if kind=='trigger':db.execute(sql)
        db.commit()
    except BaseException:db.rollback();raise
    return report
