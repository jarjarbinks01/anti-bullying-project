import copy

import pytest

from study2.common import PipelineError
from study2.matching import identity_evidence, link_records
from study2.parent_panel import build_parent_panel
from study2.respondents import adult_evidence
from test_identity_and_time import rec

POLICY = {"allow_one_digit_phone": True, "allow_school_transfer": True,
          "allow_contact_bridge_components": True, "allow_contact_subgroups": True}


def parent(sid, day=0, year=1980, **kw):
    row = rec(sid, day, "parent", **kw)
    row["answer"].update(adult_demographics_05=year)
    return row


def panel(rows, decisions=()):
    groups, _, _ = link_records(rows, decisions, POLICY)
    children = {sid: "child_" + group[0] for group in groups for sid in group}
    return build_parent_panel(rows, children, decisions, matching_policy=POLICY)


def adult_decision(a, b, action="UNLINK_ADULT"):
    return {"decision_id": "manual", "payload": {
        "action": action, "record_a": a["submission_id"], "record_b": b["submission_id"],
        "version_a": a["version_id"], "version_b": b["version_id"],
        "evidence_a": adult_evidence(a), "evidence_b": adult_evidence(b)}}


def test_parent_only_baseline_and_two_followup_branches_do_not_mutate_records():
    rows = [parent("mother0"), parent("mother1", 104), parent("father", 120, year=1977)]
    groups, _, _ = link_records(rows, [], POLICY)
    before = copy.deepcopy(rows)
    result = build_parent_panel(rows, {sid: "child" for sid in groups[0]}, matching_policy=POLICY)
    assert rows == before
    assert result.child_pairs[0]["t1"] == "father"
    assert result.adult_pairs[0]["t1"] == "mother1"
    assert result.child_pairs[0]["t0"] == result.adult_pairs[0]["t0"] == "mother0"
    assert result.summary()["same_adult_alternative_T1"] == 1


@pytest.mark.parametrize("day,expected", [(29, 0), (30, 0), (89, 0), (90, 1), (89.999, 0)])
def test_elapsed_90_day_boundary_and_baseline_protection(day, expected):
    result = panel([parent("first"), parent("later", day)])
    assert len(result.child_pairs) == len(result.adult_pairs) == expected
    assert result.baselines[0]["t0"] == "first"


@pytest.mark.parametrize("gap,repeated", [(29, True), (30, False)])
def test_only_same_adult_short_repeats_collapse_and_keep_original_rows(gap, repeated):
    result = panel([parent("first"), parent("p1", 90), parent("p2", 90 + gap)])
    assert result.child_pairs[0]["t1"] == "p2"
    assert next(r for r in result.audit if r["submission_id"] == "p1")["panel_status"] == (
        "short_repeat" if repeated else "extra_followup")
    assert len(result.audit) == 3
    changed = panel([parent("first"), parent("other", 90, year=1977), parent("last", 91)])
    assert not any(r["panel_status"] == "short_repeat" for r in changed.audit)


def test_one_digit_phone_is_child_link_but_only_experimental_adult_link():
    result = panel([parent("p0"), parent("p1", 90, phone_value="61234568")])
    assert len(result.child_pairs) == len(result.shadow_pairs) == 1
    assert result.adult_pairs == []
    assert result.summary()["experiment_added_children"] == 1
    assert result.comparisons[0]["one_digit_candidate"] is True
    assert all(c["kind"] == "identity" for c in result.guard_cases)


def test_other_caregiver_between_two_responses_does_not_hide_a_short_repeat():
    result = panel([parent('base'), parent('mother90', 90), parent('father95', 95, year=1977),
                    parent('mother100', 100)])
    audit = {r['submission_id']: r for r in result.audit}
    assert audit['mother90']['duplicate_of'] == 'mother100'
    assert audit['father95']['panel_status'] != 'short_repeat'


def test_siblings_and_school_only_coincidences_stay_separate():
    result = panel([parent("one"), parent("sibling", 90, dob="2013-02-02"),
                    parent("same_demo", 120, phone_value="69876543")])
    assert len(result.baselines) == 3
    assert result.child_pairs == result.adult_pairs == []


