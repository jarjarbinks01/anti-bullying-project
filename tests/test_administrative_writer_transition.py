"""Different-release migration: immutable OLD evidence, current TARGET authority."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest
from test_administrative_historical_read import historical
from test_administrative_carry_current import environment
import test_coordinated_update as native
from study2 import administrative_carry_current as carry, compatibility_profiles as trust
from study2 import flag_binding as binding, group_cleaning_operator as group
from study2 import review_core, coordinated_update as update
from study2.common import digest, file_hash
from study2.analysis_eligibility import sha


@pytest.fixture
def migration(historical, monkeypatch):
    env=historical
    old=native.NEW; new='RUN_'+'3'*32
    # The fixture's historical contract resolves authenticated relocated records.
    native.save(env['state']/'release_locations.json',{old:str(env['state']/'relocated-release')})
    (env['state']/update.JOURNAL).unlink()  # completed first synthetic transition
    monkeypatch.setattr(native,'OLD',old); monkeypatch.setattr(native,'NEW',new)
    target=native.release(env['releases'],new,env['rows'],env['db'])
    active=group.read_active(env['root'])
    inv=native.flags.Inventory.from_records(new,env['rows'])
    spam=native.flags.compile_snapshot(env['reg'],inv,operator='SYNTHETIC PREPARER',persist=False)['manifest']
    prior=native.policy.exclusion_manifest(env['rows'],new,{'policy'},operator='SYNTHETIC PREPARER',at=native.AT)
    bp,pp,proposal,b=native.bundle(env['tmp_path']/'third-inputs',env['cfg'],new,env['rows'],spam,prior=prior)
    _,data,options=group.load_bundle(bp)
    b['files'].pop('prior_policy_manifest')
    b['files']['carry']=native.save(bp.parent/'carry.json',group._carry_from_active(active,data,options))
    b['revision']=sha({k:v for k,v in b.items() if k!='revision'}); native.save(bp,b)
    proposal=group.preview(bp); native.save(pp,proposal)
    subject=sha({'bundle_revision':b['revision'],'proposal_revision':proposal['revision'],
                 'old_release_id':old,'target_release_id':new})
    proof=native.proof(env['trusted'],'third-group-review.json','group_policy',subject)
    review=bp.parent/'review.json'
    native.save(review,{'format':group.REVIEW_FORMAT,'proposal_revision':proposal['revision'],'accepted':True,
        'reviewer':'INDEPENDENT SYNTHETIC TEST REVIEWER','reason':'SYNTHETIC new target review only',
        'review_manifest_sha256':proof['sha256']})
    scope=deepcopy(env['scope']);scope.update(target_rules_hash=review_core.rules_hash(env['cfg']),
        target_code_sha256=env['reader'],accepted_evidence_manifest_sha256='4'*64,acceptance_report_sha256='5'*64)
    monkeypatch.setattr(carry,'SCOPED_CERTIFICATE_SHA256',digest(scope))
    monkeypatch.setattr(trust,'_SCOPE_SHA256',digest(scope))
    env.update(scope=scope,old=env['new'],new=target,oldwork=env['carry_result']['pointer'],
        oldmanifest=Path(env['staged']['manifest']),active=active,bp=bp,pp=pp,proposal=proposal,b=b,
        review=review,group_proof=proof,subject=subject,summary=env['value'])
    native.prepared(env)
    result=carry.stage_workload(env['cfg'],scope,bp,pp,
        {'path':env['staged']['manifest'],'sha256':file_hash(Path(env['staged']['manifest']))},target,
        env['state']/'review_dispositions/third-carry')
    plan=env['plan'];plan['target_workload']=result['pointer']
    plan['target_selection']['environment']['STUDY2_CURRENT_REVIEW_WORKLOAD']=result['pointer']['workload_path']
    plan['revision']=sha({k:v for k,v in plan.items() if k!='revision'})
    env['planpin']=native.save(env['trusted']/'third-plan.json',plan)
    env['accepted']=native.proof(env['trusted'],'third-publication-review.json','publication_tuple',plan['revision'])
    env['carry_result']=result
    return env


def test_current_target_authority_preserves_history(migration,monkeypatch):
    env=migration; before=file_hash(env['state']/'review.sqlite')
    assert binding.historical_current(env['cfg'])
    assert binding.resolve_current(env['cfg'],historical_read=True)==env['oldmanifest']
    with pytest.raises(Exception):binding.resolve_current(env['cfg'])
    result=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert result['release_id']==native.NEW
    assert not binding.historical_current(env['cfg'])
    assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
    assert file_hash(env['state']/'review.sqlite')==before
    assert env['carry_result']['closed_comparisons']==4
    assert update.recover(env['cfg'])['verified_side']=='target'
    @binding.guarded_consumer(historical_read=True)
    def reader(cfg):return 'strict target read'
    assert reader(env['cfg'])=='strict target read'
    from study2 import entrypoint
    calls=[]
    class StopAfterAdmission(Exception):pass
    def resolve(cfg,**kwargs):
        calls.append(kwargs.get('historical_read',False));raise StopAfterAdmission
    monkeypatch.setattr(binding,'resolve_current',resolve)
    for command in ('controls-capture','static-export','dashboard'):
        with pytest.raises(StopAfterAdmission):
            entrypoint.dispatch(env['tmp_path']/'cfg.json',env['cfg'],[command])
    assert calls==[False,False,False]


@pytest.mark.parametrize('phase,side',[('after_gate','old'),('before_sqlite_commit','old'),('after_sqlite_commit','target')])
def test_migration_recovery_uses_actual_publication(migration,phase,side):
    env=migration; before=file_hash(env['state']/'review.sqlite')
    def fail(point):
        if point==phase:raise OSError('SYNTHETIC INTERRUPTION')
    with pytest.raises(OSError,match='SYNTHETIC INTERRUPTION'):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=fail)
    assert update._recover_fenced(env['cfg'])['recovered_to']==side
    assert update.recover(env['cfg'])['verified_side']==side
    assert file_hash(env['state']/'review.sqlite')==before


def test_target_source_drift_does_not_borrow_old_read_authority(migration,monkeypatch):
    env=migration
    monkeypatch.setattr(carry,'_current_code_pins',lambda names:{name:'f'*64 for name in names})
    with pytest.raises(Exception):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert binding._current_inventory(env['cfg']).release_id==native.OLD


@pytest.mark.parametrize('mapped',[False,True])
def test_recover_pointer_repairs_path_and_preserves_correct_pointer(environment,mapped):
    env=environment; pointer=env['releases']/'CURRENT.json'
    expected=str(env['old'])
    if mapped:
        expected=str(env['state']/'relocated-old')
        native.save(env['state']/'release_locations.json',{native.OLD:expected})
    native.save(pointer,{'release_id':native.OLD,'path':'stale-path'})
    native.runner.recover_pointer(env['db'],env['cfg'])
    assert json.loads(pointer.read_bytes())['path']==expected
    before=pointer.read_bytes(); modified=pointer.stat().st_mtime_ns
    native.runner.recover_pointer(env['db'],env['cfg'])
    assert pointer.read_bytes()==before and pointer.stat().st_mtime_ns==modified


def test_recover_pointer_invalid_mapping_preserves_pointer(environment):
    env=environment; pointer=env['releases']/'CURRENT.json';before=pointer.read_bytes()
    (env['state']/'release_locations.json').write_text('not JSON')
    with pytest.raises(ValueError):native.runner.recover_pointer(env['db'],env['cfg'])
    assert pointer.read_bytes()==before


@pytest.mark.parametrize('value',[None,42,[],{},''])
def test_recover_pointer_invalid_location_preserves_pointer(environment,value):
    env=environment; pointer=env['releases']/'CURRENT.json';before=pointer.read_bytes()
    native.save(env['state']/'release_locations.json',{native.OLD:value})
    with pytest.raises(native.runner.PipelineError,match='Invalid release location'):
        native.runner.recover_pointer(env['db'],env['cfg'])
    assert pointer.read_bytes()==before


def test_recover_pointer_nonobject_mapping_preserves_pointer(environment):
    env=environment; pointer=env['releases']/'CURRENT.json';before=pointer.read_bytes()
    native.save(env['state']/'release_locations.json',[])
    with pytest.raises(AttributeError):
        native.runner.recover_pointer(env['db'],env['cfg'])
    assert pointer.read_bytes()==before
