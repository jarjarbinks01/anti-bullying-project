"""Read-only sample views from published analysis membership, never candidates."""
from __future__ import annotations

import pandas as pd

from .common import PipelineError

SAMPLE_NAMES = {
    "AC": "AC｜學生 T0／T1",
    "BD": "BD｜同一成人 T0／T1",
    "E": "E｜T0 親子",
    "F": "F｜T1 親子",
    "EF": "EF｜兩輪親子（四份回應）",
    "parent_child_longitudinal": "同一孩子的家長 T0／T1（可換填卷人）",
    "A": "A｜全部學生 T0",
    "B": "B｜全部家長 T0",
    "C": "C｜全部學生 T1",
    "D": "D｜全部家長 T1（可換填卷人）",
}


def sample_names(summary):
    from .bd_pairing import POLICY
    names = dict(SAMPLE_NAMES)
    if summary.get('bd_pairing_policy') == POLICY:
        names['BD'] = 'BD｜同一孩子的家長 T0／T1（填卷人可不同）'
    return names
SLOTS = {
    "A": [("student", "T0")], "B": [("parent", "T0")],
    "C": [("student", "T1")], "D": [("parent", "T1")],
    "AC": [("student", "T0"), ("student", "T1")],
    "BD": [("parent", "T0"), ("parent", "T1")],
    "parent_child_longitudinal": [("parent", "T0"), ("parent", "T1")],
    "E": [("student", "T0"), ("parent", "T0")],
    "F": [("student", "T1"), ("parent", "T1")],
    "EF": [("student", "T0"), ("parent", "T0"), ("student", "T1"), ("parent", "T1")],
}
COHORT_FLAGS = {
    "跨期配對樣本": "longitudinal", "親子配對樣本": "dyad",
    "跨期親子樣本": "longitudinal_dyad", "同一孩子的家長跨期回應": "child_report_longitudinal",
}
SAFE_FIELDS = ["submission_id", "school", "grade", "source_type", "mainstream", "identity_rules",
               "observed_at", "claimed_wave", "wave", "date_basis", "time_confidence",
               "student_parent_calendar_gap_days", "student_parent_elapsed_gap_days", "parent_response_interval_days"]
SOURCE_NAMES = {"legacy_online": "舊線上系統", "paperform": "paperform", "qualtrics": "Qualtrics",
                "school_batch": "學校批次", "socialworkdream": "Social Work Dream"}
STAGE_PURPOSES = {
    "1.1": "登記提交及來源，保留原始版本以供追查",
    "1.3/2.1.1/2.1.2": "標準化紙本及網上資料，合併為 A–D；本版直接接入合併檔",
    "2.1.3": "整理校名、年級及答案編碼，檢查提交資格",
    "2.1.4": "確認同一孩子及家長所指孩子，建立身份群組",
    "2.1.5": "固定最早 T0、處理短期重填，選取至少相隔 90 日的最新 T1",
    "2.1.6": "套用有效人工修正，保留修正及排除紀錄",
    "3.1.1": "輸出各輪學生／家長回應及 AC／BD 跨期樣本",
    "3.1.2/3.1.3": "建立各輪親子 E／F 及兩輪親子 EF 樣本",
}


def stage_overview(summary):
    rows = []
    for stage, count in summary["stage_counts"].items():
        if isinstance(count, dict):
            if stage == "2.1.4":
                quantity = f"{count['eligible_submissions']:,} 份合資格提交；{count['child_groups']:,} 個身份群組"
            elif stage == "3.1.1":
                quantity = (f"學生 T0：{count['A']:,}；T1：{count['C']:,}。"
                            f"家長 T0：{count['B']:,}；T1：{count['D']:,}")
            elif stage == "3.1.2/3.1.3":
                quantity = f"T0 親子 E：{count['E']:,} 組；T1 親子 F：{count['F']:,} 組；跨期 EF：{count['EF']:,} 組"
            else:
                quantity = "；".join(f"{name}：{value:,}" for name, value in count.items())
        else:
            quantity = f"{count:,} 份提交"
        purpose = STAGE_PURPOSES.get(stage, "此版本未提供階段說明")
        if stage == '2.1.5' and summary.get('parent_wave_policy'):
            purpose = '學生保留最早T0及至少90日後的最新T1；家長按學生香港日期分輪，同輪處理重填'
            if summary['parent_wave_policy'] == 'student_anchored_hk_nearest_v2':
                purpose = '學生保留最早T0及至少90日後的最新T1；先保留家長T1，再選最接近學生T0的家長基線（可較早）'
        rows.append({"階段": stage, "主要目的": purpose, "數量／結果": quantity})
    return pd.DataFrame(rows)


