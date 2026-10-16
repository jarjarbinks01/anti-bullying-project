import copy
import json
from itertools import combinations
from pathlib import Path

import pytest
from openpyxl import load_workbook

from study2 import review_core as core
from study2.common import PipelineError, dumps
from study2.matching import candidate, identity_evidence
from study2.review_dispatch import summary
from study2.review_excel import read_package
from study2.review_groups import build_groups
from study2.store import connect
from test_identity_and_time import rec
from test_store_and_review import database, published


@pytest.fixture
def group_project(tmp_path):
    cfg = {'state_dir':str(tmp_path), 'matching_policy':{'allow_school_transfer':True},
           'minimum_followup_days':90, 'duplicate_days':30}
    rows = [rec('a',child_id='child_a'), rec('b',120,role='parent',child_id='child_b'),
            rec('c',240,child_id='child_c')]
    rows[0]['answer']['contact_01']='61234567'
    rows[1]['answer'].update(contact_01='61234567',contact_02='62345678')
    rows[2]['answer']['contact_01']='62345678'
    db=database(tmp_path); published(db,cfg,rows)
    db.execute('DELETE FROM release_candidates')
    for a,b in combinations(rows,2):
        kind='identity' if a['role']==b['role'] else 'family'
        c=candidate(a,b,kind,'exact_school_contact_child_demo' if b['submission_id']=='b' or a['submission_id']=='b' else 'school_child_demo','pending','Competing or contradictory candidate component')
        db.execute('INSERT INTO release_candidates VALUES(?,?,?)',('release',c['case_id'],dumps(c)))
    db.commit();db.close()
    return cfg


def ctx(cfg):
    db=connect(Path(cfg['state_dir']),readonly=True)
    try:return core.Context(db,cfg)
    finally:db.close()


def submitted(cfg, verdict='確認相同'):
    package=core.create_package(cfg,'helper')
    assert len(package['tasks'])==1
    task=package['tasks'][0]
    core.submit_reviews(cfg,package['package_id'],[{'task_id':task['task_id'],'verdict':verdict,
        'evidence_source':'既有收集紀錄','reason':'核對全組 R 編號及聯絡連結'}])
    return package,task


def test_one_group_replaces_strong_pairs_and_exposes_actual_gap(group_project):
    cfg=group_project;c=ctx(cfg)
    assert len(c.group_cases)==1
    g=next(iter(c.group_cases.values()))
    assert g['group_review']['members']==['a','b','c']
    assert g['group_review']['issue']=='contact_bridge'
    assert g['record_a']=='a' and g['record_b']=='c'
    assert len(g['group_review']['passed_pairs'])==2
    assert len(g['group_review']['missing_pairs'])==1
    queue=summary(c,include_cases=True)
    assert queue['reviewable_comparisons_before_grouping']==2
    assert queue['reviewable_pending']==queue['child_groups_pending']==1
    assert all(r['route']=='group_reference' for r in queue['cases'] if r['case_id'] not in c.group_cases)
    before=copy.deepcopy(c.records)
    assert build_groups(c.records,{k:v for k,v in reversed(list(c.cases.items()))},[],cfg['matching_policy'])==c.group_cases
    assert c.records==before


def test_child_pair_cannot_bypass_group_dispatch(group_project):
    c=ctx(group_project);cid=next(k for k,v in c.cases.items() if v['rule']=='exact_school_contact_child_demo')
    with pytest.raises(PipelineError,match='整組派審'):
        core.create_package(group_project,'helper',case_ids=[cid])


def test_group_match_stages_approves_and_applies_complete_membership(group_project):
    cfg=group_project;pkg,task=submitted(cfg)
    db=connect(Path(cfg['state_dir']))
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0
    batch=core.preview_batch(cfg)
    assert not batch['conflicts']
    assert len([r for r in batch['rows'] if r['action']=='LINK'])==2
    core.approve_batch(cfg,batch['batch_id'],reason='Jarvis 已核對整組')
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0
    assert core.apply_batch(cfg,batch['batch_id'])['corrections']==2
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==2
    assert core.apply_batch(cfg,batch['batch_id'])['recovered_or_repeated']
    db.close()


def test_group_bridge_can_record_a_missing_cross_school_pair(group_project):
    cfg=group_project
    db=connect(Path(cfg['state_dir']))
    r=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='c'").fetchone()[0])
    r['school']='New School'
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='c'",(dumps(r),))
    for row in db.execute('SELECT case_id,payload_json FROM release_candidates').fetchall():
        c=json.loads(row['payload_json'])
        if {c['record_a'],c['record_b']}=={'a','c'}:
            db.execute('DELETE FROM release_candidates WHERE case_id=?',(row['case_id'],))
    db.commit();db.close()
    submitted(cfg)
    batch=core.preview_batch(cfg)
    assert not batch['conflicts'] and any(r['case_id']=='NEW' for r in batch['rows'])
    core.approve_batch(cfg,batch['batch_id'],reason='核對跨校群組')
    assert core.apply_batch(cfg,batch['batch_id'])['corrections']==2


