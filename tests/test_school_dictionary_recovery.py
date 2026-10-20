"""Synthetic coverage for school-dictionary failure recovery in commit_review_rows.

Scope is deliberately narrow: study2/review.py commit_review_rows only.

Everything is built from scratch inside pytest tmp_path - a throwaway SQLite
database, a throwaway school dictionary and synthetic records. No private
configuration, no real questionnaire, no real dictionary, no published release
and no real research data are read. Nothing outside tmp_path is written.

The behaviour under test is the boundary between the database transaction and
the external Excel dictionary file:

  review.py:272  with db:            -> decisions / labels / review_applications
  review.py:283  marker insert
  review.py:286  copy2(current, prev) -> school_dictionary.previous.xlsx
  review.py:288  tmp.replace(current) -> school_dictionary.xlsx
  review.py:290  except Exception:    -> restore only what this operation replaced
  review.py:300  finally             -> drop this operation's staging file

The file replacement happens inside the database transaction but is not part of
it, so a failure has to leave the live dictionary exactly as the last successful
application left it, and a failure after the replacement has to put the
pre-operation dictionary back.
"""
import json
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from study2 import review as review_module
from study2.common import dumps, file_hash, utcnow
from study2.review import commit_review_rows, validate_review_rows
from study2.store import connect, ingest


SCHOOL_COLUMNS = ["raw_name", "normalized_key", "action", "canonical_school_name",
                  "school_type", "school_sex", "school_district", "school_religion"]

DICTIONARY_ROWS = [
    {"raw_name": "Example School", "normalized_key": "example school", "action": "map",
     "canonical_school_name": "Example School", "school_type": "primary",
     "school_sex": "", "school_district": "", "school_religion": ""},
    {"raw_name": "Second School", "normalized_key": "second school", "action": "map",
     "canonical_school_name": "Second School", "school_type": "secondary",
     "school_sex": "", "school_district": "", "school_religion": ""},
]

SYNTHETIC_RECORD = {
    "submission_id": "synthetic-s1", "version_id": "synthetic-v1", "role": "student",
    "answer": {"contact_01": "61234567", "student_demographics_02": "01"},
    "status": "eligible", "dob": "2012-01-01", "gender": "0", "school": "Example School",
    "grade": 3, "observed_at": "2025-01-01T00:00:00+00:00", "time_confidence": "observed",
    "claimed_wave": "T0", "issues": [],
}

FIRST_CANONICAL = {"example school": "Example School (2026)", "second school": "Second School (2026)"}
STALE_CANONICAL = {"example school": "Example School", "second school": "Second School"}


def _write_dictionary(path, rows):
    pd.DataFrame(rows, columns=SCHOOL_COLUMNS).to_excel(path, index=False)


def _canonical_names(path):
    frame = pd.read_excel(path).fillna("")
    return {row["normalized_key"]: row["canonical_school_name"] for row in frame.to_dict("records")}


def _setup(tmp_path):
    """Fresh state dir: synthetic database, one published release, synthetic dictionary."""
    state = tmp_path / "state"
    state.mkdir()
    cfg = {"state_dir": str(state)}
    db = connect(state)
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
               ("run", "fingerprint", utcnow(), "published", "{}", "{}", None))
    db.commit()
    source = {**SYNTHETIC_RECORD, "source_key": SYNTHETIC_RECORD["submission_id"],
              "source_id": "synthetic-source", "raw_hash": SYNTHETIC_RECORD["version_id"],
              "raw": {"answer": "synthetic"}, "location": {"row": 2}}
    ingest(db, "run", [source])
    db.execute("INSERT INTO normalized_records VALUES(?,?,?)",
               ("run", SYNTHETIC_RECORD["submission_id"], dumps(SYNTHETIC_RECORD)))
    db.execute("INSERT INTO releases VALUES(?,?,?,?,?)",
               ("release", "run", utcnow(), str(state), "{}"))
    db.execute("INSERT INTO publication VALUES(1,'release')")
    db.commit()
    _write_dictionary(state / "school_dictionary.xlsx", DICTIONARY_ROWS)
    return cfg, db


