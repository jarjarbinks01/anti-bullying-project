"""Informational review hints; never identity decisions or exclusion rules."""
from zoneinfo import ZoneInfo

from .common import text, timestamp

HK = ZoneInfo("Asia/Hong_Kong")


def grade_position(record):
    """P1-P6 -> 1-6; S1-S6 -> 7-12. Do not guess a mixed school's stage."""
    grade = record.get("grade")
    if grade not in range(1, 7):
        return None, None
    raw = text(record.get("grade_raw")).upper()
    explicit = ("primary" if raw.startswith(("PRIMARY", "P", "小")) else
                "secondary" if raw.startswith(("SECONDARY", "FORM", "S", "F", "中")) else None)
    school = text(record.get("school_type") or record.get("answer", {}).get("school_type")).lower()
    stage = explicit or (school if school in {"primary", "secondary"} else None)
    return (int(grade) + (6 if stage == "secondary" else 0), stage) if stage else (None, None)


def pair_review_hints(a, b=None):
    hints = {}
    rows = [a] + ([b] if b else [])
    times = [timestamp(r.get("observed_at")) for r in rows]
    if any(t is None for t in times):
        hints["observation_date_missing"] = "建立時間缺失或無法解讀；年級先後次序需核實。"
    if any(r.get("date_basis") == "batch_assigned_creation" for r in rows):
        hints["batch_date_basis"] = "日期包含批次指定建立時間；時間及年級提示須連同日期來源核實。"
    for r in rows:
        _, stage = grade_position(r)
        school = text(r.get("school_type") or r.get("answer", {}).get("school_type")).lower()
        if stage and school in {"primary", "secondary"} and stage != school:
            hints["school_grade_stage_disagrees"] = "原填年級階段與校名字典的小學／中學分類不同，請核實。"
        elif r.get("grade") in range(1, 7) and school == "primary & secondary" and stage is None:
            hints["grade_stage_unclear"] = "學校兼有小學及中學；原填數字年級未能確認階段。"
    if b and all(times):
        first, later = sorted(rows, key=lambda r: timestamp(r["observed_at"]))
        g0, _ = grade_position(first)
        g1, _ = grade_position(later)
        if g0 is not None and g1 is not None:
            def academic_year(r):
                t = timestamp(r["observed_at"]).astimezone(HK)
                return t.year if t.month >= 9 else t.year - 1
            elapsed = academic_year(later) - academic_year(first)
            change = g1 - g0
            if change < 0:
                hints["grade_decreased"] = "按建立時間排序，較後回應年級下降；請核實留級、轉制或填寫錯誤。"
            elif change > elapsed:
                hints["grade_advance_exceeds_school_years"] = f"兩份建立時間跨 {elapsed} 個學年，年級上升 {change} 級；請核實日期及年級。"
            elif elapsed > 0 and change == 0:
                hints["grade_unchanged_across_school_years"] = f"建立時間跨 {elapsed} 個學年，但年級未變；請核實留級或填寫時間。"
    return {"review_warning_codes": sorted(hints),
            "review_warnings": [hints[k] for k in sorted(hints)]}
