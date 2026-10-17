"""Adult continuity is separate from the child's identity and family waves."""
from collections import defaultdict
from datetime import timedelta

from .common import PipelineError, contacts, digest, phone, text, timestamp
from .matching import candidate, validate_manual_links


def _adult_evidence(r, *, legacy=False):
    answer = r.get("answer", {})
    if legacy:
        number = phone(answer.get("contact_02"))
        own = {number} if number else set()
    else:
        own = contacts({"contact_02": answer.get("contact_02")}, extended_separators=True)
    # Email field meaning is documented for these versions. Other old-system
    # contact extensions are not silently assumed to identify the respondent.
    label = r.get("source_label", text(answer.get("Survey")))
    if "qualtrics" in label or label.startswith(("paperform", "socialworkdream")):
        email_contacts = contacts(
            {"contact_03.1": answer.get("contact_03.1")}, extended_separators=not legacy,
        )
        own.update(value for value in email_contacts if "@" in value)
    evidence = {
        "birth_year": text(answer.get("adult_demographics_05")),
        "relationship": text(answer.get("adult_demographics_06")),
        "other_relationship": text(answer.get("adult_demographics_06.1")).lower(),
        "personal_contacts": sorted(own),
    }
    if not legacy:
        evidence['all_contacts'] = sorted(contacts(answer, extended_separators=True))
    return evidence


def adult_evidence(r):
    return _adult_evidence(r)


def adult_evidence_matches(r, saved, saved_version=None):
    if adult_evidence(r) == saved:
        return True
    # The former snapshot omitted general contacts and could not parse a list
    # in contact_02. Carry it only for the exact original source version and
    # an exactly reproducible old snapshot; never rewrite the original decision.
    return bool(isinstance(saved, dict) and 'all_contacts' not in saved and saved_version
                and r.get('version_id') == saved_version and _adult_evidence(r, legacy=True) == saved)


def adult_match(a, b, policy=None):
    """Check adult evidence only after both responses refer to the same child."""
    if (policy or {}).get('adult_contact_scope', 'any_exact') != 'any_exact':
        raise PipelineError('Unsupported adult contact scope; current research policy is any_exact')
    ea, eb = adult_evidence(a), adult_evidence(b)
    if a["role"] != "parent" or b["role"] != "parent":
        return "rejected", "not_two_parent_responses"
    if a.get('child_id') and b.get('child_id') and a['child_id'] != b['child_id']:
        return 'rejected', 'different_child_identity'
    years = [e["birth_year"] for e in [ea, eb]]
    from .common import utcnow
    maximum = min((timestamp(r.get("observed_at")) or timestamp(utcnow())).year for r in [a, b])
    if any(not y.isdigit() or len(y) != 4 or not 1900 <= int(y) <= maximum for y in years):
        return "pending", "adult_birth_year_missing_or_invalid"
    if ea["birth_year"] != eb["birth_year"]:
        return "rejected", "reported_birth_year_changed"
    if set(ea["personal_contacts"]) & set(eb["personal_contacts"]):
        return "confirmed", "same_adult_reported_birth_personal_contact"
    if set(ea['all_contacts']) & set(eb['all_contacts']):
        return 'confirmed', 'same_adult_reported_birth_any_exact_contact'
    return "pending", "no_exact_adult_contact"


