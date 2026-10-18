import copy
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from study2.common import PipelineError, dumps, utcnow
from study2.outputs import descriptive_summary
from study2.parent_panel import ADULT, CHILD
from study2.parent_panel_views import (panel_cohort, pairs_for_cohort, read_panel,
                                     reconcile_panel, verify_panel)
from study2.parent_waves import POLICY
from study2.runner import publish_release
from study2.store import connect
from test_pipeline_integration import execute, project


def test_parent_only_release_has_independent_samples_without_changing_family_samples(project):
    cfg, _, rows, _ = project
    cfg.update(parent_wave_policy=POLICY, bd_requires_same_adult=True)
    rows[:] = [r for r in rows if r['role'] == 'parent']
    for row in rows:
        row['answer']['adult_demographics_05'] = 1980
    summary = execute(project)
    assert all(summary[k] == 0 for k in ['A', 'B', 'C', 'D', 'AC', 'BD', 'E', 'F', 'EF'])
    assert summary['independent_parent']['child_report_pairs'] == 1
    assert summary['independent_parent']['same_adult_pairs'] == 1
    folder = Path(cfg['release_dir']) / summary['release_id']
    data = read_panel(folder)
    assert reconcile_panel(data, summary['independent_parent'])['核對'].eq('一致').all()
    assert len(data['audit']) == 2
    for branch in [CHILD, ADULT]:
        current = panel_cohort(data['analysis'], branch, 'T1', True)
        assert len(current) == len(pairs_for_cohort(data['pairs'], current, branch, 'T1')) == 1
        stats = descriptive_summary(current)
        assert stats['sample_n'].eq(1).all()
        assert (stats['valid_n'] + stats['missing_n']).eq(1).all()
    workbook = pd.read_excel(folder/'independent_parent.xlsx', sheet_name=None)
    assert len(workbook['正式跨期樣本']) == 2
    assert len(workbook['全部家長處理追查']) == 2
    assert set(workbook) == {'數量及規則', '正式跨期樣本', '選定回應及描述資料', '全部家長處理追查', '成人候選與核實', '電話差一位試算'}
    broken = copy.deepcopy(data)
    broken['pairs'].loc[0, 't0'] = 'wrong-id'
    with pytest.raises(PipelineError, match='baseline'):
        verify_panel(broken, summary['independent_parent'])
    second = execute(project, force=True)
    again = read_panel(Path(cfg['release_dir']) / second['release_id'])
    for key in data:
        pd.testing.assert_frame_equal(data[key], again[key])


def test_new_independent_nonmatch_label_blocks_later_publication(project):
    cfg, _, rows, _ = project
    cfg.update(parent_wave_policy=POLICY, bd_requires_same_adult=True)
    rows[:] = [r for r in rows if r['role'] == 'parent']
    for row in rows:
        row['answer']['adult_demographics_05'] = 1980
    summary = execute(project, publish=False)
    folder = Path(cfg['release_dir']) / summary['release_id']
    with gzip.open(folder/'independent_parent_guard.jsonl.gz', 'rt') as handle:
        case = next(json.loads(line) for line in handle if json.loads(line)['kind'] == 'respondent')
    db = connect(Path(cfg['state_dir']))
    with db:
        db.execute('INSERT INTO labels VALUES(?,?,?,?,?,?)',
                   (case['case_id'], 'NONMATCH', 'Synthetic reviewer', 'Synthetic known false match', utcnow(), dumps(case)))
    with pytest.raises(PipelineError, match='NONMATCH'):
        publish_release(db, cfg, summary['release_id'])
    db.close()


def test_empty_parent_release_has_valid_schema_and_no_dashboard_filter_errors(project):
    cfg, _, rows, _ = project
    rows[:] = [r for r in rows if r['role'] == 'student']
    summary = execute(project)
    data = read_panel(Path(cfg['release_dir']) / summary['release_id'])
    verify_panel(data, summary['independent_parent'])
    assert panel_cohort(data['analysis'], CHILD, 'T0', True, True).empty
    from study2.descriptive_exploration_outputs import available
    assert available(Path(cfg['release_dir']) / summary['release_id'], summary)


