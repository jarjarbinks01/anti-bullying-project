"""Finite semester asset binding and protected synthetic export checks."""
from copy import deepcopy
import hashlib
import json

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.static_period_assets import (PERIOD_V1_FILES, SEMESTER_FILES, prepare_semester_assets,
    validate_semester_assets, validate_semester_catalog)


def test_native_synthetic_cohorts_bind_both_controls_and_respondents(tmp_path):
    from study2.parent_panel_views import read_panel
    from test_static_release_context import publication
    value, manifest, _ = publication(tmp_path/'inputs')
    measurements = pd.read_parquet(value['folder']/'descriptive_measurements.parquet')
    measurements['school_stage_status'] = 'valid'
    catalog, assets = prepare_semester_assets(value['frame'], value['parents'], measurements,
        value['summary'], records=value['records'], manifest=manifest, panel=read_panel(value['folder']))
    validate_semester_assets(catalog, assets, value['summary']['release_id'])
    assert catalog['active_on_revision'] == manifest['revision']
    assert len(assets) == len(catalog['refs']) == 22
    assert set(assets) == set(SEMESTER_FILES) and not set(assets) & set(PERIOD_V1_FILES)
    refs = {(r['eligibility'], r['mode'], r['role']): r for r in catalog['refs']}
    assert all(r['status'] == 'available' for r in refs.values())
    def size(eligibility, mode, role):
        ref = refs[eligibility, mode, role]
        cube = json.loads(assets[ref['asset']])
        assert cube['active_on_revision'] == manifest['revision']
        assert cube['eligibility_revision'] == (manifest['revision'] if eligibility == 'on' else None)
        return sum(row[cube['cell_fields'].index('n')] for row in cube['cells'])
    assert size('off','independent_all','parent') == 3
    assert size('on','independent_all','parent') == 2
    parent = json.loads(assets[refs['on','abcd','parent']['asset']])
    subjects = {m['variable_id']:m['subject'] for m in parent['metrics']}
    assert subjects['PHQ_total'] == 'respondent_adult'
    assert subjects['TBV_prevalence2'] == 'parent_reported_child'
    assert subjects['FQOL_total'] == 'family'
    assert all('toy-record-' not in text for text in assets.values())


def test_suppression_and_revision_mismatch_fail_closed(tmp_path):
    from study2.static_export import FORMAT, validate_snapshot, write_site
    release='synthetic-release'
    catalog,assets=prepare_semester_assets(None,None,None,{'release_id':release},minimum=5)
    assert catalog['status']=='unavailable' and all(ref['status']=='unavailable' for ref in catalog['refs'])
    assert all('cells' not in json.loads(text) for text in assets.values())
    validate_semester_assets(catalog,assets,release)
    snapshot=dict(format=FORMAT,release_id=release,generated_at='2026-01-01T00:00:00Z',
                  published_at='2026-01-01T00:00:00Z',views=[],minimum_cell_n=5,
                  period_semester_selection=catalog)
    with pytest.raises(PipelineError,match='required'):
        write_site(snapshot,tmp_path/'site')
    write_site(snapshot,tmp_path/'site',semester_assets=assets)
    old={p.name:p.read_bytes() for p in (tmp_path/'site').iterdir() if p.is_file()}
    bad=dict(assets);bad[SEMESTER_FILES[0]]+=' '
    with pytest.raises(PipelineError,match='checksum'):
        write_site(snapshot,tmp_path/'site',semester_assets=bad)
    assert old=={p.name:p.read_bytes() for p in (tmp_path/'site').iterdir() if p.is_file()}
    altered=deepcopy(snapshot);altered['minimum_cell_n']=0
    with pytest.raises(PipelineError,match='thresholds differ'):validate_snapshot(altered)
    altered=deepcopy(catalog);altered['refs'][0]['asset']='../private.json'
    with pytest.raises(PipelineError):validate_semester_catalog(altered,release)


def test_semester_assets_in_site_manifest_and_access_gate(tmp_path):
    from study2.static_access import PUBLIC_FILES
    from study2.static_export import DEPLOY_FILES, FORMAT, write_site
    from test_static_access import node
    snapshot=dict(format=FORMAT,release_id='synthetic-release',generated_at='2026-01-01T00:00:00Z',
                  published_at='2026-01-01T00:00:00Z',views=[])
    site=tmp_path/'site';write_site(snapshot,site)
    assert set(SEMESTER_FILES)<=set(PUBLIC_FILES) and set(SEMESTER_FILES)<=DEPLOY_FILES
    manifest=json.loads((site/'snapshot-manifest.json').read_text())
    for name in SEMESTER_FILES:
        assert hashlib.sha256((site/name).read_bytes()).hexdigest()==manifest['files'][name]
        assert '!'+name+'\n' in (site/'.vercelignore').read_text()
    node(site,"for(const path of ['/period-semester-off-abcd-student.json','/period-semester-on-acbd-parent.json'])assert.equal(gate(request(path),env).status,401);")
