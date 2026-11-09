"""Synthetic independent fixture approvals, real parsers/ledgers/publisher.

These files are test-only evidence in pytest tmp_path. They are never operational
approvals, and no accepted-policy loader or publication validation is mocked.
"""
import fcntl
import gzip
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from study2 import coordinated_update as update
from study2 import flag_binding as binding, manual_flags as flags
from study2 import group_cleaning_operator as group, group_cleaning as policy
from study2 import runner, store, dyads, review_core
from study2.common import digest, file_hash
from study2.analysis_eligibility import sha
from study2.owned_locks import exclusive, assert_owned

OLD='RUN_'+'1'*32
NEW='RUN_'+'2'*32
AT='2026-11-05T00:00:00+00:00'
CODE=Path(__file__).parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True)+'\n')
    return {'path':str(path), 'sha256':file_hash(path)}


def proof(root, name, kind, subject):
    return save(root/name, dict(format='study2_independent_update_review_v1',kind=kind,
        subject_revision=subject,accepted=True,reviewer='INDEPENDENT SYNTHETIC TEST REVIEWER',
        reason='TEST FIXTURE ONLY: not an operational acceptance'))


def record(name):
    raw={'Survey':'SYNTHETIC-'+name,'contact_01':'','contact_02':''}
    return dict(submission_id=name,version_id='v-'+name,role='student',raw=raw,answer={},
        raw_hash=digest(raw),child_id='child-'+name,selected_wave='T0',status='eligible',
        observed_at=AT,time_confidence='observed',date_basis='system_creation',
        source_id='synthetic',source_label='synthetic',dob='2010-01-01',gender='0',school='SYNTHETIC')


def release(root, rid, rows, db):
    path=root/rid;path.mkdir()
    save(path/'summary.json',{'release_id':rid})
    with gzip.open(path/'records.jsonl.gz','wt') as stream:
        for row in rows:stream.write(json.dumps(row)+'\n')
    save(path/'checksums.json',{name:file_hash(path/name) for name in ('summary.json','records.jsonl.gz')})
    db.execute('INSERT INTO runs(run_id,fingerprint,created_at,status,manifest_json,stats_json) VALUES(?,?,?,?,?,?)',
               (rid,'synthetic',AT,'published' if rid==OLD else 'validated','{}','{}'))
    db.execute('INSERT INTO releases(release_id,run_id,created_at,path,stats_json) VALUES(?,?,?,?,?)',(rid,rid,AT,str(path),'{}'))
    db.commit()
    backup=sqlite3.connect(path/'backup.sqlite');db.backup(backup);backup.close()
    save(path/'backup.sha256.json',{'backup.sqlite':file_hash(path/'backup.sqlite')})
    return path


