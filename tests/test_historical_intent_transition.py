"""Protected-head compatibility, using native tiny fixtures only."""
from copy import deepcopy
from pathlib import Path
import pytest
from study2 import continuity_integration as ci, group_cleaning_operator as group
from study2 import group_decision_intents as intents, coordinated_update as update
from study2.analysis_eligibility import sha
from study2.common import file_hash
import test_coordinated_update as native
import test_coordinated_update_r2 as nonempty
import test_group_intent_native_path as generic
from test_group_decision_intents import original, record, case, scope, options

@pytest.fixture
def protected_environment(tmp_path, monkeypatch):
    original_prepare=group.prepare_intent_bundle
    def prepare(source,target,root,out):
        active=group.read_active(root)
        monkeypatch.setitem(ci.PROFILES, 'SYNTHETIC_ANCHOR_ONLY', {
            'historical_policy_head_sha256':active['pointer']['manifest_sha256'],
            'historical_group_id':'GROUP_BOUNDARY_OLD'})
        return original_prepare(source,target,root,out)
    monkeypatch.setattr(group,'prepare_intent_bundle',prepare)
    gen=generic.migrated_environment.__wrapped__(tmp_path,monkeypatch)
    env=next(gen)
    try:yield env
    finally:
        try:next(gen)
        except StopIteration:pass

def test_protected_native_stage_publish_retry(protected_environment):
    generic.test_native_stage_publish_reader_and_idempotent_retry_consume_intents(protected_environment)

@pytest.mark.parametrize('change',['omit','duplicate','boundary','subject','receipt','origin','claim','source','head','flag'])
def test_guard_rejects_changed_authority(protected_environment,change):
    env=protected_environment
    _,data,opts=group.load_bundle(env['bp'])
    current=group.read_active(env['root']);proposal=deepcopy(env['proposal'])
    item=proposal['decision_intents']['intents'][0]
    if change=='omit':proposal['decision_intents']['intents']=[]
    elif change=='duplicate':proposal['decision_intents']['intents']*=2
    elif change=='boundary':item['boundary']=[['removed','ordinary']]
    elif change=='subject':item['subjects'][0]['raw_hash']='f'*64
    elif change=='receipt':item['origin']['receipt']['reason']='UNAUTHORIZED'
    elif change=='origin':item['origin']['release_id']='WRONG'
    elif change=='claim':data={'verified_migration':True}
    elif change=='source':data['intent_origin']['source_bundle_pin']['sha256']='f'*64
    elif change=='head':current['pointer']['manifest_sha256']='f'*64
    elif change=='flag':data['records']['policy']['raw_hash']='f'*64
    with pytest.raises(Exception):ci.guard_transition(current,proposal,native.NEW,data=data)

def test_unchanged_partition_branch_and_missing_evidence(protected_environment):
    env=protected_environment;current=group.read_active(env['root'])
    ci.guard_transition(current,{'partitions':deepcopy(current['policy']['partitions'])},native.NEW)
    with pytest.raises(Exception,match='historical_partition_cannot_be_dropped'):
        ci.guard_transition(current,env['proposal'],native.NEW)

def test_stage_rechecks_original_source_before_return(protected_environment):
    env=protected_environment;_,data,opts=group.load_bundle(env['bp'])
    current=group.read_active(env['root']); before=deepcopy(current['pointer'])
    receipt=dict(release_id=native.NEW,main_revision=opts['main_revision'],rules_hash=opts['rules_hash'],
                 operator='SYNTHETIC',reason='TEST ONLY',at=native.AT)
    def fault(phase):
        if phase=='after_complete_backup':
            p=Path(data['intent_origin']['source_bundle_pin']['path']);p.write_text(p.read_text()+' ')
    with pytest.raises(Exception,match='input_pin_changed'):
        group._stage(env['root'],current,env['proposal'],data,receipt,commit_pointer=False,
                     guard_base={**opts,'release_id':native.OLD},fault=fault)
    assert group.read_active(env['root'])['pointer']==before

def test_successive_generic_target_preserves_intents_without_profile(protected_environment,tmp_path):
    env=protected_environment
    update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    current=group.read_active(env['root']);old=deepcopy(current['proposal']['decision_intents'])
    third='RUN_'+'3'*32
    rows=list(group.load_bundle(env['bp'])[1]['records'].values())
    eric=group.exclusion_manifest(rows,third,{'keep'},operator='SYNTHETIC',at=native.AT)
    bp,pp,proposal,b=native.bundle(tmp_path/'third',env['cfg'],third,rows,eric)
    data=group.load_bundle(bp)[1];opts=group.load_bundle(bp)[2]
    carry=group._carry_from_active(current,data,opts)
    assert carry['decision_intents']==old
    b['files']['carry']=native.save(tmp_path/'third/carry.json',carry)
    b['revision']=sha({k:v for k,v in b.items() if k!='revision'});native.save(bp,b)
    proposal=group.preview(bp);_,data,opts=group.load_bundle(bp)
    ci.guard_transition(current,proposal,third,data=data)
    assert proposal['decision_intents']==old
    assert proposal['decision_application']['entries'][0]['status']=='carried'
    assert third not in ci.PROFILES

def test_all_eight_original_authorities_are_retained(original):
    records,cases,groups,_,receipt,_=deepcopy(original)
    partitions={}
    for i in range(8):
        a,b=f'A{i}',f'B{i}';records[a]=record(a);records[b]=record(b,contact='91230002')
        cid=f'C{i}';gid=f'G{i}';cases[cid]=case(cid,a,b);groups.update(scope(gid,[a,b],[cid]));partitions[gid]=[[a],[b]]
    from study2 import group_cleaning as policy
    proposal=policy.make_proposal(records,cases,groups,[],**options(records,'RUN_SYN_OLD',partitions=partitions))
    receipt['review']['proposal_revision']=proposal['revision']
    collection=intents.migrate(proposal,records,cases,groups,receipt)
    assert len(collection['intents'])==8
    assert {i['origin']['group_id'] for i in collection['intents']}==set(partitions)
    for item in collection['intents']:
        assert item['origin']['receipt']==receipt
        assert item['boundary']==partitions[item['origin']['group_id']]

def test_historical_source_uses_accepted_rules_but_target_remains_current(protected_environment,monkeypatch):
    env=protected_environment;active=group.read_active(env['root'])
    monkeypatch.setattr(group,'current_rules_hash',lambda cfg:'f'*64)
    with pytest.raises(Exception,match='scientific_rules_hash_changed'):
        group.load_bundle(env['oldbundle'])
    _,source,_=group._load_intent_source(env['oldbundle'],active)
    assert group._migrate_active_intents(active,source)==env['proposal']['decision_intents']
    with pytest.raises(Exception,match='scientific_rules_hash_changed'):
        group.load_bundle(env['bp'])
    bad=deepcopy(active);bad['proposal']['base']['rules_hash']='a'*64
    with pytest.raises(Exception,match='intent_origin_inputs_changed'):
        group._load_intent_source(env['oldbundle'],bad)
