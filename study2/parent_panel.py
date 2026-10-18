"""Independent parent measurements, derived without changing family selections.

Child membership comes from the existing, reviewed identity graph. Only the
measurement clock is independent: each child's earliest eligible parent is the
shared baseline. Adult continuity is checked separately and is not transitive.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta

from .common import PipelineError, text, timestamp
from .matching import candidate, one_digit_phone
from .parent_waves import TRUSTED
from .respondents import (adult_decision_state, adult_evidence, classify_adult,
                          _consistent_adult_matches)

POLICY = "independent_parent_earliest_90d_v1"
CHILD = "child_report"
ADULT = "same_adult"
SHADOW = "one_digit_experiment"
BRANCH_NAMES = {
    CHILD: "同一孩子，填卷人可不同",
    ADULT: "同一孩子、同一成人",
}


@dataclass
class ParentPanel:
    baselines: list[dict]
    child_pairs: list[dict]
    adult_pairs: list[dict]
    shadow_pairs: list[dict]
    audit: list[dict]
    comparisons: list[dict]
    guard_cases: list[dict]
    duplicate_days: int
    followup_days: int

    def summary(self):
        exact = {p["child_id"]: p for p in self.adult_pairs}
        shadow = {p["child_id"]: p for p in self.shadow_pairs}
        return {
            "policy": POLICY, "duplicate_days": self.duplicate_days,
            "minimum_followup_days": self.followup_days,
            "parent_submissions": len(self.audit), "baselines": len(self.baselines),
            "child_report_pairs": len(self.child_pairs), "same_adult_pairs": len(exact),
            "same_adult_alternative_T1": sum(p["different_child_report_T1"] for p in self.adult_pairs),
            "audit_status_counts": dict(Counter(r["panel_status"] for r in self.audit)),
            "adult_comparison_counts": dict(Counter(r["exact_status"] for r in self.comparisons)),
            "one_digit_candidates": sum(r["one_digit_candidate"] for r in self.comparisons),
            "experiment_pairs": len(shadow),
            "experiment_overlap_children": len(exact.keys() & shadow.keys()),
            "experiment_added_children": len(shadow.keys() - exact.keys()),
            "experiment_held_exact_children": len(exact.keys() - shadow.keys()),
            "experiment_changed_T1": sum(exact[c]["t1"] != shadow[c]["t1"]
                                         for c in exact.keys() & shadow.keys()),
            "verification": "Rule agreement and review labels, not measured matching accuracy",
        }


def _complete_child_profiles(rows):
    try:
        complete = all(date.fromisoformat(text(r.get("dob")))
                       and text(r.get("gender")) in {"0", "1"} and r.get("school") for r in rows)
    except ValueError:
        return False
    return complete and len({r["dob"] for r in rows}) == len({r["gender"] for r in rows}) == 1


def _one_digit_adult(a, b, state, policy):
    """A shadow candidate cannot override a manual restriction or changed year."""
    status, reason = classify_adult(a, b, policy, state)
    if status == "confirmed":
        return status, reason
    if reason != "no_exact_adult_contact":
        return status, reason
    # classify_adult already requires valid, equal birth years and one child.
    ea, eb = adult_evidence(a), adult_evidence(b)
    if any(one_digit_phone(x, y) for x in ea["all_contacts"] for y in eb["all_contacts"]):
        return "confirmed", "experimental_adult_one_digit_phone"
    return status, reason


def _collapse_repeats(rows, baseline, classify, audit, duplicate_days):
    """Collapse only confirmed adult cliques; protect the earliest baseline."""
    kept, clusters = [], {}
    for row in rows:
        sid = row["submission_id"]
        clusters[sid] = [row]
        compatible = []
        if not row.get('manual_keep'):
            for earlier in kept:
                gap = timestamp(row['observed_at']) - timestamp(earlier['observed_at'])
                # Equal timestamps are competing measurements, never broken by ID.
                if (timedelta(0) < gap < timedelta(days=duplicate_days)
                        and not earlier.get('manual_keep')
                        and all(classify(a, row)[0] == 'confirmed'
                                for a in clusters[earlier['submission_id']])):
                    compatible.append(earlier)
        all_members = [row] + [r for previous in compatible for r in clusters[previous['submission_id']]]
        clique = all(classify(a, b)[0] == 'confirmed' for i, a in enumerate(all_members)
                     for b in all_members[i + 1:])
        if compatible and clique:
            representative = baseline if any(r is baseline for r in compatible) else row
            target = representative['submission_id']
            clusters[target] = all_members
            for previous in compatible + [row]:
                if previous is not representative:
                    audit[previous['submission_id']].update(panel_status='short_repeat', duplicate_of=target)
            kept = [r for r in kept if not any(r is old for old in compatible) or r is representative]
            if representative is row:
                kept.append(row)
        else:
            kept.append(row)
    for item in audit.values():
        target = item.get("duplicate_of")
        while target and audit[target].get("duplicate_of"):
            target = audit[target]["duplicate_of"]
        if target:
            item["duplicate_of"] = target
    return kept


def _unique_latest(rows):
    if not rows:
        return None, "no_eligible_followup"
    latest = max(timestamp(r["observed_at"]) for r in rows)
    winners = [r for r in rows if timestamp(r["observed_at"]) == latest]
    return (winners[0], "selected") if len(winners) == 1 else (None, "ambiguous_latest_timestamp")


def build_parent_panel(records, children, decisions=(), *, matching_policy=None,
                       duplicate_days=30, followup_days=90):
    """Run on pre-wave eligible records. Never mutate records or decisions.

    Existing confirmed child subgroups remain independent even when their wider
    review scope is unresolved. This function never discovers or merges children.
    """
    if duplicate_days <= 0 or followup_days <= 0:
        raise PipelineError("Independent parent intervals must be positive")
    parents = deepcopy([r for r in records if r["role"] == "parent"])
    for r in parents:
        r["child_id"] = children.get(r["submission_id"])
    state = adult_decision_state(parents, decisions)
    classify = lambda a, b: classify_adult(a, b, matching_policy, state)
    shadow_classify = lambda a, b: _one_digit_adult(a, b, state, matching_policy)
    audit, groups = {}, defaultdict(list)
    for r in parents:
        sid = r["submission_id"]
        audit[sid] = {"submission_id": sid, "child_id": r["child_id"], "version_id": r.get("version_id"),
                      "input_status": r["status"], "panel_status": "excluded_" + r["status"],
                      "duplicate_of": None, "t0_id": None, "child_report_T1_id": None,
                      "same_adult_T1_id": None, "child_report_issue": None, "same_adult_issue": None}
        if r["status"] == "eligible" and r["child_id"]:
            groups[r["child_id"]].append(r)
            audit[sid]["panel_status"] = "eligible"
    baselines, child_pairs, adult_pairs, shadow_pairs, comparisons, guard_cases = [], [], [], [], [], []
    for child, rows in sorted(groups.items()):
        if not _complete_child_profiles(rows):
            for r in rows:
                audit[r["submission_id"]]["panel_status"] = "child_identity_incomplete_or_conflicting"
            continue
        unknown = [r for r in rows if not timestamp(r.get("observed_at"))
                   or r.get("time_confidence") not in TRUSTED]
        if unknown:
            for r in rows:
                audit[r["submission_id"]]["panel_status"] = "pending_chronology"
            continue
        rows.sort(key=lambda r: (timestamp(r["observed_at"]), r["submission_id"]))
        baseline = rows[0]
        if sum(timestamp(r["observed_at"]) == timestamp(baseline["observed_at"]) for r in rows) != 1:
            for r in rows:
                audit[r["submission_id"]]["panel_status"] = "ambiguous_baseline_timestamp"
            continue
        baselines.append({"child_id": child, "t0": baseline["submission_id"]})
        kept = _collapse_repeats(rows, baseline, classify, audit, duplicate_days)
        eligible = [r for r in kept if timestamp(r["observed_at"]) - timestamp(baseline["observed_at"])
                    >= timedelta(days=followup_days)]
        general, general_issue = _unique_latest(eligible)
        if general:
            child_pairs.append({"child_id": child, "t0": baseline["submission_id"], "t1": general["submission_id"]})
            guard_cases.append(candidate(baseline, general, "identity", "independent_parent_confirmed_child_group",
                                         "confirmed", "Existing confirmed child membership; independent parent waves"))
        exact_matches, experiment_matches, case_rows = [], [], {}
        for later in eligible:
            status, rule = classify(baseline, later)
            exp_status, exp_rule = shadow_classify(baseline, later)
            case = candidate(baseline, later, "respondent", rule, status, "Independent parent adult continuity")
            experiment = dict(case, status=exp_status, rule=exp_rule)
            if status == "confirmed":
                exact_matches.append((later, case))
            if exp_status == "confirmed":
                experiment_matches.append((later, experiment))
            item = {"case_id": case["case_id"], "child_id": child,
                    "t0": baseline["submission_id"], "t1": later["submission_id"],
                    "exact_status": status, "exact_rule": rule, "experiment_status": exp_status,
                    "experiment_rule": exp_rule, "one_digit_candidate": exp_rule == "experimental_adult_one_digit_phone"}
            comparisons.append(item)
            case_rows[later["submission_id"]] = (item, case, experiment)
        exact_matches = _consistent_adult_matches(baseline, exact_matches, state[0], classify)
        experiment_matches = _consistent_adult_matches(baseline, experiment_matches, state[0], shadow_classify)
        adult, adult_issue = _unique_latest([r for r, _ in exact_matches])
        if eligible and not exact_matches:
            adult_issue = "adult_identity_unconfirmed_or_conflicting"
        experimental, experiment_issue = _unique_latest([r for r, _ in experiment_matches])
        for item, case, experiment in case_rows.values():
            item.update(exact_status=case["status"], experiment_status=experiment["status"],
                        exact_reason=case["reason"], experiment_reason=experiment["reason"],
                        experiment_selection_issue=experiment_issue)
            # Reuse the existing NONMATCH publication guard, separately from
            # the family candidate queue. Experimental links are never guards.
            if adult and item["t1"] == adult["submission_id"]:
                guard_cases.append(case)
        if adult:
            case = case_rows[adult["submission_id"]][1]
            adult_pairs.append({"child_id": child, "t0": baseline["submission_id"], "t1": adult["submission_id"],
                                "rule": case["rule"], "case_id": case["case_id"],
                                "different_child_report_T1": bool(general and general["submission_id"] != adult["submission_id"])})
        if experimental:
            exp = case_rows[experimental["submission_id"]][2]
            shadow_pairs.append({"child_id": child, "t0": baseline["submission_id"], "t1": experimental["submission_id"],
                                 "rule": exp["rule"], "experimental_only": True})
        for r in rows:
            item = audit[r["submission_id"]]
            item.update(t0_id=baseline["submission_id"],
                        child_report_T1_id=general["submission_id"] if general else None,
                        same_adult_T1_id=adult["submission_id"] if adult else None,
                        child_report_issue=general_issue, same_adult_issue=adult_issue)
            if r is baseline:
                item["panel_status"] = "baseline"
            elif item["panel_status"] != "short_repeat":
                item["panel_status"] = ("followup_selected" if r is general or r is adult else
                                        "extra_followup" if r in eligible else "under_90_days")
    return ParentPanel(baselines, child_pairs, adult_pairs, shadow_pairs,
                       [audit[sid] for sid in sorted(audit)], comparisons, guard_cases,
                       duplicate_days, followup_days)