def bundle(root, cfg, rid, rows, eric, *, prior=None):
    groups={'GROUP_SYNTHETIC':{'case_id':'GROUP_SYNTHETIC','group_review':{
        'members':['policy'],'comparison_ids':[],'passed_pairs':[],'conflicts':[],'manual_restrictions':[]}}}
    auth={'workbook_sha256':'1'*64,'request_sha256':'2'*64,'partition_groups':[],
          'user_exclusion_groups':['GROUP_SYNTHETIC']}
    values={'config':cfg,'records':rows,'cases':{},'groups':groups,'decisions':[],
        'eric_manifest':eric,'source_evidence':{},'authorization':auth,'partitions':{},
        'user_exclusions':{'GROUP_SYNTHETIC':[policy.pin(next(r for r in rows if r['submission_id']=='policy'))]}}
    if prior is not None:values['prior_policy_manifest']=prior
    pins={name:save(root/(name+'.json'),value) for name,value in values.items()}
    result=dict(format=group.BUNDLE_FORMAT,release_id=rid,
        main_revision=group._main_revision(cfg)['main_revision'],rules_hash=review_core.rules_hash(cfg),files=pins)
    result['revision']=sha(result)
    path=root/'bundle.json';save(path,result)
    proposal=group.preview(path);proposal_path=root/'proposal.json';save(proposal_path,proposal)
    return path,proposal_path,proposal,result


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for key in ['STUDY2_FLAG_CONTROL','STUDY2_GROUP_POLICY_POINTER','STUDY2_MANUAL_EXCLUSION_MANIFEST',
                'STUDY2_CURRENT_REVIEW_WORKLOAD','STUDY2_REVIEW_STATE_DIR']:
        monkeypatch.delenv(key,raising=False)
    state=tmp_path/'state';state.mkdir()
    releases=tmp_path/'releases';releases.mkdir()
    root=tmp_path/'group-policy';root.mkdir()
    trusted=tmp_path/'independent-review';trusted.mkdir()
    selection=tmp_path/'selection.json';save(selection,{})
    cfg={'state_dir':str(state),'release_dir':str(releases),'project_root':str(tmp_path),
         'inbox_dir':str(tmp_path/'inbox'),'mapping_dir':str(tmp_path/'mappings'),
         'matching_policy':{},'duplicate_days':30,'minimum_followup_days':90,
         'coordinated_update':{'review_root':str(trusted),
             'reviewers':['INDEPENDENT SYNTHETIC TEST REVIEWER'],'selection_path':str(selection)},
         'recovery_policy':{'mode':'lean','required_assets':[
             {'kind':'directory','path':str(root),'restore_path':'dependencies/group'},
             {'kind':'directory','path':str(trusted),'restore_path':'dependencies/independent-review'},
             {'kind':'file','path':str(selection),'restore_path':'dependencies/selection.json'}]}}
    db=store.connect(state);dyads.migrate(db);db.commit()
    work=review_core.workspace(cfg);work.close()
    rows=[record(x) for x in ['keep','removed','policy','ordinary']]
    old=release(releases,OLD,rows,db);new=release(releases,NEW,rows,db)
    db.execute('INSERT INTO publication VALUES(1,?)',(OLD,));db.commit()
    save(releases/'CURRENT.json',{'release_id':OLD,'path':str(old)})
    control=state/'analysis_eligibility/control';control.mkdir(parents=True)
    reg=control/'registry.sqlite3';flags.initialize_registry(reg,operator='SYNTHETIC PREPARER')
    oldinv=flags.Inventory.from_records(OLD,rows)
    initial=policy.exclusion_manifest(rows,OLD,{'keep','removed'},operator='SYNTHETIC PREPARER',at=AT)
    flags.seed_manifest(reg,initial,oldinv,operator='SYNTHETIC PREPARER',reason='TEST ONLY')
    flags.decide_flags(reg,['removed'],action='remove',operator='SYNTHETIC PREPARER',reason='TEST ONLY documented false positive')
    eric=flags.compile_snapshot(reg,oldinv,operator='SYNTHETIC PREPARER',persist=False)['manifest']
    oldbundle,oldproposal,p,b=bundle(tmp_path/'old-inputs',cfg,OLD,rows,eric)
    oldreview=tmp_path/'old-inputs/review.json'
    save(oldreview,{'format':group.REVIEW_FORMAT,'proposal_revision':p['revision'],'accepted':True,
        'reviewer':'INDEPENDENT SYNTHETIC TEST REVIEWER','reason':'TEST ONLY native initial apply',
        'review_manifest_sha256':'a'*64})
    group.apply(root,oldbundle,oldproposal,oldreview,operator='SYNTHETIC PREPARER',reason='TEST ONLY')
    active=group.read_active(root)
    save(control/'control.json',{'format':binding.CONTROL_FORMAT,'baseline_release_id':OLD,
                               'baseline_policy_head':active['pointer']['manifest_sha256']})
    monkeypatch.setenv(binding.CONTROL_ENV,str(control/'control.json'))
    monkeypatch.setenv(binding.POLICY_ENV,str(root/'CURRENT.json'))
    oldmanifest=binding.prepare_generation(cfg,old)
    workload=state/'review_dispositions/old.json'
    summary={'format':'study2_current_review_workload_v1','release_id':OLD,'decision_revision':digest([]),
        'exclusion_manifest_revision':binding._json(oldmanifest)['revision'],
        'native_workload':{'field_correction_comparisons':0,'remaining_pending_comparisons':0},
        'correction_bundles':0,'source_groups_resolved':0,'accepted_historical_policy_closures':0,
        'original_answers':{'total':0,'same_child':0,'different_children':0}}
    save(workload,summary)
    oldwork={'release_id':OLD,'workload_path':str(workload),'workload_sha256':file_hash(workload)}
    save(state/'CURRENT_REVIEW_DISPOSITION.json',oldwork)
    monkeypatch.setenv(binding.MANIFEST_ENV,str(oldmanifest))
    monkeypatch.setenv('STUDY2_CURRENT_REVIEW_WORKLOAD',str(workload))
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR',str(state))
    targetinv=flags.Inventory.from_records(NEW,rows)
    targetspam=flags.compile_snapshot(reg,targetinv,operator='SYNTHETIC PREPARER',persist=False)['manifest']
    targetprior=policy.exclusion_manifest(rows,NEW,{'policy'},operator='SYNTHETIC PREPARER',at=AT)
    bp,pp,proposal,b=bundle(tmp_path/'target-inputs',cfg,NEW,rows,targetspam,prior=targetprior)
    # Same ID/version policy pins; its origin must be the current policy revision.
    # Existing native apply expects release-specific prior revision, so use the
    # native carry representation for an actual old-to-new prior head.
    data=group.load_bundle(bp)[1]
    options=group.load_bundle(bp)[2]
    carry=group._carry_from_active(active,data,options)
    (tmp_path/'target-inputs/prior_policy_manifest.json').unlink()
    b['files'].pop('prior_policy_manifest')
    b['files']['carry']=save(tmp_path/'target-inputs/carry.json',carry)
    b['revision']=sha({k:v for k,v in b.items() if k!='revision'});save(bp,b)
    proposal=group.preview(bp);save(pp,proposal)
    subject=sha({'bundle_revision':b['revision'],'proposal_revision':proposal['revision'],
                 'old_release_id':OLD,'target_release_id':NEW})
    group_proof=proof(trusted,'group-review.json','group_policy',subject)
    review=tmp_path/'target-inputs/review.json'
    save(review,{'format':group.REVIEW_FORMAT,'proposal_revision':proposal['revision'],'accepted':True,
        'reviewer':'INDEPENDENT SYNTHETIC TEST REVIEWER','reason':'TEST ONLY exact future policy',
        'review_manifest_sha256':group_proof['sha256']})
    item=locals().copy()
    yield item
    db.close()