def _school_change(cfg, key, canonical_name, reason):
    """One MAP row for the currently published dictionary version."""
    dictionary_path = Path(cfg["state_dir"]) / "school_dictionary.xlsx"
    return {"release_id": "release", "dictionary_hash": file_hash(dictionary_path),
            "normalized_key": key, "raw_name": key.title(), "action": "MAP",
            "canonical_school_name": canonical_name, "school_type": "", "school_sex": "",
            "school_district": "", "school_religion": "",
            "reviewer": "Synthetic reviewer", "reason": reason}


def _validated(cfg, db, school_rows):
    return validate_review_rows(db, cfg, [], school_rows)


def _decision_rows(db):
    return [tuple(row) for row in db.execute(
        "SELECT decision_id,payload_json,reviewer,reason FROM decisions ORDER BY decision_id")]


def _marker_rows(db):
    return [tuple(row) for row in db.execute(
        "SELECT batch_id,applied_at FROM review_applications ORDER BY batch_id")]


def _first_success(cfg, db):
    """Apply the first successful correction, so the live dictionary holds D1 and
    school_dictionary.previous.xlsx holds the older D0."""
    first = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2026)", "Synthetic first correction"),
        _school_change(cfg, "second school", "Second School (2026)", "Synthetic first correction"),
    ])
    commit_review_rows(db, first, {"batch_id": "batch-1", "result": {}})


@pytest.fixture
def workspace(tmp_path):
    """Synthetic state dir plus its database. The connection is always closed."""
    cfg, db = _setup(tmp_path)
    try:
        yield cfg, db
    finally:
        db.close()


def test_successful_school_correction_persists_dictionary_decision_and_marker(workspace):
    """Case A - a normal application keeps the dictionary, the decision and the marker."""
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"

    validated = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2026)", "Synthetic first correction"),
    ])
    result = commit_review_rows(db, validated, {"batch_id": "batch-1", "result": {}})

    assert result == {"corrections": 0, "validation_labels": 0, "school_changes": 1}

    # The live dictionary carries the approved canonical name.
    assert _canonical_names(dictionary_path)["example school"] == "Example School (2026)"
    # The untouched school is unchanged.
    assert _canonical_names(dictionary_path)["second school"] == "Second School"

    # The pre-correction state is kept as the previous backup.
    assert previous_path.exists()
    assert _canonical_names(previous_path)["example school"] == "Example School"
    assert _canonical_names(previous_path)["second school"] == "Second School"

    # Exactly one decision was written, and it is the school decision.
    decisions = _decision_rows(db)
    assert len(decisions) == 1
    payload = json.loads(decisions[0][1])
    assert payload["target_key"] == "school:example school"
    assert payload["action"] == "map"
    assert payload["canonical_school_name"] == "Example School (2026)"
    assert decisions[0][2] == "Synthetic reviewer"
    assert decisions[0][3] == "Synthetic first correction"

    # No validation labels were requested.
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0

    # The application marker is present.
    assert [row[0] for row in _marker_rows(db)] == ["batch-1"]

    # The staging file of this operation is gone.
    assert not (state / "school_dictionary.next.xlsx").exists()


def test_failed_second_application_keeps_the_first_successful_dictionary(workspace):
    """Case B - a failure before the backup must not restore a stale previous file.

    The first application succeeds, so the live dictionary holds D1 and the
    previous backup holds the older D0. The second application then fails inside
    the database write phase, which is before review.py:286 copies the previous
    backup and before review.py:288 replaces the live dictionary.

    Correct behaviour: the live dictionary still holds D1, the failed database
    write is fully rolled back, and the first application remains in place.
    """
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"

    _first_success(cfg, db)

    live_after_first = _canonical_names(dictionary_path)
    assert live_after_first == FIRST_CANONICAL
    assert _canonical_names(previous_path) == STALE_CANONICAL
    live_hash_after_first = file_hash(dictionary_path)
    decisions_after_first = _decision_rows(db)
    markers_after_first = _marker_rows(db)
    assert len(decisions_after_first) == 2
    assert [row[0] for row in markers_after_first] == ["batch-1"]

    # The second correction is prepared against the current D1 dictionary.
    second = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2027)", "Synthetic second correction"),
    ])

    # The trigger fires on the decisions insert at review.py:280, which is before
    # review.py:286 copies the previous backup and before review.py:288 replaces
    # the live dictionary.
    db.execute("CREATE TRIGGER synthetic_fail_decision BEFORE INSERT ON decisions "
               "BEGIN SELECT RAISE(ABORT, 'synthetic failure during decision write'); END")
    db.commit()

    with pytest.raises(sqlite3.DatabaseError):
        commit_review_rows(db, second, {"batch_id": "batch-2", "result": {}})

    # The live dictionary must still be D1, byte for byte.
    assert _canonical_names(dictionary_path) == live_after_first
    assert file_hash(dictionary_path) == live_hash_after_first

    # The failed database write is fully rolled back and the first application
    # is still in place.
    assert _decision_rows(db) == decisions_after_first
    assert _marker_rows(db) == markers_after_first
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0
    surviving = [json.loads(row[1]) for row in _decision_rows(db)]
    assert {payload["canonical_school_name"] for payload in surviving} == {
        "Example School (2026)", "Second School (2026)"}

    # The stale previous file is untouched and this operation left no staging file.
    assert _canonical_names(previous_path) == STALE_CANONICAL
    assert not (state / "school_dictionary.next.xlsx").exists()


