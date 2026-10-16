import copy

import pytest

from study2.matching import candidate, identity_evidence, link_records, select_waves
from study2.respondents import adult_evidence, adult_followups, adult_match
from study2.review_hints import pair_review_hints
from test_approved_merged_rules import parent
from test_identity_and_time import rec

FALLBACK = {"adult_contact_scope": "any_exact"}


@pytest.mark.parametrize("missing", ["a", "b", "both"])
def test_exact_general_phone_can_replace_missing_personal_contact(missing):
    a, b = parent("a", 0), parent("b", 120)
    for label, record in [("a", a), ("b", b)]:
        if missing in {label, "both"}:
            record["answer"]["contact_02"] = ""
    assert adult_match(a, b)[0] == "confirmed"
    assert adult_match(a, b, FALLBACK) == (
        "confirmed", "same_adult_reported_birth_any_exact_contact")


def test_email_fallback_is_exact_and_does_not_overrule_adult_conflicts():
    a, b = parent("a", 0, personal=""), parent("b", 120, personal="")
    a["answer"]["contact_01"] = "61234567"
    b["answer"]["contact_01"] = "63456789"
    a["answer"]["contact_03.3"] = "Family@Example.org"
    b["answer"]["contact_03.3"] = "family@example.org"
    assert adult_match(a, b, FALLBACK)[0] == "confirmed"
    b["answer"]["contact_03.3"] = "families@example.org"
    assert adult_match(a, b, FALLBACK)[0] == "pending"
    b["answer"]["contact_03.3"] = "family@example.org"
    b["answer"]["adult_demographics_05"] = 1981
    assert adult_match(a, b, FALLBACK)[1] == "reported_birth_year_changed"
    b["answer"]["adult_demographics_05"] = ""
    assert adult_match(a, b, FALLBACK)[1] == "adult_birth_year_missing_or_invalid"
    b["answer"].update(adult_demographics_05=1980, adult_demographics_06=0)
    assert adult_match(a, b, FALLBACK)[0] == 'confirmed'


def test_different_personal_contacts_allow_an_exact_shared_general_contact():
    a, b = parent("a", 0), parent("b", 120, personal="63456789")
    assert adult_match(a, b, FALLBACK) == ('confirmed', 'same_adult_reported_birth_any_exact_contact')


def test_fallback_drives_repeat_selection_and_never_links_different_children():
    rows = [parent("p0", 0, personal=""), parent("p1", 120, personal=""),
            parent("p2", 143, personal="")]
    selected, _ = select_waves(rows, {r["submission_id"]: "child" for r in rows},
                               parent_requires_same_adult=True, matching_policy=FALLBACK)
    assert selected[1]["status"] == "short_repeat"
    assert selected[1]["duplicate_of"] == "p2"
    assert selected[2]["selected_wave"] == "T1"
    pairs, _, _ = adult_followups(selected, [], policy=FALLBACK)
    assert len(pairs) == 1 and pairs[0]["t1"] == "p2"
    selected[2]["child_id"] = "sibling"
    assert not adult_followups([selected[0], selected[2]], [], policy=FALLBACK)[0]


def graded(sid, date, grade, stage, raw=None):
    r = rec(sid, observed_at=date, grade=grade)
    r["answer"]["school_type"] = stage
    r["grade_raw"] = raw or str(grade)
    return r


def test_primary_to_secondary_is_progression_not_regression():
    a = graded("a", "2025-03-16T00:00:00+00:00", 5, "primary")
    b = graded("b", "2026-09-06T00:00:00+00:00", 1, "secondary")
    assert not pair_review_hints(a, b)["review_warnings"]
    a["grade"] = 6
    b["observed_at"] = "2026-04-01T00:00:00+00:00"
    assert not pair_review_hints(a, b)["review_warnings"]


def test_grade_jump_is_only_a_hint_and_is_invariant_to_comparison_order():
    a = graded("a", "2026-07-27T00:00:00+00:00", 2, "secondary")
    b = graded("b", "2026-07-28T13:00:00+00:00", 4, "secondary")
    original = copy.deepcopy([a, b])
    hints = pair_review_hints(a, b)
    assert "grade_advance_exceeds_school_years" in hints["review_warning_codes"]
    assert pair_review_hints(b, a) == hints
    assert [a, b] == original
    c = candidate(a, b, "family", "manual_link", "confirmed", "Synthetic review")
    assert c["status"] == "confirmed" and c["review_warnings"] == hints["review_warnings"]


