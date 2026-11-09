"""Tiny code/configuration fixtures; no production inputs or publication."""
import json
import sqlite3
from pathlib import Path

import pytest

from study2 import checkpoints
from study2.common import PipelineError, atomic_json, file_hash
from study2.lean_recovery import ENVIRONMENT_PATHS


@pytest.fixture
def package(tmp_path, monkeypatch):
    for name in ENVIRONMENT_PATHS:
        monkeypatch.delenv(name, raising=False)
    code = tmp_path/'package'
    for name in ['study2/checkpoints.py', 'study2/presentation/view.py',
                 'study2/presentation/assets/view.js', 'study2/presentation/assets/local-preview.mjs',
                 'study2/assets/theme.css',
                 'study2/assets/review_template.xlsx', 'local_update_entry.py',
                 'study2/__pycache__/ignored.pyc', 'study2/assets/private.json']:
        path = code/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic fixture only')
    monkeypatch.setattr(checkpoints, '__file__', str(code/'study2/checkpoints.py'))
    monkeypatch.setattr('study2.store.current', lambda db: None)
    state = tmp_path/'state'; state.mkdir()
    trust = tmp_path/'synthetic-trust.json'; trust.write_text('{"synthetic": true}')
    cfg = {'state_dir': str(state), 'compatibility': {
        'profile_path': str(trust), 'profile_sha256': file_hash(trust)}}
    return cfg, code, trust


def test_inventory_includes_recursive_code_assets_and_pinned_profile(package):
    cfg, code, trust = package
    _, assets = checkpoints._asset_inventory(cfg, None)
    expected = {'code/'+str(p.relative_to(code)) for p in code.rglob('*')
                if p.is_file() and p.suffix in {'.py', '.js', '.mjs', '.css', '.xlsx'}}
    assert set(assets) == expected | {'dependencies/compatibility/trust.json'}
    assert assets['dependencies/compatibility/trust.json'] == trust
    trust.write_text('changed')
    with pytest.raises(PipelineError, match='compatibility profile checksum'):
        checkpoints._asset_inventory(cfg, None)


def capture(cfg, tmp_path):
    folder = tmp_path/'checkpoint'; folder.mkdir()
    _, assets = checkpoints._asset_inventory(cfg, None)
    manifest = {'format_version': 1, 'checkpoint_id': 'SYNTHETIC', 'files': {}}
    with sqlite3.connect(':memory:') as db:
        checkpoints._capture_assets(folder, manifest, cfg, db, assets,
                                    {name: file_hash(path) for name, path in assets.items()})
    atomic_json(folder/'manifest.json', manifest)
    atomic_json(folder/'manifest.sha256.json', {'manifest.json': file_hash(folder/'manifest.json')})
    return folder


@pytest.mark.parametrize('lean', [False, True])
def test_restore_relocates_profile_and_configured_runtime_paths(package, tmp_path, lean):
    cfg, code, trust = package
    cfg['runtime_environment'] = {
        'STUDY2_REVIEW_STATE_DIR': cfg['state_dir'],
        'STUDY2_FLAG_CONTROL': str(trust)}
    if lean:
        cfg['recovery_policy'] = {'mode': 'lean', 'required_assets': []}
    original = json.loads(json.dumps(cfg))
    folder = capture(cfg, tmp_path)
    destination = tmp_path/'restored'
    checkpoints.restore_checkpoint(folder, destination)
    restored = json.loads((destination/'config.restored.json').read_text())
    assert restored['compatibility'] == {
        'profile_path': str(destination/'dependencies/compatibility/trust.json'),
        'profile_sha256': original['compatibility']['profile_sha256']}
    assert restored['runtime_environment'] == {
        'STUDY2_REVIEW_STATE_DIR': str(destination),
        'STUDY2_FLAG_CONTROL': str(destination/'dependencies/compatibility/trust.json')}
    assert (destination/'code/study2/presentation/assets/view.js').is_file()
    assert (destination/'code/study2/presentation/assets/local-preview.mjs').is_file()
    assert cfg == original
    assert file_hash(trust) == original['compatibility']['profile_sha256']


def test_uncaptured_runtime_path_is_refused(package, tmp_path):
    cfg, _, _ = package
    cfg['runtime_environment'] = {'STUDY2_FLAG_CONTROL': str(tmp_path/'not-captured')}
    with pytest.raises(PipelineError, match='runtime dependency is not captured'):
        capture(cfg, tmp_path)


def test_profile_pin_is_independently_checked_on_restore(package, tmp_path):
    cfg, _, _ = package
    folder = capture(cfg, tmp_path)
    profile = folder/'dependencies/compatibility/trust.json'; profile.write_text('tampered')
    manifest = json.loads((folder/'manifest.json').read_text())
    manifest['files']['dependencies/compatibility/trust.json']['sha256'] = file_hash(profile)
    atomic_json(folder/'manifest.json', manifest)
    atomic_json(folder/'manifest.sha256.json', {'manifest.json': file_hash(folder/'manifest.json')})
    with pytest.raises(PipelineError, match='Restored compatibility profile checksum'):
        checkpoints.restore_checkpoint(folder, tmp_path/'restored')
    assert not (tmp_path/'restored').exists()
