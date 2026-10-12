"""Disposable synthetic review workbook used for rendering/native Excel QA."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from study2.common import dumps
from study2.matching import candidate
from study2.review_core import create_package
from test_identity_and_time import rec
from test_store_and_review import database,published

state=Path(sys.argv[1])
state.mkdir(parents=True,exist_ok=True)
cfg={'state_dir':str(state),'minimum_followup_days':90,'duplicate_days':30}
db=database(state)
rows=[rec('SYNTH_STUDENT_T0',child_id='SYNTH_CHILD',claimed_wave='T0',selected_wave='T0'),
      rec('SYNTH_STUDENT_T1',120,child_id='SYNTH_CHILD',claimed_wave='T1',selected_wave='T1'),
      rec('SYNTH_PARENT_T0',3,role='parent',child_id='SYNTH_CHILD',claimed_wave='T0',selected_wave='T0'),
      rec('SYNTH_PARENT_T1',400,role='parent',child_id='SYNTH_CHILD',claimed_wave='T1',selected_wave='T1')]
for r in rows:
    r['answer']['建立時間']=r['observed_at']
    r['date_basis']='system_creation'
    r['grade_raw']='小三'
for r in rows[2:]:
    r['answer'].update(adult_demographics_05='1980',adult_demographics_06='2',adult_demographics_06_1='',contact_02='61234567')
    r['answer']['adult_demographics_06.1']='祖母'
c=published(db,cfg,rows)
ids=[c['case_id']]
for a,b,kind in [(rows[1],rows[3],'family'),(rows[2],rows[3],'respondent')]:
    case=candidate(a,b,kind,'synthetic_'+kind,'pending','合成身份比較案例；沒有真實參加者資料')
    db.execute('INSERT INTO release_candidates VALUES(?,?,?)',('release',case['case_id'],dumps(case)))
    ids.append(case['case_id'])
for r in rows:
    r['location']={'file':'synthetic_survey.xlsx','row':2,'sheet':0}
    db.execute('UPDATE normalized_records SET payload_json=? WHERE submission_id=?',(dumps(r),r['submission_id']))
db.commit();db.close()
package=create_package(cfg,'合成測試審核者',state/'synthetic_cards.xlsx',case_ids=ids)
print(json.dumps({'path':str(state/'synthetic_cards.xlsx'),'package_id':package['package_id']},ensure_ascii=False))
