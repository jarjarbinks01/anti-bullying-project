"""Actual native publisher and recovery with genuine owned groups, synthetic data."""
from copy import deepcopy
import json
import os
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys

import pytest

from test_coordinated_update import environment, save, proof, CODE, OLD, NEW
from test_coordinated_update_r2 import seed_nonempty, assert_published_once, tracking, file_state
from study2 import coordinated_update as update, flag_binding as binding
from study2.analysis_eligibility import sha
from study2.common import PipelineError, file_hash
from study2.consumer_owner_fence import OwnedConsumerFence, OwnerFenceError


@pytest.fixture
def owned(environment):
    env = seed_nonempty(environment)
    cfg, plan = env['cfg'], deepcopy(env['plan'])
    canonical = env['state'] / 'synthetic-canonical-config.json'
    save(canonical, cfg)
    for name in ('old_selection', 'target_selection'):
        plan[name].update({'canonical_config':str(canonical),
            'canonical_config_sha256':file_hash(canonical), 'config':str(canonical),
            'state_dir':str(env['state'])})
    plan['gate_selection'] = {**plan['old_selection'], 'coordinated_update_gate':True}
    save(env['selection'], plan['old_selection'])
    worker = Path(__file__).with_name('owned_journal_reader.py')
    argv = [sys.executable, '-B', str(worker), str(CODE/'local_update_entry.py'),
            '--activation', str(env['selection'])]
    plan['consumer_owner_scope'] = {
        'format':'study2_owned_consumer_scope_v1', 'state_dir':str(env['state']),
        'selection_path':str(env['selection']), 'owners':{'reader':{
            'kind':'owned_popen', 'argv':argv, 'input_pins':[
                {'path':str(worker), 'sha256':file_hash(worker)},
                {'path':str(canonical), 'sha256':file_hash(canonical)}]}}}
    plan['input_pins'].append({'path':str(canonical), 'sha256':file_hash(canonical)})
    plan['revision'] = sha({k:v for k,v in plan.items() if k != 'revision'})
    planpin = save(env['trusted']/'owned-publication-plan.json', plan)
    accepted = proof(env['trusted'], 'owned-publication-review.json', 'publication_tuple', plan['revision'])
    owner = OwnedConsumerFence(cfg, plan)
    env.update(plan=plan, planpin=planpin, accepted=accepted, owner=owner, argv=argv)
    yield env
    owner.cleanup_owned()


def start(env):
    process = env['owner'].start('reader')
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(5), 'Synthetic reader did not become ready'
    assert process.stdout.readline() == 'READY\n', process.stderr.read() if process.poll() is not None else ''
    return process


def publish(env, **kwargs):
    return update.publish(env['cfg'], env['planpin'], env['accepted'],
                          operator='SYNTHETIC PREPARER', **kwargs)


def publication(env):
    with sqlite3.connect(env['state']/'study2.sqlite') as db:
        return db.execute('SELECT release_id FROM publication WHERE singleton=1').fetchone()[0]


def test_real_public_publish_owns_drain_and_completed_retry_is_readonly(owned):
    env = owned
    process = start(env)
    result = publish(env, owner_fence=env['owner'])
    assert result['release_id'] == NEW and process.poll() is not None
    before = assert_published_once(env)
    files = file_state(env)
    repeated = publish(env)
    assert repeated['idempotent'] and repeated['read_only'] and repeated['release_id'] == NEW
    assert assert_published_once(env) == before
    assert file_state(env) == files


@pytest.mark.parametrize('phase', ['owner_journal:after_directory_sync', 'owner_gate:after_replace'])
def test_predrain_interruption_has_journal_and_explicit_recovery_never_publishes(owned, phase):
    env = owned
    process = start(env)
    before = tracking(env)
    def fail(actual):
        if actual == phase:
            raise RuntimeError('TEST ONLY predrain interruption')
    with pytest.raises(RuntimeError, match='predrain interruption'):
        publish(env, owner_fence=env['owner'], fault=fail)
    assert binding._json(env['state']/update.JOURNAL)['status'] == 'draining'
    assert process.poll() is None and publication(env) == OLD
    with pytest.raises(PipelineError, match='recovery_required'):
        publish(env, owner_fence=env['owner'])
    restart = subprocess.run(env['argv'], capture_output=True, text=True, timeout=5)
    assert restart.returncode != 0 and 'transition' in restart.stderr.lower()
    files = file_state(env)
    with pytest.raises(PipelineError, match='owner_fence_not_implemented'):
        update.recover(env['cfg'])
    assert file_state(env) == files
    result = update.recover(env['cfg'], owner_fence=env['owner'])
    assert result['recovered_to'] == 'old' and process.poll() is not None
    assert publication(env) == OLD and tracking(env) == before
    repeated = publish(env)
    assert repeated['read_only'] and repeated['release_id'] == OLD
    assert tracking(env) == before