def source_wave_counts(imported, selected, role=None):
    """Original-wave input counts beside selected-wave final responses, by source."""
    if role:
        imported = imported[imported["role"] == role]
        selected = selected[selected["role"] == role]
    if not imported["wave"].isin(["T0", "T1"]).all() or not selected["wave"].isin(["T0", "T1"]).all():
        raise PipelineError("來源輪次包含未識別值，不能把它默默排除於 T0／T1 總數")
    imported = imported.copy()
    selected = selected.copy()
    for frame in (imported, selected):
        frame["source_type"] = frame["source_type"].fillna("unknown")
    originals = imported.groupby(["source_type", "wave"])["submissions"].sum()
    finals = selected.groupby(["source_type", "wave"]).size()
    additional = (set(imported["source_type"]) | set(selected["source_type"])) - set(SOURCE_NAMES)
    rows = []
    for category in [*SOURCE_NAMES, *sorted(additional)]:
        row = {"來源": SOURCE_NAMES.get(category, "其他／未識別來源" if category == "unknown" else category)}
        for wave in ["T0", "T1"]:
            row["匯入 " + wave] = int(originals.get((category, wave), 0))
            row["最終 " + wave] = int(finals.get((category, wave), 0))
        row["匯入合計"] = row["匯入 T0"] + row["匯入 T1"]
        row["最終合計"] = row["最終 T0"] + row["最終 T1"]
        rows.append(row)
    counts = pd.DataFrame(rows).reindex(columns=["來源", "匯入 T0", "匯入 T1", "匯入合計", "最終 T0", "最終 T1", "最終合計"])
    return pd.concat([counts, pd.DataFrame([{"來源": "合計", **counts.drop(columns="來源").sum().to_dict()}])], ignore_index=True)


def analysis_cohort(frame, parent_longitudinal, role, wave, cohort):
    source = parent_longitudinal if role == "parent" and cohort == "跨期配對樣本" and parent_longitudinal is not None else frame
    result = source[(source["role"] == role) & (source["wave"] == wave)].copy()
    flag = COHORT_FLAGS.get(cohort)
    if flag:
        result = result[result[flag].fillna(False).astype(bool)].copy()
    return result


def selected_sample(frame, parent_longitudinal, sample):
    """One selected child/role/wave row per slot; one final sample per output row."""
    source = parent_longitudinal if sample == "BD" and parent_longitudinal is not None else frame
    result = None
    for role, wave in SLOTS[sample]:
        slot = source[(source["role"] == role) & (source["wave"] == wave)].copy()
        if slot["child_id"].isna().any() or slot["child_id"].duplicated().any():
            raise PipelineError("發布資料的孩子／填卷類別／輪次不唯一，不能重現樣本數")
        prefix = role + "_" + wave
        slot = slot.reindex(columns=["child_id"] + SAFE_FIELDS)
        slot = slot.rename(columns={field: prefix + "_" + field for field in SAFE_FIELDS})
        result = slot if result is None else result.merge(slot, on="child_id", how="inner", validate="one_to_one")
    return result.sort_values("child_id").reset_index(drop=True)


def sample_reconciliation(frame, parent_longitudinal, summary):
    rows = []
    for sample, label in sample_names(summary).items():
        if sample not in summary:
            continue
        count = len(selected_sample(frame, parent_longitudinal, sample))
        expected = summary[sample]
        rows.append({"樣本": label, "首頁／版本組數": expected, "明細組數": count,
                     "核對": "一致" if count == expected else "不一致"})
    return pd.DataFrame(rows)


def sample_display(rows, sample):
    labels = {"submission_id": "提交ID", "school": "學校", "grade": "年級", "source_type": "來源",
              "observed_at": "建立時間", "claimed_wave": "原始輪次", "wave": "選定輪次",
              "date_basis": "日期依據", "time_confidence": "日期類別", "identity_rules": "孩子身份規則",
              "student_parent_calendar_gap_days": "距學生該輪日數（香港曆日）",
              "student_parent_elapsed_gap_days": "家長減學生時間差（日）",
              "parent_response_interval_days": "距家長T0日數（實際間隔）"}
    columns = ["child_id"]
    names = {"child_id": "孩子ID"}
    for field in labels:
        for role, wave in SLOTS[sample]:
            column = role + "_" + wave + "_" + field
            columns.append(column)
            names[column] = ("學生" if role == "student" else "家長") + wave + "_" + labels[field]
    return rows.reindex(columns=columns).rename(columns=names)
