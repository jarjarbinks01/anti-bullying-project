"""Only tiny package-native fixtures, never production state or databases."""
import hashlib
import json
import subprocess
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
from test_coordinated_update import environment, prepared, save, proof
from study2.analysis_eligibility import sha
from study2 import coordinated_update as update
from study2.owned_locks import exclusive, assert_owned
from study2 import journal_retirement as helper


def complete(environment, side, *, already_prepared=False):
    env = environment if already_prepared else prepared(environment)
    if side == 'target':
        update._publish_fenced(env['cfg'], env['planpin'], env['accepted'], operator='SYNTHETIC PREPARER')
    else:
        def stop(phase):
            if phase == 'after_gate':
                raise RuntimeError('synthetic interruption')
        with pytest.raises(RuntimeError, match='synthetic interruption'):
            update._publish_fenced(env['cfg'], env['planpin'], env['accepted'], operator='SYNTHETIC PREPARER', fault=stop)
        update._recover_fenced(env['cfg'])
    (env['state']/'consumer-maintenance.lock').touch(mode=0o600)
    env['raw'] = (env['state']/update.JOURNAL).read_bytes()
    env['sha'] = hashlib.sha256(env['raw']).hexdigest()
    env['side'] = side
    env['archive'] = env['trusted']/helper.HISTORY
    env['archive'].mkdir(mode=0o700)
    assert update.recover(env['cfg'])['verified_side'] == side
    return env


def retire(env, **kw):
    return helper.retire_completed(env['cfg'], expected_sha256=env['sha'], expected_side=env['side'], archive_directory=env['archive'], **kw)


def snapshot(env):
    base = env['state'].parent
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in base.rglob('*') if p.is_file() and p.name != update.JOURNAL
            and not p.name.endswith('.lock') and helper.HISTORY not in p.parts}


@pytest.mark.parametrize('side', ['old', 'target'])
def test_native_complete_exact_archive_and_no_active_changes(environment, side):
    env = complete(environment, side)
    before = snapshot(env)
    def check(phase):
        for path in (env['state']/'consumer-maintenance.lock', env['state']/'writer.lock', env['root']/'writer.lock'):
            assert_owned(path)
    result = retire(env, fault=check)
    assert result['status'] == 'retired' and result['verified_side'] == side
    assert Path(result['archive_path']).read_bytes() == env['raw']
    assert not (env['state']/update.JOURNAL).exists()
    assert snapshot(env) == before
    again = retire(env)
    assert again['status'] == 'already_absent' and not again['current_tuple_verified']
    assert not again['publication_authorized'] and snapshot(env) == before


def test_preexisting_exact_archive(environment):
    env = complete(environment, 'old')
    history = env['archive']
    archive = history/(env['sha']+'.json'); archive.write_bytes(env['raw'])
    inode = archive.stat().st_ino
    assert retire(env)['status'] == 'retired'
    assert archive.stat().st_ino == inode


@pytest.mark.parametrize('phase', ['archive:after_temp_sync', 'archive:after_install',
    'archive:after_directory_sync', 'retirement:before_unlink', 'retirement:after_unlink',
    'retirement:after_directory_sync'])
def test_real_process_death_and_retry(environment, phase):
    env = complete(environment, 'old'); before = snapshot(env)
    code = """import sys, json, os
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from study2.journal_retirement import retire_completed
retire_completed(json.loads(sys.argv[3]), expected_sha256=sys.argv[4], expected_side=sys.argv[5], archive_directory=sys.argv[7],
                 fault=lambda phase: os._exit(71) if phase == sys.argv[6] else None)
os._exit(72)
"""
    process = subprocess.run([sys.executable, '-I', '-B', '-c', code,
        str(ROOT), str(ROOT), json.dumps(env['cfg']), env['sha'], env['side'], phase, str(env['archive'])],
        timeout=30, capture_output=True, text=True)
    assert process.returncode == 71, process.stderr
    assert snapshot(env) == before
    result = retire(env)
    assert result['status'] in ('retired', 'already_absent')
    assert (env['archive']/(env['sha']+'.json')).read_bytes() == env['raw']
    assert snapshot(env) == before


@pytest.mark.parametrize('status', ['pending', 'draining', 'unknown'])
def test_noncomplete_refused(environment, status):
    env = complete(environment, 'old')
    value = json.loads(env['raw']); value['status'] = status
    source = env['state']/update.JOURNAL; save(source, value)
    env['sha'] = hashlib.sha256(source.read_bytes()).hexdigest()
    before = source.read_bytes()
    with pytest.raises(helper.RetirementError, match='completed_journal_required'):
        retire(env)
    assert source.read_bytes() == before and not list(env['archive'].iterdir())


@pytest.mark.parametrize('kind', ['journal', 'journal_inode', 'selection', 'archive'])
def test_mutations_refuse_without_retiring_source(environment, kind):
    env = complete(environment, 'old'); source = env['state']/update.JOURNAL
    def mutate(phase):
        if phase != 'retirement:before_unlink': return
        if kind == 'journal': source.write_bytes(env['raw'] + b' ')
        elif kind == 'journal_inode':
            source.unlink(); source.write_bytes(env['raw'])
        elif kind == 'selection': save(env['selection'], {'unexpected': True})
        else: (env['archive']/(env['sha']+'.json')).write_bytes(b'bad archive')
    with pytest.raises(Exception): retire(env, fault=mutate)
    assert source.exists()
    if kind not in ('journal',): assert source.read_bytes() == env['raw']


