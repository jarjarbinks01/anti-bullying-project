"""Bounded empty inventory, real native exclusion, no invented consumers."""
from copy import deepcopy
import json
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys

import pytest

from test_coordinated_update import environment, save, proof, CODE, OLD, NEW
from test_owned_journal_integration import owned, publication
from test_coordinated_update_r2 import tracking, assert_published_once
from study2 import coordinated_update as update, flag_binding as binding
from study2.analysis_eligibility import sha
from study2.common import PipelineError, file_hash
from study2.consumer_owner_fence import ScopedEmptyFence, OwnerFenceError, require_publication_fence


@pytest.fixture
def empty(owned):
    env = owned
    cfg = env['cfg']
    outside = env['state'].parent/'synthetic-other-project'
    outside.mkdir()
    for name in ['state','releases','flags','policy']:
        (outside/name).mkdir()
    other_cfg = {'state_dir':str(outside/'state'), 'release_dir':str(outside/'releases'),
                 'recovery_policy':{'mode':'lean'}}
    configpin = save(outside/'selected-config.json', other_cfg)
    canonicalpin = save(outside/'canonical-config.json', other_cfg)
    entry = outside/'local_update_entry.py'
    entry.write_bytes((CODE/'local_update_entry.py').read_bytes())
    entrypin = {'path':str(entry), 'sha256':file_hash(entry)}
    other_selection = {'enabled':True, 'entry':str(entry), 'config':configpin['path'],
        'canonical_config':canonicalpin['path'], 'canonical_config_sha256':canonicalpin['sha256'],
        'state_dir':other_cfg['state_dir'], 'environment':{
            binding.CONTROL_ENV:str(outside/'flags/control.json'),
            binding.POLICY_ENV:str(outside/'policy/CURRENT.json')}}
    selectionpin = save(outside/'selection.json', other_selection)
    evidence = []
    for role, status, session, exitcode in [
        ('SYNTHETIC COORDINATOR','not_started',None,None),
        ('SYNTHETIC WORK4','exited','TEST-SESSION',2)]:
        evidence.append(save(env['trusted']/(role.replace(' ','-')+'.json'), {
            'format':'study2_target_activity_observation_v1', 'scope':'target_state_only',
            'state_dir':str(env['state']), 'participant':role, 'process_state':status,
            'session_id':session, 'exit_code':exitcode,
            'note':'SYNTHETIC ONLY. Exit status is separate from data-outcome acceptance.'}))
    inventory = {'format':'study2_bounded_consumer_inventory_v1',
        'scope':'declared_project_target_activities_only', 'state_dir':str(env['state']),
        'release_dir':str(env['releases']), 'selection_path':str(env['selection']),
        'declared_participants':['SYNTHETIC COORDINATOR','SYNTHETIC WORK4'],
        'active_target_consumers':[], 'observation_pins':evidence,
        'excluded_runtimes':[{'selection_pin':selectionpin,'configuration_pin':configpin,
            'canonical_configuration_pin':canonicalpin,'entry_pin':entrypin}]}
    env.update(empty_inventory=inventory, outside=outside, other_selection=other_selection,
               other_config=other_cfg)
    yield env


def prepare(env, *, inventory=None, remove_guard=False, approved=True):
    inventory = deepcopy(inventory if inventory is not None else env['empty_inventory'])
    pin = save(env['trusted']/'bounded-inventory.json', inventory)
    plan = deepcopy(env['plan'])
    plan['consumer_owner_scope'] = {'format':'study2_bounded_empty_owner_scope_v1',
        'state_dir':str(env['state']), 'selection_path':str(env['selection']), 'inventory_pin':pin}
    paths = {p['path'] for p in plan['input_pins']}
    for rel in ScopedEmptyFence.GUARDS:
        p = CODE/rel
        if str(p) not in paths:
            plan['input_pins'].append({'path':str(p),'sha256':file_hash(p)})
    if remove_guard:
        plan['input_pins'] = [p for p in plan['input_pins'] if p['path'] != str(CODE/'dashboard.py')]
    plan['revision'] = sha({k:v for k,v in plan.items() if k != 'revision'})
    planpin = save(env['trusted']/'empty-plan.json', plan)
    acceptance = proof(env['trusted'],'empty-review.json','publication_tuple',plan['revision'])
    if not approved:
        review = json.loads(Path(acceptance['path']).read_text())
        review['accepted'] = False
        acceptance = save(Path(acceptance['path']), review)
    owner = ScopedEmptyFence(env['cfg'], plan)
    return owner, plan, planpin, acceptance


def publish_empty(env, prepared, **kwargs):
    owner, _, planpin, accepted = prepared
    return update.publish(env['cfg'], planpin, accepted, operator='SYNTHETIC PREPARER',
                          owner_fence=owner, **kwargs)


