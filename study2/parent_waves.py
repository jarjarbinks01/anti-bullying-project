"""Parent measurements follow the confirmed student's waves, in Hong Kong days.

Identity and adult adjudications are independent of this measurement policy.
No original labels, timestamps or submission identifiers are rewritten.
"""
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from .common import PipelineError, timestamp

LEGACY_POLICY = "student_anchored_hk_v1"
POLICY = "student_anchored_hk_nearest_v2"
TRUSTED = {"observed", "manual_verified", "accepted_creation_time"}
FIELDS = ["parent_phase", "student_t0_id", "student_t1_id", "student_anchor_id",
          "student_anchor_at", "student_parent_calendar_gap_days", "student_parent_elapsed_gap_days",
          "parent_response_interval_days"]


def hk_day(value):
    dt = timestamp(value)
    return dt.astimezone(ZoneInfo("Asia/Hong_Kong")).date() if dt else None


def validate_policy(policy):
    if policy not in (None, LEGACY_POLICY, POLICY):
        raise PipelineError("Unsupported parent wave policy: " + str(policy))


def select_parent_waves(records, duplicate_days=30, matching_policy=None, adult_decisions=(), wave_policy=POLICY):
    from .matching import candidate
    from .respondents import adult_decision_state, classify_adult

    validate_policy(wave_policy)
    nearest_baseline = wave_policy == POLICY
    groups, students = defaultdict(list), {}
    for r in records:
        if r["role"] == "student" and r.get("selected_wave"):
            students[(r.get("child_id"), r["selected_wave"])] = r
        if r["role"] == "parent" and r["status"] == "eligible":
            groups[r.get("child_id")].append(r)
    cases = []
    adult_state = adult_decision_state(records, adult_decisions)
    for child, parents in sorted(groups.items()):
        s0, s1 = students.get((child, "T0")), students.get((child, "T1"))
        reliable_anchor = s0 and timestamp(s0.get("observed_at")) and s0.get("time_confidence") in TRUSTED
        d0 = hk_day(s0.get("observed_at")) if reliable_anchor else None
        d1 = hk_day(s1.get("observed_at")) if s1 else None
        phases = defaultdict(list)
        unknown = []
        for r in parents:
            r.update(parent_wave_policy=wave_policy, parent_phase="unanchored",
                     student_t0_id=s0["submission_id"] if s0 else None,
                     student_t1_id=s1["submission_id"] if s1 else None)
            if not d0:
                r["wave_reason"] = "parent_no_reliable_student_baseline"
                continue
            day = hk_day(r.get("observed_at"))
            if day is None or r.get("time_confidence") not in TRUSTED:
                r.update(parent_phase="date_unreliable", wave_reason="pending_chronology")
                unknown.append(r)
                cases.append(candidate(r, None, "date", "parent_unreliable_date", "pending",
                                       "Parent phase requires a reliable date and student baseline"))
                continue
            # The already agreed T1 reservation applies to all original labels.
            # v2 removes only the T0 lower bound, keeping v1 reproducible.
            phase = ("historical" if not nearest_baseline and day < d0
                     else "T1" if d1 and day >= d1 else "T0")
            anchor = s1 if phase == "T1" else s0
            r.update(parent_phase=phase, student_anchor_id=anchor["submission_id"],
                     student_anchor_at=anchor["observed_at"],
                     student_parent_calendar_gap_days=(day - hk_day(anchor["observed_at"])).days,
                     student_parent_elapsed_gap_days=(timestamp(r["observed_at"]) - timestamp(anchor["observed_at"])).total_seconds()/86400)
            if phase == "historical":
                r["wave_reason"] = "parent_before_student_baseline"
            else:
                phases[phase].append(r)
        # An undated parent could precede or compete with either selected parent
        # measurement. Preserve the conservative chronology hold, without touching AC.
        if unknown:
            for rs in phases.values():
                for r in rs:
                    r["wave_reason"] = "pending_chronology"
            continue
        for phase, rs in sorted(phases.items()):
            rs.sort(key=lambda r: (timestamp(r["observed_at"]), r["submission_id"]))
            if len({timestamp(r["observed_at"]) for r in rs}) != len(rs):
                for r in rs:
                    r["wave_reason"] = "pending_chronology"
                    cases.append(candidate(r, None, "date", "ambiguous_parent_phase_timestamp", "pending",
                                           "Equal parent timestamps within one student wave need adjudication"))
                continue
            if nearest_baseline and phase == "T0":
                distance = min(abs(timestamp(r['observed_at']) - timestamp(s0['observed_at'])) for r in rs)
                closest = [r for r in rs if abs(timestamp(r['observed_at']) - timestamp(s0['observed_at'])) == distance]
                if len(closest) != 1:
                    for r in rs:
                        r['wave_reason'] = 'pending_chronology'
                        cases.append(candidate(r, None, 'date', 'ambiguous_parent_baseline_distance', 'pending',
                                               'Two parent responses are equally close to student T0; do not select by source order'))
                    continue
                # Protect the measurement nearest to student baseline BEFORE
                # collapsing short repeats; an earlier/later repeat cannot displace it.
                anchor = closest[0]
                rs = [anchor] + [r for r in rs if r is not anchor]
            clusters = {r["submission_id"]: [r] for r in rs}

            def same_adult(a, b):
                return all(classify_adult(x, y, matching_policy, adult_state)[0] == "confirmed"
                           for x in clusters[a["submission_id"]] for y in clusters[b["submission_id"]])

            kept = []
            for r in rs:
                if phase == "T0" and kept:
                    first = kept[0]
                    gap = timestamp(r['observed_at']) - timestamp(first['observed_at'])
                    if nearest_baseline:
                        gap = abs(gap)
                    if (gap < timedelta(days=duplicate_days)
                            and not r.get("manual_keep") and same_adult(first, r)):
                        r.update(status="short_repeat", duplicate_of=first["submission_id"],
                                 wave_reason="parent_same_phase_short_repeat")
                        clusters[first["submission_id"]].extend(clusters[r["submission_id"]])
                        cases.append(candidate(first, r, "dedup", "parent_T0_nearest_preserved_under_30_days" if nearest_baseline else "parent_T0_preserved_under_30_days", "confirmed",
                                               "Same adult and same student T0 phase; selected parent baseline preserved"))
                        continue
                # Within the T1 phase only, close repeats retain the latest. Never
                # compare a T1 with the T0 phase, even when less than 30 days apart.
                while (kept and (phase == "T1" or len(kept) > 1) and same_adult(kept[-1], r)
                       and timestamp(r["observed_at"]) - timestamp(kept[-1]["observed_at"]) < timedelta(days=duplicate_days)):
                    earlier = kept[-1]
                    if earlier.get("manual_keep") or r.get("manual_keep"):
                        break
                    earlier.update(status="short_repeat", duplicate_of=r["submission_id"],
                                   wave_reason="parent_same_phase_short_repeat")
                    clusters[r["submission_id"]].extend(clusters[earlier["submission_id"]])
                    kept.pop()
                    cases.append(candidate(earlier, r, "dedup", "parent_" + phase + "_latest_under_30_days", "confirmed",
                                           "Same adult and same student wave; latest non-baseline repeat retained"))
                kept.append(r)
            selected = kept[0] if phase == "T0" else kept[-1]
            selected.update(selected_wave=phase, wave_reason="parent_nearest_student_T0" if phase == "T0"
                            else "parent_latest_student_T1_phase")
            for r in kept:
                if r is not selected:
                    r.update(status="extra_followup", wave_reason="parent_other_same_phase_response")
            by_id = {r["submission_id"]: r for r in rs}
            for r in rs:
                target = r.get("duplicate_of")
                while target and by_id[target].get("duplicate_of"):
                    target = by_id[target]["duplicate_of"]
                if target:
                    r["duplicate_of"] = target
        p0 = next((r for r in parents if r.get("selected_wave") == "T0"), None)
        if p0:
            for r in parents:
                if r.get("parent_phase") == "T1":
                    r["parent_response_interval_days"] = (timestamp(r["observed_at"]) - timestamp(p0["observed_at"])).total_seconds() / 86400
    return records, cases