def test_new_journal_after_retirement_is_preserved(environment):
    env = complete(environment, 'old'); retire(env)
    source = env['state']/update.JOURNAL
    save(source, {'status': 'pending', 'new': 'transaction'})
    before = source.read_bytes()
    with pytest.raises(helper.RetirementError, match='journal_hash_mismatch'): retire(env)
    assert source.read_bytes() == before


@pytest.mark.parametrize('kind', ['archive_collision', 'journal_hardlink', 'journal_symlink',
    'archive_symlink', 'lock_hardlink', 'wrong_side', 'missing_lock', 'unsupported_platform'])
def test_refusal_boundaries(environment, kind, monkeypatch):
    env = complete(environment, 'old'); source = env['state']/update.JOURNAL
    if kind in ('archive_collision', 'archive_symlink'):
        history = env['archive']
        archive = history/(env['sha']+'.json')
        if kind == 'archive_collision': archive.write_bytes(b'incorrect')
        else: archive.symlink_to(source)
    elif kind == 'journal_hardlink': os.link(source, source.with_name('linked-journal'))
    elif kind == 'journal_symlink':
        other = source.with_name('original-journal'); source.rename(other); source.symlink_to(other)
    elif kind == 'lock_hardlink': os.link(env['state']/'writer.lock', env['state']/'linked-lock')
    elif kind == 'wrong_side': env['side'] = 'target'
    elif kind == 'missing_lock': (env['state']/'consumer-maintenance.lock').unlink()
    else: monkeypatch.setattr(helper.sys, 'platform', 'unsupported')
    with pytest.raises(Exception): retire(env)
    assert source.read_bytes() == env['raw']


def test_native_competing_lock_refuses(environment):
    env = complete(environment, 'old')
    import fcntl
    with (env['state']/'consumer-maintenance.lock').open('r') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(Exception, match='exclusive_writer_busy'): retire(env)
    assert (env['state']/update.JOURNAL).read_bytes() == env['raw']


@pytest.mark.parametrize('kind', ['source_mode', 'archive_mode', 'missing_archive', 'outside_archive',
    'state_symlink', 'replaced_lock'])
def test_metadata_path_and_replaced_lock_refusal(environment, kind):
    env = complete(environment, 'old'); source = env['state']/update.JOURNAL
    if kind == 'source_mode': source.chmod(0o666)
    elif kind == 'archive_mode': env['archive'].chmod(0o755)
    elif kind == 'missing_archive': env['archive'] = env['trusted']/'not-created'
    elif kind == 'outside_archive': env['archive'] = env['state']
    elif kind == 'state_symlink':
        link = env['state'].with_name('linked-state'); link.symlink_to(env['state'])
        env['cfg'] = {**env['cfg'], 'state_dir': str(link)}
    def replace(phase):
        if kind == 'replaced_lock' and phase == 'verification:after_native':
            lock = env['state']/'writer.lock'; lock.unlink(); lock.touch(mode=0o600)
    with pytest.raises(Exception): retire(env, fault=replace)
    assert source.read_bytes() == env['raw']


def test_exclusive_install_never_replaces(tmp_path):
    directory = tmp_path.resolve()
    source = directory/'pending'; source.write_bytes(b'new')
    destination = directory/'history'; destination.write_bytes(b'existing')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            helper.exclusive_rename(fd, source.name, destination.name)
        assert destination.read_bytes() == b'existing'
        assert source.read_bytes() == b'new'
        destination.unlink()
        helper.exclusive_rename(fd, source.name, destination.name)
        assert destination.read_bytes() == b'new'
        assert not source.exists()
    finally:
        os.close(fd)


def test_duplicate_journal_keys_are_rejected():
    raw = b'{"status":"complete","status":"pending"}'
    with pytest.raises(helper.RetirementError, match='duplicate_json_key'):
        helper.parse_completed(raw, hashlib.sha256(raw).hexdigest(), 'target')


def test_housekeeping_without_journal_needs_no_managed_config(tmp_path):
    assert helper.retire_if_complete({'state_dir': str(tmp_path)}) is None


@pytest.mark.parametrize('value,reason', [
    ({'status': 'pending'}, 'journal_requires_native_recovery'),
    ({'status': 'complete', 'recovered_to': 'unknown'}, 'unknown_completed_journal_outcome'),
    ({'status': 'complete'}, 'managed_review_root_required'),
])
def test_housekeeping_hint_refuses_without_mutation(tmp_path, value, reason):
    source = tmp_path/helper.JOURNAL
    raw = json.dumps(value).encode(); source.write_bytes(raw)
    with pytest.raises(helper.RetirementError, match=reason):
        helper.retire_if_complete({'state_dir': str(tmp_path)})
    assert source.read_bytes() == raw


def test_housekeeping_native_retirement(environment):
    env = complete(environment, 'old')
    assert helper.retire_if_complete(env['cfg'])['status'] == 'retired'
    assert helper.retire_if_complete(env['cfg']) is None
