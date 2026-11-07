"""Nonempty native dyad publication and real process-death regressions.

Operational publication and pending recovery stay blocked. Only the private
integration engines may manipulate these explicitly synthetic fixtures.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from test_coordinated_update import environment, prepared, OLD, NEW, AT, CODE
from study2 import coordinated_update as update, flag_binding as binding
from study2.common import digest, file_hash
from study2.dyad_operator import workspace_snapshot


def seed_nonempty(env):
    db=env['db']
    entries=[('TEST_EXISTING_ACTIVE','active',OLD,OLD),
             ('TEST_RESERVED_TARGET','reserved',None,NEW),
             ('TEST_EXISTING_RETIRED','retired',OLD,OLD)]
    for did,lifecycle,first_published,first_run in entries:
        db.execute('INSERT INTO dyad_registry VALUES(?,?,?,?,?,?,?,?)',
            (did,'keep','ordinary',first_run,AT,'{"synthetic":true}',lifecycle,first_published))
        db.execute('INSERT INTO dyad_lineage VALUES(?,?,?,?)',(did,'keep','e'*64,1))
    for index,did in enumerate(['TEST_RESERVED_TARGET','TEST_EXISTING_RETIRED']):
        child='TEST_CHILD_'+str(index)
        payload={'dyad_id':did,'child_id':child,'registration_state':'active'}
        db.execute('INSERT INTO dyad_memberships VALUES(?,?,?,?,?,?)',
            (NEW,'TEST_MEMBERSHIP_'+str(index),did,child,'active',json.dumps(payload)))
    db.execute('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',
        ('TEST_EXISTING_RESTRICTION',AT,'synthetic_restriction','TEST_EXISTING_RETIRED','fixture','TEST ONLY','{}'))
    db.commit()
    with sqlite3.connect(env['state']/'review.sqlite') as work:
        work.execute('INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)',
            (AT,'TEST_EXISTING_REVIEW','fixture','{"preserve":true}'))
    return prepared(env)


def tracking(env):
    with sqlite3.connect(env['state']/'study2.sqlite') as db:
        db.row_factory=sqlite3.Row
        return workspace_snapshot(db)


def assert_published_once(env):
    data=tracking(env)
    registry={r['dyad_id']:r for r in data['dyad_registry']}
    assert len(registry)==3
    assert registry['TEST_RESERVED_TARGET']['lifecycle']=='active'
    assert registry['TEST_RESERVED_TARGET']['first_published_run_id']==NEW
    assert registry['TEST_EXISTING_ACTIVE']['first_published_run_id']==OLD
    assert registry['TEST_EXISTING_RETIRED']['lifecycle']=='retired'
    assert registry['TEST_EXISTING_RETIRED']['first_published_run_id']==OLD
    assert sum(r['kind']=='published_mapping' for r in data['dyad_events'])==2
    assert sum(r['event_id']=='TEST_EXISTING_RESTRICTION' for r in data['dyad_events'])==1
    assert len(data['dyad_lineage'])==3
    journal=binding._json(env['state']/update.JOURNAL)
    assert journal['status']=='complete'
    assert journal['post_tracking_revision']==digest(data)
    return data


def file_state(env):
    paths=[env['state']/'study2.sqlite',env['state']/'review.sqlite',env['reg'],env['selection'],
        env['root']/'CURRENT.json',env['state']/update.JOURNAL,
        env['state']/'CURRENT_REVIEW_DISPOSITION.json',env['releases']/'CURRENT.json']
    return {str(p):file_hash(p) for p in paths}


@pytest.mark.parametrize('phase',[None,'completion:after_temp_sync','completion:after_replace','completion:after_directory_sync'])
def test_nonempty_native_commit_keeps_metadata_and_never_republishes_on_retry(environment,phase):
    env=seed_nonempty(environment)
    review_before=file_hash(env['state']/'review.sqlite')
    def fail(value):
        if value==phase:raise OSError('TEST COMPLETION INTERRUPTION')
    if phase:
        with pytest.raises(OSError,match='TEST COMPLETION INTERRUPTION'):
            update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=fail)
    else:
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    journal=binding._json(env['state']/update.JOURNAL)
    assert journal['post_tracking_revision']==digest(tracking(env))
    if journal['status']=='pending':
        unchanged=file_state(env)
        with pytest.raises(Exception,match='coordinated_consumer_owner_fence_not_implemented'):
            update.recover(env['cfg'])
        assert file_state(env)==unchanged
        update._recover_fenced(env['cfg'])
    baseline=assert_published_once(env)
    assert update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')['idempotent']
    before=file_state(env);environment_before=dict(os.environ)
    result=update.recover(env['cfg'])
    assert result['idempotent'] and result['read_only']
    assert file_state(env)==before and dict(os.environ)==environment_before
    assert tracking(env)==baseline
    assert file_hash(env['state']/'review.sqlite')==review_before


@pytest.mark.parametrize('phase',['post_tracking:after_replace','policy:after_replace','after_sqlite_commit',
                                  'completion:after_replace','completion:after_directory_sync'])
def test_nonempty_process_death_retains_durable_tracking_and_history(environment,phase):
    env=seed_nonempty(environment)
    payload={'cfg':env['cfg'],'plan':env['planpin'],'acceptance':env['accepted'],'phase':phase}
    script="""
