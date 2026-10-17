"""Research-approved separation of child identity from repeat timing."""
import copy

import pytest

from study2.matching import identity_evidence, link_records, select_waves
from test_approved_merged_rules import POLICY, parent
from test_identity_and_time import rec


@pytest.mark.parametrize("role", ["student", "parent"])
@pytest.mark.parametrize("gap", [0, 3, 29, 30, 89, 90])
@pytest.mark.parametrize("roll", [None, "different-roll"])
def test_grade_roll_and_interval_do_not_gate_identity(role, gap, roll):
    a, b = rec("a", role=role), rec("b", gap, role=role, grade=6)
    key = "student_demographics_02" if role == "student" else "adult_demographics_02"
    a["answer"][key] = None
    b["answer"][key] = roll
    groups, cases, _ = link_records([a, b], [], POLICY)
    assert groups == [["a", "b"]]
    assert cases[0]["status"] == "confirmed"


@pytest.mark.parametrize("variant", ["one_digit_phone", "school_transfer"])
def test_accepted_contact_rules_also_ignore_class_number_on_close_repeats(variant):
    a, b = rec("a"), rec("b", 3, grade=6)
    b["answer"]["student_demographics_02"] = None
    if variant == "one_digit_phone":
        b["answer"]["contact_01"] = "61234568"
    else:
        b["school"] = "New School"
    assert link_records([a, b], [], POLICY)[0] == [["a", "b"]]


@pytest.mark.parametrize("field,value", [("dob", "2013-02-02"), ("gender", "1"),
                                         ("dob", None), ("gender", None)])
def test_core_child_evidence_is_still_required(field, value):
    a, b = rec("a"), rec("b", 3, **{field: value})
    groups, cases, _ = link_records([a, b], [], POLICY)
    assert groups == [["a"], ["b"]]
    assert not any(c["status"] == "confirmed" for c in cases)


@pytest.mark.parametrize("gap,status", [(29, "short_repeat"), (30, "short_interval_followup"),
                                      (89, "short_interval_followup"), (90, "eligible")])
def test_link_before_time_selection_respects_boundaries(gap, status):
    a, b = rec("a"), rec("b", gap, grade=4)
    b["answer"]["student_demographics_02"] = None
    groups, _, _ = link_records([a, b], [], POLICY)
    children = {sid: str(i) for i, group in enumerate(groups) for sid in group}
    rows, _ = select_waves([a, b], children)
    assert rows[0]["selected_wave"] == "T0"
    assert rows[1]["status"] == status
    assert (rows[1]["selected_wave"] == "T1") == (gap == 90)


def test_missing_time_does_not_block_identity_but_does_block_chronology():
    rows = [rec("a"), rec("b", observed_at=None, time_confidence="unknown")]
    groups, _, _ = link_records(rows, [], POLICY)
    assert groups == [["a", "b"]]
    rows, cases = select_waves(rows, {"a": "child", "b": "child"})
    assert not any(r["selected_wave"] for r in rows)
    assert cases[0]["kind"] == "date"


def test_existing_manual_nonmatch_still_blocks_close_repeat_linkage():
    a, b = rec("a"), rec("b", 3)
    b["answer"]["student_demographics_02"] = None
    decision = {"decision_id": "reviewed", "payload": {
        "action": "UNLINK", "record_a": "a", "record_b": "b",
        "evidence_a": identity_evidence(a), "evidence_b": identity_evidence(b)}}
    groups, cases, events = link_records([a, b], [decision], POLICY)
    assert groups == [["a"], ["b"]]
    assert cases[0]["status"] == "rejected"
    assert events[0]["status"] == "applied"


def test_same_child_different_adults_are_not_short_repeat_duplicates():
    a, b = parent("a", 0), parent("b", 3, relation=0, birth=1978, personal="63456789")
    b["answer"]["adult_demographics_02"] = None
    assert link_records([a, b], [], POLICY)[0] == [["a", "b"]]
    rows, _ = select_waves([a, b], {"a": "child", "b": "child"}, parent_requires_same_adult=True)
    assert rows[0]["selected_wave"] == "T0"
    assert rows[1]["status"] == "short_interval_followup"
    assert not rows[1].get("duplicate_of")


def test_eight_form_component_links_before_dedup_without_class_numbers():
    # Synthetic reproduction of the reported eight-form review-group pattern.
    dates = ["2025-10-12", "2026-04-03", "2026-06-22", "2026-06-25"]
    rows = []
    for role in ("student", "parent"):
        for i, date in enumerate(dates):
            r = rec(role + str(i), role=role, grade=6 if i == 1 else 5,
                    grade_raw="S6" if i == 1 else "S5", school_type="secondary",
                    observed_at=date + ("T10:00:00+00:00" if role == "student" else "T11:00:00+00:00"))
            r["answer"].update(student_demographics_02=None, adult_demographics_02=None,
                               adult_demographics_05=1980, adult_demographics_06=1, contact_02="62345678")
            rows.append(r)
    groups, cases, _ = link_records(copy.deepcopy(rows), [], POLICY)
    reverse_groups, _, _ = link_records(copy.deepcopy(rows[::-1]), [], POLICY)
    assert groups == reverse_groups == [sorted(r["submission_id"] for r in rows)]
    assert len(cases) == 28 and all(c["status"] == "confirmed" for c in cases)
    assert any("grade_decreased" in c["review_warning_codes"] for c in cases)
    children = {r["submission_id"]: "child" for r in rows}
    selected, dedup = select_waves(rows, children, parent_requires_same_adult=True)
    assert len(dedup) == 2
    for role in ("student", "parent"):
        by_id = {r["submission_id"]: r for r in selected if r["role"] == role}
        assert by_id[role + "0"]["selected_wave"] == "T0"
        assert by_id[role + "2"]["status"] == "short_repeat"
        assert by_id[role + "2"]["duplicate_of"] == role + "3"
        assert by_id[role + "3"]["selected_wave"] == "T1"


def test_frozen_evidence_keeps_legacy_snapshot_format():
    r = rec("a")
    assert identity_evidence(r) == {
        "school": "Example School", "dob": "2012-01-01", "gender": "0",
        "grade": 3, "roll": "01", "contacts": ["61234567"],
        "observed_at": "2025-01-01T00:00:00+00:00"}
