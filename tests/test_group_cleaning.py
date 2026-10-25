from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from study2.common import digest,file_hash,dumps
from study2.analysis_eligibility import sha,validate_manifest,inventory_revision
from study2.group_cleaning import (classify_scope,burst_candidate,project_workload,
    exclusion_manifest,make_proposal,PolicyError,SOURCE_FORMAT)
from study2 import group_cleaning_operator as op
from study2.review_core import rules_hash
from study2.store import SCHEMA


def rec(sid,number='61234567',second=0,child=None):
    at=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=second)).isoformat()
    raw={'Survey':'Synthetic Qualtrics','建立時間':at,'tag':sid}
    h=digest(raw)
    return dict(submission_id=sid,version_id=digest([sid,h]),raw_hash=h,raw=raw,
        answer={'contact_01':number},child_id=child or 'CHILD_'+sid,role='student',
        dob='2012-01-01',gender='0',school='Synthetic Academy',status='eligible',
        source_label='Synthetic Qualtrics',observed_at=at,time_confidence='observed',
        date_basis='system_creation',selected_wave='T0')


def scope(rows,gid='GROUP_synthetic'):
    records={r['submission_id']:r for r in rows};ids=sorted(records)
    cases={f'CASE_{i}':dict(case_id=f'CASE_{i}',record_a=a,record_b=b,kind='identity',
        status='pending',version_a=records[a]['version_id'],version_b=records[b]['version_id'])
        for i,(a,b) in enumerate(zip(ids,ids[1:]))}
    g=dict(case_id=gid,kind='identity',rule='child_group_contact_gap',status='pending',
        record_a=ids[0],record_b=ids[-1],reason='Synthetic scope',group_review=dict(
        members=ids,comparison_ids=sorted(cases),passed_pairs=[],unresolved_pairs=[],missing_pairs=[],
        contact_components=[[s] for s in ids],conflicts=[],manual_restrictions=[],issue='contact_gap',route='review'))
    return records,cases,g


def source(records):
    body=dict(format=SOURCE_FORMAT,records={s:dict(submission_id=s,version_id=r['version_id'],
        raw_hash=r['raw_hash'],source_key=r['raw']['Survey'].lower(),observed_at=r['observed_at'],
        raw_timestamp=r['raw']['建立時間'],timestamp_kind='genuine_submission',precision='second',
        origin_kind='qualtrics',source=dict(path='/invented/source.xlsx',sha256='a'*64,sheet='Sheet1',
            row=i+2,column='建立時間')) for i,(s,r) in enumerate(records.items())})
    body['revision']=sha(body);return body


@pytest.mark.parametrize('a,b',[('61234567','61234568'),('61234567','61237564'),
    ('+852 (6123) 4567','6123-4568')])
def test_existing_phone_rule_and_normalization(a,b):
    r,c,g=scope([rec('a',a),rec('b',b)])
    result=classify_scope(r,g,c)
    assert len(result['questions'])==1 and not result['holds'] and not result['closures']


def test_email_exact_protected_and_distinct_emails_no_similarity_operation():
    r,c,g=scope([rec('a','first@example.com'),rec('b','firsx@example.com')])
    assert len(classify_scope(r,g,c)['closures'])==1
    r['b']['answer']['contact_01']='first@example.com'
    assert classify_scope(r,g,c)['holds'][0]['reasons']==['exact_contact_across_unconfirmed_atoms']
    r['b']['child_id']=r['a']['child_id'];g['group_review']['passed_pairs']=[dict(a='a',b='b')]
    result=classify_scope(r,g,c);assert result['protected_atoms']==[['a','b']] and not result['closures']


@pytest.mark.parametrize('value',['','invalid','123456','61234567；63456789'])
def test_missing_invalid_uncertain_contact_hold(value):
    r,c,g=scope([rec('a',value),rec('b','63456789')])
    assert len(classify_scope(r,g,c)['holds'])==1


