"""Tiny native fixtures only; all mutations are confined to pytest tmp_path."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

from study2 import group_cleaning_operator as group
from study2.common import file_hash
import test_coordinated_update as native
from test_group_intent_native_path import migrated_environment
from study2 import review_preparation as helper

@pytest.fixture
def prepared(migrated_environment, tmp_path):
    env = migrated_environment
    release = Path(env['cfg']['release_dir'])/native.NEW
    with gzip.open(release/'cases.jsonl.gz', 'wt') as stream:
        pass
    checks = json.loads((release/'checksums.json').read_text())
    checks['cases.jsonl.gz'] = file_hash(release/'cases.jsonl.gz')
    native.save(release/'checksums.json', checks)
    config = tmp_path/'helper-config.json'; native.save(config, env['cfg'])
    args = argparse.Namespace(source_evidence=None, source_evidence_sha256=None, config=str(config), release_folder=str(release),
        source_bundle=str(env['oldbundle']), control_root=str(env['root']), flag_registry=str(env['reg']),
        output=str(tmp_path/'helper-output'), config_sha256=file_hash(config),
        checksums_sha256=file_hash(release/'checksums.json'), source_sha256=file_hash(env['oldbundle']),
        registry_sha256=file_hash(env['reg']), policy_head=group.read_active(env['root'])['pointer']['manifest_sha256'],
        release_id=native.NEW, publication_id=native.OLD,
        main_revision=group._main_revision(env['cfg'])['main_revision'], operator='SYNTHETIC TEST ONLY')
    return env,args


def cli(args):
    command = [sys.executable, '-B', '-m', 'study2.review_preparation']
    for name,value in vars(args).items():
        if value is not None: command += ['--'+name.replace('_','-'), str(value)]
    return subprocess.run(command, text=True, capture_output=True)


def test_initial_cli_and_no_overwrite(prepared):
    env,args = prepared
    before = file_hash(env['reg'])
    run = cli(args)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result['mode'] == 'historical_migration'
    assert file_hash(env['reg']) == before
    assert group.read_active(env['root'])['pointer']['manifest_sha256'] == args.policy_head
    assert (Path(args.output)/'result.json').stat().st_mode & 0o777 == 0o600
    again = cli(args)
    assert again.returncode != 0
    assert 'requires_new_external_directory' in again.stderr


@pytest.mark.parametrize('field', ['release_id','policy_head','source_sha256','config_sha256','checksums_sha256','registry_sha256','publication_id','main_revision'])
def test_wrong_identity_creates_nothing(prepared, field):
    env,args = prepared
    setattr(args, field, 'WRONG')
    with pytest.raises(Exception): helper.prepare(args)
    assert not Path(args.output).exists()


def test_wrong_folder_cli(prepared, tmp_path):
    env,args = prepared
    args.release_folder = str(Path(args.release_folder).parent/native.OLD)
    args.checksums_sha256 = file_hash(Path(args.release_folder)/'checksums.json')
    run = cli(args)
    assert run.returncode != 0 and 'folder_mismatch' in run.stderr
    assert not Path(args.output).exists()


def test_symlink_output(prepared, tmp_path):
    env,args = prepared
    link = tmp_path/'alias'; link.symlink_to(tmp_path, target_is_directory=True)
    args.output = str(link/'new-output')
    with pytest.raises(Exception, match='symlink'): helper.prepare(args)
    assert not (tmp_path/'new-output').exists()


def test_generic_cli_uses_current_intents(prepared, tmp_path):
    env,args = prepared
    # Establish a tiny accepted migrated generation using the native fixture's
    # existing migration bundle. No production paths or publication are touched.
    b,data,options = group.load_bundle(env['bp'])
    receipt = dict(release_id=native.NEW, main_revision=options['main_revision'], rules_hash=options['rules_hash'],
                   operator='SYNTHETIC', reason='TEST ONLY', at=native.AT)
    group._stage(env['root'], group.read_active(env['root']), env['proposal'], data, receipt,
                 guard_base={**options, 'release_id': native.OLD})
    args.policy_head = group.read_active(env['root'])['pointer']['manifest_sha256']
    args.source_bundle = None; args.source_sha256 = None
    args.source_evidence = b['files']['source_evidence']['path']
    args.source_evidence_sha256 = b['files']['source_evidence']['sha256']
    run = cli(args)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result['mode'] == 'current_intent_carry'
    proposal = json.loads(Path(result['preparation']['proposal']).read_text())
    assert proposal['decision_intents'] == env['proposal']['decision_intents']
    bundle = json.loads(Path(result['preparation']['bundle']).read_text())
    assert 'intent_origin' not in bundle['files']


def test_historical_requires_source_bundle(prepared):
    env,args = prepared
    meta = json.loads(Path(args.source_bundle).read_text())
    args.source_bundle = None; args.source_sha256 = None
    args.source_evidence = meta['files']['source_evidence']['path']
    args.source_evidence_sha256 = meta['files']['source_evidence']['sha256']
    with pytest.raises(Exception, match='historical_source_bundle_required'):
        helper.prepare(args)
    assert not Path(args.output).exists()