def test_failed_backup_copy_leaves_the_live_dictionary_untouched(workspace, monkeypatch):
    """Case C - when this operation's backup copy fails, the live dictionary is not
    overwritten with the older previous file."""
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"

    _first_success(cfg, db)
    live_after_first = _canonical_names(dictionary_path)
    live_hash_after_first = file_hash(dictionary_path)
    decisions_after_first = _decision_rows(db)
    markers_after_first = _marker_rows(db)

    second = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2027)", "Synthetic second correction"),
    ])

    # review.py:286 is the backup copy of this operation. Make it fail.
    real_copy2 = shutil.copy2

    def failing_copy2(source, target, *args, **kwargs):
        if Path(target).name == "school_dictionary.previous.xlsx":
            raise OSError("synthetic backup copy failure")
        return real_copy2(source, target, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", failing_copy2)

    with pytest.raises(OSError, match="synthetic backup copy failure"):
        commit_review_rows(db, second, {"batch_id": "batch-2", "result": {}})

    monkeypatch.undo()

    # The live dictionary is exactly as the first successful application left it.
    assert _canonical_names(dictionary_path) == live_after_first
    assert file_hash(dictionary_path) == live_hash_after_first

    # The database write was rolled back and no marker was left behind.
    assert _decision_rows(db) == decisions_after_first
    assert _marker_rows(db) == markers_after_first
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0

    # The older previous file is not used as a recovery source and stays as it was.
    assert _canonical_names(previous_path) == STALE_CANONICAL

    # This operation's staging file is cleaned up.
    assert not (state / "school_dictionary.next.xlsx").exists()


def test_failed_dictionary_replacement_leaves_the_live_dictionary_untouched(workspace, monkeypatch):
    """Case D - when the replacement fails, the live dictionary is not overwritten
    with an incomplete or older backup."""
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"

    _first_success(cfg, db)
    live_after_first = _canonical_names(dictionary_path)
    live_hash_after_first = file_hash(dictionary_path)
    decisions_after_first = _decision_rows(db)
    markers_after_first = _marker_rows(db)

    second = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2027)", "Synthetic second correction"),
    ])

    # review.py:288 is the replacement of the live dictionary. Make it fail.
    def failing_replace(self, target):
        raise OSError("synthetic dictionary replacement failure")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="synthetic dictionary replacement failure"):
        commit_review_rows(db, second, {"batch_id": "batch-2", "result": {}})

    monkeypatch.undo()

    # The live dictionary is exactly as the first successful application left it.
    assert _canonical_names(dictionary_path) == live_after_first
    assert file_hash(dictionary_path) == live_hash_after_first

    # The database write was rolled back and no marker was left behind.
    assert _decision_rows(db) == decisions_after_first
    assert _marker_rows(db) == markers_after_first
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0

    # The previous file written by this operation holds the pre-operation state
    # and was not used to overwrite the live dictionary.
    assert _canonical_names(previous_path) == live_after_first

    # This operation's staging file is cleaned up.
    assert not (state / "school_dictionary.next.xlsx").exists()


