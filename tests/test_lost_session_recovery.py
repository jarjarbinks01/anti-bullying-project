"""Fresh actual entry recovery with reviewed empty scope, synthetic native state."""
from copy import deepcopy
import json
import sqlite3
import subprocess

import pytest

from test_coordinated_update import environment,save,proof,OLD,NEW
from test_owned_journal_integration import owned,start,publication
from test_scoped_empty_fence import empty
from test_reviewed_switch_entry import reviewed,argv
from test_coordinated_update_r2 import tracking,file_state
from study2 import coordinated_update as update,flag_binding as binding
from study2.consumer_owner_fence import OwnedConsumerFence,ScopedEmptyFence,empty_recovery_request,OwnerFenceError
from study2.common import file_hash
from study2.analysis_eligibility import sha


def interrupted(env,phase='owner_journal:after_directory_sync',*,stop=True):
    env=reviewed(env,env['plan']);owner=OwnedConsumerFence(env['cfg'],env['plan']);env['owner']=owner
    reader=start(env)
    def fail(actual):
        if actual==phase:raise OSError('SYNTHETIC OWNER LOSS')
    try:
        with pytest.raises(OSError,match='SYNTHETIC OWNER LOSS'):
            update.publish(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',owner_fence=owner,fault=fail)
        if stop:owner.cleanup_owned()
    except BaseException:
        owner.cleanup_owned();raise
    env['reader']=reader
    return env


def admission(env,*,exited=True,coverage=True,accepted=True):
    inventory=deepcopy(env['empty_inventory'])
    if coverage:
        name='owner:reader';inventory['declared_participants'].append(name)
        code=env['reader'].poll()
        observation={'format':'study2_target_activity_observation_v1','scope':'target_state_only',
            'state_dir':str(env['state']),'participant':name,'process_state':'exited' if exited else 'unknown',
            'session_id':'SYNTHETIC_POPEN_'+str(env['reader'].pid),'exit_code':code if code is not None else 0}
        inventory['observation_pins'].append(save(env['trusted']/'owner-exit.json',observation))
    inventorypin=save(env['trusted']/'recovery-inventory.json',inventory)
    request=empty_recovery_request(env['cfg'],inventorypin)
    requestpin=save(env['trusted']/'recovery-scope.json',request)
    acceptedpin=proof(env['trusted'],'recovery-review.json','empty_session_recovery',sha(request))
    if not accepted:
        receipt=binding._json(acceptedpin['path']);receipt['accepted']=False
        acceptedpin=save(env['trusted']/'recovery-review.json',receipt)
    env['recovery']={'request_pin':requestpin,'acceptance_pin':acceptedpin}
    env['recovery_args']=[save(env['trusted']/'recovery-scope-pin.json',requestpin)['path'],
                          save(env['trusted']/'recovery-review-pin.json',acceptedpin)['path']]
    return env


def recover_entry(env):
    return subprocess.run(argv(env,'reviewed-recover')+env['recovery_args'],capture_output=True,text=True,timeout=15)


@pytest.mark.parametrize('phase,side',[('owner_journal:after_directory_sync','old'),('after_sqlite_commit','target')])
def test_fresh_entry_recovers_lost_owner_using_exact_reviewed_empty_scope(empty,phase,side):
    env=interrupted(empty,phase);env=admission(env)
    review,flags=file_hash(env['state']/'review.sqlite'),file_hash(env['reg']);rows=tracking(env)
    result=recover_entry(env);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['recovered_to']==side
    assert publication(env)==(OLD if side=='old' else NEW) and tracking(env)==rows
    assert file_hash(env['state']/'review.sqlite')==review and file_hash(env['reg'])==flags
    files=file_state(env)
    result=recover_entry(env);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['read_only'] and file_state(env)==files


@pytest.mark.parametrize('problem',['coverage','approval','journal','unknown'])
def test_lost_recovery_requires_current_independent_scope_and_all_original_exits(empty,problem):
    env=interrupted(empty);admission(env,coverage=problem!='coverage',accepted=problem!='approval',exited=problem!='unknown')
    if problem=='journal':
        path=env['state']/update.JOURNAL;path.write_bytes(path.read_bytes()+b'\n')
    before=file_state(env)
    result=recover_entry(env);assert result.returncode!=0
    expected={'coverage':'original_owned_reader_exit_coverage_required','approval':'independent_update_review_required',
              'journal':'recovery_journal_or_scope_changed','unknown':'target_activity_not_quiescent'}[problem]
    assert expected in result.stderr and publication(env)==OLD and file_state(env)==before


def test_false_exited_observation_cannot_bypass_actual_reader_lock_or_stop_reader(empty):
    env=interrupted(empty,stop=False)
    try:
        admission(env) # Deliberately wrong synthetic observation, testing the actual exclusion lock.
        assert env['reader'].poll() is None
        result=recover_entry(env);assert result.returncode!=0 and 'exclusive_writer_busy' in result.stderr
        assert env['reader'].poll() is None and publication(env)==OLD
        env['owner'].cleanup_owned()
        # The failed request is not silently reused as exit evidence. Review the
        # actual exit and the now-gated journal again before the next recovery.
        admission(env)
        result=recover_entry(env);assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['recovered_to']=='old'
    finally:env['owner'].cleanup_owned()


def test_recovery_only_lease_cannot_publish_and_interrupted_recovery_can_retry(empty):
    env=admission(interrupted(empty));owner=ScopedEmptyFence(env['cfg'],env['plan'],recovery=env['recovery'])
    with pytest.raises(OwnerFenceError,match='recovery_scope_cannot_publish'):owner.check_publish_ready(env['cfg'],env['plan'])
    def fail(phase):
        if phase=='workload:after_replace':raise OSError('SYNTHETIC RECOVERY INTERRUPTION')
    with pytest.raises(OSError,match='SYNTHETIC RECOVERY INTERRUPTION'):
        update.recover(env['cfg'],owner_fence=owner,fault=fail)
    result=recover_entry(env);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['recovered_to']=='old'


def test_fresh_empty_recovery_does_not_override_stale_decision_state(empty):
    env=admission(interrupted(empty));rows=tracking(env)
    with sqlite3.connect(env['state']/'study2.sqlite') as db:
        db.execute("INSERT INTO labels VALUES('SYN_STALE','MATCH','SYN','SYN','SYN','{}')")
    result=recover_entry(env);assert result.returncode!=0 and publication(env)==OLD
    assert binding._json(env['selection'])['coordinated_update_gate']
    with sqlite3.connect(env['state']/'study2.sqlite') as db:db.execute("DELETE FROM labels WHERE case_id='SYN_STALE'")
    result=recover_entry(env);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['recovered_to']=='old' and tracking(env)==rows
