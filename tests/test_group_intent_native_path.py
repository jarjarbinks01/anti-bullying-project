"""Small real native stage/publish fixtures; no matching or real-state access."""
from pathlib import Path

import pytest

import test_coordinated_update as native
import test_coordinated_update_r2 as nonempty
from study2 import group_cleaning_operator as group, coordinated_update as update
from study2 import flag_binding as binding, manual_flags as flags
from study2.analysis_eligibility import sha
from study2.common import file_hash


@pytest.fixture
def migrated_environment(tmp_path,monkeypatch):
    original_bundle=native.bundle

    def with_boundary(root,cfg,rid,rows,eric,*,prior=None):
        bp,pp,proposal,b=original_bundle(root,cfg,rid,rows,eric,prior=prior)
        gid='GROUP_BOUNDARY_OLD' if rid==native.OLD else 'GROUP_BOUNDARY_NEW'
        groups=group._json(b['files']['groups']['path'])
        groups[gid]={'case_id':gid,'group_review':{'members':['removed','ordinary'],
            'comparison_ids':['RO'],'passed_pairs':[],'conflicts':[],'manual_restrictions':[]}}
        cases={'RO':{'case_id':'RO','kind':'identity','status':'pending','record_a':'removed',
                     'record_b':'ordinary','rule':'fuzzy_contact_child_demo'}}
        auth=group._json(b['files']['authorization']['path']);auth['partition_groups']=[gid]
        for name,value in [('groups',groups),('cases',cases),('authorization',auth),
                           ('partitions',{gid:[['removed'],['ordinary']]})]:
            b['files'][name]=native.save(root/(name+'.json'),value)
        b['revision']=sha({k:v for k,v in b.items() if k!='revision'});native.save(bp,b)
        proposal=group.preview(bp);native.save(pp,proposal)
        return bp,pp,proposal,b

    monkeypatch.setattr(native,'bundle',with_boundary)
    generator=native.environment.__wrapped__(tmp_path,monkeypatch)
    env=next(generator)
    try:
        result=group.prepare_intent_bundle(env['oldbundle'],env['bp'],env['root'],tmp_path/'intent-preview')
        assert result['status']=='proposed_not_applied'
        assert Path(result['review']).read_text().startswith('<!doctype html>')
        assert 'Candidate group decisions' in Path(result['review']).read_text()
        assert result['pending_decision_intents']==0
        assert group.read_active(env['root'])['pointer']==env['active']['pointer']
        env['bp']=Path(result['bundle']);env['pp']=Path(result['proposal'])
        env['proposal']=group._json(env['pp']);env['b']=group._json(env['bp'])
        assert len(env['proposal']['decision_intents']['intents'])==1
        assert env['proposal']['partitions']=={}
        assert env['proposal']['decision_application']['entries'][0]['status']=='carried'
        env['subject']=sha({'bundle_revision':env['b']['revision'],
            'proposal_revision':env['proposal']['revision'],'old_release_id':native.OLD,'target_release_id':native.NEW})
        env['group_proof']=native.proof(env['trusted'],'intent-group-review.json','group_policy',env['subject'])
        native.save(env['review'],{'format':group.REVIEW_FORMAT,'proposal_revision':env['proposal']['revision'],
            'accepted':True,'reviewer':'INDEPENDENT SYNTHETIC TEST REVIEWER',
            'reason':'SYNTHETIC migration fixture only','review_manifest_sha256':env['group_proof']['sha256']})
        yield nonempty.seed_nonempty(env)
    finally:
        try:next(generator)
        except StopIteration:pass