def test_commit_failure_after_replacement_restores_the_previous_dictionary(workspace):
    """Case E - the dictionary was replaced and the database commit then failed.

    The commit failure is produced by a real SQLite deferred foreign key
    constraint, so the marker row is written inside the transaction and the
    failure only surfaces at COMMIT. The live dictionary has to go back to the
    state it had before this operation, and the written rows have to be gone.

    Correct behaviour: the live dictionary holds D1 again, the marker of the
    failed batch is absent, and the first application is untouched.
    """
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"

    _first_success(cfg, db)
    live_after_first = _canonical_names(dictionary_path)
    live_hash_after_first = file_hash(dictionary_path)
    decisions_after_first = _decision_rows(db)
    markers_after_first = _marker_rows(db)

    second = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2027)", "Synthetic second correction"),
    ])

    # A real deferred foreign key constraint. The guard row breaks it, and the
    # violation is only reported when the transaction commits.
    db.execute("CREATE TABLE synthetic_deferred_guard("
               "batch_id TEXT PRIMARY KEY, payload_json TEXT, "
               "FOREIGN KEY (batch_id) REFERENCES review_applications(batch_id) "
               "DEFERRABLE INITIALLY DEFERRED)")
    db.execute("CREATE TRIGGER synthetic_fail_commit AFTER INSERT ON review_applications BEGIN "
               "INSERT INTO synthetic_deferred_guard(batch_id,payload_json) "
               "VALUES ('synthetic-missing-batch','{}'); END")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        commit_review_rows(db, second, {"batch_id": "batch-2", "result": {}})

    # The live dictionary is back to the state before this operation.
    assert _canonical_names(dictionary_path) == live_after_first
    assert file_hash(dictionary_path) == live_hash_after_first

    # The rows written inside the failed transaction were rolled back.
    assert _decision_rows(db) == decisions_after_first
    assert _marker_rows(db) == markers_after_first
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM synthetic_deferred_guard").fetchone()[0] == 0
    assert not db.in_transaction

    # The first application is untouched and no staging file is left.
    surviving = [json.loads(row[1]) for row in _decision_rows(db)]
    assert {payload["canonical_school_name"] for payload in surviving} == {
        "Example School (2026)", "Second School (2026)"}
    assert not (state / "school_dictionary.next.xlsx").exists()


def test_failed_staging_write_removes_the_partial_file_and_keeps_the_dictionary(workspace, monkeypatch):
    """Case F - the staging write itself fails after writing part of the file.

    study2.review.write_excel is replaced by a writer that writes a partial
    staging file and then raises, which is what a full disk or a closed writer
    looks like. The original error has to reach the caller, the partial staging
    file has to be removed, and the live dictionary and the database must be
    untouched.
    """
    cfg, db = workspace
    state = Path(cfg["state_dir"])
    dictionary_path = state / "school_dictionary.xlsx"
    previous_path = state / "school_dictionary.previous.xlsx"
    staging_path = state / "school_dictionary.next.xlsx"

    _first_success(cfg, db)
    live_after_first = _canonical_names(dictionary_path)
    live_hash_after_first = file_hash(dictionary_path)
    decisions_after_first = _decision_rows(db)
    markers_after_first = _marker_rows(db)

    second = _validated(cfg, db, [
        _school_change(cfg, "example school", "Example School (2027)", "Synthetic second correction"),
    ])

    def failing_write_excel(path, sheets, tracking=False):
        Path(path).write_bytes(b"partial staging content")
        raise OSError("synthetic staging write failure")

    monkeypatch.setattr(review_module, "write_excel", failing_write_excel)

    with pytest.raises(OSError, match="synthetic staging write failure"):
        commit_review_rows(db, second, {"batch_id": "batch-2", "result": {}})

    monkeypatch.undo()

    # The partial staging file is gone.
    assert not staging_path.exists()

    # The live dictionary is untouched, content and fingerprint.
    assert _canonical_names(dictionary_path) == live_after_first
    assert file_hash(dictionary_path) == live_hash_after_first

    # No decision, label or marker was written.
    assert _decision_rows(db) == decisions_after_first
    assert _marker_rows(db) == markers_after_first
    assert db.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0

    # The older previous file is untouched and was not used as a recovery source.
    assert _canonical_names(previous_path) == STALE_CANONICAL