def test_exact_contact_transfer_and_multiple_contact_separators():
    rows = [parent("p0"), parent("p1", 90, school="Other School", phone_value="63456789")]
    rows[1]["answer"]["contact_02"] = "67777777；61234567 / alpha@example.org"
    # Existing child parser supports western separators; supply the shared
    # email in another column to establish the accepted transfer identity.
    rows[0]["answer"]["contact_03.1"] = "alpha@example.org"
    rows[1]["answer"]["contact_03.1"] = "alpha@example.org;beta@example.org"
    result = panel(rows)
    assert len(result.adult_pairs) == 1


def test_shared_contacts_different_years_and_unknown_years_keep_child_report():
    for year in [1979, "", 9999]:
        result = panel([parent("first"), parent("later", 90, year=year)])
        assert len(result.child_pairs) == 1
        assert result.adult_pairs == result.shadow_pairs == []


def test_different_child_sex_or_missing_contact_does_not_create_a_panel():
    for other in [parent('p1', 90, gender='1'), parent('p1', 90, phone_value='')]:
        assert panel([parent('p0'), other]).child_pairs == []


def test_experiment_does_not_accept_transpositions_insertions_or_approximate_emails():
    for contact in ['61234576', '612345678', 'alpha@example.org']:
        rows = [parent('p0'), parent('p1', 90, phone_value=contact)]
        result = build_parent_panel(rows, {'p0': 'reviewed_child', 'p1': 'reviewed_child'}, matching_policy=POLICY)
        assert result.adult_pairs == result.shadow_pairs == []


def test_manual_adult_unlink_and_reopened_evidence_are_not_bypassed():
    a, b = parent("p0"), parent("p1", 90)
    decision = adult_decision(a, b)
    assert panel([a, b], [decision]).adult_pairs == []
    a, b = parent("p0"), parent("p1", 90)
    decision = adult_decision(a, b, "LINK_ADULT")
    b["answer"]["adult_demographics_05"] = 1981
    result = panel([a, b], [decision])
    assert len(result.child_pairs) == 1
    assert result.adult_pairs == result.shadow_pairs == []


def test_manual_child_nonmatch_is_preserved():
    a, b = parent("p0"), parent("p1", 90)
    decision = {"decision_id": "manual", "payload": {
        "action": "UNLINK", "record_a": "p0", "record_b": "p1",
        "evidence_a": identity_evidence(a), "evidence_b": identity_evidence(b)}}
    assert panel([a, b], [decision]).child_pairs == []


def test_whole_adult_group_prevents_contact_chain_union():
    rows = [parent("p0"), parent("p1", 90), parent("p2", 130, phone_value="63456789")]
    rows[0]["answer"]["contact_02"] = "63456789"
    result = panel(rows)
    assert len(result.child_pairs) == 1
    assert result.adult_pairs == []
    assert all(r["exact_status"] == "pending" for r in result.comparisons)


def repeat_contact_bridge():
    rows = [parent('base'), parent('day90', 90), parent('day100', 100),
            parent('day130', 130, phone_value='63456789')]
    for row in (rows[0], rows[2]):
        row['answer']['contact_02'] = '63456789'
    return rows


def test_collapsed_missing_contact_does_not_add_a_new_pairwise_requirement():
    rows = repeat_contact_bridge()
    result = panel(rows)
    assert next(r for r in result.audit if r['submission_id'] == 'day90')['duplicate_of'] == 'day100'
    assert result.adult_pairs[0]['t1'] == 'day130'
    assert result.child_pairs[0]['t1'] == 'day130'
    # Existing retained-profile checks still apply; this fix does not relax them.
    rows[1]['manual_keep'] = True
    assert panel(rows).adult_pairs == []


def test_collapsed_manual_nonmatch_is_not_bypassed_by_a_contact_bridge():
    rows = repeat_contact_bridge()
    decision = adult_decision(rows[1], rows[3])
    before = copy.deepcopy((rows, decision))
    children = {r['submission_id']: 'confirmed_child' for r in rows}
    result = build_parent_panel(rows, children, [decision], matching_policy=POLICY)
    assert result.adult_pairs == result.shadow_pairs == []
    assert result.child_pairs[0]['t1'] == 'day130'
    assert next(r for r in result.audit if r['submission_id'] == 'day90')['duplicate_of'] == 'day100'
    assert all(r['exact_status'] == 'pending' for r in result.comparisons)
    assert (rows, decision) == before
    assert build_parent_panel(rows[::-1], children, [decision], matching_policy=POLICY) == result