def test_optional_blanks_and_explicit_partition_priority_without_identity_split():
    r,c,g=scope([rec('a','bad-token'),rec('b','63456789')])
    assert classify_scope(r,g,c,partition=[['a'],['b']])['closures']
    assert classify_scope(r,g,c,partition=[['a'],['b']])['closures'][0]['contact_evidence']['a']['invalid']
    r['b']['child_id']=r['a']['child_id']
    with pytest.raises(PolicyError,match='splits_supported'):classify_scope(r,g,c,partition=[['a'],['b']])


@pytest.mark.parametrize('problem',['dob','manual','direct'])
def test_contradictory_direct_and_manual_evidence_hold(problem):
    r,c,g=scope([rec('a'),rec('b','63456789')])
    if problem=='dob':r['b']['dob']='2013-02-02'
    if problem=='manual':g['group_review']['manual_restrictions']=[['a','b']]
    if problem=='direct':g['group_review']['passed_pairs']=[dict(a='a',b='b',rule='existing_rule')]
    result=classify_scope(r,g,c);assert result['holds'] and not result['closures']
    assert len(result['protected_atoms'])==2


def test_only_concrete_atom_pairs_and_partial_scope_native_pair_lists():
    r,c,g=scope([rec('a'),rec('b','63456789'),rec('c','65678901')])
    g['group_review']['conflicts']=[['a','b']];g['group_review']['manual_restrictions']=[['a','b']]
    p=project_workload(r,c,{'g':g},excluded={'a'})
    assert len(p['closures'])==1 and p['closures'][0]['comparison_ids']==['CASE_1']


def test_policy_closure_does_not_remove_unrelated_field_correction():
    r,c,g=scope([rec('a'),rec('b','63456789')])
    r['missing']=rec('missing','62345678');r['missing']['dob']=''
    c['correction']=dict(case_id='correction',kind='identity',record_a='a',record_b='missing',status='pending')
    p=project_workload(r,c,{'g':g})
    assert p['correction_comparison_ids']==['correction'] and p['closures']


@pytest.mark.parametrize('n,span,outcome',[(5,100,'not_burst'),(6,120,'candidate'),(6,121,'not_burst'),(6,500,'not_burst')])
def test_burst_boundary_and_full_range(n,span,outcome):
    r={str(i):rec(str(i),str(61230000+i),i*span/(n-1)) for i in range(n)}
    before=deepcopy(r);p=burst_candidate(r,list(r),source(r));assert p['outcome']==outcome and r==before


@pytest.mark.parametrize('basis',[None,'unknown','imported_creation','batch_date','manual_verified','batch_assigned_creation',''])
def test_only_explicit_genuine_basis(basis):
    r={str(i):rec(str(i),second=i) for i in range(6)};r['0']['date_basis']=basis
    assert burst_candidate(r,list(r),source(r))['outcome']=='hold'


@pytest.mark.parametrize('mutation',['date_only','no_zone','minute','bad_proof','stale','mixed_source','missing_source'])
def test_source_precision_version_and_genuine_source_binding(mutation):
    r={str(i):rec(str(i),second=i) for i in range(6)};s=source(r)
    if mutation=='date_only':s['records']['0']['raw_timestamp']='2026-01-01'
    elif mutation=='no_zone':s['records']['0']['raw_timestamp']='2026-01-01T00:00:00'
    elif mutation=='minute':s['records']['0']['precision']='minute'
    elif mutation=='bad_proof':s['records']['0']['source']['sha256']='bad'
    elif mutation=='stale':s['records']['0']['version_id']='old'
    elif mutation=='mixed_source':s['records']['0']['source_key']='different'
    elif mutation=='missing_source':del s['records']['0']
    s['revision']=sha({k:v for k,v in s.items() if k!='revision'})
    assert burst_candidate(r,list(r),s)['outcome']=='hold'


def test_raw_date_only_cannot_be_hidden_by_normalized_proof():
    r={str(i):rec(str(i),second=i) for i in range(6)};s=source(r)
    r['0']['raw']['建立時間']='2026-01-01';r['0']['raw_hash']=digest(r['0']['raw']);s['records']['0']['raw_hash']=r['0']['raw_hash']
    s['revision']=sha({k:v for k,v in s.items() if k!='revision'})
    assert burst_candidate(r,list(r),s)['outcome']=='hold'


