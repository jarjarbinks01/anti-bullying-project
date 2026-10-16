import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from study2.common import PipelineError, file_hash
from study2.runner import run, verify_release
from study2.store import connect, current
from test_identity_and_time import rec
from test_store_and_review import source


@pytest.fixture
def project(tmp_path):
    state=tmp_path/"state"
    state.mkdir()
    raw=tmp_path/"1.1_raw_file"
    raw.mkdir()
    path=raw/"synthetic.csv"
    path.write_text("synthetic data,not human identifiers\n")
    mapping=tmp_path/"mappings"
    mapping.mkdir()
    dictionary=pd.DataFrame([{"raw_name":"Example School", "normalized_key":"example school", "action":"map", "canonical_school_name":"Example School", "school_type":"primary"}])
    dictionary.to_excel(state/"school_dictionary.xlsx",index=False)
    cfg={"project_root":str(tmp_path),"state_dir":str(state),"release_dir":str(tmp_path/"releases"),
         "mapping_dir":str(mapping),"mapping_hashes":{},"duplicate_days":30,"minimum_followup_days":90,
         "sources":[{"source_id":"source","pattern":"synthetic.csv","kind":"system","role":"student"}]}
    manifest={"manifest_version":1,"sources":[{"source_id":"source","file":path.name,"sha256":file_hash(path)}]}
    rows=[]
    for sid,day,role in [("s0",0,"student"),("s1",120,"student"),("p0",0,"parent"),("p1",120,"parent")]:
        r=source(rec(sid,day,role))
        r.update(source_kind="system",claimed_wave="T0" if day==0 else "T1",batch_at=None)
        demo="student_demographics_" if role=="student" else "adult_demographics_"
        r["answer"].update({"school_from_"+role:"Example School", demo+"01":3,
                            demo+("06" if role=="student" else "03"):"2012-01-01",
                            demo+("03" if role=="student" else "04"):"0"})
        r["answer"].update({f"{role}_PHQ_{i:02d}":0 for i in range(1,5)})
        rows.append(r)
    fake=SimpleNamespace(STUDENT_COLUMNS=list(rows[0]["answer"]),PARENT_COLUMNS=list(rows[2]["answer"]))
    return cfg,manifest,rows,fake


def execute(project, **kwargs):
    cfg,manifest,rows,fake=project
    with patch("study2.runner.input_records",side_effect=lambda *_:copy.deepcopy(rows)),patch("study2.runner.modules",return_value=(fake,None,None)):
        return run(cfg,manifest,**kwargs)


def test_complete_run_repeat_force_reorder_and_rollback(project):
    first=execute(project)
    assert all(first[k]==1 for k in ["A","B","C","D","AC","BD","E","F","EF"])
    assert execute(project)["unchanged"] is True
    cfg,manifest,rows,fake=project
    rows.reverse()
    second=execute(project,force=True)
    db=connect(Path(cfg["state_dir"]))
    original=list(db.execute("SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY submission_id",(first["release_id"],)))
    repeated=list(db.execute("SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY submission_id",(second["release_id"],)))
    assert [tuple(r) for r in original]==[tuple(r) for r in repeated]
    assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]==4
    verify_release(db,second["release_id"])
    from study2.runner import publish_release
    publish_release(db,cfg,first["release_id"])
    assert current(db)["release_id"]==first["release_id"]
    db.close()
    data=pd.read_parquet(Path(cfg["release_dir"])/first["release_id"]/"analysis.parquet")
    assert len(data)==4 and data["longitudinal_dyad"].all()
    for name in ["A_T0-student_final","B_T0-parent_final","C_T1-student_final","D_T1-parent_final"]:
        assert len(pd.read_excel(Path(cfg["release_dir"])/first["release_id"]/"3.1.1_ABCD_reconstruction"/(name+".xlsx")))==1


def test_failed_input_preserves_previous_release(project):
    first=execute(project)
    cfg,manifest,_,_=project
    manifest["sources"]=[]
    with pytest.raises(PipelineError,match="each registered source"):
        execute(project)
    db=connect(Path(cfg["state_dir"]))
    assert current(db)["release_id"]==first["release_id"]
    assert json.loads((Path(cfg["state_dir"])/"last_failure.json").read_text())["error"]
    db.close()


def test_output_tampering_blocks_release(project):
    first=execute(project)
    cfg,_,_,_=project
    folder=Path(cfg["release_dir"])/first["release_id"]
    (folder/"summary.json").write_text("{}")
    db=connect(Path(cfg["state_dir"]))
    with pytest.raises(PipelineError,match="checksum"):
        verify_release(db,first["release_id"])
    db.close()