def test_collapsed_adult_nonmatch_cannot_publish_a_same_person_phq_change(project):
    from study2.respondents import adult_evidence
    from test_identity_and_time import rec
    cfg, _, rows, _ = project
    cfg.update(parent_wave_policy=POLICY, bd_requires_same_adult=True,
               matching_policy={'allow_contact_bridge_components': True})
    template = copy.deepcopy(rows[2])
    rows.clear()
    for sid, day, number in [('base', 0, '61234567'), ('day90', 90, '61234567'),
                             ('day100', 100, '61234567'), ('day130', 130, '63456789')]:
        row = copy.deepcopy(template)
        row.update(submission_id=sid, source_key=sid, version_id='version_'+sid,
                   raw_hash='version_'+sid, observed_at=rec(sid, day)['observed_at'])
        row['answer'].update(adult_demographics_05=1980, contact_01=number)
        if sid in {'base', 'day100'}:
            row['answer']['contact_02'] = '63456789'
        for i in range(1, 5):
            row['answer'][f'parent_PHQ_{i:02d}'] = 3 if sid == 'day130' else 0
        rows.append(row)
    a, b = rows[1], rows[3]
    payload = dict(action='UNLINK_ADULT', target_key='adult:day90:day130',
                   record_a=a['submission_id'], record_b=b['submission_id'],
                   version_a=a['version_id'], version_b=b['version_id'],
                   evidence_a=adult_evidence(a), evidence_b=adult_evidence(b))
    db = connect(Path(cfg['state_dir']))
    with db:
        db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?)',
                   ('synthetic_nonmatch', utcnow(), 'Synthetic reviewer',
                    'Different adults', dumps(payload), None))
    db.close()
    summary = execute(project)
    assert summary['independent_parent']['child_report_pairs'] == 1
    assert summary['independent_parent']['same_adult_pairs'] == 0
    assert summary['independent_parent']['experiment_pairs'] == 0
    folder = Path(cfg['release_dir']) / summary['release_id']
    data = read_panel(folder)
    assert data['pairs'].query("panel_branch == 'same_adult'").empty
    assert data['audit'].set_index('submission_id').loc['day90', 'duplicate_of'] == 'day100'
    changes = pd.read_parquet(folder/'descriptive_pair_summary.parquet')
    assert changes.query("mode == 'independent_same_adult' and variable_id == 'PHQ_total'")['paired_valid_n'].sum() == 0
    assert data['analysis'].query("panel_branch == 'child_report' and panel_wave == 'T1'")['PHQ_total'].iloc[0] == 12
    workbook = pd.read_excel(folder/'independent_parent.xlsx', sheet_name='正式跨期樣本')
    assert not workbook['panel_branch'].eq(ADULT).any()


def test_dashboard_widget_roundtrip_and_empty_filter(project):
    from streamlit.testing.v1 import AppTest
    cfg, _, rows, _ = project
    for r in rows:
        if r['role'] == 'parent':
            r['answer']['adult_demographics_05'] = 1980
    summary = execute(project)
    folder = str(Path(cfg['release_dir']) / summary['release_id'])
    app = AppTest.from_string(
        'from study2.parent_panel_dashboard import render_parent_panel\n'
        + 'render_parent_panel(' + repr(folder) + ', ' + repr(summary) + ')', default_timeout=30).run()
    assert not app.exception
    assert [m.value for m in app.metric[:3]] == ['1', '1', '1']
    app.selectbox(key='ipp_cohort_'+CHILD).set_value('全部獨立基線及追蹤').run()
    app.selectbox(key='ipp_branch').set_value(ADULT).run()
    assert app.selectbox(key='ipp_cohort_'+ADULT).value=='跨期樣本'
    app.selectbox(key='ipp_wave').set_value('T1').run()
    assert not app.exception and app.metric[-1].value == '1'
    app.selectbox(key='ipp_gender').set_value('女').run()
    assert not app.exception and app.metric[-1].value == '0'
