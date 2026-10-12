from datetime import datetime, timedelta, timezone

import pytest

from study2.common import PipelineError, contacts, phone
from study2.matching import identity_evidence, link_records, select_waves
from study2.outputs import metrics


def rec(sid, day=0, role="student", dob="2012-01-01", gender="0", phone_value="61234567", school="Example School", **kwargs):
    answer = {"contact_01": phone_value, "student_demographics_02": "01", "adult_demographics_02": "01"}
    record = {"submission_id": sid, "version_id": "version_" + sid, "role": role, "answer": answer,
              "status": "eligible", "dob": dob, "gender": gender, "school": school, "grade": 3,
              "observed_at": (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat(),
              "time_confidence": "observed", "claimed_wave": "T0", "issues": []}
    record.update(kwargs)
    return record


def test_shared_family_phone_does_not_merge_siblings():
    rows = [rec("s1"), rec("s2", dob="2013-02-02"), rec("p1", role="parent"), rec("p2", role="parent", dob="2013-02-02")]
    groups, cases, _ = link_records(rows, [])
    assert sorted(groups) == [["p1", "s1"], ["p2", "s2"]]
    assert any(c["status"] == "pending" for c in cases)


def test_twin_class_conflict_makes_whole_component_pending():
    rows = [rec("s1"), rec("s2"), rec("p", role="parent")]
    rows[0]["answer"]["student_demographics_02"] = "3A-01"
    rows[1]["answer"]["student_demographics_02"] = "3A-02"
    groups, cases, _ = link_records(rows, [])
    assert all(len(g) == 1 for g in groups)
    assert all(c["status"] != "confirmed" for c in cases)


def test_fuzzy_phone_and_missing_measurements_are_review_only():
    groups, cases, _ = link_records([rec("a"), rec("b", 120, phone_value="61234568")], [])
    assert groups == [["a"], ["b"]]
    assert len(cases) == 1 and cases[0]["status"] == "pending"


def test_contact_bridge_does_not_pick_first_candidate():
    a, b, c = rec("a"), rec("b", 120), rec("c", 240, phone_value="62345678")
    b["answer"]["contact_02"] = "62345678"
    groups, cases, _ = link_records([a, b, c], [])
    assert all(len(g) == 1 for g in groups)
    assert all(case["status"] == "pending" for case in cases)


def test_order_independence():
    a, b, p = rec("a"), rec("b", 120), rec("p", 0, role="parent")
    first, _, _ = link_records([a, b, p], [])
    second, _, _ = link_records([p, b, a], [])
    assert first == second == [["a", "b", "p"]]


@pytest.mark.parametrize("gap,status,t1", [(29, "eligible", False), (30, "eligible", False), (89, "eligible", False), (90, "eligible", True)])
def test_time_boundaries(gap, status, t1):
    a, b = rec("a"), rec("b", gap)
    rows, _ = select_waves([a, b], {"a": "child", "b": "child"})
    assert rows[0]["status"] == status
    assert bool(rows[1]["selected_wave"] == "T1") == t1
    if gap in [30, 89]:
        assert rows[1]["status"] == "short_interval_followup"
    if gap == 29:
        assert rows[1]["status"] == "short_repeat"
        assert rows[0]["selected_wave"] == "T0"


def test_short_interval_is_not_a_duplicate_and_latest_followup_wins():
    rows = [rec("a"), rec("b", 60), rec("c", 120), rec("d", 240)]
    rows, _ = select_waves(rows, {r["submission_id"]: "child" for r in rows})
    assert [r["selected_wave"] for r in rows] == ["T0", None, None, "T1"]
    assert rows[1]["status"] == "short_interval_followup"
    assert rows[2]["status"] == "extra_followup"


def test_batch_dates_never_prove_followup():
    rows = [rec("a", time_confidence="batch_only", observed_at=None), rec("b", 120)]
    rows, cases = select_waves(rows, {"a": "child", "b": "child"})
    assert not any(r["selected_wave"] for r in rows)
    assert cases[0]["kind"] == "date"


def test_equal_dates_need_review_instead_of_lexical_t0():
    rows=[rec("a"),rec("b")]
    rows,cases=select_waves(rows,{"a":"child","b":"child"})
    assert not any(r["selected_wave"] for r in rows)
    assert all(c["rule"]=="ambiguous_same_timestamp" for c in cases)


def test_single_t1_claim_infers_t0():
    row = rec("a", claimed_wave="T1", time_confidence="batch_only", observed_at=None)
    rows, _ = select_waves([row], {"a": "child"})
    assert rows[0]["selected_wave"] == "T0"
    assert rows[0]["claimed_wave"] == "T1"


def test_manual_unlink_blocks_automatic_relink_and_new_version_reopens():
    a, b = rec("a"), rec("b", 120)
    d = {"decision_id": "d", "payload": {"record_a": "a", "record_b": "b", "version_a": a["version_id"], "version_b": b["version_id"], "action": "UNLINK"}}
    groups, _, events = link_records([a, b], [d])
    assert len(groups) == 2 and events[0]["status"] == "applied"
    b["version_id"] = "new_version"
    groups, _, events = link_records([a, b], [d])
    assert events[0]["status"] == "reopened"
    assert len(groups) == 2


def test_chain_never_moves_earliest_t0():
    rows = [rec(str(day), day) for day in [0, 29, 58, 87, 120]]
    rows, _ = select_waves(rows, {r["submission_id"]: "child" for r in rows})
    assert [r["selected_wave"] for r in rows] == ["T0", None, None, None, "T1"]
    assert rows[2]["status"] == rows[3]["status"] == "short_interval_followup"


def test_indistinguishable_twins_without_class_number_are_pending():
    rows = [rec("s1"), rec("s2"), rec("p", role="parent")]
    for r in rows:
        r["answer"]["student_demographics_02"] = None
        r["answer"]["adult_demographics_02"] = None
    groups, cases, _ = link_records(rows, [])
    assert len(groups) == 3
    assert all(c["status"] == "pending" for c in cases)


def test_conflicting_manual_triangle_is_rejected():
    rows = [rec("a"), rec("b", 120), rec("c", 240)]
    decisions = [{"decision_id": action+a+b, "payload": {"action": action, "record_a": a, "record_b": b,
                  "version_a": "version_"+a, "version_b": "version_"+b}}
                 for action,a,b in [("LINK","a","b"),("LINK","b","c"),("UNLINK","a","c")]]
    with pytest.raises(PipelineError, match="transitive"):
        link_records(rows, decisions)


def test_unrelated_answer_update_preserves_reviewed_identity_decision():
    a, b = rec("a"), rec("b", 120)
    payload = {"action": "UNLINK", "record_a": "a", "record_b": "b", "version_a": a["version_id"],
               "version_b": b["version_id"], "evidence_a": identity_evidence(a), "evidence_b": identity_evidence(b)}
    b["version_id"] = "new_version"
    b["answer"]["student_PHQ_01"] = 2
    groups, _, events = link_records([a,b], [{"decision_id": "d", "payload": payload}])
    assert len(groups) == 2 and events[0]["status"] == "applied"


def test_phone_normalization_does_not_concatenate_or_take_email_digits():
    assert phone(61234567.0) == "61234567"
    assert phone("+852 6123-4567") == "61234567"
    assert phone("61234567/62345678") == ""
    assert phone("someone61234567@example.org") == ""
    assert contacts({"contact_01": "61234567/62345678"}) == {"61234567", "62345678"}


def test_school_transfer_requires_review_with_otherwise_shared_evidence():
    a, b = rec("a"), rec("b", 120)
    b["school"] = "New School"
    groups, cases, _ = link_records([a, b], [])
    assert len(groups) == 2
    assert any(c["rule"] == "transfer_contact_child_demo" and c["status"] == "pending" for c in cases)


def test_complete_item_scoring_and_single_sec_shift():
    answer = {f"student_PHQ_{i:02d}": 1 for i in range(1, 5)}
    answer.update({f"student_SEC_{i:02d}": 0 for i in range(1, 23)})
    assert metrics(answer, "student")["PHQ_total"] == 4
    assert metrics(answer, "student")["SEC_total"] == 1
    answer["student_PHQ_01"] = None
    assert metrics(answer, "student")["PHQ_total"] is None
    assert metrics(answer, "student")["TBV_prevalence1"] is None
