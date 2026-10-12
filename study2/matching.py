"""Child identity evidence, conservative linking, and independent wave selection."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations, product

from .common import PipelineError, contacts, digest, fuzzy_phone, phone, text, timestamp


def identity_evidence(r: dict) -> dict:
    return {"school": r.get("school"), "dob": r.get("dob"), "gender": r.get("gender"),
            "grade": r.get("grade"), "roll": child_roll(r),
            "contacts": sorted(contacts(r["answer"])), "observed_at": r.get("observed_at")}


def child_roll(r: dict) -> str:
    return text(r["answer"].get("student_demographics_02" if r["role"] == "student" else "adult_demographics_02"))


def validate_manual_links(links, forbidden):
    parent = {}
    def find(s):
        parent.setdefault(s, s)
        while parent[s] != s:
            s = parent[s]
        return s
    for a, b in links:
        parent[find(a)] = find(b)
    if any(find(a) == find(b) for a, b in forbidden):
        raise PipelineError("Conflicting manual LINK/UNLINK instructions, including transitive links")


def candidate(a: dict, b: dict | None, kind: str, rule: str, status: str, reason: str) -> dict:
    from .review_hints import pair_review_hints
    ids = sorted([a["submission_id"], b["submission_id"]] if b else [a["submission_id"]])
    return {"case_id": "CASE_" + digest([kind, ids])[:28], "kind": kind,
            "record_a": ids[0], "record_b": ids[1] if len(ids) == 2 else "",
            "version_a": (a if ids[0] == a["submission_id"] else b)["version_id"],
            "version_b": (b if ids[0] == a["submission_id"] else a)["version_id"] if b else "",
            "rule": rule, "status": status, "reason": reason,
            **pair_review_hints(a, b)}


def hard_conflict(a: dict, b: dict) -> bool:
    if a.get("dob") and b.get("dob") and a["dob"] != b["dob"]:
        return True
    if a.get("gender") and b.get("gender") and a["gender"] != b["gender"]:
        return True
    # Same-school near-contemporaneous class conflicts are a twin/sibling warning.
    ta, tb = timestamp(a.get("observed_at")), timestamp(b.get("observed_at"))
    if a.get("school") and a["school"] == b.get("school") and ta and tb and abs((ta - tb).total_seconds()) < 30 * 86400:
        if a.get("grade") and b.get("grade") and a["grade"] != b["grade"]:
            return True
        if child_roll(a) and child_roll(b) and child_roll(a) != child_roll(b):
            return True
        if a["role"] == b["role"] == "student":
            ca = text(a["answer"].get("student_demographics_02"))
            cb = text(b["answer"].get("student_demographics_02"))
            if ca and cb and ca != cb:
                return True
    return False


def strict_evidence(a: dict, b: dict) -> bool:
    base = bool(a.get("school") and a["school"] == b.get("school") and
                a.get("dob") and a["dob"] == b.get("dob") and
                a.get("gender") and a["gender"] == b.get("gender") and
                a["contacts"] & b["contacts"] and not hard_conflict(a, b))
    if not base:
        return False
    ta, tb = timestamp(a.get("observed_at")), timestamp(b.get("observed_at"))
    contemporaneous = bool(ta and tb and abs((ta - tb).total_seconds()) < 30 * 86400)
    # Same-sex twins share all the base fields. Near-contemporaneous records
    # without a shared child class number need human evidence.
    if contemporaneous and a["role"] == b["role"] and (not child_roll(a) or child_roll(a) != child_roll(b)):
        return False
    return True


def one_digit_phone(a: str, b: str) -> bool:
    # Exactly one substitution in two valid eight-digit numbers. Transposed,
    # inserted, deleted digits and similar emails remain review-only.
    return bool(phone(a) and phone(b) and sum(x != y for x, y in zip(a, b)) == 1)


def automatic_rule(a: dict, b: dict, policy: dict | None = None) -> str | None:
    if strict_evidence(a, b):
        return "exact_school_contact_child_demo"
    policy = policy or {}
    if not (a.get("dob") and a["dob"] == b.get("dob") and a.get("gender") and
            a["gender"] == b.get("gender") and a.get("school") and b.get("school")) or hard_conflict(a, b):
        return None
    ta, tb = timestamp(a.get("observed_at")), timestamp(b.get("observed_at"))
    if a["role"] == b["role"] and ta and tb and abs((ta-tb).total_seconds()) < 30*86400:
        if not child_roll(a) or child_roll(a) != child_roll(b):
            return None
    if policy.get("allow_one_digit_phone") and a["school"] == b["school"] and any(
            one_digit_phone(x, y) for x in a["contacts"] for y in b["contacts"]):
        return "one_digit_phone_school_child_demo"
    if policy.get("allow_school_transfer") and a["school"] != b["school"] and a["contacts"] & b["contacts"]:
        return "exact_contact_school_transfer_child_demo"
    return None


def link_records(records: list[dict], decisions: list[dict], policy: dict | None = None) -> tuple[list[list[str]], list[dict], list[dict]]:
    by_id = {r["submission_id"]: r for r in records}
    for r in records:
        r["contacts"] = contacts(r["answer"])
    eligible = [r for r in records if r["status"] == "eligible"]
    parent = {r["submission_id"]: r["submission_id"] for r in eligible}
    members = {sid: {sid} for sid in parent}
    forbidden = set()
    applied = []
    manual_links = []
    overrides = {}
    reopened_ids = set()
    for d in decisions:
        p = d["payload"]
        if p["action"] in {"LINK_ADULT", "UNLINK_ADULT"}:
            continue  # Independent adult evidence is evaluated after child linkage.
        ids = [p["record_a"]] + ([p.get("record_b")] if p.get("record_b") else [])
        action = p["action"]
        changed = any(i not in by_id for i in ids)
        for i in ids:
            if i not in by_id:
                continue
            suffix = "a" if i == p["record_a"] else "b"
            evidence = p.get("evidence_" + suffix)
            same_evidence = evidence is not None and identity_evidence(by_id[i]) == evidence
            if action in {"LINK", "UNLINK"} and evidence is not None:
                changed |= not same_evidence
            else:
                changed |= by_id[i]["version_id"] != p.get("version_" + suffix)
        if changed:
            applied.append({"decision_id": d["decision_id"], "status": "reopened", "message": "Source changed or record is outside current batch"})
            reopened_ids.update(i for i in ids if i in by_id)
            continue
        if action in {"LINK", "UNLINK"}:
            pair = tuple(sorted(ids))
            if action == "UNLINK":
                forbidden.add(pair)
            else:
                manual_links.append(pair)
        else:
            overrides.setdefault(ids[0], {})[action] = p.get("value")
        applied.append({"decision_id": d["decision_id"], "status": "applied", "message": action})
    for sid, override in overrides.items():
        r = by_id[sid]
        if "EXCLUDE" in override:
            r["status"] = "manual_excluded"
        elif "KEEP" in override and r["status"] not in {"unrecognized_survey", "incomplete"}:
            r["status"] = "eligible"
            r["manual_keep"] = True
        if "SET_DATE" in override:
            r["observed_at"] = timestamp(override["SET_DATE"]).isoformat()
            r["time_confidence"] = "manual_verified"
    # Rebuild eligible membership after explicit keep/exclude.
    eligible = [r for r in records if r["status"] == "eligible"]
    parent = {r["submission_id"]: r["submission_id"] for r in eligible}
    members = {sid: {sid} for sid in parent}
    validate_manual_links(manual_links, forbidden)

    def find(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    def union(a, b, manual=False):
        if a not in parent or b not in parent:
            return False
        ra, rb = find(a), find(b)
        if ra == rb:
            return True
        cross = list(product(members[ra], members[rb]))
        if any(tuple(sorted(pair)) in forbidden for pair in cross):
            return False
        if not manual and (members[ra] | members[rb]) & reopened_ids:
            return False
        # Automatic evidence must be consistent for EVERY pair in a group,
        # preventing contact bridges and transitive demographic contradictions.
        if not manual and any(not automatic_rule(by_id[x], by_id[y], policy) for x, y in cross):
            return False
        keep, lose = sorted([ra, rb])
        parent[lose] = keep
        members[keep].update(members.pop(lose))
        return True

    for a, b in manual_links:
        if not union(a, b, manual=True):
            raise PipelineError("Manual LINK refers to an ineligible submission; resolve exclusion first")
    blocks = defaultdict(list)
    for r in eligible:
        if r.get("dob") and r.get("gender"):
            blocks[(r["dob"], r["gender"])].append(r)
    cases = {}
    strict_edges = []
    for block in blocks.values():
        if len(block) > 200:
            for r in block:
                c = candidate(r, None, "identity", "oversized_block", "pending", "Common DOB/gender block exceeds 200; no automatic linkage")
                cases[c["case_id"]] = c
            continue
        for a, b in combinations(block, 2):
            exact = bool(a["contacts"] & b["contacts"])
            same_school = bool(a.get("school") and a["school"] == b.get("school"))
            fuzzy = any(fuzzy_phone(x, y) for x in a["contacts"] for y in b["contacts"])
            if not (same_school or exact or fuzzy):
                continue
            kind = "family" if a["role"] != b["role"] else "identity"
            accepted = automatic_rule(a, b, policy)
            rule = accepted or (
                "fuzzy_contact_child_demo" if fuzzy else "school_child_demo" if same_school else "transfer_contact_child_demo")
            c = candidate(a, b, kind, rule, "pending", "Insufficient or non-unique identity evidence")
            cases[c["case_id"]] = c
            if accepted:
                strict_edges.append((a["submission_id"], b["submission_id"], c))
    contact_index = defaultdict(list)
    for r in eligible:
        for contact in r["contacts"]:
            contact_index[contact].append(r)
    for block in contact_index.values():
        if len(block) > 200:
            continue
        for a, b in combinations(block, 2):
            kind = "family" if a["role"] != b["role"] else "identity"
            c = candidate(a, b, kind, "contact_missing_or_conflicting_child_demo", "pending", "Shared contact alone cannot identify a child; possible sibling or data-entry error")
            cases.setdefault(c["case_id"], c)
    # Determine strict connected components before consuming any candidate. A
    # non-clique component stays pending in full rather than choosing its first edge.
    adjacency = defaultdict(set)
    for a, b, _ in strict_edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    visited, ambiguous_nodes = set(), set()
    for seed in sorted(adjacency):
        if seed in visited:
            continue
        stack, comp = [seed], set()
        while stack:
            node = stack.pop()
            if node in comp:
                continue
            comp.add(node)
            stack.extend(adjacency[node] - comp)
        visited.update(comp)
        if any(not automatic_rule(by_id[a], by_id[b], policy) for a, b in combinations(comp, 2)):
            ambiguous_nodes.update(comp)
    for a, b, c in sorted(strict_edges):
        if a not in ambiguous_nodes and b not in ambiguous_nodes and union(a, b):
            c.update(status="confirmed", reason="Unique consistent component under the research-approved rules")
        elif tuple(sorted([a, b])) in forbidden:
            c.update(status="rejected", reason="Research reviewer rejected this link")
        else:
            c["reason"] = "Competing or contradictory candidate component"
    for c in cases.values():
        a, b = c["record_a"], c["record_b"]
        if b and tuple(sorted([a, b])) in forbidden:
            c.update(status="rejected", reason="Manual unlink")
        elif b and a in parent and b in parent and find(a) == find(b):
            c.update(status="confirmed", reason="Confirmed child identity under accepted rules or manual decision")
    for a, b in manual_links:
        if a in parent and b in parent and find(a) == find(b):
            c = candidate(by_id[a], by_id[b], "family" if by_id[a]["role"] != by_id[b]["role"] else "identity", "manual_link", "confirmed", "Reviewer-confirmed child identity")
            cases[c["case_id"]] = c
    pending_ids = {sid for c in cases.values() if c["status"] == "pending" for sid in [c["record_a"], c["record_b"]] if sid}
    for r in eligible:
        r["identity_pending"] = r["submission_id"] in pending_ids
        if r["submission_id"] in reopened_ids:
            c = candidate(r, None, "identity", "manual_decision_reopened", "pending", "Changed evidence requires reviewer reconfirmation; automatic linkage blocked")
            cases[c["case_id"]] = c
            r["identity_pending"] = True
    case_members = {sid for c in cases.values() for sid in [c["record_a"], c["record_b"]] if sid}
    for r in eligible:
        if r["submission_id"] not in case_members:
            c = candidate(r, None, "identity", "unmatched", "unmatched", "No candidate identity evidence")
            cases[c["case_id"]] = c
    grouped = defaultdict(list)
    for sid in parent:
        grouped[find(sid)].append(sid)
    return [sorted(ids) for _, ids in sorted(grouped.items())], list(cases.values()), applied


def assign_children(db, run_id: str, groups: list[list[str]]) -> dict[str, str]:
    # Reuse prior published child anchors, unaffected by input order or new rows.
    previous = db.execute("SELECT i.submission_id,i.child_id,c.anchor_submission_id FROM identity_members i JOIN children c USING(child_id) JOIN releases r ON i.run_id=r.run_id JOIN publication p ON r.release_id=p.release_id").fetchall()
    prev = {r["submission_id"]: (r["child_id"], r["anchor_submission_id"]) for r in previous}
    result = {}
    used = set()
    for ids in groups:
        candidates = sorted({prev[s][0] for s in ids if s in prev and prev[s][1] in ids})
        child = next((c for c in candidates if c not in used), None)
        if child is None:
            child = "CHILD_" + digest(ids[0])[:24]
            from .common import utcnow
            db.execute("INSERT OR IGNORE INTO children VALUES(?,?,?)", (child, utcnow(), ids[0]))
        used.add(child)
        for sid in ids:
            result[sid] = child
            db.execute("INSERT INTO identity_members VALUES(?,?,?)", (run_id, sid, child))
    return result


def select_waves(records: list[dict], children: dict[str, str], duplicate_days: int = 30,
                 followup_days: int = 90, parent_requires_same_adult: bool = False,
                 matching_policy: dict | None = None) -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    cases = []
    for r in records:
        r["child_id"] = children.get(r["submission_id"])
        r["selected_wave"] = None
        if r["status"] == "eligible":
            groups[(r["child_id"], r["role"])].append(r)
    for (child, role), group in groups.items():
        def same_respondent(a, b):
            if role != "parent" or not parent_requires_same_adult:
                return True
            from .respondents import adult_match
            return adult_match(a, b, matching_policy)[0] == "confirmed"
        trusted = [r for r in group if timestamp(r.get("observed_at")) is not None and r["time_confidence"] in {"observed", "manual_verified", "accepted_creation_time"}]
        unknown = [r for r in group if r not in trusted]
        for r in unknown:
            cases.append(candidate(r, None, "date", "unreliable_date", "pending", "Batch/unknown date cannot establish submission order or 90-day interval"))
        # A single unknown-date response may be inferred T0, but never T1.
        if len(group) == 1 and unknown:
            r = group[0]
            r["selected_wave"] = "T0"
            r["wave_reason"] = "first_observed_T0_date_unverified"
            continue
        if unknown:
            # Any undated member may be earlier than the supposed baseline.
            for r in group:
                r["wave_reason"] = "pending_chronology"
            continue
        if len({r["observed_at"] for r in trusted}) != len(trusted):
            for r in group:
                r["wave_reason"] = "pending_chronology"
                cases.append(candidate(r, None, "date", "ambiguous_same_timestamp", "pending", "Equal observation timestamps cannot establish the earliest original response"))
            continue
        trusted.sort(key=lambda r: (timestamp(r["observed_at"]), r["submission_id"]))
        # Research instruction: the earliest eligible original observation is
        # T0. Later repeats must NEVER replace that baseline.
        baseline = trusted[0]
        baseline["selected_wave"] = "T0"
        baseline["wave_reason"] = "first_eligible_observation" if baseline["claimed_wave"] != "T1" else "first_T1_inferred_as_T0"
        kept = []
        for r in trusted[1:]:
            gap = timestamp(r["observed_at"]) - timestamp(baseline["observed_at"])
            if gap < timedelta(days=duplicate_days) and not r.get("manual_keep") and same_respondent(baseline, r):
                r["status"] = "short_repeat"
                r["duplicate_of"] = baseline["submission_id"]
                cases.append(candidate(baseline, r, "dedup", "baseline_preserved_under_30_days", "confirmed", "Earliest eligible T0 preserved; close later repeat retained in registry"))
                continue
            if gap < timedelta(days=followup_days):
                r["status"] = "short_interval_followup"
                continue
            while kept and same_respondent(kept[-1], r) and (timestamp(r["observed_at"]) - timestamp(kept[-1]["observed_at"])) < timedelta(days=duplicate_days):
                earlier = kept[-1]
                if earlier.get("manual_keep") or r.get("manual_keep"):
                    break
                earlier["status"] = "short_repeat"
                earlier["duplicate_of"] = r["submission_id"]
                cases.append(candidate(earlier, r, "dedup", "under_30_days", "confirmed", "Earlier close repeat retained in registry, excluded from wave selection"))
                kept.pop()
            kept.append(r)
        # Point every excluded duplicate at the final retained representative.
        by_id = {r["submission_id"]: r for r in group}
        for r in group:
            target = r.get("duplicate_of")
            while target and by_id[target].get("duplicate_of"):
                target = by_id[target]["duplicate_of"]
            if target:
                r["duplicate_of"] = target
        qualifying = kept
        if qualifying:
            followup = qualifying[-1]
            followup["selected_wave"] = "T1"
            followup["wave_reason"] = "latest_eligible_followup_at_least_90_days"
        for r in kept:
            if not r["selected_wave"]:
                r["status"] = "extra_followup" if r in qualifying else "short_interval_followup"
    return records, cases