import json,os,sys
from study2 import coordinated_update as update
value=json.load(sys.stdin)
def die(phase):
    if phase==value['phase']:os._exit(77)
update._publish_fenced(value['cfg'],value['plan'],value['acceptance'],operator='SYNTHETIC PREPARER',fault=die)
"""
    result=subprocess.run([sys.executable,'-B','-c',script],input=json.dumps(payload),text=True,
        capture_output=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},timeout=30)
    assert result.returncode==77,result.stderr
    journal=binding._json(env['state']/update.JOURNAL)
    assert len(journal['post_tracking_revision'])==64
    if journal['status']=='pending':
        selection_before=file_hash(env['selection']);journal_before=file_hash(env['state']/update.JOURNAL)
        with pytest.raises(Exception,match='coordinated_consumer_owner_fence_not_implemented'):
            update.recover(env['cfg'])
        assert file_hash(env['selection'])==selection_before
        assert file_hash(env['state']/update.JOURNAL)==journal_before
        update._recover_fenced(env['cfg'])
    else:
        assert update.recover(env['cfg'])['read_only']
    actual=binding._current_inventory(env['cfg']).release_id
    if phase in {'post_tracking:after_replace','policy:after_replace'}:
        assert actual==OLD
        old=tracking(env)
        assert next(r for r in old['dyad_registry'] if r['dyad_id']=='TEST_RESERVED_TARGET')['first_published_run_id'] is None
        assert sum(r['kind']=='published_mapping' for r in old['dyad_events'])==0
    else:
        assert actual==NEW
        assert_published_once(env)
    update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert_published_once(env)


def test_public_pending_recovery_is_unchanged_and_completed_check_never_repairs(environment):
    env=seed_nonempty(environment)
    def stop(phase):
        if phase=='after_gate':raise OSError('TEST STOP')
    with pytest.raises(OSError):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=stop)
    before=file_state(env);env_before=dict(os.environ)
    with pytest.raises(Exception,match='coordinated_consumer_owner_fence_not_implemented'):
        update.recover(env['cfg'])
    assert file_state(env)==before and dict(os.environ)==env_before
    update._recover_fenced(env['cfg'])
    derived=env['releases']/'CURRENT.json'
    wrong=binding._json(derived);wrong['path']='TEST WRONG DERIVED PATH'
    derived.write_text(json.dumps(wrong)+'\n')
    before=file_state(env)
    with pytest.raises(Exception,match='completed_transition_derived_pointer_changed'):
        update.recover(env['cfg'])
    assert file_state(env)==before


def test_completion_cas_never_overwrites_an_unrelated_journal_change(environment):
    env=seed_nonempty(environment)
    def change(phase):
        if phase=='after_sqlite_commit':
            path=env['state']/update.JOURNAL
            value=binding._json(path);value['operator']='TEST UNRELATED OPERATOR'
            path.write_text(json.dumps(value)+'\n')
    with pytest.raises(Exception,match='transition_journal_changed'):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=change)
    journal=binding._json(env['state']/update.JOURNAL)
    assert journal['status']=='pending' and journal['operator']=='TEST UNRELATED OPERATOR'
    assert journal['post_tracking_revision']==digest(tracking(env))
