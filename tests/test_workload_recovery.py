"""Synthetic actual checkpoint save/restore with a real policy-generation loader."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from study2 import checkpoints, flag_binding as binding, manual_flags as flags
from study2.common import digest
from study2.group_cleaning import exclusion_manifest
from study2.group_cleaning_operator import GEN_FORMAT, POINTER_FORMAT, read_active
from study2.lean_recovery import ENVIRONMENT_PATHS

CODE = Path(__file__).resolve().parents[1]
RUN = 'RUN_' + '1' * 32
AT = '2026-10-28T00:00:00+00:00'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_actual_checkpoint_restore_requires_and_allows_explicit_reference_rebinding(tmp_path, monkeypatch):
    for key in ENVIRONMENT_PATHS:
        monkeypatch.delenv(key, raising=False)
    state = tmp_path / 'state'
    control = state / 'analysis_eligibility' / 'control'
    control.mkdir(parents=True)
    release = tmp_path / 'scientific' / RUN
    release.mkdir(parents=True)
    rows = []
    for name in ('remove', 'keep', 'policy'):
        raw = {'fixture': name}
        rows.append(dict(submission_id=name, version_id='v-' + name, role='student',
                         raw_hash=digest(raw), raw=raw, child_id='c-' + name,
                         selected_wave='T0', status='eligible'))
    save(release / 'summary.json', {'release_id': RUN})
    with gzip.open(release / 'records.jsonl.gz', 'wt', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row) + '\n')
    save(release / 'checksums.json', {name: file_hash(release / name)
                                     for name in ('summary.json', 'records.jsonl.gz')})
    inventory = flags.Inventory.from_records(RUN, rows)
    spam = exclusion_manifest(rows, RUN, {'remove', 'keep'}, operator='fixture', at=AT)
    flags.initialize_registry(control / 'registry.sqlite3', operator='fixture')
    flags.seed_manifest(control / 'registry.sqlite3', spam, inventory, operator='fixture', reason='fixture')
    flags.decide_flags(control / 'registry.sqlite3', ['remove'], action='remove', operator='fixture', reason='fixture')

    group = tmp_path / 'group-control'
    generation = group / ('gen_' + 'a' * 32)
    generation.mkdir(parents=True)
    group_manifest = exclusion_manifest(rows, RUN, {'policy', 'remove'}, operator='fixture', at=AT)
    flags.initialize_registry(generation / 'policy-flags.sqlite', operator='fixture')
    flags.seed_manifest(generation / 'policy-flags.sqlite', group_manifest, inventory,
                        operator='fixture', reason='fixture')
    data = {'policy.json': {'policy_active': True, 'release_id': RUN},
            'policy-manifest.json': group_manifest, 'combined-manifest.json': group_manifest,
            'receipt.json': {}, 'proposal.json': None, 'eric-reference.json': {},
            'before-pointer.json': None}
    for name, value in data.items():
        save(generation / name, value)
    save(generation / 'MANIFEST.json', {'format': GEN_FORMAT,
         'files': {name: file_hash(generation / name) for name in [*data, 'policy-flags.sqlite']}})
    policy_pointer = {'format': POINTER_FORMAT, 'generation': generation.name,
                      'manifest_sha256': file_hash(generation / 'MANIFEST.json')}
    save(group / 'CURRENT.json', policy_pointer)
    assert read_active(group)['pointer'] == policy_pointer
    save(control / 'control.json', {'format': binding.CONTROL_FORMAT, 'baseline_release_id': RUN,
                                   'baseline_policy_head': policy_pointer['manifest_sha256']})
    monkeypatch.setenv(binding.CONTROL_ENV, str(control / 'control.json'))
    monkeypatch.setenv(binding.POLICY_ENV, str(group / 'CURRENT.json'))
    with sqlite3.connect(state / 'study2.sqlite') as db:
        db.executescript('CREATE TABLE releases(release_id TEXT PRIMARY KEY,run_id TEXT,path TEXT,stats_json TEXT);'
                         'CREATE TABLE publication(singleton INTEGER PRIMARY KEY,release_id TEXT);'
                         'CREATE TABLE decisions(decision_id TEXT,payload_json TEXT,supersedes TEXT);')
        db.execute('INSERT INTO releases VALUES(?,?,?,?)', (RUN, RUN, str(release), '{}'))
        db.execute('INSERT INTO publication VALUES(1,?)', (RUN,))

    cfg = {'state_dir': str(state), 'release_dir': str(release.parent),
           'mapping_dir': str(tmp_path / 'mappings'),
           'recovery_policy': {'mode': 'lean', 'required_assets': []}}
    Path(cfg['mapping_dir']).mkdir()
    manifest = binding.prepare_generation(cfg, release)
    monkeypatch.setenv(binding.MANIFEST_ENV, str(manifest))
    workload = state / 'review_dispositions' / 'fixture' / 'workload.json'
    save(workload, {'format': 'study2_current_review_workload_v1', 'release_id': RUN,
        'decision_revision': digest([]), 'exclusion_manifest_revision': json.loads(manifest.read_text())['revision'],
        'native_workload': {'remaining_pending_comparisons': 1}, 'correction_bundles': 0,
        'source_groups_resolved': 0, 'accepted_historical_policy_closures': 0,
        'original_answers': {'total': 0, 'same_child': 0, 'different_children': 0}})
    save(state / 'CURRENT_REVIEW_DISPOSITION.json', {'release_id': RUN, 'workload_path': str(workload),
                                                       'workload_sha256': file_hash(workload)})
    monkeypatch.setenv('STUDY2_CURRENT_REVIEW_WORKLOAD', str(workload))
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', str(state))
    assert binding.resolve_current(cfg) == manifest

    canonical, config, selection = (tmp_path / name for name in ('canonical.json', 'lean.json', 'selection.json'))
    save(canonical, {'fixture': True})
    cfg['recovery_policy']['required_assets'] = [
        {'kind': 'directory', 'path': str(group), 'restore_path': 'dependencies/group'},
        {'kind': 'file', 'path': str(CODE / 'local_update_entry.py'), 'restore_path': 'dependencies/runtime/entry.py'},
        {'kind': 'file', 'path': str(canonical), 'restore_path': 'dependencies/runtime/canonical.json'},
        {'kind': 'file', 'path': str(config), 'restore_path': 'dependencies/runtime/config.json'},
        {'kind': 'file', 'path': str(selection), 'restore_path': 'dependencies/runtime/selection.json'}]
    save(config, cfg)
    environment = {name: os.environ[name] for name in ENVIRONMENT_PATHS if name in os.environ}
    save(selection, {'entry': str(CODE / 'local_update_entry.py'), 'config': str(config),
        'canonical_config': str(canonical), 'canonical_config_sha256': file_hash(canonical),
        'state_dir': str(state), 'environment': environment})
    checkpoint = checkpoints.save_checkpoint(cfg, force=True)
    restored = tmp_path / 'actual-restored-state'
    checkpoints.restore_checkpoint(checkpoint['path'], restored)
    restored_environment = json.loads((restored / 'recovery_environment.json').read_text())
    paths = json.loads((restored / 'recovery_paths.json').read_text())
    restored_pointer_path = restored / 'CURRENT_REVIEW_DISPOSITION.json'
    restored_pointer = json.loads(restored_pointer_path.read_text())
    assert restored_pointer['workload_path'] != restored_environment['STUDY2_CURRENT_REVIEW_WORKLOAD']

    # The existing restore preserves the old absolute reference. It cannot be
    # used as a managed binding until explicitly mapped to the captured asset.
    for key, value in restored_environment.items():
        monkeypatch.setenv(key, value)
    restored_cfg = json.loads((restored / 'config.restored.json').read_text())
    import pytest
    from study2.common import PipelineError
    with pytest.raises(PipelineError):
        binding.resolve_current(restored_cfg)
    restored_pointer['workload_path'] = paths[restored_pointer['workload_path']]
    assert restored_pointer['workload_path'] == restored_environment['STUDY2_CURRENT_REVIEW_WORKLOAD']
    assert restored_pointer['workload_sha256'] == file_hash(restored_pointer['workload_path'])
    save(restored_pointer_path, restored_pointer)
    assert binding.resolve_current(restored_cfg) == Path(restored_environment[binding.MANIFEST_ENV])

    # The checkpoint captures the actual selected entry as an external asset;
    # restore currently needs a reconstructed entry/selection in code/.
    entry = restored / 'code' / 'local_update_entry.py'
    shutil.copyfile(paths[str(CODE / 'local_update_entry.py')], entry)
    restored_canonical = Path(paths[str(canonical)])
    restored_selection = restored / 'code' / 'selection.restored.json'
    save(restored_selection, {'entry': str(entry), 'config': str(restored / 'config.restored.json'),
        'canonical_config': str(restored_canonical), 'canonical_config_sha256': file_hash(restored_canonical),
        'state_dir': str(restored), 'environment': restored_environment})
    result = subprocess.run([sys.executable, '-B', '-I', str(entry), '--activation', str(restored_selection),
                             '--runtime-info'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info['state_dir'] == str(restored) and not info['update_executed'] and not info['checkpoint_executed']
    restored_manifest = Path(restored_environment[binding.MANIFEST_ENV])
    assert {x['submission_id'] for x in json.loads(restored_manifest.read_text())['entries']} == {'keep', 'policy', 'remove'}