def test_empty_inventory_publishes_with_actual_locks_and_no_child_creation(empty, monkeypatch):
    env = empty
    prepared = prepare(env)
    def forbidden(*args, **kwargs):
        raise AssertionError('Empty maintenance must not create a canary or service')
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    result = publish_empty(env, prepared)
    assert result['release_id'] == NEW
    before = assert_published_once(env)
    _, _, planpin, accepted = prepared
    retry = update.publish(env['cfg'],planpin,accepted,operator='SYNTHETIC PREPARER')
    assert retry['read_only'] and retry['idempotent']
    assert assert_published_once(env) == before


def test_undeclared_guarded_reader_still_excludes_empty_lease(empty):
    env = empty
    prepared = prepare(env)
    reader = subprocess.Popen(env['argv'], stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(reader.stdout,selectors.EVENT_READ)
            assert selector.select(5)
        assert reader.stdout.readline() == 'READY\n'
        before = tracking(env)
        with pytest.raises(PipelineError,match='exclusive_writer_busy'):
            publish_empty(env, prepared)
        assert reader.poll() is None
        assert publication(env) == OLD and tracking(env) == before
        assert binding._json(env['state']/update.JOURNAL)['status'] == 'draining'
        reader.stdin.write('\n');reader.stdin.flush();reader.wait(timeout=5)
        assert update.recover(env['cfg'],owner_fence=prepared[0])['recovered_to'] == 'old'
        assert publication(env) == OLD and tracking(env) == before
    finally:
        if reader.poll() is None:
            reader.terminate();reader.wait(timeout=5)
        for stream in (reader.stdin,reader.stdout,reader.stderr):
            stream.close()


def test_writer_without_state_lock_still_blocks_empty_publication(empty):
    env = empty
    prepared = prepare(env)
    db = sqlite3.connect(env['state']/'review.sqlite',timeout=0)
    db.execute('BEGIN IMMEDIATE')
    before = tracking(env)
    try:
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            publish_empty(env, prepared)
        assert publication(env) == OLD and tracking(env) == before
    finally:
        db.rollback();db.close()
    assert update.recover(env['cfg'],owner_fence=prepared[0])['recovered_to'] == 'old'
    assert tracking(env) == before


@pytest.mark.parametrize('case',['active','unknown'])
def test_nonempty_or_unknown_target_inventory_refuses_before_journal(empty, case):
    env = empty
    inventory = deepcopy(env['empty_inventory'])
    if case == 'active':
        inventory['active_target_consumers'] = ['SYNTHETIC STILL RUNNING']
        message = 'known_target_consumers_not_empty'
    else:
        record = {'format':'study2_target_activity_observation_v1','scope':'target_state_only',
            'state_dir':str(env['state']),'participant':'SYNTHETIC WORK4','process_state':'unknown',
            'session_id':'UNCERTAIN','exit_code':None}
        inventory['observation_pins'][1] = save(env['trusted']/'unknown-status.json', record)
        message = 'target_activity_not_quiescent'
    with pytest.raises(OwnerFenceError,match=message):
        prepare(env, inventory=inventory)
    assert not (env['state']/update.JOURNAL).exists()


def test_excluded_runtime_cannot_overlap_target_resources(empty):
    env = empty
    inventory = deepcopy(env['empty_inventory'])
    excluded = inventory['excluded_runtimes'][0]
    selected = deepcopy(env['other_selection'])
    config = {**env['other_config'],'state_dir':str(env['state'])}
    excluded['configuration_pin'] = save(env['outside']/'overlap-config.json',config)
    selected.update(state_dir=str(env['state']),config=excluded['configuration_pin']['path'])
    excluded['selection_pin'] = save(env['outside']/'overlap-selection.json',selected)
    with pytest.raises(OwnerFenceError,match='excluded_runtime_overlaps_target'):
        prepare(env,inventory=inventory)
    assert not (env['state']/update.JOURNAL).exists()


def test_empty_claim_cannot_replace_guarded_runtime_profile(empty):
    env = empty
    with pytest.raises(OwnerFenceError,match='reviewed_guarded_runtime_required'):
        prepare(env,remove_guard=True)
    assert not (env['state']/update.JOURNAL).exists()


def test_inventory_is_not_publication_approval_or_an_opaque_lease(empty):
    env = empty
    prepared = prepare(env,approved=False)
    owner, plan, _, _ = prepared
    with pytest.raises(OwnerFenceError,match='actual_owner_lease_required'):
        require_publication_fence(owner,object(),env['cfg'],plan)
    with pytest.raises(PipelineError,match='independent_update_review_required'):
        publish_empty(env,prepared)
    assert not (env['state']/update.JOURNAL).exists()
    assert not (env['state']/'consumer-maintenance.lock').exists()