def prepared(env):
    cfg=env['cfg'];state=env['state']
    before=file_hash(env['reg'])
    staged=update.stage_policy(cfg,env['bp'],env['pp'],env['review'],env['group_proof'],
        expected_old_release=OLD,operator='SYNTHETIC PREPARER',reason='TEST ONLY')
    assert file_hash(env['reg'])==before
    summary={**env['summary'],'release_id':NEW,'exclusion_manifest_revision':staged['manifest_revision']}
    workload=state/'review_dispositions/target.json';save(workload,summary)
    targetwork={'release_id':NEW,'workload_path':str(workload),'workload_sha256':file_hash(workload)}
    def selection(manifest,work):
        return {'enabled':True,'entry':str(CODE/'local_update_entry.py'),'environment':{
            binding.CONTROL_ENV:str(env['control']/'control.json'),
            binding.POLICY_ENV:str(env['root']/'CURRENT.json'),
            binding.MANIFEST_ENV:str(manifest),'STUDY2_CURRENT_REVIEW_WORKLOAD':work['workload_path'],
            'STUDY2_REVIEW_STATE_DIR':str(state)}}
    oldselection=selection(env['oldmanifest'],env['oldwork']);save(env['selection'],oldselection)
    tx=update.Transition(cfg,{'target_release_id':NEW},'SYNTHETIC PREPARER')
    plan={'format':'study2_coordinated_publication_plan_v1','old_release_id':OLD,'target_release_id':NEW,
        'target_release_path':str(env['new']),'old_policy':env['active']['pointer'],
        'target_policy':staged['policy_pointer'],'old_workload':env['oldwork'],'target_workload':targetwork,
        'old_selection':oldselection,'target_selection':selection(staged['manifest'],targetwork),
        'gate_selection':{**oldselection,'coordinated_update_gate':True},
        'old_manifest':str(env['oldmanifest']),'target_manifest':staged['manifest'],
        'target_manifest_sha256':file_hash(Path(staged['manifest'])),'revisions':tx.revisions(),
        'old_tracking_revision':digest(tx.tracking()),'group_review_subject':env['subject'],'input_pins':[{'path':str(CODE/'local_update_entry.py'),'sha256':file_hash(CODE/'local_update_entry.py')}]}
    plan['revision']=sha(plan)
    planpin=save(env['trusted']/'publication-plan.json',plan)
    accepted=proof(env['trusted'],'publication-review.json','publication_tuple',plan['revision'])
    env.update(plan=plan,planpin=planpin,accepted=accepted,staged=staged)
    return env