def fixture_bundle(tmp_path,*,append=False):
    state=tmp_path/'state';state.mkdir(exist_ok=True);(state/'writer.lock').touch(exist_ok=True)
    db=sqlite3.connect(state/'study2.sqlite');db.executescript(SCHEMA)
    if not db.execute('SELECT 1 FROM runs').fetchone():
        db.execute("INSERT INTO runs VALUES('run','fp','now','published','{}','{}',NULL)")
        db.execute("INSERT INTO releases VALUES('release','run','now','unused','{}')")
        db.execute("INSERT INTO publication VALUES(1,'release')")
    db.commit();db.close()
    r,c,g=scope([rec(str(i),str(61230000+i),i) for i in range(6)])
    if append:r['unrelated']=rec('unrelated','64567890',500)
    cfg={'state_dir':str(state)}
    eric=exclusion_manifest(list(r.values()),'release',[],operator='synthetic',at='2026-01-01T00:00:00+00:00')
    values=dict(config=cfg,records=r,cases=c,groups={'group':g},decisions=[],eric_manifest=eric,
                source_evidence=source(r),authorization={},partitions={},user_exclusions={})
    files={}
    for name,value in values.items():
        p=tmp_path/(name+('_append' if append else '')+'.json');p.write_text(json.dumps(value))
        files[name]={'path':str(p),'sha256':file_hash(p)}
    main=op._main_revision(cfg)['main_revision']
    b=dict(format=op.BUNDLE_FORMAT,release_id='release',main_revision=main,rules_hash=rules_hash(cfg),files=files)
    b['revision']=sha(b);path=tmp_path/('bundle_append.json' if append else 'bundle.json');path.write_text(json.dumps(b))
    return path,values


def proposal_review(tmp_path,bundle):
    proposal=op.preview(bundle);p=tmp_path/('proposal_'+proposal['revision'][:12]+'.json');p.write_text(json.dumps(proposal))
    review=dict(format=op.REVIEW_FORMAT,proposal_revision=proposal['revision'],accepted=True,
                reviewer='Independent synthetic reviewer',reason='Synthetic accepted candidate',review_manifest_sha256='f'*64)
    q=tmp_path/('review_'+proposal['revision'][:12]+'.json');q.write_text(json.dumps(review));return p,q


def test_apply_idempotent_local_workflow_undo_restore_histories(tmp_path,monkeypatch):
    bundle,values=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    before=file_hash(tmp_path/'state/study2.sqlite')
    result=op.apply(root,bundle,p,q,operator='Jarvis',reason='synthetic')
    assert not result['idempotent'];assert op.apply(root,bundle,p,q,operator='Jarvis',reason='synthetic')['idempotent']
    view=op.local_snapshot(bundle,root,include_cases=True);assert view['status']=='applied_local_policy'
    h=result['pointer']['manifest_sha256'];undone=op.undo(root,bundle,expected_head=h,operator='Jarvis',reason='undo')
    assert op.undo(root,bundle,expected_head=h,operator='Jarvis',reason='undo')['idempotent']
    assert op.local_snapshot(bundle,root)['status']=='inactive'
    op.apply(root,bundle,p,q,operator='Jarvis',reason='restore reviewed policy')
    assert op.local_snapshot(bundle,root)['status']=='applied_local_policy'
    assert file_hash(tmp_path/'state/study2.sqlite')==before
    assert len(list(root.glob('gen_*')))==3


@pytest.mark.parametrize('phase',['after_before_backup','after_registry_copy','after_registry_update','after_complete_backup','after_pointer_commit'])
def test_interrupted_generation_never_exposes_partial_state(tmp_path,phase):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    def fail(at):
        if at==phase:raise OSError('synthetic interruption')
    with pytest.raises(OSError):op.apply(root,bundle,p,q,operator='Jarvis',reason='synthetic',fault=fail)
    committed=phase=='after_pointer_commit'
    assert (op.read_active(root) is not None)==committed
    result=op.apply(root,bundle,p,q,operator='Jarvis',reason='synthetic')
    assert result['idempotent']==committed
    assert op.read_active(root)['policy']['policy_active']


