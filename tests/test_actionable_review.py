import json
import sqlite3
from pathlib import Path
from itertools import combinations

import pytest
from openpyxl import load_workbook

from study2 import review_core as core
from study2.common import PipelineError,dumps
from study2.matching import candidate,link_records
from study2.review_dispatch import Router,summary,export_waiting_dataset
from study2.review_groups import build_groups
from study2.store import connect
from test_identity_and_time import rec
from test_store_and_review import database,published


@pytest.fixture
def gap_project(tmp_path):
    cfg={'state_dir':str(tmp_path),'duplicate_days':30,'minimum_followup_days':90}
    rows=[rec('s0',child_id='one'),rec('p0',role='parent',child_id='one'),
          rec('s1',120,phone_value='98765432',child_id='two'),rec('p1',120,role='parent',phone_value='98765432',child_id='two')]
    db=database(tmp_path);published(db,cfg,rows);db.execute('DELETE FROM release_candidates')
    for a,b in combinations(rows,2):
        c=candidate(a,b,'family' if a['role']!=b['role'] else 'identity','synthetic',
                    'confirmed' if a['child_id']==b['child_id'] else 'pending','synthetic')
        db.execute('INSERT INTO release_candidates VALUES(?,?,?)',('release',c['case_id'],dumps(c)))
    db.commit();db.close()
    return cfg


def context(cfg):
    db=connect(Path(cfg['state_dir']),readonly=True)
    try:return core.Context(db,cfg)
    finally:db.close()


def register(cfg,reference='原始收集名冊第 7 行'):
    gid=next(iter(context(cfg).group_cases))
    return core.register_review_evidence(cfg,gid,'既有收集紀錄',reference,'核對兩個子群是否記錄同一孩子的收集編號')


def test_no_extra_evidence_is_parked_without_changing_science(gap_project):
    ctx=context(gap_project);g=next(iter(ctx.group_cases.values()))
    assert g['group_review']['route']=='awaiting_evidence'
    result=summary(ctx,include_cases=True)
    assert result['remaining_general_reviews']==0
    assert result['awaiting_evidence_groups']==result['awaiting_evidence_work']==1
    assert result['unresolved_between_identity_comparisons']==4
    assert len({r['child_id'] for r in ctx.records.values()})==2
    assert set(g['group_review']['members'])=={'s0','p0','s1','p1'}
    raw=build_groups(ctx.records,ctx.cases,ctx.decisions)
    assert next(iter(raw.values()))['group_review']['route']=='review'  # Scientific scopes are independent of dispatch.
    with pytest.raises(PipelineError,match='沒有可派發'):
        core.create_package(gap_project,'helper')


@pytest.mark.parametrize('purpose',['review','validation','adjudication'])
def test_explicit_ids_cannot_bypass_missing_evidence(gap_project,purpose):
    gid=next(iter(context(gap_project).group_cases))
    with pytest.raises(PipelineError):
        core.create_package(gap_project,'Jarvis',case_ids=[gid],purpose=purpose)


def test_contact_typo_does_not_invent_an_available_original():
    a,b=rec('a',child_id='a'),rec('b',phone_value='61234576',child_id='b')
    c=candidate(a,b,'identity','fuzzy','pending','synthetic')
    assert Router({'a':a,'b':b}).classify(c)=={'route':'awaiting_evidence','reasons':['unverified_contact_discrepancy']}


def test_verified_source_restores_only_specific_group_and_is_visible(gap_project,tmp_path):
    lead=register(gap_project);ctx=context(gap_project)
    assert len(ctx.review_evidence)==1
    assert summary(ctx)['remaining_general_reviews']==1
    before=ctx.main_revision
    output=tmp_path/'cards.xlsx';p=core.create_package(gap_project,'helper',output)
    assert len(p['tasks'])==1
    assert p['tasks'][0]['snapshot']['case']['group_review']['verification_source']==lead
    assert context(gap_project).main_revision==before
    book=load_workbook(output)
    content='\n'.join(str(c.value) for s in book for row in s for c in row if c.value)
    assert lead['question'] in content and lead['reference'] in content
    book.close()
    task=p['tasks'][0]
    core.submit_reviews(gap_project,p['package_id'],[{'task_id':task['task_id'],'verdict':'確認相同',
        'evidence_source':'既有收集紀錄','reason':'已核對原始收集編號'}])
    preview=core.preview_batch(gap_project)
    assert not preview['conflicts'] and preview['rows']


def test_registration_revisions_and_stale_sources_are_preserved(gap_project):
    first=register(gap_project)
    assert register(gap_project)['unchanged']
    second=register(gap_project,'名冊第 8 行')
    assert second['lead_id']!=first['lead_id']
    db=connect(Path(gap_project['state_dir']))
    r=json.loads(db.execute("SELECT payload_json FROM normalized_records WHERE submission_id='s1'").fetchone()[0])
    r['answer']['contact_02']='85432109'
    db.execute("UPDATE normalized_records SET payload_json=? WHERE submission_id='s1'",(dumps(r),));db.commit();db.close()
    ctx=context(gap_project)
    assert not ctx.review_evidence and len(ctx.expired_review_evidence)==1
    assert summary(ctx)['awaiting_evidence_groups']==1
    work=core.workspace(gap_project)
    assert work.execute('SELECT COUNT(*) FROM review_evidence_leads').fetchone()[0]==2
    work.close()


@pytest.mark.parametrize('source,reference,question,reviewer',[
    ('問卷資料比較','位置','問題','Jarvis'),('原始紙本','','問題','Jarvis'),
    ('原始紙本','位置','','Jarvis'),('原始紙本','位置','問題','helper')])
def test_registration_requires_operator_and_specific_source(gap_project,source,reference,question,reviewer):
    gid=next(iter(context(gap_project).group_cases))
    with pytest.raises(PipelineError):core.register_review_evidence(gap_project,gid,source,reference,question,reviewer)


def test_new_source_invalidates_existing_preview(gap_project):
    register(gap_project);p=core.create_package(gap_project,'helper');t=p['tasks'][0]
    core.submit_reviews(gap_project,p['package_id'],[{'task_id':t['task_id'],'verdict':'資料不足',
        'evidence_source':'既有收集紀錄','reason':'原始紀錄未清楚指出是哪一位孩子'}])
    preview=core.preview_batch(gap_project);register(gap_project,'另一份名冊第 20 行')
    with pytest.raises(PipelineError):core.approve_batch(gap_project,preview['batch_id'],reason='test')


def test_fixed_waiting_dataset_is_not_a_nonmatch_or_edit(gap_project,tmp_path):
    before=context(gap_project).main_revision
    output=tmp_path/'waiting';result=export_waiting_dataset(gap_project,output)
    assert result['child_groups']==1 and result['unique_submissions']==4
    db=sqlite3.connect(output/'awaiting_evidence.sqlite')
    assert db.execute('SELECT COUNT(*) FROM comparisons').fetchone()[0]==6
    assert db.execute('SELECT COUNT(*) FROM members').fetchone()[0]==4
    assert db.execute('SELECT DISTINCT route FROM cases').fetchall()==[('awaiting_evidence',)]
    db.close()
    assert context(gap_project).main_revision==before
    with pytest.raises(PipelineError):export_waiting_dataset(gap_project,output)


def test_new_direct_contact_still_automatically_connects_parked_subgroups():
    rows=[rec('a'),rec('b',120,phone_value='98765432'),rec('p',role='parent')]
    rows[2]['answer']['contact_02']='98765432'
    policy={'allow_contact_bridge_components':True,'allow_contact_subgroups':True}
    assert link_records(rows,[],policy)[0]==[['a','b','p']]
