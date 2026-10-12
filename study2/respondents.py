"""Adult continuity is separate from the child's identity and family waves."""
from collections import defaultdict
from datetime import timedelta

from .common import PipelineError, contacts, digest, phone, text, timestamp
from .matching import candidate, validate_manual_links


def adult_evidence(r):
    answer = r.get("answer", {})
    own = set()
    number = phone(answer.get("contact_02"))
    if number:
        own.add(number)
    # Email field meaning is documented for these versions. Other old-system
    # contact extensions are not silently assumed to identify the respondent.
    label = r.get("source_label", text(answer.get("Survey")))
    if "qualtrics" in label or label.startswith(("paperform", "socialworkdream")):
        own.update(x for x in contacts({"contact_03.1": answer.get("contact_03.1")}) if "@" in x)
    return {"birth_year": text(answer.get("adult_demographics_05")),
            "relationship": text(answer.get("adult_demographics_06")),
            "other_relationship": text(answer.get("adult_demographics_06.1")).lower(),
            "personal_contacts": sorted(own)}


def adult_match(a, b, policy=None):
    ea, eb = adult_evidence(a), adult_evidence(b)
    if a["role"] != "parent" or b["role"] != "parent":
        return "rejected", "not_two_parent_responses"
    if ea["relationship"] in {"0", "1", "2"} and eb["relationship"] in {"0", "1", "2"} and ea["relationship"] != eb["relationship"]:
        return "rejected", "reported_relationship_changed"
    years = [e["birth_year"] for e in [ea, eb]]
    from .common import utcnow
    maximum = min((timestamp(r.get("observed_at")) or timestamp(utcnow())).year for r in [a, b])
    if any(not y.isdigit() or len(y) != 4 or not 1900 <= int(y) <= maximum for y in years):
        return "pending", "adult_birth_year_missing_or_invalid"
    if ea["birth_year"] != eb["birth_year"]:
        return "rejected", "reported_birth_year_changed"
    if ea["relationship"] not in {"0", "1", "2"} or eb["relationship"] not in {"0", "1", "2"}:
        return "pending", "adult_relationship_missing_or_invalid"
    if ea["relationship"] != eb["relationship"]:
        return "rejected", "reported_relationship_changed"
    if ea["relationship"] == "2":
        if not ea["other_relationship"] or not eb["other_relationship"]:
            return "pending", "adult_other_relationship_unspecified"
        if ea["other_relationship"] != eb["other_relationship"]:
            return "rejected", "reported_other_relationship_changed"
    if set(ea["personal_contacts"]) & set(eb["personal_contacts"]):
        return "confirmed", "same_adult_reported_birth_relationship_personal_contact"
    # Research-approved fallback: at least one response has no usable personal
    # contact. Different, present personal contacts are not treated as omission.
    if ((policy or {}).get("allow_exact_general_contact_when_personal_missing") and
            (not ea["personal_contacts"] or not eb["personal_contacts"]) and
            contacts(a["answer"]) & contacts(b["answer"])):
        return "confirmed", "same_adult_reported_birth_relationship_general_contact_fallback"
    return "pending", "no_exact_personal_adult_contact"


