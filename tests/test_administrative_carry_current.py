"""Temporary native tuples only. No operational data, service or DB copy."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3
import sys

import pytest

import test_coordinated_update as native
from study2 import administrative_carry_current as carry, coordinated_update as update
from study2 import review_dispositions as admin, review_workload, group_cleaning_operator as group
from study2 import flag_binding as binding
from study2.common import digest,file_hash
from study2.analysis_eligibility import sha


def case_rows(rid):
    return {f'SYN_CORRECTION_{i}':{'case_id':f'SYN_CORRECTION_{i}','kind':'identity','status':'pending',
        'rule':f'SYN_FIELD_{i}','record_a':'removed','record_b':'ordinary'}
        for i in range(4 if rid==native.OLD else 5)}


@pytest.fixture
def environment(tmp_path,monkeypatch):
    original_record,original_release,original_bundle=native.record,native.release,native.bundle
    def record(name):
        row=original_record(name)
        if name in {'removed','ordinary'}:
            row['dob']=None;row['answer']={'contact_01':'91234567'}
        return row
    def release(root,rid,rows,db):
        p=original_release(root,rid,rows,db)
        with gzip.open(p/'cases.jsonl.gz','wt') as f:
            for c in case_rows(rid).values():f.write(json.dumps(c)+'\n')
        checks=binding._json(p/'checksums.json');checks['cases.jsonl.gz']=file_hash(p/'cases.jsonl.gz');native.save(p/'checksums.json',checks)
        return p
    def bundle(root,cfg,rid,rows,eric,*,prior=None):
        bp,pp,_,b=original_bundle(root,cfg,rid,rows,eric,prior=prior)
        b['files']['cases']=native.save(root/'cases.json',case_rows(rid));b['revision']=sha({k:v for k,v in b.items() if k!='revision'});native.save(bp,b)
        proposal=group.preview(bp);native.save(pp,proposal)
        return bp,pp,proposal,b
    monkeypatch.setattr(native,'record',record);monkeypatch.setattr(native,'release',release);monkeypatch.setattr(native,'bundle',bundle)
    generator=native.environment.__wrapped__(tmp_path,monkeypatch);env=next(generator)
    try:
        old_cases=carry.canonical_cases({r['submission_id']:r for r in env['rows']},case_rows(native.OLD),list(case_rows(native.OLD)),[])
        source_bind={'release_id':native.OLD,'decision_revision':digest([]),'rules_hash':env['b']['rules_hash'],
                     'source_bindings':{'original_user_authority':'1'*64},'output_bindings':{'cases':digest(old_cases)}}
        request={'operation_id':'SYNTHETIC_ORIGINAL_CLOSURE','bindings':source_bind,
            'authorization':{'authorizer':'SYNTHETIC USER','reference':'SYNTHETIC ORIGINAL','reason':'SYNTHETIC ONLY'},
            'cases':old_cases,'questions':[{'case_index':i+1,'question_index':1,'record_id':c['record_a'],
                'version_id':c['version_a'],'field':'dob','comparison_ids':[c['case_id']]} for i,c in enumerate(old_cases)]}
        with sqlite3.connect(env['state']/'review.sqlite') as db:
            admin.apply_closed_unresolvable(db,request)
            projection=admin.project_closures(db,source_bind,old_cases)
        source_proposal=group.read_active(env['root'])['proposal']
        summary=deepcopy(env['summary']);summary['native_workload']=deepcopy(source_proposal['projection']['counts'])
        summary['active_workload']=deepcopy(summary['native_workload']);summary['active_workload']['field_correction_comparisons']=0
        summary['field_decisions_in_this_followup']=0
        summary['administrative_disposition']={'bindings':source_bind,'case_inventory':old_cases,
            'projection':projection,'admin_revision':projection['admin_revision'],'operation_id':request['operation_id']}
        native.save(env['workload'],summary);source_projection=env['state']/'review_dispositions/old-projection.json';native.save(source_projection,projection)
        env['oldwork'].update(workload_sha256=file_hash(env['workload']),admin_revision=projection['admin_revision'],
            operation_id=request['operation_id'],active_dataset_path=str(source_projection))
        native.save(env['state']/'CURRENT_REVIEW_DISPOSITION.json',env['oldwork']);env['summary']=summary
        names=['matching.py','respondents.py','review_core.py','review_hints.py','grades.py','common.py','parent_waves.py','review_dispatch.py','review_dispositions.py']
        scope={'format':'study2_admin_carry_scope_v1','source_bindings':source_bind,'source_admin_revision':projection['admin_revision'],
               'source_operation_id':request['operation_id'],'closed_cases':old_cases,'target_rules_hash':source_bind['rules_hash'],
               'target_code_sha256':carry._current_code_pins(names),'accepted_evidence_manifest_sha256':'2'*64,'acceptance_report_sha256':'3'*64}
        monkeypatch.setattr(carry,'SCOPED_CERTIFICATE_SHA256',digest(scope))
        env['scope']=scope;env['source_review_hash']=file_hash(env['state']/'review.sqlite')
        yield env
    finally:
        try:next(generator)
        except StopIteration:pass


def prepared(env):
    native.prepared(env)
    staged=env['staged']
    result=carry.stage_workload(env['cfg'],env['scope'],env['bp'],env['pp'],
        {'path':staged['manifest'],'sha256':file_hash(Path(staged['manifest']))},env['new'],
        env['state']/'review_dispositions/current-carry-target')
    plan=env['plan'];plan['target_workload']=result['pointer']
    plan['target_selection']['environment']['STUDY2_CURRENT_REVIEW_WORKLOAD']=result['pointer']['workload_path']
    plan['revision']=sha({k:v for k,v in plan.items() if k!='revision'})
    env['planpin']=native.save(env['trusted']/'publication-plan.json',plan)
    env['accepted']=native.proof(env['trusted'],'publication-review.json','publication_tuple',plan['revision'])
    env['carry_result']=result
    return env


def test_current_carry_is_consumed_by_native_activation_and_retry_without_reclosing(environment):
    env=prepared(environment);flags_before=file_hash(env['reg'])
    assert env['carry_result']['closed_comparisons']==4 and env['carry_result']['active_comparisons']==1
    assert env['carry_result']['held_comparisons']==0
    assert binding.resolve_current(env['cfg'])==env['oldmanifest']
    result=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert result['release_id']==native.NEW
    assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
    value,rows=review_workload.load_summary(release_id=native.NEW,decision_revision=digest([]),
        exclusion_revision=env['staged']['manifest_revision'],path=env['carry_result']['pointer']['workload_path'],review_state=env['state'],cfg=env['cfg'])
    assert value['active_workload']['field_correction_comparisons']==1
    assert value['administrative_disposition']['projection']['closed_unresolvable_comparisons']==4
    again=update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert again['idempotent']
    assert file_hash(env['reg'])==flags_before and file_hash(env['state']/'review.sqlite')==env['source_review_hash']


def test_public_owned_publish_consumes_carry_and_completed_retry_is_readonly(environment):
    from study2.consumer_owner_fence import OwnedConsumerFence
    from test_owned_journal_integration import start
    from test_coordinated_update_r2 import file_state, tracking
    env=prepared(environment);plan=env['plan']
    canonical=env['state']/'synthetic-canonical-config.json';native.save(canonical,env['cfg'])
    for name in ('old_selection','target_selection'):
        plan[name].update(canonical_config=str(canonical),canonical_config_sha256=file_hash(canonical),
                          config=str(canonical),state_dir=str(env['state']))
    plan['gate_selection']={**plan['old_selection'],'coordinated_update_gate':True}
    native.save(env['selection'],plan['old_selection'])
    worker=Path(__file__).with_name('owned_journal_reader.py')
    argv=[sys.executable,'-B',str(worker),str(native.CODE/'local_update_entry.py'),'--activation',str(env['selection'])]
    plan['consumer_owner_scope']={'format':'study2_owned_consumer_scope_v1','state_dir':str(env['state']),
        'selection_path':str(env['selection']),'owners':{'reader':{'kind':'owned_popen','argv':argv,
        'input_pins':[{'path':str(worker),'sha256':file_hash(worker)},{'path':str(canonical),'sha256':file_hash(canonical)}]}}}
    plan['input_pins'].append({'path':str(canonical),'sha256':file_hash(canonical)})
    plan['revision']=sha({k:v for k,v in plan.items() if k!='revision'})
    env['planpin']=native.save(env['trusted']/'owned-carry-plan.json',plan)
    env['accepted']=native.proof(env['trusted'],'owned-carry-review.json','publication_tuple',plan['revision'])
    owner=OwnedConsumerFence(env['cfg'],plan);env['owner']=owner
    flags_before=file_hash(env['reg'])
    try:
        process=start(env)
        result=update.publish(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',owner_fence=owner)
        assert result['release_id']==native.NEW and process.poll() is not None
        assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
        before,files=tracking(env),file_state(env)
        retry=update.publish(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
        assert retry['idempotent'] and retry['read_only'] and retry['release_id']==native.NEW
        assert tracking(env)==before and file_state(env)==files
        assert file_hash(env['reg'])==flags_before and file_hash(env['state']/'review.sqlite')==env['source_review_hash']
    finally:
        owner.cleanup_owned()


def test_individual_target_drift_is_held_while_three_unaffected_closures_proceed(environment):
    env=environment
    # Change one case's evidence without changing the other three comparisons.
    changed=binding._json(env['b']['files']['cases']['path']);changed['SYN_CORRECTION_0']['rule']='SYN_CHANGED_RULE'
    env['b']['files']['cases']=native.save(env['bp'].parent/'cases.json',changed)
    env['b']['revision']=sha({k:v for k,v in env['b'].items() if k!='revision'});native.save(env['bp'],env['b'])
    with gzip.open(env['new']/'cases.jsonl.gz','wt') as f:
        for c in changed.values():f.write(json.dumps(c)+'\n')
    checks=binding._json(env['new']/'checksums.json');checks['cases.jsonl.gz']=file_hash(env['new']/'cases.jsonl.gz');native.save(env['new']/'checksums.json',checks)
    env['proposal']=group.preview(env['bp']);native.save(env['pp'],env['proposal'])
    env['subject']=sha({'bundle_revision':env['b']['revision'],'proposal_revision':env['proposal']['revision'],'old_release_id':native.OLD,'target_release_id':native.NEW})
    env['group_proof']=native.proof(env['trusted'],'group-review.json','group_policy',env['subject'])
    native.save(env['review'],{'format':group.REVIEW_FORMAT,'proposal_revision':env['proposal']['revision'],'accepted':True,
        'reviewer':'INDEPENDENT SYNTHETIC TEST REVIEWER','reason':'TEST ONLY','review_manifest_sha256':env['group_proof']['sha256']})
    env=prepared(env)
    assert (env['carry_result']['closed_comparisons'],env['carry_result']['active_comparisons'],env['carry_result']['held_comparisons'])==(3,1,1)
    update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert binding.resolve_current(env['cfg'])==Path(env['staged']['manifest'])
    summary=binding._json(env['carry_result']['pointer']['workload_path'])
    assert summary['active_workload']['administrative_carry_holds']==1
    assert summary['administrative_disposition']['projection']['held_case_ids']==['SYN_CORRECTION_0']
    assert file_hash(env['state']/'review.sqlite')==env['source_review_hash']


@pytest.mark.parametrize('phase',['workload:after_replace','before_sqlite_commit','after_sqlite_commit'])
def test_existing_journal_recovers_old_or_target_tuple_without_replaying_closures(environment,phase):
    env=prepared(environment);flags_before=file_hash(env['reg'])
    def fail(point):
        if point==phase:raise OSError('SYNTHETIC INTERRUPTION')
    with pytest.raises(OSError):update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER',fault=fail)
    assert binding._json(env['state']/update.JOURNAL)['status']=='pending'
    update._recover_fenced(env['cfg'])
    rid=binding._current_inventory(env['cfg']).release_id
    assert rid==(native.NEW if phase=='after_sqlite_commit' else native.OLD)
    binding.resolve_current(env['cfg'])
    assert file_hash(env['reg'])==flags_before and file_hash(env['state']/'review.sqlite')==env['source_review_hash']


@pytest.mark.parametrize('change',['main','rules','review','target_case'])
def test_stale_global_context_or_inputs_block_before_gate(environment,change):
    env=prepared(environment)
    if change=='main':
        with sqlite3.connect(env['state']/'study2.sqlite') as db:db.execute("INSERT INTO labels VALUES('SYN_LATE','MATCH','SYN','SYN','SYN','{}')")
    elif change=='rules':env['cfg']['duplicate_days']=31
    elif change=='review':
        with sqlite3.connect(env['state']/'review.sqlite') as db:db.execute("UPDATE followups SET state='SYN_CORRUPT' WHERE case_id='SYN_CORRECTION_0'")
    elif change=='target_case':
        with (env['new']/'cases.jsonl.gz').open('ab') as f:f.write(b'SYN_CHANGED')
    with pytest.raises(Exception):update._publish_fenced(env['cfg'],env['planpin'],env['accepted'],operator='SYNTHETIC PREPARER')
    assert not (env['state']/update.JOURNAL).exists()
    assert binding._current_inventory(env['cfg']).release_id==native.OLD


def test_unresolved_source_case_missing_from_target_is_preserved_as_separate_hold(environment):
    env=environment
    source=deepcopy(env['summary']);extra=deepcopy(source['administrative_disposition']['case_inventory'][0]);extra['case_id']='SYN_UNRESOLVED_MISSING'
    source['administrative_disposition']['case_inventory'].append(extra)
    source['administrative_disposition']['projection']['active_case_ids'].append(extra['case_id'])
    target=carry.canonical_cases({r['submission_id']:r for r in env['rows']},case_rows(native.NEW),list(case_rows(native.NEW)),[])
    with sqlite3.connect(env['state']/'review.sqlite') as work:
        projection,holds=carry.project_current(work,env['scope'],source,env['scope']['source_bindings'],target)
    assert projection['closed_unresolvable_comparisons']==4 and projection['active_correction_comparisons']==1
    assert projection['source_only_hold_comparisons']==1
    assert holds[0]['case_id']=='SYN_UNRESOLVED_MISSING'


def test_untrusted_scope_and_partial_preparation_never_move_current_tuple(environment):
    env=environment;native.prepared(env)
    before_pointer=binding._json(env['state']/'CURRENT_REVIEW_DISPOSITION.json')
    before_registry=file_hash(env['reg']);before_review=file_hash(env['state']/'review.sqlite')
    args=(env['cfg'],env['scope'],env['bp'],env['pp'],
          {'path':env['staged']['manifest'],'sha256':file_hash(Path(env['staged']['manifest']))},env['new'])
    bad=deepcopy(env['scope']);bad['closed_cases'][0]['evidence_hash']='0'*64
    with pytest.raises(ValueError,match='unaccepted_scope'):
        carry.stage_workload(env['cfg'],bad,*args[2:],env['state']/'review_dispositions/untrusted')
    output=env['state']/'review_dispositions/interrupted'
    def fail(phase):
        if phase=='workload.json:after_sync':raise OSError('SYNTHETIC PREP INTERRUPTION')
    with pytest.raises(OSError,match='SYNTHETIC PREP INTERRUPTION'):
        carry.stage_workload(*args,output,fault=fail)
    assert (output/'workload.json').exists() and not (output/'pointer.json').exists()
    assert binding._json(env['state']/'CURRENT_REVIEW_DISPOSITION.json')==before_pointer
    assert file_hash(env['reg'])==before_registry and file_hash(env['state']/'review.sqlite')==before_review
    assert binding.resolve_current(env['cfg'])==env['oldmanifest']
    with pytest.raises(ValueError,match='new_derived_output_required'):
        carry.stage_workload(*args,output)


def test_derived_hold_is_visible_without_identifiers_in_existing_workload_panel(environment,monkeypatch):
    from test_group_intent_review import UI
    env=environment;source=deepcopy(env['summary'])
    extra=deepcopy(source['administrative_disposition']['case_inventory'][0]);extra['case_id']='SYN_MISSING_UNRESOLVED'
    source['administrative_disposition']['case_inventory'].append(extra)
    source['administrative_disposition']['projection']['active_case_ids'].append(extra['case_id'])
    cases=carry.canonical_cases({r['submission_id']:r for r in env['rows']},case_rows(native.NEW),list(case_rows(native.NEW)),[])
    with sqlite3.connect(env['state']/'review.sqlite') as db:
        projection,holds=carry.project_current(db,env['scope'],source,env['scope']['source_bindings'],cases)
    value=deepcopy(env['summary']);value['administrative_disposition'].update(projection=projection,carry_forward={'holds':holds})
    monkeypatch.setattr(review_workload,'load_summary',lambda **kwargs:(value,[]))
    ui=UI()
    # Only the existing renderer is exercised here; live validation is covered
    # by the real tuple tests rather than mocked into the activation path.
    ui.columns=lambda number:[UI() for _ in range(number)]
    assert review_workload.render_current_review_workload(ui,release_id=native.NEW,decision_revision=digest([]),cfg=env['cfg'])
    tables=[args[0] for name,args,_ in ui.calls if name=='dataframe']
    assert 'unresolved source comparison' in tables[-1][0]['Reason'].lower()
    assert 'SYN_MISSING' not in json.dumps(tables)