def test_hong_kong_school_year_boundary_and_missing_or_batch_dates():
    a = graded("a", "2026-08-31T15:00:00+00:00", 3, "primary")
    b = graded("b", "2026-08-31T16:00:00+00:00", 4, "primary")
    assert not pair_review_hints(a, b)["review_warning_codes"]
    b["date_basis"] = "batch_assigned_creation"
    assert "batch_date_basis" in pair_review_hints(a, b)["review_warning_codes"]
    b["observed_at"] = None
    assert "observation_date_missing" in pair_review_hints(a, b)["review_warning_codes"]


def test_mixed_school_stage_is_not_guessed_and_regression_is_flagged():
    a = graded("a", "2025-03-01T00:00:00+00:00", 6, "primary & secondary")
    b = graded("b", "2026-03-01T00:00:00+00:00", 1, "primary & secondary")
    assert pair_review_hints(a, b)["review_warning_codes"] == ["grade_stage_unclear"]
    a["grade_raw"], b["grade_raw"] = "P6", "S1"
    assert not pair_review_hints(a, b)["review_warning_codes"]
    a["answer"]["school_type"] = "secondary"
    b["answer"]["school_type"] = "primary"
    assert "school_grade_stage_disagrees" in pair_review_hints(a, b)["review_warning_codes"]
    a["grade_raw"], b["grade_raw"] = "6", "1"
    assert "grade_decreased" in pair_review_hints(a, b)["review_warning_codes"]


def test_reviewed_parent_repeat_without_merging_dob_conflict():
    p0, p1, p2 = parent("p0", 0, personal=""), parent("p1", 420, personal=""), parent("p2", 443, personal="")
    s0, s1 = rec("s0"), rec("s1", 443, dob="2012-01-02")
    for r in (p1, p2):
        r["answer"]["adult_demographics_02"] = ""
        r["grade"] = 4
    rows = [p0, s0, p1, p2, s1]
    original_answers = {r["submission_id"]: copy.deepcopy(r["answer"]) for r in rows}
    decisions = []
    for a, b in ((p0, s0), (p0, p1), (p1, p2)):
        decisions.append({"decision_id": a["submission_id"]+b["submission_id"], "payload": {
            "action": "LINK", "record_a": a["submission_id"], "record_b": b["submission_id"],
            "evidence_a": identity_evidence(a), "evidence_b": identity_evidence(b)}})
    policy = {**FALLBACK, "allow_one_digit_phone": True, "allow_school_transfer": True}
    groups, _, _ = link_records(rows, decisions, policy)
    assert sorted(groups) == [["p0", "p1", "p2", "s0"], ["s1"]]
    assert link_records(list(reversed(copy.deepcopy(rows))), decisions, policy)[0] == groups
    children = {sid: "child" if sid != "s1" else "unresolved_student" for group in groups for sid in group}
    rows, _ = select_waves(rows, children, parent_requires_same_adult=True, matching_policy=policy)
    assert p0["selected_wave"] == s0["selected_wave"] == "T0"
    assert p1["status"] == "short_repeat" and p1["duplicate_of"] == "p2"
    assert p2["selected_wave"] == "T1"
    assert s1["child_id"] != p2["child_id"]
    assert len(rows) == 5
    assert original_answers == {r["submission_id"]: r["answer"] for r in rows}


def test_new_fallback_candidate_cannot_cancel_reviewed_typo_pair_or_inherit_exception():
    a, b, c = parent('a', 0, personal=''), parent('b', 120, birth=1981, personal=''), parent('c', 160, personal='')
    rows = [a, b, c]
    rows, _ = select_waves(rows, {r['submission_id']: 'child' for r in rows},
                           parent_requires_same_adult=True, matching_policy=FALLBACK)
    exception = {'type': 'accepted_typo_unknown_year', 'child_id': 'child'}
    decision = {'decision_id': 'reviewed_typo', 'payload': {'action': 'LINK_ADULT',
                'record_a': 'a', 'record_b': 'b', 'evidence_a': adult_evidence(a),
                'evidence_b': adult_evidence(b), 'adult_identity_exception': exception}}
    pairs, cases, events = adult_followups(rows, [decision], policy=FALLBACK)
    assert pairs[0]['t1'] == 'b' and pairs[0]['rule'] == 'reviewer_confirmed_same_adult'
    assert events[0]['status'] == 'applied'
    assert a['adult_birth_year_status'] == b['adult_birth_year_status'] == 'unconfirmed'
    assert 'adult_birth_year_status' not in c
    assert next(x for x in cases if x['record_b'] == 'c')['status'] == 'pending'
    # Even if the old followup no longer qualifies by date, its accepted typo
    # remains visible; wave selection must never silently validate the year.
    b['observed_at'] = rec('b', 30)['observed_at']
    adult_followups(rows, [decision], policy=FALLBACK)
    assert b['adult_birth_year_status'] == 'unconfirmed'
