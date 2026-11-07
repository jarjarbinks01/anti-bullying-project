"""Actual selected entry subprocesses, tiny native fixtures, no live services."""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import time

import pytest

from test_coordinated_update import environment, save, proof, CODE, OLD, NEW
from test_owned_journal_integration import owned, publication
from test_scoped_empty_fence import empty, prepare
from test_coordinated_update_r2 import tracking, file_state
from study2 import coordinated_update as update, flag_binding as binding
from study2.analysis_eligibility import sha
from study2.common import file_hash
from study2.consumer_owner_fence import ScopedEmptyFence


def reviewed(env,plan):
    plan=deepcopy(plan)
    pins={p['path']:p for p in plan['input_pins']}
    for rel in ScopedEmptyFence.GUARDS:
        path=CODE/rel;pins[str(path)]={'path':str(path),'sha256':file_hash(path)}
    plan['input_pins']=list(pins.values())
    plan['revision']=sha({k:v for k,v in plan.items() if k!='revision'})
    env['plan']=plan;env['planpin']=save(env['trusted']/'entry-plan.json',plan)
    env['accepted']=proof(env['trusted'],'entry-review.json','publication_tuple',plan['revision'])
    env['plan_wrapper']=Path(save(env['trusted']/'entry-plan-pin.json',env['planpin'])['path'])
    env['review_wrapper']=Path(save(env['trusted']/'entry-review-pin.json',env['accepted'])['path'])
    return env


def argv(env,command):
    result=[sys.executable,'-I','-B',str(CODE/'local_update_entry.py'),'--activation',str(env['selection']),command]
    if command!='reviewed-recover':result += [str(env['plan_wrapper']),str(env['review_wrapper']),'SYNTHETIC PREPARER']
    return result


def invoke(env,command):
    return subprocess.run(argv(env,command),capture_output=True,text=True,timeout=15)


def message(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout,selectors.EVENT_READ)
        assert selector.select(8),'Selected entry did not respond'
    line=process.stdout.readline()
    assert line,process.stderr.read() if process.poll() is not None else 'Entry closed stdout'
    return json.loads(line)


def command(process,value):
    process.stdin.write(value+'\n');process.stdin.flush()
    return message(process)


