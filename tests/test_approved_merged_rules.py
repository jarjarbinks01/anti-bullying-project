import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from study2.adapters import input_records, make_manifest, source_root
from study2.common import PipelineError, digest, file_hash
from study2.matching import link_records, one_digit_phone, select_waves
from study2.merged import mark_exact_input_repeats
from study2.respondents import adult_evidence, adult_followups, adult_match
from study2.review import export_review, import_review
from study2.store import connect, current
from test_identity_and_time import rec
from test_pipeline_integration import execute, project

POLICY = {"allow_one_digit_phone": True, "allow_school_transfer": True}


def parent(sid, day, relation=1, birth=1980, personal="62345678"):
    r = rec(sid, day, "parent")
    r["answer"].update(adult_demographics_06=relation, adult_demographics_05=birth, contact_02=personal)
    return r


def test_approved_one_digit_school_transfer_and_unsupported_combination():
    a = rec("a")
    fuzzy = rec("b", 120, phone_value="61234568")
    transfer = rec("c", 120, school="New School")
    assert link_records([a, fuzzy], [], POLICY)[0] == [["a", "b"]]
    assert link_records([a, transfer], [], POLICY)[0] == [["a", "c"]]
    unsupported = rec("d", 120, phone_value="61234568", school="New School")
    groups, cases, _ = link_records([a, unsupported], [], POLICY)
    assert groups == [["a"], ["d"]] and all(c["status"] != "confirmed" for c in cases)


@pytest.mark.parametrize("a,b,expected", [("61234567", "61234568", True), ("61234567", "61234576", False),
                                        ("61234567", "6123456", False), ("a@example.org", "b@example.org", False)])
def test_one_digit_is_exactly_one_substitution(a, b, expected):
    assert one_digit_phone(a, b) == expected


def test_fuzzy_chain_stays_pending_and_class_numbers_are_not_identity_gates():
    rows = [rec("a"), rec("b", 120, phone_value="61234568"), rec("c", 240, phone_value="61234588")]
    groups, cases, _ = link_records(rows, [], POLICY)
    assert all(len(g) == 1 for g in groups) and all(c["status"] != "confirmed" for c in cases)
    twins = [rec("s1"), rec("s2"), rec("p", role="parent")]
    twins[0]["answer"]["student_demographics_02"] = "01"
    twins[1]["answer"]["student_demographics_02"] = "02"
    assert link_records(twins, [], POLICY)[0] == [["p", "s1", "s2"]]
    twins[2]["answer"]["adult_demographics_02"] = ""
    assert link_records(twins, [], POLICY)[0] == [["p", "s1", "s2"]]


def test_accepted_batch_dates_establish_90_days_without_claiming_observed_dates():
    rows = [rec("a", time_confidence="accepted_creation_time"), rec("b", 90, time_confidence="accepted_creation_time")]
    rows, _ = select_waves(rows, {"a": "child", "b": "child"})
    assert [r["selected_wave"] for r in rows] == ["T0", "T1"]
    assert all(r["time_confidence"] == "accepted_creation_time" for r in rows)


def test_same_adult_birth_year_and_any_exact_contact_ignore_relationship():
    a, b = parent("a", 0), parent("b", 120)
    assert adult_match(a, b)[0] == "confirmed"
    b["answer"]["contact_02"] = ""
    assert adult_match(a, b) == ("confirmed", "same_adult_reported_birth_any_exact_contact")
    b["answer"]["adult_demographics_06"] = 0
    assert adult_match(a, b)[0] == 'confirmed'
    b["answer"]["adult_demographics_06"] = 1
    b["answer"]["adult_demographics_05"] = 1981
    assert adult_match(a, b) == ("rejected", "reported_birth_year_changed")


def test_adult_replacement_cannot_deduplicate_baseline_caregivers_valid_followup():
    mother0, mother1, father1 = parent("m0", 0), parent("m1", 120), parent("f1", 125, relation=0, birth=1978, personal="63456789")
    rows = [mother0, mother1, father1]
    rows, _ = select_waves(rows, {r["submission_id"]: "child" for r in rows}, parent_requires_same_adult=True)
    assert mother1["status"] == "extra_followup" and father1["selected_wave"] == "T1"
    pairs, cases, _ = adult_followups(rows, [])
    assert pairs[0]["t0"] == "m0" and pairs[0]["t1"] == "m1"
    assert mother1["bd_selected_wave"] == "T1"
    assert any(c["rule"] == "reported_birth_year_changed" for c in cases)


def test_adult_manual_evidence_change_reopens_and_blocks_automatic_decision():
    rows = [parent("a", 0), parent("b", 120)]
    rows, _ = select_waves(rows, {"a": "child", "b": "child"}, parent_requires_same_adult=True)
    d = {"decision_id": "manual", "payload": {"action": "LINK_ADULT", "record_a": "a", "record_b": "b",
         "evidence_a": adult_evidence(rows[0]), "evidence_b": adult_evidence(rows[1])}}
    assert len(adult_followups(rows, [d])[0]) == 1
    rows[1]["answer"]["contact_02"] = "63456789"
    pairs, cases, events = adult_followups(rows, [d])
    assert not pairs and events[0]["status"] == "reopened" and cases[0]["status"] == "pending"


