"""Report publication gates and researcher controls over synthetic data."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from study2.descriptive_reports import write_reports, verify_reports
from study2.descriptive_spec import MODES, VERSION
from study2.store import connect, current
from test_descriptives import inputs
from test_pipeline_integration import execute, project


def test_report_failure_preserves_current_release_and_retry_is_safe(project):
    first=execute(project)
    cfg,_,_,_=project
    with patch('study2.descriptive_reports.workbook_bytes',side_effect=RuntimeError('Synthetic report export interruption')):
        with pytest.raises(RuntimeError,match='export interruption'):
            execute(project,force=True)
    db=connect(Path(cfg['state_dir']),readonly=True)
    assert current(db)['release_id']==first['release_id'];db.close()
    again=execute(project,force=True)
    assert {k:first[k] for k in ['A','B','C','D','AC','BD','E','F','EF']}=={
        k:again[k] for k in ['A','B','C','D','AC','BD','E','F','EF']}
    folder=Path(cfg['release_dir'])/again['release_id']
    verify_reports(folder,again['descriptive'])
    assert not list(folder.rglob('*.partial'))


def test_all_modes_controls_reset_and_population_tables(inputs,tmp_path):
    from streamlit.testing.v1 import AppTest
    f,p,m,_=inputs
    folder=tmp_path/'synthetic-release';folder.mkdir()
    m.to_parquet(folder/'descriptive_measurements.parquet',index=False)
    pd.DataFrame([{'child_id':c,'caregiver_status':'identity_unconfirmed'} for c in ['one','two']]).to_parquet(
        folder/'descriptive_caregivers.parquet',index=False)
    details=write_reports(folder,m,f,p,'synthetic-release')
    f.to_parquet(folder/'analysis.parquet',index=False);p.to_parquet(folder/'parent_longitudinal.parquet',index=False)
    summary={'release_id':'synthetic-release','descriptive':details}
    app=AppTest.from_string(
        'import pandas as pd\nfrom study2.descriptive_dashboard import render_descriptive\n'
        +'from pathlib import Path\np=Path('+repr(str(folder))+')\n'
        +'render_descriptive(p,'+repr(summary)+',pd.read_parquet(p/"analysis.parquet"),'
        +'pd.read_parquet(p/"parent_longitudinal.parquet"),{})',default_timeout=60).run()
    assert not app.exception
    for mode in MODES:
        app.selectbox(key="ds_mode").set_value(mode).run()
        assert not app.exception
        assert app.metric[0].value=="2 / 2"
    app.selectbox(key="ds_role").set_value("parent").run()
    assert not app.exception
    app.selectbox(key="ds_detail_family").set_value("demographics").run()
    assert app.selectbox(key="ds_detail_demographics_parent").options
    app.selectbox(key="ds_detail_demographics_parent").set_value("dem_children_count").run()
    assert not app.exception
    app.selectbox(key="ds_role").set_value("student").run()
    assert not app.exception
    assert app.selectbox(key="ds_detail_demographics_student").value!="dem_children_count"
    app.selectbox(key="ds_group").set_value("female").run()
    assert app.metric[0].value=="1 / 1"
    app.button(key="ds_home").click().run()
    assert not app.exception and app.metric[0].value=="2 / 2"
    app.multiselect(key="ds_sources").set_value(["qualtrics"]).run()
    app.selectbox(key="ds_mode").set_value("abcd").run()
    assert not app.exception and app.multiselect(key="ds_sources").value==['qualtrics']
    app.button(key="ds_reset").click().run()
    assert not app.exception and app.selectbox(key="ds_mainstream").value is True
    app.radio(key="ds_reading").set_value("跨期比較").run()
    assert not app.exception and app.info
    assert "This release does not support longitudinal exploration" in app.info[0].value


@pytest.mark.parametrize('version_one',[False,True])
def test_older_release_displays_existing_statistics_without_inventing_demographics(inputs,tmp_path,version_one):
    from streamlit.testing.v1 import AppTest
    f,p,_,_=inputs
    f.to_parquet(tmp_path/'analysis.parquet');p.to_parquet(tmp_path/'parent_longitudinal.parquet')
    summary={}
    if version_one:
        pd.DataFrame({'submission_id':[]}).to_parquet(tmp_path/'descriptive_measurements.parquet')
        summary={'descriptive':{'version':'study2_descriptive_v1'}}
    app=AppTest.from_string(
        'import pandas as pd\nfrom study2.descriptive_dashboard import render_descriptive\n'
        +'from pathlib import Path\np=Path('+repr(str(tmp_path))+')\n'
        +'render_descriptive(p,'+repr(summary)+',pd.read_parquet(p/"analysis.parquet"),pd.read_parquet(p/"parent_longitudinal.parquet"),{})',
        default_timeout=30).run()
    assert not app.exception and app.info
    assert app.metric[0].value=='2'