@pytest.mark.parametrize('drift',['publication','config','versions'])
def test_stale_bundle_cannot_activate(tmp_path,drift):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle)
    if drift=='publication':
        db=sqlite3.connect(tmp_path/'state/study2.sqlite');db.execute("INSERT INTO releases VALUES('new','run','now','unused','{}')");db.execute("UPDATE publication SET release_id='new'");db.commit();db.close()
    else:
        b=json.loads(bundle.read_text());key='config' if drift=='config' else 'records';path=Path(b['files'][key]['path']);v=json.loads(path.read_text())
        if drift=='config':v['minimum_followup_days']=180
        else:v['0']['version_id']='changed'
        path.write_text(json.dumps(v))
    with pytest.raises(PolicyError):op.apply(tmp_path/'control',bundle,p,q,operator='Jarvis',reason='synthetic')


def test_explicit_append_refresh_preserves_exact_flags_and_history(tmp_path):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    op.apply(root,bundle,p,q,operator='Jarvis',reason='first')
    old=op.read_active(root);old_sha=file_hash(old['folder']/'policy-flags.sqlite')
    new_bundle,_=fixture_bundle(tmp_path,append=True)
    carry=op.carry_preview(new_bundle,root)
    cp=tmp_path/'carry.json';cp.write_text(json.dumps(carry))
    b=json.loads(new_bundle.read_text());b['files']['carry']={'path':str(cp),'sha256':file_hash(cp)};b['revision']=sha({k:v for k,v in b.items() if k!='revision'});new_bundle.write_text(json.dumps(b))
    p2,q2=proposal_review(tmp_path,new_bundle)
    op.apply(root,new_bundle,p2,q2,operator='Jarvis',reason='explicit reviewed append refresh')
    current=op.read_active(root)
    assert len(current['policy_manifest']['entries'])==6
    assert current['policy_manifest']['inventory_revision']!=old['policy_manifest']['inventory_revision']
    assert file_hash(old['folder']/'policy-flags.sqlite')==old_sha
    assert current['receipt']['previous_pointer']==old['pointer']