def test_group_nonmatch_requires_explicit_partition_not_all_pair_unlinks(group_project):
    cfg=group_project;pkg,task=submitted(cfg,'確認不同');gid=task['snapshot']['case']['case_id']
    batch=core.preview_batch(cfg)
    assert not batch['rows'] and 'group_partition' in batch['conflicts'][0]['message']
    review_id=batch['conflicts'][0]['reviews'][0]['review_id']
    resolution={gid:{'review_id':review_id,'reason':'採納同事分組並核對紀錄','group_partition':[['a','b'],['c']]}}
    good=core.preview_batch(cfg,adjudications=resolution)
    assert not good['conflicts']
    assert len([r for r in good['rows'] if r['action']=='LINK'])==1
    assert len([r for r in good['rows'] if r['action']=='UNLINK'])==2
    core.approve_batch(cfg,good['batch_id'],reason='確認分組')
    assert core.apply_batch(cfg,good['batch_id'])['corrections']==3


def test_unresolved_group_keeps_matching_and_creates_one_followup(group_project):
    cfg=group_project;pkg,task=submitted(cfg,'資料不足')
    batch=core.preview_batch(cfg);assert not batch['conflicts']
    core.approve_batch(cfg,batch['batch_id'],reason='保留待查')
    assert core.apply_batch(cfg,batch['batch_id'])['corrections']==0
    work=core.workspace(cfg)
    assert work.execute("SELECT COUNT(*) FROM followups WHERE state='pending'").fetchone()[0]==1
    work.close()


def test_group_duplicate_assignment_and_independent_review(group_project):
    cfg=group_project;p=core.create_package(cfg,'A');gid=p['tasks'][0]['snapshot']['case']['case_id']
    with pytest.raises(PipelineError,match='已有有效任務'):
        core.create_package(cfg,'B',case_ids=[gid])
    p2=core.create_package(cfg,'B',case_ids=[gid],independent=True)
    assert p2['tasks'][0]['independent']


def test_group_snapshot_invalidates_when_third_member_changes(group_project):
    cfg=group_project;pkg,task=submitted(cfg)
    db=connect(Path(cfg['state_dir']))
    r=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='b'").fetchone()[0])
    r['answer']['contact_02']='63456789'
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='b'",(dumps(r),));db.commit();db.close()
    batch=core.preview_batch(cfg)
    assert not batch['rows'] and batch['conflicts']


def test_published_group_conflict_or_manual_nonmatch_never_hides_in_clean_pair(group_project):
    c=ctx(group_project)
    records=copy.deepcopy(c.records)
    records['a']['child_id']=records['b']['child_id']='joined'
    records['a']['dob']='2011-01-01'
    groups=build_groups(records,{k:v for k,v in c.cases.items() if k not in c.group_cases})
    assert groups and all(g['group_review']['route']=='operator' for g in groups.values())
    records=copy.deepcopy(c.records)
    d={'payload':{'action':'UNLINK','record_a':'a','record_b':'c',
                 'evidence_a':identity_evidence(records['a']),'evidence_b':identity_evidence(records['c'])}}
    groups=build_groups(records,{k:v for k,v in c.cases.items() if k not in c.group_cases},[d])
    assert groups and next(iter(groups.values()))['group_review']['route']=='operator'


def test_existing_pair_assignment_blocks_overlapping_group(group_project):
    cfg=group_project;c=ctx(cfg);cid=next(k for k,v in c.cases.items() if v['rule']=='exact_school_contact_child_demo')
    core.create_package(cfg,'old helper',case_ids=[cid],purpose='validation')
    with pytest.raises(PipelineError,match='沒有可派發'):
        core.create_package(cfg,'new helper')


def test_existing_pair_helper_cannot_independently_review_their_group(group_project):
    cfg=group_project;c=ctx(cfg);cid=next(k for k,v in c.cases.items() if v['rule']=='exact_school_contact_child_demo')
    core.create_package(cfg,'helper',case_ids=[cid],purpose='validation')
    gid=next(iter(c.group_cases))
    with pytest.raises(PipelineError,match='另一位審核者'):
        core.create_package(cfg,'helper',case_ids=[gid],independent=True)


def test_family_filter_includes_mixed_child_groups(group_project):
    package=core.create_package(group_project,'helper',kinds=['family'])
    assert len(package['tasks'])==1 and package['tasks'][0]['snapshot']['case']['group_review']


@pytest.mark.parametrize('partition', [[['a','b']], [['a'],['b']], [['a','a'],['b','c']]])
def test_invalid_group_partition_cannot_be_approved(group_project,partition):
    cfg=group_project;pkg,task=submitted(cfg,'確認不同');gid=task['snapshot']['case']['case_id']
    batch=core.preview_batch(cfg);rid=batch['conflicts'][0]['reviews'][0]['review_id']
    batch=core.preview_batch(cfg,adjudications={gid:{'review_id':rid,'reason':'synthetic partition','group_partition':partition}})
    assert not batch['rows'] and batch['conflicts']


def test_group_excel_scope_node_labels_and_immutable_evidence(group_project,tmp_path):
    path=tmp_path/'group.xlsx';p=core.create_package(group_project,'helper',path)
    book=load_workbook(path);sheet=book['審核卡']
    assert '全部 3 份' in sheet['A2'].value
    assert '2 對已通過' in sheet['A26'].value
    assert sheet['A27'].hyperlink and sheet['A27'].protection.locked
    reference='\n'.join(str(cell.value) for row in book['群組參考'] for cell in row if cell.value)
    assert all(x in reference for x in ('R001','R002','R003','沒有直接符合聯絡規則','毋須逐對重審'))
    package,answers=read_package(group_project,path)
    assert len(answers)==1
    sheet['A26']='changed group evidence';book.save(path);book.close()
    with pytest.raises(PipelineError):read_package(group_project,path)