def test_actual_future_policy_stages_without_changing_current_or_registry(environment):
    env=prepared(environment)
    assert group.read_active(env['root'])['pointer']==env['active']['pointer']
    assert binding.resolve_current(env['cfg'])==env['oldmanifest']
    assert {e['submission_id'] for e in binding._json(env['staged']['manifest'])['entries']}=={'keep','policy'}
    assert flags.status(env['reg'])['flags']['removed']['state']=='removed'


def test_real_publication_and_idempotent_retry(environment):
    env=prepared(environment)
    result=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert result['release_id']==NEW
    assert binding._current_inventory(env['cfg']).release_id==NEW
    assert group.read_active(env['root'])['pointer']==env['staged']['policy_pointer']
    assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
    again=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert again['idempotent']


def test_actual_lock_borrowing_and_competing_handle(environment):
    env=environment
    with store.writer_lock(env['state']):
        with exclusive(env['state']/'writer.lock'):
            assert_owned(env['state']/'writer.lock')
            with (env['state']/'writer.lock').open('a') as other:
                with pytest.raises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            prepared(env)


def test_failed_policy_does_not_write_registry_snapshot(environment):
    env=environment;before=file_hash(env['reg'])
    with pytest.raises(Exception,match='reviewed_group_policy_required_for_release'):
        binding.prepare_generation(env['cfg'],env['new'])
    assert file_hash(env['reg'])==before


@pytest.mark.parametrize('phase',[
    'journal:after_temp_sync','journal:after_replace','journal:after_directory_sync',
    'gate:after_temp_sync','gate:after_replace','gate:after_directory_sync','after_gate',
    *[name+':'+point for name in ('policy','workload','selection') for point in ('after_temp_sync','after_replace','after_directory_sync')],
    *['post_tracking:'+point for point in ('after_temp_sync','after_replace','after_directory_sync')],
    'before_sqlite_commit','after_sqlite_commit',
    'completion:after_temp_sync','completion:after_replace','completion:after_directory_sync'])
def test_fault_boundaries_recover_without_replaying_publication(environment,phase):
    env=prepared(environment)
    def fail(value):
        if value==phase:raise OSError('SYNTHETIC INTERRUPTION')
    with pytest.raises(OSError,match='SYNTHETIC INTERRUPTION'):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=fail)
    journal=env['state']/update.JOURNAL
    if not journal.exists():
        assert binding.resolve_current(env['cfg'])==env['oldmanifest']
        return
    if binding._json(journal)['status']=='pending':
        with pytest.raises(Exception,match='coordinated_transition_recovery_required'):
            binding.resolve_current(env['cfg'])
        update._recover_fenced(env['cfg'])
    current=binding._current_inventory(env['cfg']).release_id
    assert current in {OLD,NEW}
    manifest=binding.resolve_current(env['cfg'])
    assert manifest==(env['oldmanifest'] if current==OLD else Path(env['staged']['manifest']))


@pytest.mark.parametrize('kind',['review','manual_flags'])
def test_actual_sqlite_fences_cover_non_state_lock_writers(environment,kind):
    env=prepared(environment)
    path=env['state']/'review.sqlite' if kind=='review' else env['reg']
    seen=[]
    def inspect(phase):
        if phase=='after_gate':
            other=sqlite3.connect(path,timeout=0)
            try:
                with pytest.raises(sqlite3.OperationalError):other.execute('BEGIN IMMEDIATE')
                seen.append(True)
            finally:other.close()
    update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=inspect)
    assert seen==[True]