def test_parent_bd_view_rescues_earlier_same_adult_without_replacing_family_f(project):
    cfg, _, rows, _ = project
    cfg.update(matching_policy=POLICY, bd_requires_same_adult=True)
    for r in rows[2:]:
        r["answer"].update(adult_demographics_05=1980, adult_demographics_06=1, contact_02="62345678")
    father = copy.deepcopy(rows[3])
    father.update(submission_id="f1", version_id="father-version", source_key="father-source", raw={"father": True})
    father["raw_hash"] = digest(father["raw"])
    father["answer"].update(adult_demographics_05=1978, adult_demographics_06=0, contact_02="63456789")
    father["observed_at"] = rec("f", 125)["observed_at"]
    rows.append(father)
    result = execute(project)
    assert result["BD"] == result["EF"] == 1 and result["BD_alternative_followups"] == 1
    root = Path(cfg["release_dir"]) / result["release_id"]
    bd = pd.read_excel(root / "3.1.1_ABCD_reconstruction/BD_T0T1-parent.xlsx")
    family = pd.read_excel(root / "3.1.3_manual_pairing/F_T1-student&parent-paired_final.xlsx", sheet_name="paired")
    assert bd.iloc[0]["T1_submission_id"] == "p1" and family.iloc[0]["parent_submission_id"] == "f1"
    tall = pd.read_parquet(root / "parent_longitudinal.parquet")
    assert set(tall["submission_id"]) == {"p0", "p1"}


def test_mother_to_father_is_not_bd_but_family_pairing_is_retained(project):
    cfg, _, rows, _ = project
    cfg.update(bd_requires_same_adult=True)
    rows[2]["answer"].update(adult_demographics_05=1980, adult_demographics_06=1, contact_02="62345678")
    rows[3]["answer"].update(adult_demographics_05=1978, adult_demographics_06=0, contact_02="63456789")
    result = execute(project)
    assert result["BD"] == 0 and result["parent_child_longitudinal"] == result["EF"] == 1


def test_adult_excel_override_is_independent_and_rejects_conflicting_commands(project):
    cfg, _, rows, _ = project
    cfg.update(bd_requires_same_adult=True)
    execute(project)
    db = connect(Path(cfg["state_dir"]))
    path = Path(cfg["project_root"]) / "adult-review.xlsx"
    export_review(db, cfg, path, limit=0)
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    # Missing adult years are no longer an ordinary identity-review task. The
    # operator can still register an explicitly verified pair using NEW.
    assert sheets["cases"].query("kind == 'respondent'").empty
    current_case=json.loads(next(row[0] for row in db.execute('SELECT payload_json FROM release_candidates')
                                 if json.loads(row[0])['kind']=='respondent'))
    case={**current_case,'case_id':'NEW','release_id':current(db)['release_id']}
    case.update(action="LINK_ADULT", reviewer="Synthetic researcher", reason="Existing synthetic consent log verifies same adult")
    sheets["cases"] = pd.DataFrame([case])
    with pd.ExcelWriter(path) as writer:
        for name, frame in sheets.items(): frame.to_excel(writer, sheet_name=name, index=False)
    assert import_review(db, cfg, path)["corrections"] == 1
    db.close()
    result = execute(project, force=True)
    assert result["BD"] == 1
    ef_path = Path(cfg["release_dir"]) / result["release_id"] / "3.1.3_manual_pairing/EF_T0T1-student&parent-paired_final.xlsx"
    assert pd.read_excel(ef_path).iloc[0]["caregiver_status"] == "same_adult_by_reviewed_evidence"


def test_exact_complete_row_copies_preserve_all_records_and_one_representative():
    rows = []
    for sid in ["a", "b"]:
        r = rec(sid)
        r.update(source_kind="merged", source_id="merged_A", raw_hash="same-full-row")
        rows.append(r)
    first, cases = mark_exact_input_repeats(rows)
    assert len(first) == 2 and first[1]["status"] == "exact_input_repeat" and cases[0]["kind"] == "dedup"
    again, _ = mark_exact_input_repeats([copy.deepcopy(r) | {"status": "eligible"} for r in reversed(rows)])
    assert next(r for r in again if r["status"] == "eligible")["submission_id"] == "a"


def test_merged_adapter_uses_only_registered_folder_keeps_ids_after_reorder(tmp_path):
    folder = tmp_path / "merged"; folder.mkdir()
    path = folder / "A.xlsx"
    frame = pd.DataFrame([{"Survey": "paperform_student_t0", "建立時間": "2026-02-01", "student_FQOL_01": 5, "contact_01": "61234567"},
                          {"Survey": "paperform_student_t0", "建立時間": "2026-03-01", "student_FQOL_01": 4, "contact_01": "62345678"}])
    frame.to_excel(path, index=False)
    cfg = {"project_root": str(tmp_path), "source_folder": "merged", "mapping_hashes": {}, "mapping_dir": "unused",
           "sources": [{"source_id": "merged_student", "kind": "merged", "role": "student", "wave": "T0", "pattern": "A.xlsx", "columns": list(frame)}]}
    db = connect(tmp_path / "state")
    from unittest.mock import patch
    with patch("study2.adapters.modules", return_value=(None, None, None)):
        first = input_records(cfg, make_manifest(cfg), db); db.commit()
        frame.iloc[::-1].to_excel(path, index=False)
        second = input_records(cfg, make_manifest(cfg), db)
        assert {r["submission_id"] for r in first} == {r["submission_id"] for r in second}
        assert all(r["time_confidence"] == "accepted_creation_time" for r in first)
        assert first[0]["answer"]["student_FQOL_01"] == 5
        edited = frame.copy(); edited.loc[0, "student_FQOL_01"] = 1; edited.to_excel(path, index=False)
        with pytest.raises(PipelineError, match="edited/deleted"):
            input_records(cfg, make_manifest(cfg), db)
    db.close()
    cfg["source_folder"] = "../outside"
    with pytest.raises(PipelineError, match="inside"):
        source_root(cfg)