def test_confirmed_family_has_no_cross_role_date_limit(project):
    cfg,_,rows,_=project
    rows[2]["observed_at"]=rec("x",60)["observed_at"]
    rows[3]["observed_at"]=rec("x",180)["observed_at"]
    result=execute(project)
    assert result["E"]==result["F"]==result["EF"]==1


def test_caregiver_change_keeps_child_tracking_but_flags_ef(project):
    cfg, _, rows, _ = project
    rows[2]['answer']['adult_demographics_06'] = 0
    rows[3]['answer']['adult_demographics_06'] = 1
    result = execute(project)
    assert result['E'] == result['F'] == result['EF'] == 1
    folder = Path(cfg['release_dir']) / result['release_id']
    pairs = pd.read_excel(folder / '3.1.3_manual_pairing/EF_T0T1-student&parent-paired_final.xlsx', sheet_name='paired')
    assert pairs.iloc[0]['caregiver_status'] == 'identity_unconfirmed'
    assert bool(pairs.iloc[0]['reported_relationship_changed'])
    db = connect(Path(cfg['state_dir']))
    assert db.execute('SELECT COUNT(DISTINCT child_id) FROM identity_members WHERE run_id=?', (result['release_id'],)).fetchone()[0] == 1
    db.close()


def test_any_contact_policy_reaches_bd_ef_and_published_summary(project):
    cfg, _, rows, _ = project
    cfg['bd_requires_same_adult'] = True
    cfg['matching_policy'] = {'adult_contact_scope': 'any_exact'}
    for row, relation, personal in [(rows[2], 0, '62345678'), (rows[3], 1, '63456789')]:
        row['answer'].update(adult_demographics_05=1980, adult_demographics_06=relation,
                             contact_01='61234567;shared@example.org', contact_02=personal)
    result = execute(project)
    assert result['BD'] == result['E'] == result['F'] == result['EF'] == 1
    assert result['BD_any_exact_contact'] == 1
    folder = Path(cfg['release_dir']) / result['release_id']
    pairs = pd.read_excel(folder / '3.1.3_manual_pairing/EF_T0T1-student&parent-paired_final.xlsx', sheet_name='paired')
    assert pairs.iloc[0]['caregiver_status'] == 'same_adult_by_accepted_evidence'
    assert bool(pairs.iloc[0]['reported_relationship_changed'])


def test_card_review_approve_apply_republish_and_workspace_backup(project):
    from study2 import review_core as core
    from study2.runner import publish_release
    first=execute(project)
    cfg,_,_,_=project
    package=core.create_package(cfg,'Synthetic reviewer',limit=20,kinds=['family'],purpose='validation')
    task=package['tasks'][0]
    core.submit_reviews(cfg,package['package_id'],[{'task_id':task['task_id'],'verdict':'確認不同',
                        'evidence_source':'既有收集紀錄','reason':'已核實合成案例指向不同孩子'}])
    batch=core.preview_batch(cfg)
    assert len(batch['rows'])==1 and not batch['conflicts']
    core.approve_batch(cfg,batch['batch_id'],reason='只批准已核實的合成案例')
    core.apply_batch(cfg,batch['batch_id'])
    db=connect(Path(cfg['state_dir']))
    assert current(db)['release_id']==first['release_id']
    with pytest.raises(PipelineError,match='NONMATCH'):
        publish_release(db,cfg,first['release_id'])
    assert current(db)['release_id']==first['release_id']
    db.close()
    second=execute(project)
    assert second['release_id']!=first['release_id'] and second['validation_cases_labelled']==1
    db=connect(Path(cfg['state_dir']))
    assert current(db)['release_id']==second['release_id']
    case=json.loads(db.execute('SELECT payload_json FROM release_candidates WHERE release_id=? AND case_id=?',
                              (second['release_id'],task['snapshot']['case']['case_id'])).fetchone()[0])
    assert case['status']!='confirmed'
    db.close()
    paths=list((Path(cfg['state_dir'])/'review_backups').glob('*.sqlite'))
    assert len(paths)>=2
    import sqlite3
    snapshots=[sqlite3.connect(p) for p in paths]
    assert all(b.execute('PRAGMA integrity_check').fetchone()[0]=='ok' for b in snapshots)
    assert any(b.execute("SELECT COUNT(*) FROM batches WHERE state='applied'").fetchone()[0] for b in snapshots)
    for b in snapshots:b.close()
    # Reopening changed evidence never erases the pre-correction verification history.
    core.reopen_tasks(cfg,[task['task_id']],reason='新發布的群組已改變，安排重審')
    report=core.review_report(cfg)
    assert sum(r['reviewed'] for r in report['original_algorithm_by_rule'].values())==1
    assert report['published_results']['release_id']==second['release_id']