def test_protected_baseline_repeat_cluster_preserves_manual_nonmatch():
    rows = [parent('base'), parent('early', 10), parent('later', 100)]
    result = panel(rows, [adult_decision(rows[1], rows[2])])
    assert next(r for r in result.audit if r['submission_id'] == 'early')['duplicate_of'] == 'base'
    assert result.adult_pairs == result.shadow_pairs == []
    assert result.child_pairs[0]['t1'] == 'later'
    assert result.comparisons[0]['exact_rule'] == 'collapsed_repeat_reviewer_rejected_same_adult'


def test_repeatedly_collapsed_cluster_keeps_oldest_manual_restriction():
    rows = [parent('base'), parent('day90', 90), parent('day100', 100),
            parent('day110', 110), parent('day140', 140)]
    result = panel(rows, [adult_decision(rows[1], rows[-1])])
    audit = {r['submission_id']: r for r in result.audit}
    assert audit['day90']['duplicate_of'] == audit['day100']['duplicate_of'] == 'day110'
    assert result.adult_pairs == result.shadow_pairs == []
    assert result.child_pairs[0]['t1'] == 'day140'


def test_pair_specific_year_exception_does_not_hide_collapsed_year_conflict():
    rows = [parent('base'), parent('day90', 90, year=1981), parent('day100', 100)]
    # Accepting this pair does not accept day90 as the same adult as the baseline.
    result = panel(rows, [adult_decision(rows[1], rows[2], 'LINK_ADULT')])
    assert next(r for r in result.audit if r['submission_id'] == 'day90')['duplicate_of'] == 'day100'
    assert result.adult_pairs == result.shadow_pairs == []
    assert result.child_pairs[0]['t1'] == 'day100'
    assert result.comparisons[0]['exact_rule'] == 'collapsed_repeat_reported_birth_year_changed'
    # A valid direct manual exception remains effective for its own pair.
    result = panel(rows[:2], [adult_decision(rows[0], rows[1], 'LINK_ADULT')])
    assert result.adult_pairs[0]['t1'] == 'day90'


def test_stale_manual_evidence_on_a_collapsed_member_holds_adult_followup():
    rows = [parent('base'), parent('early', 10), parent('later', 100)]
    decision = adult_decision(rows[1], rows[2])
    rows[1]['answer']['contact_02'] = '63456789'
    result = panel(rows, [decision])
    # A reopened decision prevents collapse itself, so it cannot disappear later.
    assert all(r['duplicate_of'] is None for r in result.audit)
    assert result.adult_pairs == result.shadow_pairs == []


def test_missing_dates_hold_both_branches_and_equal_latest_holds_only_affected_branch():
    missing = panel([parent("p0"), parent("undated", observed_at=None)])
    assert missing.baselines == []
    assert {r["panel_status"] for r in missing.audit} == {"pending_chronology"}
    result = panel([parent("p0"), parent("mother", 90), parent("father", 90, year=1977)])
    assert result.child_pairs == []
    assert result.adult_pairs[0]["t1"] == "mother"
    assert {r["child_report_issue"] for r in result.audit} == {"ambiguous_latest_timestamp"}
    equal = panel([parent("p0"), parent("p0b"), parent("later", 90)])
    assert equal.baselines == equal.child_pairs == equal.adult_pairs == []


def test_batch_creation_date_policy_and_manual_keep_are_respected():
    rows = [parent("p0", time_confidence="accepted_creation_time", date_basis="batch_assigned_creation"),
            parent("p1", 90), parent("p2", 91, manual_keep=True)]
    result = panel(rows)
    assert result.adult_pairs[0]["t1"] == "p2"
    assert not any(r["panel_status"] == "short_repeat" for r in result.audit)
    rows[0]["time_confidence"] = "batch_assigned"
    assert panel(rows).baselines == []


def test_shuffle_is_stable_and_excluded_rows_stay_in_audit():
    rows = [parent("p0"), parent("p1", 90), parent("p2", 180), parent("excluded", 2, status="incomplete")]
    left, right = panel(copy.deepcopy(rows)), panel(copy.deepcopy(rows[::-1]))
    assert left == right
    assert len(left.audit) == 4
    assert left.summary()["audit_status_counts"]["excluded_incomplete"] == 1
    with pytest.raises(PipelineError, match="positive"):
        build_parent_panel([], {}, followup_days=0)
