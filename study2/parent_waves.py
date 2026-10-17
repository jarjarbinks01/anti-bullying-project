"""Select parent measurements using the confirmed student's waves.

Identity and adult adjudications are independent of this measurement policy.
Hong Kong calendar dates determine phases; exact timestamps select the nearest
baseline and collapse repeats. Original labels, dates and IDs are never changed.
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
    """Return the Hong Kong calendar date, or None for an unusable timestamp."""
    observed = timestamp(value)
    return observed.astimezone(ZoneInfo("Asia/Hong_Kong")).date() if observed else None


def validate_policy(policy):
    if policy not in (None, LEGACY_POLICY, POLICY):
        raise PipelineError("Unsupported parent wave policy: " + str(policy))


def _parent_phase(day, baseline_day, followup_day, nearest_baseline):
    """Reserve T1 first, regardless of the parent's original survey label.

    Only the legacy policy excludes parent responses before student T0.
    """
    if not nearest_baseline and day < baseline_day:
        return "historical"
    if followup_day and day >= followup_day:
        return "T1"
    return "T0"


def _assign_parent_phases(parents, student_t0, student_t1, wave_policy, cases):
    """Annotate each response and collect dated candidates for each phase."""
    from .matching import candidate

    reliable_anchor = (
        student_t0
        and timestamp(student_t0.get("observed_at"))
        and student_t0.get("time_confidence") in TRUSTED
    )
    baseline_day = hk_day(student_t0.get("observed_at")) if reliable_anchor else None
    followup_day = hk_day(student_t1.get("observed_at")) if student_t1 else None
    phases = defaultdict(list)
    unknown = []
    for parent in parents:
        parent.update(
            parent_wave_policy=wave_policy,
            parent_phase="unanchored",
            student_t0_id=student_t0["submission_id"] if student_t0 else None,
            student_t1_id=student_t1["submission_id"] if student_t1 else None,
        )
        if not baseline_day:
            parent["wave_reason"] = "parent_no_reliable_student_baseline"
            continue
        day = hk_day(parent.get("observed_at"))
        if day is None or parent.get("time_confidence") not in TRUSTED:
            parent.update(parent_phase="date_unreliable", wave_reason="pending_chronology")
            unknown.append(parent)
            cases.append(candidate(
                parent, None, "date", "parent_unreliable_date", "pending",
                "Parent phase requires a reliable date and student baseline",
            ))
            continue
        phase = _parent_phase(day, baseline_day, followup_day, wave_policy == POLICY)
        anchor = student_t1 if phase == "T1" else student_t0
        elapsed = timestamp(parent["observed_at"]) - timestamp(anchor["observed_at"])
        parent.update(
            parent_phase=phase,
            student_anchor_id=anchor["submission_id"],
            student_anchor_at=anchor["observed_at"],
            student_parent_calendar_gap_days=(day - hk_day(anchor["observed_at"])).days,
            student_parent_elapsed_gap_days=elapsed.total_seconds() / 86400,
        )
        if phase == "historical":
            parent["wave_reason"] = "parent_before_student_baseline"
        else:
            phases[phase].append(parent)
    return phases, unknown


def _order_phase_responses(responses, phase, student_t0, nearest_baseline, cases):
    """Keep deterministic order, without resolving an ambiguous baseline by ID."""
    from .matching import candidate

    responses.sort(key=lambda record: (timestamp(record["observed_at"]), record["submission_id"]))
    if len({timestamp(record["observed_at"]) for record in responses}) != len(responses):
        for record in responses:
            record["wave_reason"] = "pending_chronology"
            cases.append(candidate(
                record, None, "date", "ambiguous_parent_phase_timestamp", "pending",
                "Equal parent timestamps within one student wave need adjudication",
            ))
        return None
    if not (nearest_baseline and phase == "T0"):
        return responses

    baseline_at = timestamp(student_t0["observed_at"])
    distance = min(abs(timestamp(record["observed_at"]) - baseline_at) for record in responses)
    closest = [record for record in responses
               if abs(timestamp(record["observed_at"]) - baseline_at) == distance]
    if len(closest) != 1:
        for record in responses:
            record["wave_reason"] = "pending_chronology"
            cases.append(candidate(
                record, None, "date", "ambiguous_parent_baseline_distance", "pending",
                "Two parent responses are equally close to student T0; do not select by source order",
            ))
        return None
    # Protect the nearest measurement before short-repeat collapse: a repeat
    # cannot displace the baseline even if it was submitted later.
    anchor = closest[0]
    return [anchor] + [record for record in responses if record is not anchor]


def _select_phase_response(responses, phase, duplicate_days, nearest_baseline,
                           matching_policy, adult_state, cases):
    """Collapse repeats within one phase, then select its baseline or latest T1.

    Adult contact overlap is not transitive. Compare every original member of
    both repeat clusters before collapsing them; never compare across phases.
    """
    from .matching import candidate
    from .respondents import classify_adult

    clusters = {record["submission_id"]: [record] for record in responses}

    def same_adult(left, right):
        return all(
            classify_adult(a, b, matching_policy, adult_state)[0] == "confirmed"
            for a in clusters[left["submission_id"]]
            for b in clusters[right["submission_id"]]
        )

    kept = []
    for record in responses:
        if phase == "T0" and kept:
            baseline = kept[0]
            gap = timestamp(record["observed_at"]) - timestamp(baseline["observed_at"])
            if nearest_baseline:
                gap = abs(gap)
            if (gap < timedelta(days=duplicate_days)
                    and not record.get("manual_keep") and same_adult(baseline, record)):
                record.update(
                    status="short_repeat", duplicate_of=baseline["submission_id"],
                    wave_reason="parent_same_phase_short_repeat",
                )
                clusters[baseline["submission_id"]].extend(clusters[record["submission_id"]])
                rule = ("parent_T0_nearest_preserved_under_30_days" if nearest_baseline
                        else "parent_T0_preserved_under_30_days")
                cases.append(candidate(
                    baseline, record, "dedup", rule, "confirmed",
                    "Same adult and same student T0 phase; selected parent baseline preserved",
                ))
                continue
        while (
            kept
            and (phase == "T1" or len(kept) > 1)
            and same_adult(kept[-1], record)
            and timestamp(record["observed_at"]) - timestamp(kept[-1]["observed_at"])
                < timedelta(days=duplicate_days)
        ):
            earlier = kept[-1]
            if earlier.get("manual_keep") or record.get("manual_keep"):
                break
            earlier.update(
                status="short_repeat", duplicate_of=record["submission_id"],
                wave_reason="parent_same_phase_short_repeat",
            )
            clusters[record["submission_id"]].extend(clusters[earlier["submission_id"]])
            kept.pop()
            cases.append(candidate(
                earlier, record, "dedup", "parent_" + phase + "_latest_under_30_days", "confirmed",
                "Same adult and same student wave; latest non-baseline repeat retained",
            ))
        kept.append(record)

    selected = kept[0] if phase == "T0" else kept[-1]
    selected.update(
        selected_wave=phase,
        wave_reason="parent_nearest_student_T0" if phase == "T0" else "parent_latest_student_T1_phase",
    )
    for record in kept:
        if record is not selected:
            record.update(status="extra_followup", wave_reason="parent_other_same_phase_response")
    by_id = {record["submission_id"]: record for record in responses}
    for record in responses:
        target = record.get("duplicate_of")
        while target and by_id[target].get("duplicate_of"):
            target = by_id[target]["duplicate_of"]
        if target:
            record["duplicate_of"] = target


def select_parent_waves(records, duplicate_days=30, matching_policy=None, adult_decisions=(), wave_policy=POLICY):
    """Assign phases, hold ambiguous dates, collapse repeats and select parents.

    Mutates the supplied records and returns them with auditable candidate cases.
    Student selections and identity membership are not changed here.
    """
    from .respondents import adult_decision_state

    validate_policy(wave_policy)
    nearest_baseline = wave_policy == POLICY
    parents_by_child, students = defaultdict(list), {}
    for record in records:
        if record["role"] == "student" and record.get("selected_wave"):
            students[(record.get("child_id"), record["selected_wave"])] = record
        if record["role"] == "parent" and record["status"] == "eligible":
            parents_by_child[record.get("child_id")].append(record)
    cases = []
    adult_state = adult_decision_state(records, adult_decisions)
    for child_id, parents in sorted(parents_by_child.items()):
        student_t0 = students.get((child_id, "T0"))
        student_t1 = students.get((child_id, "T1"))
        phases, unknown = _assign_parent_phases(parents, student_t0, student_t1, wave_policy, cases)
        # An undated parent might compete with either measurement. Hold all
        # parent selections for this child without affecting student AC.
        if unknown:
            for responses in phases.values():
                for record in responses:
                    record["wave_reason"] = "pending_chronology"
            continue
        for phase, responses in sorted(phases.items()):
            ordered = _order_phase_responses(responses, phase, student_t0, nearest_baseline, cases)
            if ordered is not None:
                _select_phase_response(
                    ordered, phase, duplicate_days, nearest_baseline, matching_policy, adult_state, cases,
                )
        parent_t0 = next((record for record in parents if record.get("selected_wave") == "T0"), None)
        if parent_t0:
            for record in parents:
                if record.get("parent_phase") == "T1":
                    elapsed = timestamp(record["observed_at"]) - timestamp(parent_t0["observed_at"])
                    record["parent_response_interval_days"] = elapsed.total_seconds() / 86400
    return records, cases
