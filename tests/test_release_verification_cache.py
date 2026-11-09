"""Synthetic checks for operation-local release backup verification reuse."""
import gzip
import json
import os
import shutil
import sqlite3

import pytest

from study2 import runner, store
from study2.common import PipelineError, file_hash


@pytest.fixture
def release(tmp_path, monkeypatch):
    folder = tmp_path / 'release'
    folder.mkdir()
    backup = folder / 'backup.sqlite'
    with sqlite3.connect(backup) as snapshot:
        snapshot.execute('CREATE TABLE sample(value TEXT)')
        snapshot.execute("INSERT INTO sample VALUES('original')")
    (folder / 'backup.sha256.json').write_text(json.dumps({'backup.sqlite': file_hash(backup)}))
    (folder / 'artifact.txt').write_text('original artifact')
    (folder / 'checksums.json').write_text(json.dumps({'artifact.txt': file_hash(folder / 'artifact.txt')}))
    db = sqlite3.connect(tmp_path / 'study2.sqlite')
    db.row_factory = sqlite3.Row
    db.executescript('CREATE TABLE runs(run_id TEXT, status TEXT); '
                     'CREATE TABLE releases(release_id TEXT, run_id TEXT, path TEXT, stats_json TEXT);')
    db.execute("INSERT INTO runs VALUES('run', 'validated')")
    db.execute("INSERT INTO releases VALUES('release', 'run', ?, '{}')", (str(folder),))
    db.commit()
    calls = []
    original = store._check_backup_integrity
    def check(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(store, '_check_backup_integrity', check)
    yield db, folder, calls
    db.close()


def verify(release):
    return runner.verify_release(release[0], 'release')


def compress(folder):
    plain = folder / 'backup.sqlite'
    archive = folder / 'backup.sqlite.gz'
    archive.write_bytes(gzip.compress(plain.read_bytes(), mtime=0))
    plain.unlink()
    return archive


def test_deduplicates_only_inside_operation_and_nested_context(release):
    with store.release_verification_cache():
        verify(release)
        with store.release_verification_cache():
            verify(release)
        verify(release)
    assert len(release[2]) == 1
    verify(release)
    with store.release_verification_cache():
        verify(release)
    assert len(release[2]) == 3
    assert all(not path.exists() for path in release[2])


def test_exception_discards_operation(release):
    with pytest.raises(RuntimeError):
        with store.release_verification_cache():
            verify(release)
            raise RuntimeError('interrupted')
    with store.release_verification_cache():
        verify(release)
    assert len(release[2]) == 2


@pytest.mark.parametrize('compressed', [False, True])
def test_same_path_size_and_mtime_tampering_rejected(release, compressed):
    folder = release[1]
    path = compress(folder) if compressed else folder / 'backup.sqlite'
    with store.release_verification_cache():
        verify(release)
        stat = path.stat()
        payload = bytearray(path.read_bytes())
        payload[0] ^= 1
        path.write_bytes(payload)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with pytest.raises(PipelineError):
            verify(release)
    assert len(release[2]) == 1


def test_gzip_hit_skips_decompression_and_plain_conversion_shares_integrity(release, monkeypatch):
    with store.release_verification_cache():
        verify(release)
        archive = compress(release[1])
        verify(release)
        assert len(release[2]) == 1
        def forbidden(*args, **kwargs):
            pytest.fail('Authenticated gzip should not be decompressed again')
        monkeypatch.setattr(store.gzip, 'open', forbidden)
        verify(release)
        # Replacing the inode with identical bytes is safe, not an mtime shortcut.
        payload = archive.read_bytes()
        archive.unlink()
        archive.write_bytes(payload)
        verify(release)


def test_changed_backup_manifest_and_relocation_rechecked(release):
    db, folder, calls = release
    relocated = folder.parent / 'relocated'
    shutil.copytree(folder, relocated)
    with store.release_verification_cache():
        verify(release)
        (folder.parent / 'release_locations.json').write_text(json.dumps({'release': str(relocated)}))
        assert verify(release)['path'] == str(relocated)
        assert len(calls) == 1
        (relocated / 'backup.sha256.json').write_text(json.dumps({'backup.sqlite': '0' * 64}))
        with pytest.raises(PipelineError, match='checksum mismatch'):
            verify(release)


@pytest.mark.parametrize('change', ['status', 'artifact', 'checksums', 'path', 'reports'])
def test_mutable_release_checks_are_not_cached(release, monkeypatch, change):
    db, folder, calls = release
    with store.release_verification_cache():
        verify(release)
        if change == 'status':
            db.execute("UPDATE runs SET status='failed'")
        elif change == 'artifact':
            (folder / 'artifact.txt').write_text('tampered artifact')
        elif change == 'checksums':
            (folder / 'checksums.json').write_text(json.dumps({'artifact.txt': '0' * 64}))
        elif change == 'path':
            db.execute("UPDATE releases SET path=?", (str(folder / 'missing'),))
        else:
            from study2 import descriptive_reports
            db.execute("UPDATE releases SET stats_json=?", (json.dumps({'descriptive': {'changed': True}}),))
            def reject(*args):
                raise PipelineError('changed report semantics')
            monkeypatch.setattr(descriptive_reports, 'verify_reports', reject)
        with pytest.raises((PipelineError, FileNotFoundError)):
            verify(release)
        assert len(calls) == 1


def test_retention_and_reappearing_backup_rechecked(release):
    folder = release[1]
    plain = folder / 'backup.sqlite'
    original = plain.read_bytes()
    with store.release_verification_cache():
        verify(release)
        plain.unlink()
        with pytest.raises(PipelineError, match='retention record'):
            verify(release)
        (folder / 'backup.retention.json').write_text('{}')
        verify(release)
        plain.write_bytes(b'corrupt')
        with pytest.raises(PipelineError, match='checksum mismatch'):
            verify(release)
        plain.write_bytes(original)
        verify(release)
    assert len(release[2]) == 1


def test_integrity_failures_are_not_cached(release, monkeypatch):
    calls = []
    def fail(path):
        calls.append(path)
        raise PipelineError('injected failed integrity')
    monkeypatch.setattr(store, '_check_backup_integrity', fail)
    with store.release_verification_cache():
        for _ in range(2):
            with pytest.raises(PipelineError, match='failed integrity'):
                verify(release)
    assert len(calls) == 2


def test_different_gzip_encoding_authenticates_then_reuses_logical_integrity(release, monkeypatch):
    folder = release[1]
    original = (folder / 'backup.sqlite').read_bytes()
    archive = compress(folder)
    opened = []
    real_open = store.gzip.open
    def tracked(*args, **kwargs):
        opened.append(args[0])
        return real_open(*args, **kwargs)
    monkeypatch.setattr(store.gzip, 'open', tracked)
    with store.release_verification_cache():
        verify(release)
        archive.write_bytes(gzip.compress(original, mtime=123))
        verify(release)
        verify(release)
        archive.unlink()
        (folder / 'backup.sqlite').write_bytes(original)
        verify(release)
    assert len(opened) == 2
    assert len(release[2]) == 1


def test_new_valid_content_requires_new_integrity_and_row_path_rechecked(release):
    db, folder, calls = release
    relocated = folder.parent / 'new-release-path'
    shutil.copytree(folder, relocated)
    backup = relocated / 'backup.sqlite'
    with sqlite3.connect(backup) as snapshot:
        snapshot.execute("UPDATE sample SET value='modified'")
    (relocated / 'backup.sha256.json').write_text(json.dumps({'backup.sqlite': file_hash(backup)}))
    with store.release_verification_cache():
        verify(release)
        db.execute('UPDATE releases SET path=?', (str(relocated),))
        assert verify(release)['path'] == str(relocated)
        verify(release)
    assert len(calls) == 2


@pytest.mark.parametrize('compressed', [False, True])
def test_authenticated_invalid_sqlite_never_gets_cached(release, compressed):
    folder = release[1]
    (folder / 'backup.sqlite').write_bytes(b'not a sqlite database')
    (folder / 'backup.sha256.json').write_text(json.dumps({'backup.sqlite': file_hash(folder / 'backup.sqlite')}))
    if compressed:
        compress(folder)
    with store.release_verification_cache():
        for _ in range(2):
            with pytest.raises(sqlite3.DatabaseError):
                verify(release)
    assert len(release[2]) == 2


def test_source_replaced_while_copying_is_rejected(release, monkeypatch):
    original = store.shutil.copyfileobj
    def altered_copy(source, target):
        original(source, target)
        target.write(b'changed during copy')
    monkeypatch.setattr(store.shutil, 'copyfileobj', altered_copy)
    with store.release_verification_cache():
        with pytest.raises(PipelineError, match='changed during verification'):
            verify(release)
    assert not release[2]


def test_independent_context_does_not_inherit_successes(release):
    from contextvars import Context
    with store.release_verification_cache():
        verify(release)
        def independent_operation():
            with store.release_verification_cache():
                verify(release)
                verify(release)
        Context().run(independent_operation)
        verify(release)
    assert len(release[2]) == 2
