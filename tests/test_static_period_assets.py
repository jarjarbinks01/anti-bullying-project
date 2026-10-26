"""Finite lazy artifacts and unchanged exclusion/auth boundaries, synthetic only."""
from copy import deepcopy
import hashlib
import json

import pytest

from study2.common import PipelineError
from study2.static_period_assets import PERIOD_FILES, prepare_assets, validate_assets, validate_catalog


def test_native_synthetic_cohorts_bind_separate_off_on_cubes(tmp_path):
    import pandas as pd
    from study2.parent_panel_views import read_panel
    from test_static_release_context import publication

    value, manifest, _ = publication(tmp_path/'inputs')
    measurements = pd.read_parquet(value['folder']/'descriptive_measurements.parquet')
    measurements['school_stage_status'] = 'valid'
    catalog, assets = prepare_assets(value['frame'], value['parents'], measurements,
        value['summary'], records=value['records'], manifest=manifest,
        panel=read_panel(value['folder']))
    validate_assets(catalog, assets, value['summary']['release_id'])
    refs = {(r['eligibility'], r['mode'], r['role']): r for r in catalog['refs']}
    for (eligibility, _, _), ref in refs.items():
        assert ref['status'] == 'available'
        assert ref['eligibility_revision'] == (manifest['revision'] if eligibility == 'on' else None)
    def size(eligibility):
        ref = refs[eligibility, 'independent_all', 'parent']
        cube = json.loads(assets[ref['asset']])
        return sum(row[cube['cell_fields'].index('n')] for row in cube['cells'])
    assert size('off') == 3 and size('on') == 2
    assert refs['off', 'independent_all', 'parent']['sha256'] != refs['on', 'independent_all', 'parent']['sha256']


def test_positive_suppression_serializes_no_fine_cells():
    catalog, assets = prepare_assets(None, None, None, {'release_id':'synthetic-period'}, minimum=5)
    assert catalog['status']=='unavailable' and catalog['code']=='day_aggregates_require_unsuppressed_profile'
    assert len(assets)==len(catalog['refs'])==22
    validate_catalog(catalog, 'synthetic-period')
    validate_assets(catalog, assets, 'synthetic-period')
    assert all('cells' not in json.loads(value) for value in assets.values())
    assert all(r['status']=='unavailable' for r in catalog['refs'])


def test_finite_catalog_rejects_path_scope_and_hash_forgery():
    catalog, _ = prepare_assets(None,None,None,{'release_id':'synthetic-period'},minimum=1)
    for key,value in [('asset','../private.json'),('sha256','short'),('role','other'),('release_id','another')]:
        altered=deepcopy(catalog);altered['refs'][0][key]=value
        with pytest.raises(PipelineError):validate_catalog(altered,'synthetic-period')
    altered=deepcopy(catalog);altered['refs'].append(altered['refs'][0])
    with pytest.raises(PipelineError):validate_catalog(altered,'synthetic-period')


def test_lazy_jsons_are_managed_built_and_gated_without_weakening_auth(tmp_path):
    from study2.static_access import PUBLIC_FILES
    from study2.static_export import DEPLOY_FILES, FORMAT, write_site
    from test_static_access import node
    snapshot=dict(format=FORMAT,release_id='synthetic-period',generated_at='2026-01-01T00:00:00Z',
                  published_at='2026-01-01T00:00:00Z',views=[])
    destination=tmp_path/'site'
    write_site(snapshot,destination)
    assert set(PERIOD_FILES)<=set(PUBLIC_FILES) and set(PERIOD_FILES)<=DEPLOY_FILES
    manifest=json.loads((destination/'snapshot-manifest.json').read_text())
    for name in PERIOD_FILES:
        assert hashlib.sha256((destination/name).read_bytes()).hexdigest()==manifest['files'][name]
        assert '!'+name+'\n' in (destination/'.vercelignore').read_text()
    node(destination,"for(const path of ['/period-off-abcd-student.json','/period-on-acbd-parent.json'])assert.equal(gate(request(path),env).status,401);")


def test_new_declared_catalog_requires_exact_files_and_preserves_previous_site(tmp_path):
    from study2.static_export import FORMAT, write_site
    snapshot=dict(format=FORMAT,release_id='synthetic-period',generated_at='2026-01-01T00:00:00Z',
                  published_at='2026-01-01T00:00:00Z',views=[])
    catalog,assets=prepare_assets(None,None,None,snapshot,minimum=1)
    snapshot['period_selection']=catalog
    snapshot['minimum_cell_n']=1
    destination=tmp_path/'site';write_site(snapshot,destination,period_assets=assets)
    old={p.name:p.read_bytes() for p in destination.iterdir() if p.is_file()}
    changed=dict(assets);changed[PERIOD_FILES[0]]+=' '
    with pytest.raises(PipelineError,match='checksum'):write_site(snapshot,destination,period_assets=changed)
    assert old=={p.name:p.read_bytes() for p in destination.iterdir() if p.is_file()}
    with pytest.raises(PipelineError,match='required'):write_site(snapshot,destination)


@pytest.mark.parametrize('snapshot_minimum,catalog_minimum', [(5, 0), (0, 5)])
def test_period_catalog_cannot_weaken_or_mislabel_snapshot_suppression(snapshot_minimum,catalog_minimum):
    from study2.static_export import FORMAT, validate_snapshot
    snapshot=dict(format=FORMAT,release_id='synthetic-period',generated_at='2026-01-01T00:00:00Z',
                  published_at='2026-01-01T00:00:00Z',views=[],minimum_cell_n=snapshot_minimum)
    catalog,_=prepare_assets(None,None,None,snapshot,minimum=5)
    if catalog_minimum == 0:
        catalog.update(minimum_cell_n=0,status='available',code=None)
    snapshot['period_selection']=catalog
    with pytest.raises(PipelineError,match='thresholds differ'):
        validate_snapshot(snapshot)
