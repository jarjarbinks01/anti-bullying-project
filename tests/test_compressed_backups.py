import gzip
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from study2 import dyad_operator, review_core
from study2.common import PipelineError, file_hash
from study2.runner import verify_release
from study2.store import backup_path, connect, current
from test_pipeline_integration import execute, project


@pytest.mark.parametrize('explicit_archive', [True, False])
def test_compressed_release_supports_validation_review_baseline_and_full_restore(project, explicit_archive):
    cfg, _, _, _ = project
    execute(project)
    state = Path(cfg['state_dir'])
    work = review_core.workspace(cfg)
    with work:
        work.execute('INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)',
                     ('now', 'synthetic', 'unpublished-review-history', '{}'))
    work.close()
    db = connect(state)
    release = current(db)
    expected_count = db.execute('SELECT count(*) FROM submissions').fetchone()[0]
    bundle = dyad_operator.backup_tracking(db, cfg, 'synthetic_compression')
    plain = Path(release['path']) / 'backup.sqlite'
    archive = plain.with_name(plain.name + '.gz')
    with plain.open('rb') as source, gzip.open(archive, 'wb') as target:
        shutil.copyfileobj(source, target)
    plain.unlink()
    verify_release(db, release['release_id'])
    dyad_operator.require_published_reviews(db, release)
    db.close()
    destination = state.parent / 'restored-compressed-state'
    dyad_operator.restore_bundle(bundle, archive if explicit_archive else plain, destination)
    saved = connect(destination, readonly=True)
    try:
        assert saved.execute('SELECT count(*) FROM submissions').fetchone()[0] == expected_count
        dyad_operator.recovery_check(saved, {**cfg, 'state_dir': str(destination)})
    finally:
        saved.close()
    with sqlite3.connect((destination / 'review.sqlite').as_uri() + '?mode=ro', uri=True) as reviews:
        assert reviews.execute("SELECT count(*) FROM events WHERE target='unpublished-review-history'").fetchone()[0] == 1


def test_compressed_backup_checks_original_hash_and_removes_temporary_plaintext(tmp_path):
    plain = tmp_path / 'backup.sqlite'
    with sqlite3.connect(plain) as db:
        db.execute('CREATE TABLE synthetic(value TEXT)')
        db.execute("INSERT INTO synthetic VALUES('preserved')")
    expected = file_hash(plain)
    archive = plain.with_name(plain.name + '.gz')
    with plain.open('rb') as source, gzip.open(archive, 'wb') as target:
        shutil.copyfileobj(source, target)
    plain.unlink()
    (tmp_path / 'backup.sha256.json').write_text(json.dumps({'backup.sqlite': expected}))
    with backup_path(plain) as restored:
        temporary = restored
        assert file_hash(restored) == expected
        assert restored.stat().st_mode & 0o777 == 0o600
    assert not temporary.exists()
    with pytest.raises(PipelineError, match='checksum mismatch'):
        with backup_path(archive, '0' * 64):
            pytest.fail('Incorrect archive must never be exposed to a caller')


def test_corrupt_and_pruned_backups_fail_without_creating_a_database(tmp_path):
    archive = tmp_path / 'backup.sqlite.gz'
    archive.write_bytes(b'not a gzip backup')
    with pytest.raises(PipelineError, match='could not be read'):
        with backup_path(archive):
            pytest.fail('Corrupt archive must be rejected')
    archive.unlink()
    plain = tmp_path / 'backup.sqlite'
    with pytest.raises(PipelineError, match='unavailable'):
        with backup_path(plain):
            pytest.fail('Missing backup must be rejected')
    assert not plain.exists()
