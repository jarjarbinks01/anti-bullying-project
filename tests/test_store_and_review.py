import json
from pathlib import Path

import pandas as pd
import pytest

from study2.common import PipelineError, digest, dumps, utcnow
from study2.matching import assign_children, candidate
from study2.review import export_review, import_review, validation_report
from study2.store import backup, connect, ingest
from test_identity_and_time import rec


def database(tmp_path):
    db = connect(tmp_path)
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("run", "fp", utcnow(), "published", "{}", "{}", None))
    db.commit()
    return db


def source(row):
    return {**row, "source_key": row["submission_id"], "source_id": "source", "raw_hash": row["version_id"], "raw": {"answer": "synthetic"}, "location": {"row": 2}}


def test_collision_rolls_back_and_repeated_versions_do_not_duplicate(tmp_path):
    db = database(tmp_path)
    with pytest.raises(PipelineError):
        with db:
            ingest(db, "run", [source(rec("a")), source(rec("a"))])
    assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0
    with db:
        ingest(db, "run", [source(rec("a"))])
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("second", "fp", utcnow(), "validated", "{}", "{}", None))
        ingest(db, "second", [source(rec("a"))])
    assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM submission_versions").fetchone()[0] == 1
    db.close()


def published(db, cfg, rows):
    for row in rows:
        row.update(source_id="source", source_kind="system", location={}, raw={}, issues=[])
    ingest(db, "run", [source(row) for row in rows])
    for row in rows:
        db.execute("INSERT INTO normalized_records VALUES(?,?,?)", ("run", row["submission_id"], dumps(row)))
    db.execute("INSERT INTO releases VALUES(?,?,?,?,?)", ("release", "run", utcnow(), str(cfg["state_dir"]), "{}"))
    db.execute("INSERT INTO publication VALUES(1,'release')")
    c = candidate(rows[0], rows[1], "identity", "exact", "confirmed", "synthetic")
    db.execute("INSERT INTO release_candidates VALUES(?,?,?)", ("release", c["case_id"], dumps(c)))
    db.commit()
    pd.DataFrame([{"raw_name": "Example School", "normalized_key": "example school", "action": "map", "canonical_school_name": "Example School"}]).to_excel(Path(cfg["state_dir"]) / "school_dictionary.xlsx", index=False)
    return c


def test_stable_child_anchor_with_new_earlier_record(tmp_path):
    db = database(tmp_path)
    ingest(db, "run", [source(rec("b")), source(rec("c"))])
    first = assign_children(db, "run", [["b", "c"]])
    db.execute("INSERT INTO releases VALUES(?,?,?,?,?)", ("r", "run", utcnow(), str(tmp_path), "{}"))
    db.execute("INSERT INTO publication VALUES(1,'r')")
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("next", "fp", utcnow(), "validated", "{}", "{}", None))
    ingest(db, "next", [source(rec("a")), source(rec("b")), source(rec("c"))])
    second = assign_children(db, "next", [["a", "b", "c"]])
    assert first["b"] == second["b"] == second["a"]
    db.close()


def test_stale_conflicting_review_is_all_or_nothing(tmp_path):
    cfg = {"state_dir": str(tmp_path)}
    db = database(tmp_path)
    published(db, cfg, [rec("a"), rec("b", 120)])
    path = tmp_path / "review.xlsx"
    export_review(db, cfg, path)
    sheets = {name: frame.fillna("") for name, frame in pd.read_excel(path, sheet_name=None).items()}
    row = sheets["cases"].iloc[0].copy()
    row[["action", "reviewer", "reason"]] = ["LINK", "Research reviewer", "Verified synthetic case"]
    other = row.copy()
    other["action"] = "UNLINK"
    sheets["cases"] = pd.DataFrame([row, other])
    with pd.ExcelWriter(path) as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    with pytest.raises(PipelineError, match="Conflicting"):
        import_review(db, cfg, path)
    assert db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    sheets["cases"] = pd.DataFrame([row])
    sheets["cases"].loc[0, "release_id"] = "stale"
    with pd.ExcelWriter(path) as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    with pytest.raises(PipelineError, match="Stale"):
        import_review(db, cfg, path)
    db.close()


def test_verified_nonmatch_blocks_publication_and_backup_restores(tmp_path):
    cfg = {"state_dir": str(tmp_path)}
    db = database(tmp_path)
    c = published(db, cfg, [rec("a"), rec("b", 120)])
    db.execute("INSERT INTO labels VALUES(?,?,?,?,?,?)", (c["case_id"], "NONMATCH", "Reviewer", "Known false", utcnow(), dumps(c)))
    db.commit()
    with pytest.raises(PipelineError, match="NONMATCH"):
        validation_report(db, [c])
    path = tmp_path / "backup.sqlite"
    backup(db, path)
    import sqlite3
    restored = sqlite3.connect(path)
    assert restored.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored.close()
    db.close()
