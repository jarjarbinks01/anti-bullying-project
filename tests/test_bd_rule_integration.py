"""The BD rule changes membership without changing selected waves or EF."""
import copy
from pathlib import Path

import pandas as pd

from study2.bd_pairing import POLICY
from study2.common import digest
from test_identity_and_time import rec
from test_pipeline_integration import execute, project


def test_selected_bd_replaces_alternative_same_adult_without_reselecting_waves(project):
    cfg, _, rows, _ = project
    cfg['bd_requires_same_adult'] = True
    for row in rows[2:]:
        row['answer'].update(adult_demographics_05=1980, adult_demographics_06=1,
                             contact_02='62345678')
    father = copy.deepcopy(rows[3])
    father.update(submission_id='f1', version_id='father-version', source_key='father-source', raw={'father': True})
    father['raw_hash'] = digest(father['raw'])
    father['answer'].update(adult_demographics_05=1978, adult_demographics_06=0, contact_02='63456789')
    father['observed_at'] = rec('f', 125)['observed_at']
    rows.append(father)

    old = execute(project)
    old_root = Path(cfg['release_dir']) / old['release_id']
    old_selected = pd.read_parquet(old_root / 'analysis.parquet')
    old_bd = pd.read_parquet(old_root / 'parent_longitudinal.parquet')
    assert set(old_bd.submission_id) == {'p0', 'p1'}
    assert old['BD_alternative_followups'] == 1

    cfg['bd_pairing_policy'] = POLICY
    new = execute(project, force=True)
    new_root = Path(cfg['release_dir']) / new['release_id']
    new_selected = pd.read_parquet(new_root / 'analysis.parquet')
    new_bd = pd.read_parquet(new_root / 'parent_longitudinal.parquet')
    keys = ['child_id', 'role', 'wave', 'submission_id']
    pd.testing.assert_frame_equal(old_selected[keys].sort_values(keys).reset_index(drop=True),
                                  new_selected[keys].sort_values(keys).reset_index(drop=True))
    assert {k: old[k] for k in ('A', 'B', 'C', 'D', 'AC', 'E', 'F', 'EF')} == {
        k: new[k] for k in ('A', 'B', 'C', 'D', 'AC', 'E', 'F', 'EF')}
    assert new['bd_pairing_policy'] == POLICY and new['bd_requires_same_adult'] is False
    assert new['BD'] == 1 and new['BD_alternative_followups'] == 0
    assert set(new_bd.submission_id) == {'p0', 'f1'}
    assert set(new_bd.bd_adult_status) == {'unconfirmed'}
    assert not new_bd.adult_continuity_confirmed.any()
    changes = pd.read_parquet(new_root / 'descriptive_changes.parquet')
    assert changes.query("mode == 'acbd' and role == 'parent' and variable_id == 'PHQ_total'").empty
    workbook = pd.read_excel(new_root / '3.1.1_ABCD_reconstruction/BD_T0T1-parent.xlsx')
    assert workbook.iloc[0]['T1_submission_id'] == 'f1'
    assert 'adult_status' in workbook and 'respondent_id' not in workbook


def test_unknown_bd_policy_is_rejected_before_the_run(project):
    import pytest
    from study2.common import PipelineError
    project[0]['bd_pairing_policy'] = 'unsupported'
    with pytest.raises(PipelineError, match='Unknown BD pairing policy'):
        execute(project)