def test_operational_entry_has_no_quiescence_boolean_or_test_override(environment):
    env=prepared(environment)
    with pytest.raises(Exception,match='coordinated_consumer_owner_fence_not_implemented'):
        update.publish(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert not (env['state']/update.JOURNAL).exists()


@pytest.mark.parametrize('kind',['review','issued_id','restriction'])
@pytest.mark.parametrize('committed',[False,True])
def test_later_changes_are_preserved_and_recovery_stays_closed(environment,kind,committed):
    env=prepared(environment)
    point='after_sqlite_commit' if committed else 'after_gate'
    def fail(phase):
        if phase==point:raise OSError('SYNTHETIC INTERRUPTION')
    with pytest.raises(OSError):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=fail)
    if kind=='review':
        path=env['state']/'review.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)',(AT,'TEST_ONLY_LATER_REVIEW','synthetic','{}'))
    else:
        with sqlite3.connect(env['state']/'study2.sqlite') as db:
            if kind=='issued_id':
                db.execute('INSERT INTO dyad_registry VALUES(?,?,?,?,?,?,?,?)',('TEST_ONLY_LATE_ID','s','p',OLD,AT,'{}','active',OLD))
            else:
                db.execute('INSERT INTO dyad_events VALUES(?,?,?,?,?,?,?)',('TEST_ONLY_LATER_RESTRICTION',AT,'test_restriction',None,'fixture','TEST ONLY','{}'))
    with pytest.raises(Exception,match='revision_changed|history_changed'):
        update._recover_fenced(env['cfg'])
    assert binding._json(env['state']/update.JOURNAL)['status']=='pending'
    if kind=='review':
        with sqlite3.connect(env['state']/'review.sqlite') as db:
            assert db.execute("SELECT count(*) FROM events WHERE kind='TEST_ONLY_LATER_REVIEW'").fetchone()[0]==1
    else:
        with sqlite3.connect(env['state']/'study2.sqlite') as db:
            table='dyad_registry' if kind=='issued_id' else 'dyad_events'
            assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]>=1


def test_untrusted_review_and_changed_target_workload_never_open_gate(environment,tmp_path):
    env=environment
    wrong=save(tmp_path/'outside-review.json',json.loads(Path(env['group_proof']['path']).read_text()))
    before=file_hash(env['reg'])
    with pytest.raises(Exception,match='untrusted_review_provenance'):
        update.stage_policy(env['cfg'],env['bp'],env['pp'],env['review'],wrong,
            expected_old_release=OLD,operator='SYNTHETIC PREPARER',reason='TEST ONLY')
    assert file_hash(env['reg'])==before
    env=prepared(env)
    target=Path(env['plan']['target_workload']['workload_path'])
    value=binding._json(target);value['exclusion_manifest_revision']='changed'
    save(target,value)
    with pytest.raises(Exception,match='review_disposition_binding_unavailable'):
        update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert not (env['state']/update.JOURNAL).exists()


def test_completed_recovery_retry_rechecks_actual_revisions(environment):
    env=prepared(environment)
    update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert update.recover(env['cfg'])['idempotent']
    with sqlite3.connect(env['state']/'review.sqlite') as db:
        db.execute('INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)',(AT,'TEST_ONLY_NEW_REVIEW','synthetic','{}'))
    with pytest.raises(Exception,match='revision_changed'):
        update.recover(env['cfg'])


@pytest.mark.parametrize('phase',['journal:after_replace','policy:after_replace','after_sqlite_commit'])
def test_actual_process_death_recovers_from_sqlite_authority(environment,phase):
    env=prepared(environment)
    payload={'cfg':env['cfg'],'plan':env['planpin'],'acceptance':env['accepted'],'phase':phase}
    child_environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    script="""
import json,os,sys
from study2 import coordinated_update as update
value=json.load(sys.stdin)
def die(phase):
    if phase==value['phase']:os._exit(73)
update._publish_fenced(value['cfg'],value['plan'],value['acceptance'],operator='SYNTHETIC PREPARER',fault=die)
"""
    result=subprocess.run([sys.executable,'-B','-c',script],input=json.dumps(payload),text=True,
        capture_output=True,env=child_environment,timeout=30)
    assert result.returncode==73,result.stderr
    with pytest.raises(Exception,match='coordinated_transition_recovery_required'):
        binding.resolve_current(env['cfg'])
    update._recover_fenced(env['cfg'])
    actual=binding._current_inventory(env['cfg']).release_id
    assert actual==(NEW if phase=='after_sqlite_commit' else OLD)
    assert binding.resolve_current(env['cfg'])==(Path(env['staged']['manifest']) if actual==NEW else env['oldmanifest'])