def adult_decision_state(records, decisions):
    """One validation path for manual adult decisions in repeats and BD."""
    by_id = {r["submission_id"]: r for r in records}
    overrides, reopened, events = {}, set(), []
    exceptions = {}
    for d in decisions:
        p = d["payload"]
        if p["action"] not in {"LINK_ADULT", "UNLINK_ADULT"}:
            continue
        ids = [p["record_a"], p["record_b"]]
        valid = all(i in by_id and by_id[i]["role"] == "parent" and
                    adult_evidence_matches(by_id[i], p.get("evidence_" + suffix), p.get('version_' + suffix))
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
    return overrides, reopened, events, exceptions


def classify_adult(a, b, policy=None, state=None):
    """Apply unchanged manual decisions before considering automatic evidence."""
    overrides, reopened = state[:2] if state is not None else ({}, set())
    key = tuple(sorted([a['submission_id'], b['submission_id']]))
    if key in overrides:
        if overrides[key] == "LINK_ADULT":
            return "confirmed", "reviewer_confirmed_same_adult"
        return "rejected", "reviewer_rejected_same_adult"
    if reopened & set(key):
        return 'pending', 'adult_decision_reopened'
    return adult_match(a, b, policy)


def _consistent_adult_matches(baseline, matches, overrides, classify):
    """Keep reviewed pairs first and require pairwise adult consistency.

    An accepted typo belongs to its reviewed pair. It never grants a third
    adult profile the same exception through shared contact information.
    Candidate dictionaries are updated in place for the audit trail.
    """
    def profiles_conflict(profiles):
        return any(
            classify(left, right)[0] != "confirmed"
            for index, (left, _) in enumerate(profiles)
            for right, _ in profiles[index + 1:]
        )

    reviewed = [
        (record, case) for record, case in matches
        if overrides.get(tuple(sorted([baseline["submission_id"], record["submission_id"]])))
            == "LINK_ADULT"
    ]
    if not reviewed:
        if profiles_conflict(matches):
            for _, case in matches:
                case.update(status="pending", reason="Competing or contradictory adult profiles")
            return []
        return matches

    if profiles_conflict(reviewed):
        for _, case in matches:
            case.update(status="pending", reason="Competing or contradictory reviewed adult profiles")
        return []

    automatic = []
    for record, case in matches:
        if any(record is anchor for anchor, _ in reviewed):
            continue
        if all(classify(record, anchor)[0] == "confirmed" for anchor, _ in reviewed):
            automatic.append((record, case))
        else:
            case.update(
                status="pending", reason="Automatic adult candidate conflicts with an unchanged reviewed pair",
            )
    if profiles_conflict(automatic):
        for _, case in automatic:
            case.update(
                status="pending", reason="Competing automatic adult profiles; unchanged reviewed pair retained",
            )
        automatic = []
    return reviewed + automatic


def adult_followups(records, decisions, followup_days=90, policy=None, parent_wave_policy=None):
    """Same-child, same-birth-year, any-exact-contact adult followups.

    Relationship is retained as reported metadata, never a confirmation gate.
    Direct manual decisions and bounded birth-year exceptions retain priority.
    """
    from .parent_waves import validate_policy
    validate_policy(parent_wave_policy)
    parents = defaultdict(list)
    for r in records:
        if r['role'] == 'parent' and r.get('child_id') and r['status'] in {
                'eligible', 'short_repeat', 'short_interval_followup', 'extra_followup'}:
            parents[r['child_id']].append(r)
    state = adult_decision_state(records, decisions)
    overrides, _, events, exceptions = state
    pairs, cases = [], []
    def classify(a, b):
        return classify_adult(a, b, policy, state)

    for child, group in sorted(parents.items()):
        baseline = next((r for r in group if r.get("selected_wave") == "T0"), None)
        if baseline is None or not timestamp(baseline.get("observed_at")):
            continue
        matches = []
        for later in group:
            if later is baseline or not timestamp(later.get("observed_at")):
                continue
            if parent_wave_policy:
                if later.get('parent_phase') != 'T1' or later.get('wave_reason') == 'pending_chronology':
                    continue
            elif timestamp(later["observed_at"]) - timestamp(baseline["observed_at"]) < timedelta(days=followup_days):
                continue
            status, rule = classify(baseline, later)
            case = candidate(baseline, later, "respondent", rule, status,
                             "Same child; adult continuity requires a valid equal birth year and at least one exact phone/email across all contact fields")
            cases.append(case)
            if status == "confirmed":
                matches.append((later, case))
        matches = _consistent_adult_matches(baseline, matches, overrides, classify)
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