def session(env):
    process=subprocess.Popen(argv(env,'reviewed-session'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        assert message(process)['status']=='owned_session_ready'
        # Observe the actual native reader lock, rather than treating Popen or
        # the entry's ready message as proof that the child has started reading.
        deadline=time.monotonic()+5
        while True:
            with (env['state']/'writer.lock').open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:break
                finally:fcntl.flock(lock,fcntl.LOCK_UN)
            assert time.monotonic()<deadline,'Owned native reader did not take its lock'
            time.sleep(.02)
        return process
    except BaseException:
        close(process);raise


def close(process):
    if process.poll() is None:
        try:process.stdin.write('exit\n');process.stdin.flush()
        except BrokenPipeError:pass
        process.communicate(timeout=8)
    for stream in (process.stdin,process.stdout,process.stderr):
        if stream is not None and not stream.closed:stream.close()
    assert process.returncode==0


def test_actual_entry_owned_session_first_switch_and_retry(owned):
    env=reviewed(owned,owned['plan']);before_review=file_hash(env['state']/'review.sqlite');before_flags=file_hash(env['reg'])
    process=session(env)
    try:
        assert command(process,'publish')['release_id']==NEW
        assert publication(env)==NEW
        files,rows=file_state(env),tracking(env)
        retry=command(process,'publish')
        assert retry['read_only'] and retry['idempotent']
        assert file_state(env)==files and tracking(env)==rows
        assert file_hash(env['state']/'review.sqlite')==before_review and file_hash(env['reg'])==before_flags
    finally:close(process)
    # A completed entry retry never starts another owned reader.
    result=invoke(env,'reviewed-publish');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['read_only'] and file_state(env)==files


def zero(env):
    _,plan,_,_=prepare(env)
    return reviewed(env,plan)


def test_actual_entry_genuinely_empty_first_switch_and_retry(empty):
    env=zero(empty);before_review=file_hash(env['state']/'review.sqlite');before_flags=file_hash(env['reg'])
    result=invoke(env,'reviewed-publish');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['release_id']==NEW
    files,rows=file_state(env),tracking(env)
    result=invoke(env,'reviewed-publish');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['read_only'] and file_state(env)==files and tracking(env)==rows
    assert file_hash(env['state']/'review.sqlite')==before_review and file_hash(env['reg'])==before_flags


def test_actual_zero_entry_does_not_adopt_or_stop_undeclared_reader(empty):
    env=zero(empty)
    reader=subprocess.Popen(env['argv'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(reader.stdout,selectors.EVENT_READ);assert selector.select(5)
        assert reader.stdout.readline()=='READY\n'
        rows=tracking(env)
        result=invoke(env,'reviewed-publish');assert result.returncode!=0
        assert 'exclusive_writer_busy' in result.stderr
        assert reader.poll() is None and publication(env)==OLD and tracking(env)==rows
        reader.stdin.write('\n');reader.stdin.flush();reader.wait(timeout=5)
        result=invoke(env,'reviewed-recover');assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['recovered_to']=='old'
    finally:
        if reader.poll() is None:reader.terminate();reader.wait(timeout=5)
        for stream in (reader.stdin,reader.stdout,reader.stderr):stream.close()


@pytest.mark.parametrize('activity',['active','unknown'])
def test_actual_entry_refuses_nonempty_or_uncertain_inventory_before_journal(empty,activity):
    env=zero(empty);plan=deepcopy(env['plan']);inventory=deepcopy(env['empty_inventory'])
    if activity=='active':inventory['active_target_consumers']=['SYNTHETIC UNOWNED READER']
    else:
        item=binding._json(inventory['observation_pins'][0]['path']);item['process_state']='unknown'
        inventory['observation_pins'][0]=save(env['trusted']/'uncertain-observation.json',item)
    plan['consumer_owner_scope']['inventory_pin']=save(env['trusted']/'entry-inventory.json',inventory)
    reviewed(env,plan)
    result=invoke(env,'reviewed-publish');assert result.returncode!=0
    assert ('known_target_consumers_not_empty' if activity=='active' else 'target_activity_not_quiescent') in result.stderr
    assert publication(env)==OLD and not (env['state']/update.JOURNAL).exists()


def test_actual_entry_stale_controls_fail_closed_and_recover_only_after_restoration(empty):
    env=zero(empty);before_flags=file_hash(env['reg']);before_review=file_hash(env['state']/'review.sqlite')
    with sqlite3.connect(env['state']/'study2.sqlite') as db:
        db.execute("INSERT INTO labels VALUES('SYN_STALE','MATCH','SYN','SYN','SYN','{}')")
    result=invoke(env,'reviewed-publish');assert result.returncode!=0 and publication(env)==OLD
    assert binding._json(env['selection'])['coordinated_update_gate']
    assert invoke(env,'reviewed-publish').returncode!=0
    assert invoke(env,'reviewed-recover').returncode!=0 and publication(env)==OLD
    with sqlite3.connect(env['state']/'study2.sqlite') as db:db.execute("DELETE FROM labels WHERE case_id='SYN_STALE'")
    result=invoke(env,'reviewed-recover');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['recovered_to']=='old'
    files=file_state(env)
    result=invoke(env,'reviewed-recover');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['read_only'] and file_state(env)==files
    assert file_hash(env['reg'])==before_flags and file_hash(env['state']/'review.sqlite')==before_review


def test_actual_owned_session_retains_handles_for_recovery_after_writer_conflict(owned):
    env=reviewed(owned,owned['plan']);process=session(env);rows=tracking(env)
    blocker=sqlite3.connect(env['state']/'review.sqlite',timeout=0);blocker.execute('BEGIN IMMEDIATE')
    try:
        assert command(process,'publish')['status']=='command_failed'
        assert publication(env)==OLD and binding._json(env['selection'])['coordinated_update_gate']
        assert 'recovery_required' in command(process,'publish')['error']
        assert command(process,'exit')['error']=='recover_pending_transition_before_exit'
        blocker.rollback();blocker.close();blocker=None
        assert command(process,'recover')['recovered_to']=='old'
        assert command(process,'recover')['read_only']
        assert publication(env)==OLD and tracking(env)==rows
    finally:
        if blocker is not None:blocker.rollback();blocker.close()
        close(process)


def test_actual_entry_recovers_committed_empty_transition_without_republication(empty):
    env=zero(empty);owner=ScopedEmptyFence(env['cfg'],env['plan'])
    def fail(phase):
        if phase=='after_sqlite_commit':raise OSError('SYNTHETIC INTERRUPTION')
    with pytest.raises(OSError):update.publish(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',owner_fence=owner,fault=fail)
    rows=tracking(env);assert publication(env)==NEW
    result=invoke(env,'reviewed-recover');assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['recovered_to']=='target' and tracking(env)==rows


def test_owned_session_loss_leaves_gate_closed_and_fresh_entry_cannot_adopt(owned):
    env=reviewed(owned,owned['plan']);process=session(env)
    blocker=sqlite3.connect(env['state']/'review.sqlite',timeout=0);blocker.execute('BEGIN IMMEDIATE')
    try:
        assert command(process,'publish')['status']=='command_failed'
        blocker.rollback();blocker.close();blocker=None
        process.stdin.close();process.stdin=None
        _,error=process.communicate(timeout=8)
        assert process.returncode!=0 and 'gate remains closed' in error
        result=invoke(env,'reviewed-recover');assert result.returncode!=0
        assert 'reviewed_empty_owner_scope_required' in result.stderr
        assert publication(env)==OLD and binding._json(env['selection'])['coordinated_update_gate']
    finally:
        if blocker is not None:blocker.rollback();blocker.close()
        if process.poll() is None:process.terminate();process.wait(timeout=5)
        for stream in (process.stdout,process.stderr):stream.close()


def test_actual_entry_requires_reviewed_dispatcher_and_rejects_wrong_scope(owned):
    env=reviewed(owned,owned['plan'])
    result=invoke(env,'reviewed-publish');assert result.returncode!=0
    assert 'reviewed_empty_owner_scope_required' in result.stderr
    plan=deepcopy(env['plan']);plan['input_pins']=[p for p in plan['input_pins'] if p['path']!=str(CODE/'study2/reviewed_switch_entry.py')]
    plan['revision']=sha({k:v for k,v in plan.items() if k!='revision'})
    env['planpin']=save(env['trusted']/'missing-guard-plan.json',plan)
    env['accepted']=proof(env['trusted'],'missing-guard-review.json','publication_tuple',plan['revision'])
    save(env['plan_wrapper'],env['planpin']);save(env['review_wrapper'],env['accepted'])
    result=invoke(env,'reviewed-session');assert result.returncode!=0
    assert 'reviewed_guarded_runtime_required' in result.stderr
    assert publication(env)==OLD and not (env['state']/update.JOURNAL).exists()