def test_native_stage_publish_reader_and_idempotent_retry_consume_intents(migrated_environment):
    env=migrated_environment
    before_registry=file_hash(env['reg'])
    baseline=group.read_active(env['root'])
    assert 'decision_intents' not in baseline['proposal']
    staged=group._load_generation(env['root'],env['staged']['policy_pointer'])
    assert staged['policy']['decision_intent_revision']==env['proposal']['decision_intents']['revision']
    assert staged['proposal']['projection']['pending_comparison_ids']==[]
    result=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert result['release_id']==native.NEW
    active=group.read_active(env['root'])
    assert active['proposal']['decision_intents']==env['proposal']['decision_intents']
    assert binding._current_inventory(env['cfg']).release_id==native.NEW
    assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
    assert {e['submission_id'] for e in binding._json(binding.resolve_current(env['cfg']))['entries']}=={'keep','policy'}
    assert flags.status(env['reg'])['flags']['removed']['state']=='removed'
    assert file_hash(env['reg'])==before_registry
    nonempty.assert_published_once(env)
    again=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert again['idempotent'] is True
    assert group.read_active(env['root'])['pointer']==active['pointer']
    assert file_hash(env['reg'])==before_registry
    nonempty.assert_published_once(env)


def test_wrong_source_bundle_cannot_migrate_accepted_generation(migrated_environment,tmp_path):
    env=migrated_environment
    wrong=group._json(env['oldbundle'])
    wrong['release_id']=native.NEW
    wrong['revision']=sha({k:v for k,v in wrong.items() if k!='revision'})
    wrong_path=tmp_path/'wrong-origin.json';native.save(wrong_path,wrong)
    output=tmp_path/'must-not-be-created'
    with pytest.raises(Exception,match='intent_origin_inputs_changed'):
        group.prepare_intent_bundle(wrong_path,env['bp'],env['root'],output)
    assert not output.exists()


@pytest.mark.parametrize('alias',['symlink','dotdot'])
def test_preview_cannot_write_through_an_alias_into_protected_state(migrated_environment,tmp_path,alias):
    env=migrated_environment
    if alias=='symlink':
        link=tmp_path/'external-looking-link';link.symlink_to(env['state'],target_is_directory=True)
        output=link/'must-not-be-created'
    else:
        output=env['root']/'..'/'state'/'must-not-be-created'
    with pytest.raises(Exception,match='intent_preview_'):
        group.prepare_intent_bundle(env['oldbundle'],env['bp'],env['root'],output)
    assert not (env['state']/'must-not-be-created').exists()


def test_preview_protects_a_distinct_original_source_state(migrated_environment,tmp_path):
    env=migrated_environment
    source_state=tmp_path/'original-source-state';source_state.mkdir()
    original=group._json(env['oldbundle'])
    source_config={**env['cfg'],'state_dir':str(source_state)}
    original['files']['config']=native.save(tmp_path/'original-source-config.json',source_config)
    original['revision']=sha({k:v for k,v in original.items() if k!='revision'})
    source_bundle=tmp_path/'relocated-source-bundle.json';native.save(source_bundle,original)
    output=source_state/'must-not-be-created'
    with pytest.raises(Exception,match='intent_preview_'):
        group.prepare_intent_bundle(source_bundle,env['bp'],env['root'],output)
    assert not output.exists()


@pytest.mark.parametrize('phase,expected',[('before_sqlite_commit',native.OLD),('after_sqlite_commit',native.NEW)])
def test_changed_projection_uses_existing_commit_point_recovery(migrated_environment,phase,expected):
    env=migrated_environment
    def fail(point):
        if point==phase:raise OSError('SYNTHETIC INTENT INTERRUPTION')
    with pytest.raises(OSError,match='SYNTHETIC INTENT INTERRUPTION'):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],
                               operator='SYNTHETIC PREPARER',fault=fail)
    with pytest.raises(Exception,match='coordinated_transition_recovery_required'):
        binding.resolve_current(env['cfg'])
    update._recover_fenced(env['cfg'])
    assert binding._current_inventory(env['cfg']).release_id==expected
    actual=binding.resolve_current(env['cfg'])
    assert actual==(env['oldmanifest'] if expected==native.OLD else Path(env['staged']['manifest']))
    assert flags.status(env['reg'])['flags']['removed']['state']=='removed'
    assert {r['dyad_id'] for r in nonempty.tracking(env)['dyad_registry']}=={
        'TEST_EXISTING_ACTIVE','TEST_RESERVED_TARGET','TEST_EXISTING_RETIRED'}
    if expected==native.NEW:nonempty.assert_published_once(env)
