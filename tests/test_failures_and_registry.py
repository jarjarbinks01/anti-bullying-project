import json
from pathlib import Path
from unittest.mock import patch

import pytest

from study2.common import PipelineError, atomic_json, dumps, utcnow
from study2.paper_registry import resolve_paper_rows
from study2.runner import publish_release, recover_pointer
from study2.store import connect, current
from study2.review import validation_report
from test_identity_and_time import rec


def test_paper_reorder_and_append_preserve_registered_ids(tmp_path):
    db = connect(tmp_path)
    source = {"source_id": "paper", "sheet": 0, "file": "synthetic.xlsx"}
    first = resolve_paper_rows(db, source, [(2,{"person":"a"}), (3,{"person":"b"})])
    second = resolve_paper_rows(db, source, [(2,{"person":"b"}), (3,{"person":"a"}), (4,{"person":"c"})])
    assert first[2] == second[3] and first[3] == second[2]
    assert second[4] not in first.values()
    with pytest.raises(PipelineError, match="edited/deleted"):
        resolve_paper_rows(db, source, [(2,{"person":"changed"}), (3,{"person":"b"}), (4,{"person":"c"})])
    db.close()


def releases(db, tmp_path):
    for run in ["old", "new"]:
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run,"fp",utcnow(),"validated","{}","{}",None))
        db.execute("INSERT INTO releases VALUES(?,?,?,?,?)", (run,run,utcnow(),str(tmp_path),"{}"))
    db.execute("INSERT INTO publication VALUES(1,'old')")
    db.commit()


def test_pointer_write_failure_keeps_published_database(tmp_path):
    db = connect(tmp_path)
    releases(db,tmp_path)
    cfg={"release_dir":str(tmp_path),"state_dir":str(tmp_path)}
    with patch("study2.runner.verify_release", return_value={"run_id":"new","path":str(tmp_path)}), patch("study2.runner.atomic_json",side_effect=OSError("Injected write failure")):
        with pytest.raises(OSError):
            publish_release(db,cfg,"new")
    assert current(db)["release_id"] == "old"
    db.close()


def test_process_crash_pointer_is_recovered_from_authoritative_database(tmp_path):
    db=connect(tmp_path)
    releases(db,tmp_path)
    atomic_json(tmp_path/"CURRENT.json",{"release_id":"new"})
    recover_pointer(db,{"release_dir":str(tmp_path)})
    assert json.loads((tmp_path/"CURRENT.json").read_text())["release_id"] == "old"
    db.close()


def test_reviewed_match_outside_candidate_search_is_reported_as_missed(tmp_path):
    db=connect(tmp_path)
    rows=[rec("a"),rec("b",120)]
    payload={"case_id":"outside", "record_a":"a","record_b":"b","version_a":"version_a","version_b":"version_b","kind":"identity"}
    db.execute("INSERT INTO labels VALUES(?,?,?,?,?,?)",("outside","MATCH","Reviewer","Independent verification",utcnow(),dumps(payload)))
    result=validation_report(db,[],rows)
    assert result[0]["rule"] == "outside_candidate_search" and result[0]["missed_match"] == 1
    db.close()
