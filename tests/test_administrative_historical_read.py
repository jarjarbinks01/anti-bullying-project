"""Exact administrative historical reads on temporary synthetic native state."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3

import pytest
from study2 import administrative_carry_current as carry, compatibility_profiles as trust
from study2 import review_core, review_workload, flag_binding as binding
from study2.common import digest, file_hash
from study2.controls_capture import code_revision
from test_administrative_carry_current import environment, prepared
import test_coordinated_update as native
from test_portable_compatibility_profiles import document


@pytest.fixture
def historical(environment, monkeypatch):
    env = prepared(environment)
    native.update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    root = env['state']
    pointer = env['carry_result']['pointer']
    value = json.loads(Path(pointer['workload_path']).read_bytes())
    block = value['administrative_disposition']; scope = block['carry_forward']['scope']
    files = {}; paths = {}; code = {}
    def add(source, relative):
        source=Path(source); target=root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        files[relative]={'sha256':file_hash(target)}
        paths[str(source)]=relative
        return target
    add(pointer['workload_path'],'review_dispositions/archived/target.json')
    add(block['carry_forward']['source_pointer']['workload_path'],'review_dispositions/archived/source.json')
    for name in scope['target_code_sha256']:
        relative='historical-code/'+name
        add(Path(carry.__file__).parent/name,relative); code[name]=relative
    relocated=root/'relocated-release'
    shutil.copytree(env['new'],relocated)
    for name,pin in block['carry_forward']['release_inputs'].items():
        relative='relocated-release/'+Path(pin['path']).name
        files[relative]={'sha256':pin['sha256']};paths[pin['path']]=relative
    manifest=root/'synthetic-checkpoint.json'
    native.save(manifest,{'format_version':1,'files':files})
    reader={**scope['target_code_sha256'],'review_core.py':'9'*64}
    contract=dict(contract=trust.ADMINISTRATIVE_READ_CONTRACT,scope_sha256=digest(scope),
        workload_pin={'path':pointer['workload_path'],'sha256':file_hash(Path(pointer['workload_path']))},
        reader_rules_hash=review_core.rules_hash(env['cfg']),reader_code_sha256=reader,reader_revision=code_revision(),
        recovery_manifest={'path':str(manifest),'sha256':file_hash(manifest)},
        recovery_root=str(root),path_map=paths,original_code=code)
    doc=document();doc.update(administrative_scope_sha256=digest(scope),administrative_read=contract)
    profile=root/'candidate-trust.json';native.save(profile,doc)
    monkeypatch.setattr(trust,'_CONFIGURED_SHA256',None)
    monkeypatch.setattr(trust,'_ADMINISTRATIVE_READ',None)
    monkeypatch.setattr(trust,'_SCOPE_SHA256',None)
    trust.configure_trust(profile,file_hash(profile))
    monkeypatch.setattr(carry,'_current_code_pins',lambda names:{k:reader[k] for k in names})
    monkeypatch.setattr(review_core,'rules_hash',lambda cfg:contract['reader_rules_hash'])
    env.update(value=value,block=block,contract=contract,profile=profile,reader=reader)
    return env


def load(env, **kwargs):
    return review_workload.load_summary(release_id=native.NEW,decision_revision=digest([]),
        exclusion_revision=env['staged']['manifest_revision'],path=env['carry_result']['pointer']['workload_path'],
        review_state=env['state'],cfg=env['cfg'],**kwargs)


def hashes(root):
    return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


def test_exact_historical_read_preserves_all_state_and_strict_default(historical):
    env=historical;before=hashes(env['state'])
    value,_=load(env,historical_read=True)
    assert value==env['value']
    with pytest.raises(review_workload.WorkloadUnavailable):load(env)
    with carry._ro(env['state']/'review.sqlite') as work:
        with pytest.raises(ValueError,match='rules_code_changed'):
            carry.validate_workload(env['cfg'],work,env['block'])
    assert hashes(env['state'])==before


def test_relocation_never_needs_original_signed_input_paths(historical):
    env=historical;carryblock=env['block']['carry_forward']
    Path(carryblock['source_pointer']['workload_path']).unlink()
    for pin in carryblock['release_inputs'].values():Path(pin['path']).unlink()
    assert load(env,historical_read=True)[0]==env['value']


@pytest.mark.parametrize('change', ['scope','workload','source','cases','original_code','reader_code','reader_rules',
    'path_map','manifest','main_controls','history','mirror','symlink','unregistered_asset','new_case','publication','pointer'])
def test_historical_read_denies_drift_without_mutation(historical,monkeypatch,change):
    env=historical;root=env['state'];contract=trust._ADMINISTRATIVE_READ
    if change=='scope':contract['scope_sha256']='f'*64
    elif change=='workload':
        value=deepcopy(env['value']);value['correction_bundles']+=1
        native.save(Path(env['carry_result']['pointer']['workload_path']),value)
    elif change in ('source','cases','original_code'):
        if change=='source':rel=contract['path_map'][env['block']['carry_forward']['source_pointer']['workload_path']]
        elif change=='cases':rel=contract['path_map'][env['block']['carry_forward']['release_inputs']['cases']['path']]
        else:rel=contract['original_code']['review_core.py']
        with (root/rel).open('ab') as f:f.write(b'changed')
    elif change=='reader_code':env['reader']['review_core.py']='f'*64
    elif change=='reader_rules':monkeypatch.setattr(review_core,'rules_hash',lambda cfg:'f'*64)
    elif change=='path_map':contract['path_map'].pop(env['block']['carry_forward']['release_inputs']['cases']['path'])
    elif change=='manifest':Path(contract['recovery_manifest']['path']).write_text('{}')
    elif change=='main_controls':
        with sqlite3.connect(root/'study2.sqlite') as db:
            db.execute("INSERT INTO labels VALUES('SYN_CHANGED','SYN','SYN','SYN','SYN','{}')")
    elif change=='history':
        with sqlite3.connect(root/'review.sqlite') as db:db.execute('DELETE FROM events')
    elif change=='mirror':
        with sqlite3.connect(root/'review.sqlite') as db:db.execute('DELETE FROM followups')
    elif change=='symlink':
        path=root/contract['original_code']['review_core.py'];other=path.with_suffix('.real');path.rename(other);path.symlink_to(other)
    elif change=='unregistered_asset':
        contract['path_map'][contract['workload_pin']['path']]='../escape.json'
    elif change=='publication':
        with sqlite3.connect(root/'study2.sqlite') as db:db.execute('UPDATE publication SET release_id=?',(native.OLD,))
    elif change=='pointer':
        pointer=json.loads((root/'CURRENT_REVIEW_DISPOSITION.json').read_bytes());pointer['workload_sha256']='f'*64
        native.save(root/'CURRENT_REVIEW_DISPOSITION.json',pointer)
    elif change=='new_case':
        original=carry.canonical_cases
        monkeypatch.setattr(carry,'canonical_cases',lambda *args:[*original(*args),{'case_id':'SYN_NEW'}])
    before=hashes(root)
    with pytest.raises((review_workload.WorkloadUnavailable,ValueError)):load(env,historical_read=True)
    assert hashes(root)==before


def test_read_capability_never_enters_staging_or_publication(historical):
    env=historical;before=hashes(env['state'])
    with pytest.raises(ValueError,match='rules_code_changed'):
        carry.stage_workload(env['cfg'],env['scope'],env['bp'],env['pp'],
            {'path':env['staged']['manifest'],'sha256':file_hash(Path(env['staged']['manifest']))},env['new'],env['state']/'review_dispositions/forbidden')
    with pytest.raises(Exception,match='review_disposition_binding_unavailable'):binding.resolve_current(env['cfg'])
    with pytest.raises(Exception,match='historical_read_not_publication'):
        binding._require_current_workload(env['cfg'],None,None,staged_pointer={},historical_read=True)
    assert hashes(env['state'])==before


def test_contract_is_independently_pinned_and_cannot_be_mutated_by_reader(historical):
    contract=trust.administrative_read_contract();contract['scope_sha256']='f'*64
    assert trust.administrative_read_contract()['scope_sha256']!=contract['scope_sha256']
    with pytest.raises(ValueError,match='file_hash_changed'):
        trust.configure_trust(historical['profile'],'f'*64)


def test_full_reader_identity_is_pinned(historical, monkeypatch):
    from study2 import controls_capture
    monkeypatch.setattr(controls_capture,'code_revision',lambda:'f'*64)
    with pytest.raises(review_workload.WorkloadUnavailable):load(historical,historical_read=True)


@pytest.mark.parametrize('command,info,expected', [
    ('manifest',False,True),('run --no-publish',False,True),
    ('run',False,False),('watch',False,False),('review-prepare',False,True),
    ('static-export',False,True),('controls-capture',False,True),('dashboard',False,True),('run',True,True)])
def test_public_entry_only_grants_explicit_read_consumers(tmp_path,monkeypatch,command,info,expected):
    from study2 import entrypoint
    calls=[]
    class StopAfterAdmission(Exception):pass
    def resolve(cfg,**kwargs):
        calls.append(kwargs.get('historical_read',False))
        raise StopAfterAdmission
    monkeypatch.setattr(trust,'_ADMINISTRATIVE_READ',{'synthetic':True})
    monkeypatch.setattr(binding,'historical_current',lambda cfg: trust._ADMINISTRATIVE_READ is not None)
    monkeypatch.setattr(binding,'resolve_current',resolve)
    with pytest.raises(StopAfterAdmission):
        entrypoint.dispatch(tmp_path/'cfg.json',{'state_dir':str(tmp_path)},[*command.split(),*(['--check'] if command=='dashboard' else [])],runtime_info=info)
    assert calls==[expected]


def test_consumer_decorator_does_not_spread_read_authority(monkeypatch):
    from contextlib import contextmanager
    calls=[]
    @contextmanager
    def guard(cfg,**kwargs):
        calls.append(kwargs.get('historical_read',False));yield
    monkeypatch.setattr(trust,'_ADMINISTRATIVE_READ',{'synthetic':True})
    monkeypatch.setattr(binding,'historical_current',lambda cfg: trust._ADMINISTRATIVE_READ is not None)
    monkeypatch.setattr(binding,'guarded_current',guard)
    @binding.guarded_consumer
    def ordinary(cfg):return 'strict'
    @binding.guarded_consumer(historical_read=True)
    def reader(cfg):
        ordinary(cfg)
        return 'reader'
    assert reader({})=='reader'
    assert calls==[True,False]
    monkeypatch.setattr(trust,'_ADMINISTRATIVE_READ',None)
    calls.clear();reader({});assert calls==[False,False]


@pytest.mark.parametrize('change', ['contract','scope_sha256','reader_revision','path_map','original_code'])
def test_malformed_read_contract_never_partially_configures(historical,monkeypatch,change):
    doc=json.loads(historical['profile'].read_bytes())
    doc['administrative_read'][change]={} if change in ('path_map','original_code') else 'invalid'
    native.save(historical['profile'],doc)
    monkeypatch.setattr(trust,'_CONFIGURED_SHA256',None)
    monkeypatch.setattr(trust,'_ADMINISTRATIVE_READ',None)
    with pytest.raises(ValueError,match='compatibility_'):
        trust.configure_trust(historical['profile'],file_hash(historical['profile']))
    assert trust._CONFIGURED_SHA256 is None and trust._ADMINISTRATIVE_READ is None
