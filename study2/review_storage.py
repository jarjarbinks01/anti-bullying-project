"""Immutable component evidence and task values with legacy SQL read views."""
from __future__ import annotations

import hashlib
import json

from .common import PipelineError, dumps


REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_schema(component TEXT PRIMARY KEY,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS review_components(component_hash TEXT PRIMARY KEY,payload_json TEXT NOT NULL,signature TEXT);
CREATE TABLE IF NOT EXISTS review_task_values(
 value_hash TEXT PRIMARY KEY,metadata_json TEXT NOT NULL,
 component_hash TEXT REFERENCES review_components(component_hash),case_json TEXT);
CREATE TABLE IF NOT EXISTS review_packages(
 id TEXT PRIMARY KEY,created_at TEXT,reviewer TEXT,metadata_json TEXT NOT NULL,tasks_present INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS review_tasks(
 id TEXT PRIMARY KEY,package_id TEXT REFERENCES review_packages(id),case_id TEXT,reviewer TEXT,
 revision INTEGER,state TEXT,value_hash TEXT NOT NULL REFERENCES review_task_values(value_hash));
CREATE INDEX IF NOT EXISTS review_tasks_case ON review_tasks(case_id,state);
CREATE TABLE IF NOT EXISTS review_package_task_refs(
 package_id TEXT REFERENCES review_packages(id),ordinal INTEGER,
 value_hash TEXT NOT NULL REFERENCES review_task_values(value_hash),PRIMARY KEY(package_id,ordinal));
CREATE VIEW IF NOT EXISTS review_task_payload AS
 SELECT v.value_hash,CASE WHEN v.component_hash IS NULL THEN v.metadata_json ELSE
 json_set(v.metadata_json,'$.snapshot',json(CASE WHEN v.case_json IS NULL THEN c.payload_json
 ELSE json_set(c.payload_json,'$.case',json(v.case_json)) END)) END AS payload
 FROM review_task_values v LEFT JOIN review_components c ON c.component_hash=v.component_hash;
CREATE VIEW IF NOT EXISTS tasks AS
 SELECT t.id,t.package_id,t.case_id,t.reviewer,t.revision,t.state,v.payload
 FROM review_tasks t JOIN review_task_payload v ON v.value_hash=t.value_hash;
CREATE VIEW IF NOT EXISTS packages AS
 SELECT p.id,p.created_at,p.reviewer,CASE WHEN p.tasks_present=0 THEN p.metadata_json ELSE
 json_set(p.metadata_json,'$.tasks',json((SELECT json_group_array(json(payload)) FROM
  (SELECT v.payload AS payload FROM review_package_task_refs r
   JOIN review_task_payload v ON v.value_hash=r.value_hash WHERE r.package_id=p.id ORDER BY r.ordinal)))) END AS payload
 FROM review_packages p;
CREATE TRIGGER IF NOT EXISTS review_packages_insert INSTEAD OF INSERT ON packages
 BEGIN SELECT study2_store_package(NEW.id,NEW.created_at,NEW.reviewer,NEW.payload,0); END;
CREATE TRIGGER IF NOT EXISTS review_packages_update INSTEAD OF UPDATE ON packages
 BEGIN
 SELECT CASE WHEN NEW.id!=OLD.id THEN RAISE(ABORT,'Package identity is immutable') END;
 SELECT study2_store_package(NEW.id,NEW.created_at,NEW.reviewer,NEW.payload,1);
 END;
CREATE TRIGGER IF NOT EXISTS review_tasks_insert INSTEAD OF INSERT ON tasks
 BEGIN SELECT study2_store_task(NEW.id,NEW.package_id,NEW.case_id,NEW.reviewer,NEW.revision,NEW.state,NEW.payload,0); END;
CREATE TRIGGER IF NOT EXISTS review_tasks_update INSTEAD OF UPDATE ON tasks
 BEGIN
 SELECT CASE WHEN NEW.id!=OLD.id THEN RAISE(ABORT,'Task identity is immutable') END;
 UPDATE review_tasks SET package_id=NEW.package_id,case_id=NEW.case_id,reviewer=NEW.reviewer,
 revision=NEW.revision,state=NEW.state WHERE id=OLD.id;
 SELECT CASE WHEN NEW.payload=OLD.payload THEN 1 ELSE
 study2_store_task(NEW.id,NEW.package_id,NEW.case_id,NEW.reviewer,NEW.revision,NEW.state,NEW.payload,1) END;
 END;
CREATE TRIGGER IF NOT EXISTS review_components_immutable BEFORE UPDATE ON review_components
 BEGIN SELECT RAISE(ABORT,'Review component evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS review_task_values_immutable BEFORE UPDATE ON review_task_values
 BEGIN SELECT RAISE(ABORT,'Frozen review task values are immutable'); END;
INSERT OR IGNORE INTO storage_schema VALUES('reviews',2);
"""


def reviews_v2(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_tasks'").fetchone() is not None


def register_review_writers(db):
    def package(pid,created,reviewer,payload,replace):
        store_package(db,pid,created,reviewer,json.loads(payload),bool(replace));return 1
    def task(tid,pid,cid,reviewer,revision,state,payload,replace):
        store_task(db,tid,pid,cid,reviewer,revision,state,json.loads(payload),bool(replace));return 1
    db.create_function('study2_store_package',5,package)
    db.create_function('study2_store_task',8,task)


def install_reviews(db):
    register_review_writers(db);db.executescript(REVIEW_SCHEMA)


def _component(db,body):
    payload=dumps(body);h=hashlib.sha256(payload.encode()).hexdigest()
    old=db.execute('SELECT payload_json FROM review_components WHERE component_hash=?',(h,)).fetchone()
    if old:
        if old[0]!=payload:raise PipelineError('Review evidence hash collision or corrupt content')
    else:db.execute('INSERT INTO review_components VALUES(?,?,?)',(h,payload,body.get('signature')))
    return h


def task_value(db,task):
    canonical=dumps(task);h=hashlib.sha256(canonical.encode()).hexdigest()
    old=db.execute('SELECT payload FROM review_task_payload WHERE value_hash=?',(h,)).fetchone()
    if old:
        if dumps(json.loads(old[0]))!=canonical:raise PipelineError('Frozen task hash collision or corrupt content')
        return h
    meta=dict(task);snapshot=meta.get('snapshot');component=None;case=None
    if isinstance(snapshot,dict):
        meta.pop('snapshot');body={k:v for k,v in snapshot.items() if k!='case'}
        component=_component(db,body)
        if 'case' in snapshot:case=dumps(snapshot['case'])
    db.execute('INSERT INTO review_task_values VALUES(?,?,?,?)',(h,dumps(meta),component,case))
    return h


def store_task(db,tid,pid,cid,reviewer,revision,state,task,replace=False):
    value=task_value(db,task);verb='INSERT OR REPLACE' if replace else 'INSERT'
    db.execute(verb+' INTO review_tasks VALUES(?,?,?,?,?,?,?)',(tid,pid,cid,reviewer,revision,state,value))


def store_package(db,pid,created,reviewer,package,replace=False):
    meta=dict(package);tasks=meta.get('tasks');present=isinstance(tasks,list)
    if present:meta.pop('tasks')
    if replace:
        db.execute('UPDATE review_packages SET created_at=?,reviewer=?,metadata_json=?,tasks_present=? WHERE id=?',
                   (created,reviewer,dumps(meta),int(present),pid))
        if not db.execute('SELECT 1 FROM review_packages WHERE id=?',(pid,)).fetchone():
            raise PipelineError('Package is missing during update')
        db.execute('DELETE FROM review_package_task_refs WHERE package_id=?',(pid,))
    else:db.execute('INSERT INTO review_packages VALUES(?,?,?,?,?)',(pid,created,reviewer,dumps(meta),int(present)))
    if present:
        for ordinal,task in enumerate(tasks):
            db.execute('INSERT INTO review_package_task_refs VALUES(?,?,?)',(pid,ordinal,task_value(db,task)))


def payload_digest(db,table):
    columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
    h=hashlib.sha256();count=0
    for row in db.execute('SELECT * FROM '+table+' ORDER BY id'):
        values=list(row)
        if 'payload' in columns:values[columns.index('payload')]=json.loads(values[columns.index('payload')])
        h.update((dumps(values)+'\n').encode());count+=1
    return {'rows':count,'sha256':h.hexdigest()}


def prepare_workspace(db,legacy_schema):
    kind=db.execute("SELECT type FROM sqlite_master WHERE name='packages'").fetchone()
    if kind and kind[0]=='table':
        db.executescript(legacy_schema)
    else:
        package="CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, created_at TEXT, reviewer TEXT, payload TEXT);"
        task=("CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, package_id TEXT, case_id TEXT, reviewer TEXT,\n"
              " revision INTEGER, state TEXT, payload TEXT, FOREIGN KEY(package_id) REFERENCES packages(id));")
        index='CREATE INDEX IF NOT EXISTS tasks_case ON tasks(case_id,state);'
        schema=legacy_schema.replace(package,'').replace(task,'').replace(index,'')
        db.executescript(schema.replace('REFERENCES tasks(id)','REFERENCES review_tasks(id)'))
        install_reviews(db)
    register_review_writers(db)


def task_heads(db):
    """Fetch only identity and signature fields needed for stale-task checks."""
    if reviews_v2(db):
        sql=("SELECT t.id,t.case_id,c.signature FROM review_tasks t "
             "JOIN review_task_values v ON v.value_hash=t.value_hash "
             "LEFT JOIN review_components c ON c.component_hash=v.component_hash "
             "WHERE t.state NOT IN ('cancelled','stale') ORDER BY t.id")
    else:
        sql=("SELECT id,case_id,json_extract(payload,'$.snapshot.signature') AS signature "
             "FROM tasks WHERE state NOT IN ('cancelled','stale') ORDER BY id")
    return list(db.execute(sql))


def migrate_reviews(db,progress=None):
    """Migrate an offline copy and preserve all package and task payload values."""
    kind=db.execute("SELECT type FROM sqlite_master WHERE name='packages'").fetchone()
    old=db.execute("SELECT 1 FROM sqlite_master WHERE name='packages_legacy' AND type='table'").fetchone()
    db.commit();db.execute('PRAGMA foreign_keys=OFF')
    if kind and kind[0]=='table':
        db.execute('BEGIN IMMEDIATE')
        db.execute('ALTER TABLE packages RENAME TO packages_legacy')
        db.execute('ALTER TABLE tasks RENAME TO tasks_legacy');db.commit();old=True
    if not old:
        if reviews_v2(db):db.execute('PRAGMA foreign_keys=ON');return {'already_migrated':True}
        raise PipelineError('Legacy review storage is missing')
    install_reviews(db)
    before={t:payload_digest(db,t+'_legacy') for t in ['packages','tasks']}
    for pid,created,reviewer,payload in db.execute(
        'SELECT o.* FROM packages_legacy o LEFT JOIN review_packages p ON p.id=o.id WHERE p.id IS NULL ORDER BY o.id'):
        store_package(db,pid,created,reviewer,json.loads(payload));db.commit()
    for row in db.execute('SELECT o.* FROM tasks_legacy o LEFT JOIN review_tasks t ON t.id=o.id WHERE t.id IS NULL ORDER BY o.id'):
        store_task(db,*tuple(row)[:-1],json.loads(row[-1]))
    db.commit()
    after={t:payload_digest(db,t) for t in ['packages','tasks']}
    if before!=after:raise PipelineError('Frozen package or task evidence differs; legacy storage retained')
    # Renaming the parent table updates the legacy foreign key. Rebuild only
    # that relationship while copying every original review field unchanged.
    db.execute('BEGIN IMMEDIATE')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='reviews' AND type='table'").fetchone():
        db.execute('ALTER TABLE reviews RENAME TO reviews_legacy')
        db.execute('CREATE TABLE reviews(id TEXT PRIMARY KEY,task_id TEXT,revision INTEGER,submitted_at TEXT,payload TEXT,'
                   'UNIQUE(task_id,revision),FOREIGN KEY(task_id) REFERENCES review_tasks(id))')
        db.execute('INSERT INTO reviews SELECT * FROM reviews_legacy');db.execute('DROP TABLE reviews_legacy')
    db.execute('DROP TABLE tasks_legacy');db.execute('DROP TABLE packages_legacy');db.commit()
    db.execute('PRAGMA foreign_keys=ON')
    violations=db.execute('PRAGMA foreign_key_check').fetchall()
    if violations:raise PipelineError('Review migration foreign keys do not reconcile')
    if progress:progress({'review_preservation':after})
    return {'before':before,'after':after}
