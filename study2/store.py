from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .common import PipelineError, dumps, secure_directory, utcnow

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
    path = state / "study2.sqlite"
    if readonly:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        secure_directory(state)
        db = sqlite3.connect(path, timeout=30)
        path.chmod(0o600)
        db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def writer_lock(state: Path):
    import fcntl
    secure_directory(state)
    with (state / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineError("Another pipeline/review operation is running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def current(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT r.* FROM releases r JOIN publication p ON r.release_id=p.release_id WHERE p.singleton=1").fetchone()
    return dict(row) if row else None


def ingest(db, run_id: str, records: list[dict]) -> None:
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
        db.execute("INSERT OR IGNORE INTO submission_versions VALUES(?,?,?,?,?,?,?)", (
            record["version_id"], sid, record["raw_hash"], dumps(record["raw"]), dumps(record["answer"]), dumps(record["location"]), utcnow()))
        db.execute("INSERT INTO run_records VALUES(?,?,?)", (run_id, sid, record["version_id"]))


def backup(db, path: Path) -> None:
    target = sqlite3.connect(path)
    try:
        db.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PipelineError("Backup integrity check failed")
    finally:
        target.close()
    path.chmod(0o600)
