from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .common import PipelineError, dumps, file_hash, secure_directory, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions(
 submission_id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
 role TEXT NOT NULL, source_id TEXT NOT NULL, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS submission_versions(
 version_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions,
 raw_hash TEXT NOT NULL, raw_json TEXT NOT NULL, standard_json TEXT NOT NULL,
 location_json TEXT NOT NULL, imported_at TEXT NOT NULL,
 UNIQUE(submission_id,raw_hash));
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL, manifest_json TEXT NOT NULL, stats_json TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS run_records(
 run_id TEXT REFERENCES runs, submission_id TEXT REFERENCES submissions,
 version_id TEXT REFERENCES submission_versions, PRIMARY KEY(run_id,submission_id));
CREATE TABLE IF NOT EXISTS children(
 child_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, anchor_submission_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identity_members(
 run_id TEXT REFERENCES runs, submission_id TEXT REFERENCES submissions,
 child_id TEXT REFERENCES children, PRIMARY KEY(run_id,submission_id));
CREATE TABLE IF NOT EXISTS normalized_records(
 run_id TEXT REFERENCES runs, submission_id TEXT REFERENCES submissions,
 payload_json TEXT NOT NULL, PRIMARY KEY(run_id,submission_id));
CREATE TABLE IF NOT EXISTS decisions(
 decision_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, reviewer TEXT NOT NULL,
 reason TEXT NOT NULL, payload_json TEXT NOT NULL, supersedes TEXT);
CREATE TABLE IF NOT EXISTS releases(
 release_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs,
 created_at TEXT NOT NULL, path TEXT NOT NULL, stats_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS publication(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), release_id TEXT REFERENCES releases);
CREATE TABLE IF NOT EXISTS release_candidates(
 release_id TEXT REFERENCES releases, case_id TEXT, payload_json TEXT NOT NULL,
 PRIMARY KEY(release_id,case_id));
CREATE TABLE IF NOT EXISTS labels(
 case_id TEXT PRIMARY KEY, label TEXT NOT NULL, reviewer TEXT NOT NULL,
 reason TEXT NOT NULL, imported_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_events(
 run_id TEXT REFERENCES runs, decision_id TEXT REFERENCES decisions,
 status TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY(run_id,decision_id));
CREATE TABLE IF NOT EXISTS review_applications(
 batch_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_registry(
 source_id TEXT NOT NULL, slot INTEGER NOT NULL, raw_hash TEXT NOT NULL,
 first_file TEXT NOT NULL, first_row INTEGER NOT NULL, registered_at TEXT NOT NULL,
 PRIMARY KEY(source_id,slot));
"""


def connect(state: Path, readonly: bool = False) -> sqlite3.Connection:
    from .maintenance import recover_activation
    recover_activation(state)
    path = state / "study2.sqlite"
    if readonly:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        secure_directory(state)
        db = sqlite3.connect(path, timeout=30)
        path.chmod(0o600)
        from .storage import install_records, register_record_writer
        record_type = db.execute("SELECT type FROM sqlite_master WHERE name='normalized_records'").fetchone()
        if record_type and record_type[0] == 'table':
            db.executescript(SCHEMA)
        else:
            legacy = "CREATE TABLE IF NOT EXISTS normalized_records(\n run_id TEXT REFERENCES runs, submission_id TEXT REFERENCES submissions,\n payload_json TEXT NOT NULL, PRIMARY KEY(run_id,submission_id));"
            candidates="CREATE TABLE IF NOT EXISTS release_candidates(\n release_id TEXT REFERENCES releases, case_id TEXT, payload_json TEXT NOT NULL,\n PRIMARY KEY(release_id,case_id));"
            db.executescript(SCHEMA.replace(legacy,'').replace(candidates,''))
            install_records(db)
            from .run_storage import install_candidates
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='release_candidates' AND type='table'").fetchone():install_candidates(db)
        register_record_writer(db)
        from .run_storage import register
        register(db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def writer_lock(state: Path):
    from .maintenance import recover_activation
    secure_directory(state)
    from .owned_locks import exclusive
    with exclusive(state / 'writer.lock'):
        from .coordinated_update import require_available
        require_available(state)
        recover_activation(state)
        yield


def current(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT r.* FROM releases r JOIN publication p ON r.release_id=p.release_id WHERE p.singleton=1").fetchone()
    result=dict(row) if row else None
    if result:
        state=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
        mapping=state/'release_locations.json'
        if mapping.exists():
            locations=json.loads(mapping.read_text())
            result['path']=locations.get(result['release_id'],result['path'])
    return result


def ingest(db, run_id: str, records: list[dict]) -> None:
    # Source versions are immutable. Avoid reserializing their full source
    # payloads merely to execute INSERT OR IGNORE for an existing version.
    versions = list({r['version_id'] for r in records})
    existing = {}
    for start in range(0, len(versions), 500):
        batch = versions[start:start + 500]
        for row in db.execute('SELECT version_id,submission_id,raw_hash FROM submission_versions '
                              'WHERE version_id IN (' + ','.join('?' for _ in batch) + ')', batch):
            existing[row[0]] = (row[1], row[2])
    seen = set()
    for record in records:
        sid = record["submission_id"]
        if sid in seen:
            raise PipelineError("Identity-key collision within batch; cannot silently combine submissions")
        seen.add(sid)
        previous = db.execute("SELECT role,source_key FROM submissions WHERE submission_id=?", (sid,)).fetchone()
        if previous and (previous["role"] != record["role"] or previous["source_key"] != record["source_key"]):
            raise PipelineError("Immutable submission identity changed; source requires review")
        db.execute("INSERT OR IGNORE INTO submissions VALUES(?,?,?,?,?)", (sid, record["source_key"], record["role"], record["source_id"], utcnow()))
        saved = existing.get(record['version_id'])
        if saved is not None and saved != (sid, record['raw_hash']):
            raise PipelineError('Immutable source version binding changed')
        if saved is None:
            db.execute("INSERT INTO submission_versions VALUES(?,?,?,?,?,?,?)", (
                record["version_id"], sid, record["raw_hash"], dumps(record["raw"]), dumps(record["answer"]), dumps(record["location"]), utcnow()))
        db.execute("INSERT INTO run_records VALUES(?,?,?)", (run_id, sid, record["version_id"]))


@contextmanager
def backup_path(path: Path, expected_hash: str | None = None):
    """Read a plain or gzip backup through a private temporary SQLite file."""
    path = Path(path)
    logical_name = path.name.removesuffix('.gz')
    checksum_file = path.parent / 'backup.sha256.json'
    if expected_hash is None and checksum_file.exists():
        expected_hash = json.loads(checksum_file.read_text()).get(logical_name)
    if path.suffix != '.gz' and path.is_file():
        if expected_hash and file_hash(path) != expected_hash:
            raise PipelineError('Release backup checksum mismatch')
        yield path
        return
    archive = path if path.suffix == '.gz' else path.with_name(path.name + '.gz')
    if not archive.is_file():
        raise PipelineError('Full recovery backup is unavailable; it may have been removed by retention')
    with tempfile.TemporaryDirectory(prefix='study2-backup-') as folder:
        restored = Path(folder) / 'backup.sqlite'
        h = hashlib.sha256()
        try:
            with gzip.open(archive, 'rb') as origin, restored.open('xb') as target:
                restored.chmod(0o600)
                for chunk in iter(lambda: origin.read(1024 * 1024), b''):
                    h.update(chunk)
                    target.write(chunk)
        except (OSError, EOFError, zlib.error) as error:
            raise PipelineError('Compressed backup could not be read or verified') from error
        if expected_hash and h.hexdigest() != expected_hash:
            raise PipelineError('Release backup checksum mismatch')
        yield restored


_release_verification = ContextVar('study2_release_verification', default=None)


@contextmanager
def release_verification_cache():
    """Reuse successful backup checks within one operation, never file metadata.

    Nested calls share the operation; the outermost exit discards all results,
    including on exceptions. Every caller must still authenticate current bytes.
    """
    if _release_verification.get() is not None:
        yield
        return
    token = _release_verification.set({'logical': set(), 'compressed': set()})
    try:
        yield
    finally:
        _release_verification.reset(token)


def _check_backup_integrity(path):
    # This is a private main-file snapshot, not a live WAL database.
    snapshot = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PipelineError("Release backup failed integrity check")
    finally:
        snapshot.close()


def verify_backup_integrity(path: Path, expected_hash: str):
    """Authenticate current backup bytes and reuse only successful integrity checks.

    A gzip hash authenticates a previously checked encoding and logical checksum.
    Plain and newly encountered gzip encodings share integrity results only after
    their logical bytes have been authenticated. Owner-writable paths and mtimes
    never establish identity; no temporary snapshot survives this call.
    """
    path = Path(path)
    source = path
    if path.suffix != '.gz' and not path.is_file():
        source = path.with_name(path.name + '.gz')
    compressed = source.suffix == '.gz'
    if not source.is_file():
        raise PipelineError('Full recovery backup is unavailable; it may have been removed by retention')
    physical_hash = file_hash(source)
    cache = _release_verification.get()
    encoded_key = (physical_hash, expected_hash)
    if not compressed:
        if expected_hash and physical_hash != expected_hash:
            raise PipelineError('Release backup checksum mismatch')
        if cache is not None and physical_hash in cache['logical']:
            return
    elif cache is not None and encoded_key in cache['compressed']:
        return

    # Check the exact authenticated bytes, not an owner-writable original path
    # that SQLite could reopen after hashing. Copying is needed only on misses.
    with tempfile.TemporaryDirectory(prefix='study2-verify-backup-') as folder:
        frozen = Path(folder) / ('backup.sqlite.gz' if compressed else 'backup.sqlite')
        with source.open('rb') as origin, frozen.open('xb') as target:
            frozen.chmod(0o600)
            shutil.copyfileobj(origin, target)
        if file_hash(frozen) != physical_hash:
            raise PipelineError('Release backup changed during verification')
        with backup_path(frozen, expected_hash) as restored:
            logical_hash = file_hash(restored)
            if cache is None or logical_hash not in cache['logical']:
                _check_backup_integrity(restored)
        if cache is not None:
            cache['logical'].add(logical_hash)
            if compressed:
                cache['compressed'].add(encoded_key)


def backup(db, path: Path) -> None:
    target = sqlite3.connect(path)
    try:
        db.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PipelineError("Backup integrity check failed")
    finally:
        target.close()
    path.chmod(0o600)