def test_committed_interruption_recovers_target_without_republishing(owned):
    env = owned
    start(env)
    def fail(phase):
        if phase == 'after_sqlite_commit':
            raise RuntimeError('TEST ONLY committed interruption')
    with pytest.raises(RuntimeError, match='committed interruption'):
        publish(env, owner_fence=env['owner'], fault=fail)
    assert publication(env) == NEW
    assert binding._json(env['state']/update.JOURNAL)['status'] == 'pending'
    before = tracking(env)
    with pytest.raises(PipelineError, match='owner_fence_not_implemented'):
        update.recover(env['cfg'])
    result = update.recover(env['cfg'], owner_fence=env['owner'])
    assert result['recovered_to'] == 'target'
    assert assert_published_once(env) == before
    assert publish(env)['idempotent']
    assert assert_published_once(env) == before


def test_expired_owner_lease_at_commit_rolls_back_and_recovers_old(owned):
    env = owned
    start(env)
    before = tracking(env)
    def expire(phase):
        if phase == 'before_sqlite_commit':
            env['owner']._lease = None
    with pytest.raises(OwnerFenceError, match='actual_owner_lease_required'):
        publish(env, owner_fence=env['owner'], fault=expire)
    assert publication(env) == OLD and tracking(env) == before
    assert binding._json(env['state']/update.JOURNAL)['status'] == 'pending'
    assert update.recover(env['cfg'], owner_fence=env['owner'])['recovered_to'] == 'old'
    assert publication(env) == OLD and tracking(env) == before


def test_no_real_handles_or_json_receipt_cannot_create_a_journal(owned):
    env = owned
    paths = [env['state']/'study2.sqlite', env['state']/'review.sqlite', env['reg'],
             env['selection'], env['root']/'CURRENT.json', env['state']/update.JOURNAL,
             env['state']/'CURRENT_REVIEW_DISPOSITION.json', env['releases']/'CURRENT.json']
    def snapshot():
        return {str(p):file_hash(p) if p.exists() else None for p in paths}
    before = snapshot()
    for alleged in [None, {'stopped':True}]:
        with pytest.raises(PipelineError, match='owner_fence_not_implemented'):
            publish(env, owner_fence=alleged)
    with pytest.raises(OwnerFenceError, match='actual_owner_handles_missing'):
        publish(env, owner_fence=env['owner'])
    assert not (env['state']/update.JOURNAL).exists()
    assert not (env['state']/'consumer-maintenance.lock').exists()
    assert snapshot() == before


def test_coordinator_death_cannot_turn_a_pending_journal_into_a_receipt(owned):
    env = owned
    config = env['state']/'synthetic-child-config.json'
    save(config, env['cfg'])
    script = '''
import json,os,sys
from study2 import coordinated_update as update
from study2.consumer_owner_fence import OwnedConsumerFence
cfg=json.load(open(sys.argv[1]))
planpin=json.loads(sys.argv[2]);acceptance=json.loads(sys.argv[3])
plan=json.load(open(planpin['path']))
owner=OwnedConsumerFence(cfg,plan)
try:
    process=owner.start('reader')
    assert process.stdout.readline()=='READY\\n'
    def die(phase):
        if phase=='after_sqlite_commit':os._exit(61)
    update.publish(cfg,planpin,acceptance,operator='SYNTHETIC PREPARER',owner_fence=owner,fault=die)
finally:
    owner.cleanup_owned()
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(config),
        json.dumps(env['planpin']), json.dumps(env['accepted'])], capture_output=True,
        text=True, timeout=20, env={**os.environ,'PYTHONPATH':str(CODE)})
    assert result.returncode == 61, result.stderr
    assert publication(env) == NEW
    assert binding._json(env['state']/update.JOURNAL)['status'] == 'pending'
    before = tracking(env)
    files = file_state(env)
    with pytest.raises(PipelineError, match='owner_fence_not_implemented'):
        update.recover(env['cfg'])
    fresh = OwnedConsumerFence(env['cfg'], env['plan'])
    with pytest.raises(OwnerFenceError, match='actual_owner_handles_missing'):
        update.recover(env['cfg'], owner_fence=fresh)
    assert tracking(env) == before and file_state(env) == files
