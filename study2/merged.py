"""Exact merged-row copies remain registered, with one analysis representative."""
from collections import defaultdict

from .matching import candidate
from .common import digest


def mark_exact_input_repeats(records):
    groups, cases = defaultdict(list), []
    for r in records:
        if r["source_kind"] == "merged":
            # A controlled correction must not be overwritten by copy handling.
            groups[(r["source_id"], r["raw_hash"], digest(r["answer"]))].append(r)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        eligible = [r for r in rows if r["status"] == "eligible"]
        if len(eligible) < 2:
            continue
        def registered_order(r):
            slot = r.get("source_key", "").rsplit(":", 1)[-1]
            return (int(slot) if slot.isdigit() else 0, r["submission_id"])
        first = min(eligible, key=registered_order)
        for r in eligible:
            if r is first:
                continue
            r.update(status="exact_input_repeat", duplicate_of=first["submission_id"])
            r["issues"].append("identical_complete_merged_row_copy")
            cases.append(candidate(first, r, "dedup", "exact_merged_row_copy", "confirmed",
                                   "Entire merged row including source label, dates and all answers is identical; retain one analysis representative and every original row"))
    return records, cases
