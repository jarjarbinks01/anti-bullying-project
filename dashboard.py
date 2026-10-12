"""Read-only local dashboard over one published Study 2 release."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from study2.common import load_config
from study2.outputs import descriptive_summary, source_category
from study2.store import connect, current
from study2.dashboard_views import (SAMPLE_NAMES, analysis_cohort, selected_sample,
                                   sample_reconciliation, sample_display, stage_overview,
                                   source_wave_counts)

st.set_page_config(page_title="Study 2 研究資料", page_icon="📊", layout="wide")
cfg = load_config(Path(os.environ.get("STUDY2_CONFIG", Path(__file__).parent / "config.local.json")))
db = connect(Path(cfg["state_dir"]), readonly=True)
release = current(db)
db.close()
st.title("Study 2 研究資料")
st.caption("本機原型 · 確認配對與待審個案分開 · 每項統計顯示有效樣本及缺失數")
if not release:
    st.info("尚未發布資料。請先完成資料匯入及檢查。")
    st.stop()
summary = json.loads(release["stats_json"])
release_path = Path(release["path"])
rule_names = {
    "exact_school_contact_child_demo": "同校、聯絡及孩子身份一致",
    "one_digit_phone_school_child_demo": "同校、電話差一位、孩子身份一致",
    "exact_contact_school_transfer_child_demo": "轉校、精確聯絡及孩子身份一致",
    "fuzzy_contact_child_demo": "電話近似，尚未符合自動規則",
    "school_child_demo": "同校及孩子身份，聯絡證據不足",
    "transfer_contact_child_demo": "轉校候選，證據未確認",
    "contact_missing_or_conflicting_child_demo": "共享聯絡，孩子身份不足或矛盾",
    "same_adult_reported_birth_relationship_personal_contact": "成人出生年份、關係及本人聯絡一致",
    "same_adult_reported_birth_relationship_general_contact_fallback": "本人聯絡缺失；成人年份、關係及其他精確聯絡一致",
    "no_exact_personal_adult_contact": "缺少一致的成人本人聯絡",
    "adult_birth_year_missing_or_invalid": "成人出生年份缺失或無效",
    "adult_relationship_missing_or_invalid": "與孩子關係缺失或無效",
    "adult_other_relationship_unspecified": "其他關係未清楚填寫",
    "reported_birth_year_changed": "成人出生年份不同",
    "reported_relationship_changed": "與孩子關係不同",
    "reported_other_relationship_changed": "其他關係文字不同",
    "reviewer_confirmed_same_adult": "研究同事確認同一成人",
    "reviewer_rejected_same_adult": "研究同事確認成人不同",
    "adult_decision_reopened": "成人證據更新，重新待審",
    "manual_link": "研究同事確認同一孩子",
    "exact_merged_row_copy": "合併檔整行完全相同的副本",
    "baseline_preserved_under_30_days": "不足30日重填，保留最早T0",
    "under_30_days": "不足30日後續重填，保留較新回應",
    "unmatched": "未找到身份候選",
}
st.caption(f"資料版本：{release['release_id']} · 版本產生時間：{release['created_at']}")
if summary.get("source_scope") == "merged_abcd":
    st.info("資料來源：2.1.2 的四份 A／B／C／D 合併 Excel。電話差一位及轉校規則已啟用；BD 要求同一成人填卷人。")
    st.caption(f"按研究負責人決定，使用目前建立時間計算90日；其中 {summary.get('batch_creation_time_submissions',0):,} 行是批次指定日期。日期來源標記保留。")
st.button("重新讀取目前版本", on_click=lambda: st.cache_data.clear())
if summary.get("research_validation") == "not_yet_reviewed":
    st.warning("程式檢查已通過；研究同事尚未建立人工核實案例集，實際配對準確度未驗證。")
failure = Path(cfg["state_dir"]) / "last_failure.json"
if failure.exists():
    event = json.loads(failure.read_text())
    st.error("最近一次更新失敗，仍顯示上一個已發布版本。" + event["error"])
freshness_date=summary.get("source_exported_at") or release["created_at"]
if not summary.get("source_exported_at"):
    st.info("下載 agent 尚未提供匯出時間；版本產生時間只代表本機處理時間，不能證明來源資料最新。")
age = (datetime.now(timezone.utc) - datetime.fromisoformat(freshness_date.replace("Z","+00:00"))).days
if age > cfg["stale_after_days"]:
    st.warning(f"{'來源匯出' if summary.get('source_exported_at') else '版本產生'}已 {age} 日，請檢查每星期匯出是否完成。")


@st.cache_data(show_spinner=False)
def data(release_id, path):
    return pd.read_parquet(Path(path) / "analysis.parquet")


frame = data(release["release_id"], str(release_path))


@st.cache_data(show_spinner=False)
def sample_frames(release_id, path, state_dir, run_id):
    parent_path = Path(path) / "parent_longitudinal.parquet"
    parents = pd.read_parquet(parent_path) if parent_path.exists() else None
    db = connect(Path(state_dir), readonly=True)
    try:
        metadata = pd.read_sql_query(
            "SELECT submission_id, json_extract(payload_json,'$.observed_at') AS observed_at, "
            "json_extract(payload_json,'$.claimed_wave') AS claimed_wave "
            "FROM normalized_records WHERE run_id=?", db, params=(run_id,))
    finally:
        db.close()
    def attach(rows):
        return rows.merge(metadata, on="submission_id", how="left", validate="one_to_one")
    return attach(data(release_id, path)), attach(parents) if parents is not None else None


sample_frame, parent_frame = sample_frames(release["release_id"], str(release_path),
                                         cfg["state_dir"], release["run_id"])


@st.cache_data(show_spinner=False)
def imported_source_counts(release_id, state_dir, run_id):
    db = connect(Path(state_dir), readonly=True)
    try:
        counts = pd.read_sql_query(
            "SELECT COALESCE(json_extract(payload_json,'$.source_label'), "
            "json_extract(payload_json,'$.answer.Survey')) AS source_label, "
            "json_extract(payload_json,'$.role') AS role, "
            "json_extract(payload_json,'$.claimed_wave') AS wave, COUNT(*) AS submissions "
            "FROM normalized_records WHERE run_id=? GROUP BY 1,2,3", db, params=(run_id,))
    finally:
        db.close()
    counts["source_type"] = counts["source_label"].map(lambda value: source_category(str(value)) if pd.notna(value) and value else "unknown")
    return counts.drop(columns="source_label")


overview, analysis, evidence_tab, method = st.tabs(["資料品質及進度", "描述統計", "配對證據", "統計口徑"])
with overview:
    cols = st.columns(4)
    for c, label, value in zip(cols, ["提交記錄", "學生跨期 AC", "同一成人跨期 BD" if summary.get("bd_requires_same_adult") else "家長回應跨期配對", "跨期親子 EF"], [summary["submissions"], summary["AC"], summary["BD"], summary["EF"]]):
        c.metric(label, f"{value:,}")
    st.caption("要核對組成首頁數字的個案，開啟「配對證據」→「最終分析樣本」；每行代表一組。候選比較的宗數另列，不等於最終樣本組數。")
    st.subheader("各輪保留樣本及親子配對")
    if summary.get("bd_requires_same_adult"):
        st.caption(f"同一孩子的家長回應跨期共 {summary.get('parent_child_longitudinal',0):,} 組；其中BD只接納同一成人證據通過的組別。{summary.get('BD_alternative_followups',0):,} 組BD使用基線家長較早的合資格T1，與F的最新家長回應不同。")
        if summary.get("matching_policy", {}).get("allow_exact_general_contact_when_personal_missing"):
            st.caption(f"BD 有 {summary.get('BD_general_contact_fallback', 0):,} 組使用本人聯絡缺失的後備規則：其他精確電話／電郵一致，並通過成人年份、關係及孩子身份檢查。")
    st.dataframe(pd.DataFrame([
        {"輪次": "T0", "學生": summary["A"], "家長回應": summary["B"], "親子配對": summary["E"]},
        {"輪次": "T1", "學生": summary["C"], "家長回應": summary["D"], "親子配對": summary["F"]}]), hide_index=True, width="stretch")
    st.subheader("各階段數量")
    st.caption("本版從 2.1.2 的四份合併檔接入；1.3／2.1.1 的標準化沿用上游結果，不重複執行。各階段按提交、身份群組或配對組數計數，不能直接相加。")
    st.table(stage_overview(summary).style.hide(axis="index"))
    st.caption("2.1.5／2.1.6 的保留提交包括未滿 90 日及其他後續回應，不全部進入最終 T0／T1。身份群組也包括尚待釐清的群組，不能當作已確認的獨立孩子人數。")
    st.markdown("**各來源的 T0／T1 提交數**")
    source_role = st.radio("來源統計的填卷類別", ["all", "student", "parent"],
                           format_func=lambda value: {"all": "學生＋家長", "student": "只看學生", "parent": "只看家長"}[value],
                           horizontal=True, key="overview_source_role")
    source_counts = source_wave_counts(
        imported_source_counts(release["release_id"], cfg["state_dir"], release["run_id"]),
        frame, None if source_role == "all" else source_role)
    st.dataframe(source_counts, hide_index=True, width="stretch")
    st.caption("匯入：2.1.2 合併檔的原始輪次，包含其後被排除的提交。最終：3.1.1 選定輪次，包括全部學校。原標 T1 可推定為 T0，因此兩組輪次分開列出。每份提交只計一次；學生與家長相加是回應數，不是孩子人數。")
    st.download_button("下載各來源輪次數量", source_counts.to_csv(index=False).encode("utf-8-sig"),
                       f"study2-source-counts-{source_role}-{release['release_id']}.csv", "text/csv")
    st.subheader("本版本原始來源")
    manifest = json.loads((release_path / "run_manifest.json").read_text())["inputs"]
    source_files = {s["source_id"]: s["file"] for s in manifest["sources"]}
    st.dataframe(pd.DataFrame([{"檔案": source_files.get(k, k), "原始提交數": n}
                              for k, n in summary.get("source_submission_counts", {}).items()]),
                 hide_index=True, width="stretch")
    st.caption("此版本只讀取以上登記檔案。原始提交數包括未完成及之後被排除的回應，並非獨立參與者人數。")
    st.caption("全部樣本按選定回應計數。身份尚未釐清時，不能把回應數直接當作已確認的獨立孩子人數。")
    with st.expander("資料核實與更新狀態"):
        quality_columns = st.columns(3)
        quality_metrics = [
            ("待處理學校名稱", summary["school_names_pending"]),
            ("已標註驗證案例", summary["validation_cases_labelled"]),
            ("因資料更新而重新待審的決定", summary["manual_decisions_reopened"]),
            ("填卷次序待審的提交", summary.get("chronology_pending_submissions", 0)),
            ("由原標籤T1推定為T0", summary.get("t0_inferred_from_T1", 0)),
            ("主流學校分析回應", summary["analysis_mainstream_rows"]),
            ("其他／未知學校回應", summary["analysis_other_or_unknown_rows"]),
            ("附年級／日期提示的候選", summary.get("review_warning_cases", 0)),
        ]
        for index, (label, value) in enumerate(quality_metrics):
            quality_columns[index % 3].metric(label, value)
        if summary.get("legacy_corrections_scope") == "not_applied":
            st.caption("舊流程人工修正未自動套用到這次來源；請使用目前版本的受控審核包。")
        else:
            st.metric("舊人工修正未能遷移",summary.get("legacy_corrections_pending",0))
    st.download_button("下載版本摘要", (release_path / "summary.json").read_bytes(), "study2-summary.json", "application/json")
with analysis:
    scope = st.selectbox("描述統計學校範圍", ["只限主流學校（研究分析）", "全部學校（與首頁一致）"], key="analysis_scope")
    st.caption("首頁包括其他及未知學校；預設研究分析只限主流學校。選「全部學校」並清除其他篩選，可重現首頁對應樣本數。")
    filters = st.columns(4)
    role = filters[0].selectbox("填卷類別", ["student", "parent"], format_func=lambda x: "學生" if x == "student" else "家長回應（按孩子）")
    wave = filters[1].selectbox("輪次", ["T0", "T1"])
    cohort_options = ["全部保留樣本", "跨期配對樣本", "親子配對樣本", "跨期親子樣本"]
    if role == "parent" and summary.get("bd_requires_same_adult"):
        cohort_options += ["同一孩子的家長跨期回應"]
    cohort = filters[2].selectbox("樣本", cohort_options)
    gender = filters[3].selectbox("孩子性別", ["全部", "男", "女", "缺失"])
    if role == "parent" and cohort == "跨期配對樣本" and summary.get("bd_requires_same_adult"):
        st.caption("此頁使用BD的同一成人T0／T1選擇；T1可以與家庭F的最新家長回應不同。")
    if role == "parent" and cohort in {"跨期親子樣本", "同一孩子的家長跨期回應"} and summary.get("bd_requires_same_adult"):
        st.caption("這個樣本確認同一孩子，可能更換填卷人。分析同一成人PHQ變化請選跨期配對樣本（BD）。")
    homepage_subset = analysis_cohort(frame, parent_frame, role, wave, cohort)
    subset = homepage_subset.copy()
    if scope.startswith("只限主流"):
        subset = subset[subset["mainstream"]].copy()
    school_scope_n = len(subset)
    if gender != "全部":
        subset = subset[subset["gender"].fillna("").astype(str) == {"男": "0", "女": "1", "缺失": ""}[gender]]
    filters2 = st.columns(3)
    types = filters2[0].multiselect("學校類型", sorted(subset["school_type"].dropna().unique()))
    schools = filters2[1].multiselect("學校", sorted(subset["school"].dropna().unique()))
    source_column = "source_type" if "source_type" in subset else "source"
    source_names = {"paperform":"紙本", "school_batch":"學校批次", "socialworkdream":"Social Work Dream", "qualtrics":"Qualtrics", "legacy_online":"舊線上系統"}
    sources = filters2[2].multiselect("資料來源", sorted(subset[source_column].dropna().unique()), format_func=lambda x: source_names.get(x,x))
    if types:
        subset = subset[subset["school_type"].isin(types)]
    if schools:
        subset = subset[subset["school"].isin(schools)]
    if sources:
        subset = subset[subset[source_column].isin(sources)]
    if "identity_rules" in subset:
        rule_options = sorted({rule for value in subset["identity_rules"].dropna() for rule in value.split(";") if rule})
        rules = st.multiselect("孩子身份配對規則", rule_options, format_func=lambda x: rule_names.get(x, x))
        if rules:
            subset = subset[subset["identity_rules"].fillna("").map(lambda s: bool(set(s.split(";")) & set(rules)))]
    count_columns = st.columns(3)
    count_columns[0].metric("首頁口徑 N（全部學校、未篩選）", len(homepage_subset))
    count_columns[1].metric("學校範圍後 N", school_scope_n)
    count_columns[2].metric("目前樣本 N", len(subset))
    st.caption(f"學校範圍排除 {len(homepage_subset)-school_scope_n:,} 份；性別、學校、來源及規則篩選再排除 {school_scope_n-len(subset):,} 份。N 按目前輪次的回應計數，量表有效 N 另扣缺題。")
    demographics = st.columns(2)
    with demographics[0]:
        genders = subset["gender"].fillna("").map({"0": "男", "1": "女", "": "缺失"}).fillna("其他／未識別").value_counts().rename_axis("孩子性別").reset_index(name="回應數")
        genders["分母"] = len(subset)
        genders["比例"] = genders["回應數"] / len(subset) if len(subset) else 0
        st.dataframe(genders, hide_index=True, width="stretch")
    with demographics[1]:
        ages = subset["age_at_observation"].dropna()
        st.write(f"孩子觀察時年齡（按已填生日）：有效 N={len(ages)}；缺失 N={len(subset)-len(ages)}")
        if len(ages):
            st.plotly_chart(px.histogram(subset, x="age_at_observation", nbins=20, labels={"age_at_observation": "孩子觀察時年齡"}), width="stretch")
    stats = descriptive_summary(subset)
    st.subheader("量表及欺凌指標")
    st.caption("家長PHQ是填卷家長自己的回應；家長SEC及欺凌題目描述所指孩子。FQOL、SEC及欺凌指標為題目平均；PHQ為總和。不同問卷版本的文字可比性仍須研究團隊核實。")
    st.dataframe(stats.rename(columns={"metric": "指標", "sample_n": "樣本N", "valid_n": "有效N", "missing_n": "缺失N", "mean_or_proportion": "平均／比例", "sd": "標準差"}), hide_index=True, width="stretch")
    st.download_button("下載目前篩選的描述統計", stats.to_csv(index=False).encode("utf-8-sig"), "study2-descriptives.csv", "text/csv")
with method:
    st.markdown("""
    - **追蹤孩子**：家長回應依問卷所指孩子連結，不能用家長電話把兄弟姊妹合併。
    - **T0**：最早的合資格原始回應。後來的短期重填不會取代T0；原填T1的首次回應保留原標籤及推定理由。
    - **T1**：最新、距 T0 至少90日的回應。本次合併資料依研究負責人決定使用現有建立時間，保留系統／批次日期來源。
    - **缺失日期**：單次回應可推定T0；多次回應的次序不明時先待審。
    - **正式配對**：只使用已確認的身份連結；待審候選不會被暫時當成已配對。
    - **量表計分**：所需題目完整才計分；缺題維持缺失，不當作零。
    - **分母**：每項指標使用其有效N；跨期樣本與每輪全部樣本的分母不同。
    - **首頁與描述統計**：首頁包括全部學校；描述統計預設只限主流學校，頁面會列明學校範圍及其他篩選造成的數量差。
    - **最終樣本與候選比較**：AC／BD／E／F每行是一組兩份選定回應；EF每行是一組四份選定回應。候選比較包括未被選為最終T0／T1的回應，一宗候選不是一組最終样本。
    - **BD家長身份**：同一孩子之外，成人出生年份及與孩子關係須一致。優先使用本人精確聯絡；本版如啟用後備規則，至少一方本人聯絡缺失時可使用其他精確電話／電郵。兩方均有本人聯絡但不一致時不使用後備規則；逐宗人工裁定另行保留。同孩子但填卷人更換不進BD。
    - **電話近似及轉校**：本次接受同校且電話只差一個數字，以及相同聯絡但轉校；孩子完整生日及性別仍須相同，候選及整組不得有矛盾。電話互換兩位、電話近似兼轉校仍待審。
    - **親子日期差**：確認指向同一孩子便可配對，不限制學生與家長日期差；輸出另保存日期差供檢查。
    - **年級／日期提示**：按香港時間、9月為學年分界及已知小學／中學階段作初步檢查；提示可涉及跳級、年級下降、跨學年不變、階段不明及批次日期。提示不會自行更正、拒配或排除回應。
    """)
with evidence_tab:
    view = st.radio("配對證據檢視", ["最終分析樣本（對照首頁）", "候選比較（供審核）"], horizontal=True, key="evidence_view")
    if view.startswith("最終"):
        sample = st.selectbox("最終樣本", list(SAMPLE_NAMES), format_func=SAMPLE_NAMES.get, key="final_sample")
        rows = selected_sample(sample_frame, parent_frame, sample)
        expected = summary.get(sample)
        count_columns = st.columns(2)
        unit = "份回應" if sample in "ABCD" else "組"
        count_columns[0].metric("首頁／版本數量", f"{expected:,} {unit}" if expected is not None else "此版本未列")
        count_columns[1].metric("最終樣本明細數量", f"{len(rows):,} {unit}")
        if expected is not None and len(rows) != expected:
            st.error("最終樣本明細與發布摘要不一致，請先核對版本；不能用候選宗數替代。")
        else:
            st.success("明細數量與首頁／發布版本一致。")
        if sample == "EF":
            st.caption("每行是一個孩子的學生T0、家長T0、學生T1、家長T1，共四份回應。可更換家長填卷人。")
        elif sample in "ABCD":
            st.caption("每行是一份最終選定回應。包括全部學校，與首頁各輪樣本數一致。")
        else:
            st.caption("每行是一組兩份最終選定回應，包括全部學校。只列實際納入該樣本的提交，不列其他重填或額外候選。")
        if sample == "BD":
            st.caption("使用BD專用的同一成人選擇；家長T1可與D／F的最新家長回應不同。")
        if sample in {"E", "F", "EF"}:
            st.caption("親子確認指向同一孩子，不限制學生與家長日期差。")
        display = sample_display(rows, sample)
        for column in display:
            if column.endswith("_孩子身份規則"):
                display[column] = display[column].fillna("").map(lambda value: "；".join(rule_names.get(rule, rule) for rule in value.split(";") if rule))
            if column.endswith("_日期依據"):
                display[column] = display[column].map({"system_creation":"系統建立時間", "batch_assigned_creation":"批次指定建立時間"}).fillna(display[column])
        st.dataframe(display, hide_index=True, width="stretch")
        st.download_button("下載目前最終樣本明細", display.to_csv(index=False).encode("utf-8-sig"), f"study2-{sample}-{release['release_id']}.csv", "text/csv")
        with st.expander("核對全部樣本數量"):
            st.dataframe(sample_reconciliation(sample_frame, parent_frame, summary), hide_index=True, width="stretch")
    evidence_path = release_path / "candidate_evidence.parquet"
    if view.startswith("候選") and not evidence_path.exists():
        st.info("此舊版本沒有配對證據摘要。")
    elif view.startswith("候選"):
        evidence = pd.read_parquet(evidence_path)
        if "review_warnings" not in evidence:
            evidence["review_warnings"] = ""
        only_hints = st.checkbox("只看有年級／日期提示的候選", key="only_review_hints")
        if only_hints:
            evidence = evidence[evidence["review_warnings"].fillna("").ne("")]
        st.caption("年級／日期提示供人工核實，不代表身份不同或自動拒配。親子日期差沒有拒配上限。")
        controls = st.columns(3)
        kind_names = {"identity":"孩子身份比較（同輪次或跨期）", "family":"親子身份比較", "respondent":"成人身份比較", "dedup":"重複回應", "date":"日期資格"}
        status_names = {"confirmed":"規則通過／人工確認", "pending":"待審", "rejected":"未通過／已拒絕", "unmatched":"未配對"}
        kinds = controls[0].multiselect("候選類別", sorted(evidence["kind"].unique()), format_func=lambda x: kind_names.get(x,x))
        states = controls[1].multiselect("審核狀態", sorted(evidence["status"].unique()), format_func=lambda x: status_names.get(x,x))
        case_rules = controls[2].multiselect("候選規則", sorted(evidence["rule"].unique()), format_func=lambda x: rule_names.get(x, x))
        for column, values in [("kind", kinds), ("status", states), ("rule", case_rules)]:
            if values:
                evidence = evidence[evidence[column].isin(values)]
        st.metric("符合篩選的候選個案", len(evidence))
        st.caption("這裡計算候選比較宗數，包括同輪次、學生、家長及多次提交；即使已確認，也不等於首頁AC／BD／EF組數。重現首頁數字請切換「最終分析樣本」。")
        st.caption("摘要只顯示欄位是否一致，不顯示完整電話、電郵或生日；詳細核實及修改使用受控Excel。")
        display_evidence = evidence.copy()
        display_evidence["kind"] = display_evidence["kind"].map(lambda x: kind_names.get(x, x))
        display_evidence["status"] = display_evidence["status"].map(lambda x: status_names.get(x, x))
        display_evidence["rule"] = display_evidence["rule"].map(lambda x: rule_names.get(x, x))
        display_evidence = display_evidence.drop(columns=["reason"]).rename(columns={
            "case_id":"審核案例ID", "kind":"類別", "status":"狀態", "rule":"規則",
            "record_a":"提交A", "record_b":"提交B", "role_a":"填卷類別A", "role_b":"填卷類別B",
            "school_a":"學校A", "school_b":"學校B", "grade_a":"年級A", "grade_b":"年級B",
            "observed_at_a":"建立時間A", "observed_at_b":"建立時間B", "date_basis_a":"日期來源A", "date_basis_b":"日期來源B",
            "dob_agrees":"孩子生日一致", "gender_agrees":"孩子性別一致", "exact_contact":"聯絡完全一致",
            "one_digit_phone":"電話差一位", "school_agrees":"校名一致",
            "adult_personal_contact_agrees":"成人本人聯絡一致", "adult_birthyear_agrees":"成人出生年份一致",
            "adult_relationship_agrees":"與孩子關係一致"})
        display_evidence = display_evidence.drop(columns=["review_warning_codes"], errors="ignore").rename(columns={"review_warnings":"年級／日期審核提示"})
        for col in ["填卷類別A", "填卷類別B"]:
            display_evidence[col] = display_evidence[col].map({"student":"學生", "parent":"家長"})
        for col in ["日期來源A", "日期來源B"]:
            display_evidence[col] = display_evidence[col].map({"system_creation":"系統建立時間", "batch_assigned_creation":"批次指定建立時間"})
        st.dataframe(display_evidence.head(500), hide_index=True, width="stretch")
        if len(display_evidence) > 500:
            st.caption(f"表格預覽前500宗；下載包含全部 {len(display_evidence):,} 宗篩選結果。")
        st.download_button("下載目前候選證據摘要", display_evidence.to_csv(index=False).encode("utf-8-sig"), "study2-pair-evidence.csv", "text/csv")