def adult_followups(records, decisions, followup_days=90, policy=None):
    """Baseline caregiver's latest eligible followup, independent of family F.

    This retains a mother's eligible followup even when a later father response
    is selected for the child's family-wave view. BD never uses the child's
    shared phone alone as evidence of the adult's identity. A policy-approved
    exact general contact may support matching when personal contact is missing,
    provided the child's identity and the other adult checks already agree.
    """
    by_id = {r["submission_id"]: r for r in records}
    parents = defaultdict(list)
    for r in records:
        if r["role"] == "parent" and r.get("child_id") and r["status"] in {
                "eligible", "short_repeat", "short_interval_followup", "extra_followup"}:
            parents[r["child_id"]].append(r)
    overrides, reopened, events, pairs, cases = {}, set(), [], [], []
    exceptions = {}
    for d in decisions:
        p = d["payload"]
        if p["action"] not in {"LINK_ADULT", "UNLINK_ADULT"}:
            continue
        ids = [p["record_a"], p["record_b"]]
        valid = all(i in by_id and by_id[i]["role"] == "parent" and
                    adult_evidence(by_id[i]) == p.get("evidence_" + suffix)
                    for suffix, i in zip(["a", "b"], ids))
        valid &= all(i in by_id and by_id[i].get("child_id") for i in ids)
        if valid:
            valid &= by_id[ids[0]]["child_id"] == by_id[ids[1]]["child_id"]
        exception = p.get("adult_identity_exception")
        if exception:
            valid &= all(i in by_id and by_id[i].get("child_id") == exception.get("child_id") for i in ids)
        events.append({"decision_id": d["decision_id"], "status": "applied" if valid else "reopened",
                       "message": p["action"] if valid else "Adult evidence or child assignment changed"})
        if valid:
            overrides[tuple(sorted(ids))] = p["action"]
            if exception:
                exceptions[tuple(sorted(ids))] = exception
                for sid in ids:
                    by_id[sid]["adult_identity_exception"] = exception
                    if exception["type"] == "accepted_typo_unknown_year":
                        by_id[sid]["adult_birth_year_status"] = "unconfirmed"
        else:
            reopened.update(ids)
    validate_manual_links([p for p, v in overrides.items() if v == "LINK_ADULT"],
                          [p for p, v in overrides.items() if v == "UNLINK_ADULT"])

    def classify(a, b):
        key = tuple(sorted([a["submission_id"], b["submission_id"]]))
        if key in overrides:
            return ("confirmed", "reviewer_confirmed_same_adult") if overrides[key] == "LINK_ADULT" else ("rejected", "reviewer_rejected_same_adult")
        if reopened & set(key):
            return "pending", "adult_decision_reopened"
        return adult_match(a, b, policy)

    for child, group in sorted(parents.items()):
        baseline = next((r for r in group if r.get("selected_wave") == "T0"), None)
        if baseline is None or not timestamp(baseline.get("observed_at")):
            continue
        matches = []
        for later in group:
            if later is baseline or not timestamp(later.get("observed_at")):
                continue
            if timestamp(later["observed_at"]) - timestamp(baseline["observed_at"]) < timedelta(days=followup_days):
                continue
            status, rule = classify(baseline, later)
            case = candidate(baseline, later, "respondent", rule, status,
                             "Same child; adult continuity requires adult birth year, relationship and approved contact evidence")
            cases.append(case)
            if status == "confirmed":
                matches.append((later, case))
        # Unchanged explicit reviewer decisions take priority over new automatic
        # candidates. A direct typo exception does not waive a third profile's
        # conflict: that extra candidate remains pending rather than cancelling
        # the reviewed pair or inheriting the exception transitively.
        reviewed = [(r, c) for r, c in matches if overrides.get(tuple(sorted(
            [baseline["submission_id"], r["submission_id"]]))) == "LINK_ADULT"]
        if reviewed:
            if any(classify(a, b)[0] != "confirmed" for i, (a, _) in enumerate(reviewed)
                   for b, _ in reviewed[i+1:]):
                for _, case in matches:
                    case.update(status="pending", reason="Competing or contradictory reviewed adult profiles")
                continue
            automatic = []
            for r, case in matches:
                if any(r is anchor for anchor, _ in reviewed):
                    continue
                if all(classify(r, anchor)[0] == "confirmed" for anchor, _ in reviewed):
                    automatic.append((r, case))
                else:
                    case.update(status="pending", reason="Automatic adult candidate conflicts with an unchanged reviewed pair")
            if any(classify(a, b)[0] != "confirmed" for i, (a, _) in enumerate(automatic)
                   for b, _ in automatic[i+1:]):
                for _, case in automatic:
                    case.update(status="pending", reason="Competing automatic adult profiles; unchanged reviewed pair retained")
                automatic = []
            matches = reviewed + automatic
        elif any(classify(a, b)[0] != "confirmed" for i, (a, _) in enumerate(matches)
                 for b, _ in matches[i+1:]):
            for _, case in matches:
                case.update(status="pending", reason="Competing or contradictory adult profiles")
            continue
        if matches:
            latest_time = max(timestamp(r["observed_at"]) for r, _ in matches)
            latest = [(r, c) for r, c in matches if timestamp(r["observed_at"]) == latest_time]
            if len(latest) != 1:
                for _, case in latest:
                    case.update(status="pending", reason="Equal timestamps cannot select a unique adult T1")
                continue
            later, case = latest[0]
            respondent_id = "ADULT_" + digest([child, baseline["submission_id"]])[:24]
            for record, wave in [(baseline, "T0"), (later, "T1")]:
                record.update(bd_selected_wave=wave, respondent_id=respondent_id, bd_match_rule=case["rule"])
            selected = exceptions.get(tuple(sorted([baseline["submission_id"], later["submission_id"]])))
            if selected:
                for record in (baseline, later):
                    record["adult_identity_exception"] = selected
                    if selected["type"] == "accepted_typo_unknown_year":
                        record["adult_birth_year_status"] = "unconfirmed"
            pairs.append({"child_id": child, "respondent_id": respondent_id,
                          "t0": baseline["submission_id"], "t1": later["submission_id"],
                          "rule": case["rule"], "status": "confirmed",
                          **({"adult_identity_exception": selected} if selected else {})})
    return pairs, cases, events