def test_append_refresh_undo_rejects_before_any_generation_or_pointer_mutation(tmp_path):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    op.apply(root,bundle,p,q,operator='Jarvis',reason='initial policy')
    new_bundle,_=fixture_bundle(tmp_path,append=True)
    carry=op.carry_preview(new_bundle,root);cp=tmp_path/'carry.json';cp.write_text(json.dumps(carry))
    body=json.loads(new_bundle.read_text());body['files']['carry']={'path':str(cp),'sha256':file_hash(cp)}
    body['revision']=sha({k:v for k,v in body.items() if k!='revision'});new_bundle.write_text(json.dumps(body))
    p2,q2=proposal_review(tmp_path,new_bundle)
    applied=op.apply(root,new_bundle,p2,q2,operator='Jarvis',reason='reviewed append refresh')
    before={str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
    assert op.local_snapshot(new_bundle,root)['status']=='applied_local_policy'
    with pytest.raises(PolicyError,match='undo_incompatible_source_or_inventory'):
        op.undo(root,new_bundle,expected_head=applied['pointer']['manifest_sha256'],operator='Jarvis',reason='undo refresh')
    assert {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}==before
    assert op.read_active(root)['pointer']==applied['pointer']
    assert op.local_snapshot(new_bundle,root,include_cases=True)['status']=='applied_local_policy'


@pytest.mark.parametrize('drift',['version','missing'])
def test_refresh_rejects_changed_or_missing_old_target(tmp_path,drift):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    op.apply(root,bundle,p,q,operator='Jarvis',reason='first')
    b=json.loads(bundle.read_text());rp=Path(b['files']['records']['path']);records=json.loads(rp.read_text())
    if drift=='version':records['0']['version_id']='changed'
    else:del records['0']
    rp.write_text(json.dumps(records));b['files']['records']['sha256']=file_hash(rp);b['revision']=sha({k:v for k,v in b.items() if k!='revision'});bundle.write_text(json.dumps(b))
    with pytest.raises(PolicyError,match='carry_missing_or_changed'):op.carry_preview(bundle,root)


def test_input_pin_checks_consumed_blob_not_later_path(tmp_path,monkeypatch):
    p=tmp_path/'value';p.write_bytes(b'old');read=Path.read_bytes
    def swap(path):
        data=read(path)
        if path==p:path.write_bytes(b'new')
        return data
    monkeypatch.setattr(Path,'read_bytes',swap)
    with pytest.raises(PolicyError,match='input_pin_changed'):
        op._read_file({'path':str(p),'sha256':hashlib.sha256(b'new').hexdigest()})


def test_parquet_uses_verified_bytes(tmp_path,monkeypatch):
    bundle,_=fixture_bundle(tmp_path);p=tmp_path/'data.parquet';pd.DataFrame({'x':[1]}).to_parquet(p)
    b=json.loads(bundle.read_text());b['files']['analysis']={'path':str(p),'sha256':file_hash(p)};b['revision']=sha({k:v for k,v in b.items() if k!='revision'});bundle.write_text(json.dumps(b))
    real=op._read_file
    def replace(pin):
        result=real(pin)
        if pin['path']==str(p):pd.DataFrame({'x':[999]}).to_parquet(p)
        return result
    monkeypatch.setattr(op,'_read_file',replace)
    _,data,_=op.load_bundle(bundle);assert data['analysis'].x.tolist()==[1]


def test_snapshot_blocks_new_publication_even_with_unchanged_decisions(tmp_path):
    bundle,_=fixture_bundle(tmp_path);p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    op.apply(root,bundle,p,q,operator='Jarvis',reason='first')
    db=sqlite3.connect(tmp_path/'state/study2.sqlite');db.execute("INSERT INTO releases VALUES('new','run','now','unused','{}')");db.execute("UPDATE publication SET release_id='new'");db.commit();db.close()
    with pytest.raises(PolicyError,match='source_publication_changed'):op.local_snapshot(bundle,root)


def test_new_flag_lane_does_not_change_eric_and_keeps_overlap(tmp_path):
    bundle,v=fixture_bundle(tmp_path);b=json.loads(bundle.read_text())
    original=exclusion_manifest(list(v['records'].values()),'release',{'0'},operator='Eric',at='2026-01-01T00:00:00+00:00')
    p=Path(b['files']['eric_manifest']['path']);p.write_text(json.dumps(original));before=p.read_bytes()
    b['files']['eric_manifest']['sha256']=file_hash(p);b['revision']=sha({k:w for k,w in b.items() if k!='revision'});bundle.write_text(json.dumps(b))
    proposal=op.preview(bundle);assert proposal['flag_counts']['eric_overlap']==1 and proposal['flag_counts']['newly_excluded']==5
    pp,q=proposal_review(tmp_path,bundle);root=tmp_path/'control';op.apply(root,bundle,pp,q,operator='Jarvis',reason='reviewed')
    active=op.read_active(root);assert len(active['combined_manifest']['entries'])==6 and p.read_bytes()==before


def test_legacy_queue_consumer_contract_is_unchanged(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from study2 import review_core,store,review_dispatch
    r,c,g=scope([rec('a'),rec('b','61234568')])
    ctx=SimpleNamespace(records=r,cases={**c,g['case_id']:g},group_cases={g['case_id']:g},
        decisions=[],release={'release_id':'release'},review_evidence={})
    class ReadOnlyDummy:
        def close(self):pass
    monkeypatch.setattr(store,'connect',lambda *a,**k:ReadOnlyDummy())
    monkeypatch.setattr(review_core,'Context',lambda *a:ctx)
    result=review_dispatch.queue_snapshot({'state_dir':str(tmp_path)},include_cases=True)
    assert {'pending_routes','awaiting_evidence_work','awaiting_evidence_groups',
        'awaiting_evidence_adult_comparisons','child_groups_pending','child_groups_operator','cases','groups'}<=result.keys()
    assert 'policy_pointer' not in result
