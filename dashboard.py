"""Read-only local dashboard over one published Study 2 release."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import study2
from study2.english_ui import st

from study2.common import load_config, digest, file_hash
from study2.parent_waves import POLICY as NEAREST_PARENT_POLICY
from study2.review_dispatch import ROUTES, REASONS, queue_snapshot
from study2.outputs import descriptive_summary, source_category
from study2.store import connect, current
from study2.dashboard_views import (SAMPLE_NAMES, analysis_cohort, selected_sample,
                                   sample_reconciliation, sample_display, stage_overview,
                                   source_wave_counts)
from study2.dashboard_header import HeaderFacts, build_header, render_header, render_missing_release
from study2.streamlit_eligibility import (ENVIRONMENT_KEY,ActiveEligibilityUnavailable,
    load_eligibility,render_selector,render_impact,stamp_frame,download_name)
from study2.review_workload import render_current_review_workload

st.set_page_config(page_title="Study 2 研究資料", page_icon="📊", layout="wide")
cfg = load_config(Path(os.environ.get("STUDY2_CONFIG", Path(__file__).parent / "config.local.json")))
db = connect(Path(cfg["state_dir"]), readonly=True)
release = current(db)
decision_revision = digest([tuple(r) for r in db.execute('SELECT decision_id,payload_json,supersedes FROM decisions ORDER BY decision_id')])
db.close()
if not release:
    render_missing_release()
    st.stop()
summary = json.loads(release["stats_json"])
student_anchored = bool(summary.get('parent_wave_policy'))
nearest_parent_baseline = summary.get('parent_wave_policy') == NEAREST_PARENT_POLICY
release_path = Path(release["path"])
rule_names = {
    "exact_school_contact_child_demo": "同校、聯絡及孩子身份一致",
    "one_digit_phone_school_child_demo": "同校、電話差一位、孩子身份一致",
    "exact_contact_school_transfer_child_demo": "不同學校、精確聯絡及孩子身份一致",
    "child_contact_bridge_component": "聯絡規則連通的身份群組／子群（自動確認）",
    'child_group_contact_bridge': '群組聯絡連結核實（部分提交沒有直接共同聯絡）',
    'child_group_contact_gap': '群組尚有未連起的子群',
    'child_group_identity_conflict': '群組身份矛盾，交指定執行者',
    'child_group_manual_nonmatch': '群組含人工不配對限制',
    'child_group_incomplete_members': '群組部分提交資料不足，交指定執行者',
    "fuzzy_contact_child_demo": "電話近似，尚未符合自動規則",
    "school_child_demo": "同校及孩子身份，聯絡證據不足",
    "transfer_contact_child_demo": "轉校候選，證據未確認",
    "contact_missing_or_conflicting_child_demo": "共享聯絡，孩子身份不足或矛盾",
    "same_adult_reported_birth_relationship_personal_contact": "成人出生年份、關係及本人聯絡一致",
    "same_adult_reported_birth_relationship_general_contact_fallback": "本人聯絡缺失；成人年份、關係及其他精確聯絡一致",
    'same_adult_reported_birth_personal_contact': '成人出生年份及任一本人電話／電郵一致',
    'same_adult_reported_birth_any_exact_contact': '成人出生年份及任一聯絡欄精確電話／電郵一致',
    'no_exact_adult_contact': '沒有任何精確相同的電話／電郵',
    'different_child_identity': '兩份回應指向不同孩子',
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
failure = Path(cfg["state_dir"]) / "last_failure.json"
last_update_error = None
if failure.exists():
    event = json.loads(failure.read_text())
    last_update_error = event.get("error") or ""
render_header(build_header(HeaderFacts(
    release_id=release["release_id"],
    created_at=release["created_at"],
    source_exported_at=summary.get("source_exported_at"),
    stale_after_days=cfg.get("stale_after_days"),
    now=datetime.now(timezone.utc),
    source_scope=summary.get("source_scope"),
    bd_requires_same_adult=summary.get("bd_requires_same_adult"),
    batch_creation_time_submissions=summary.get("batch_creation_time_submissions"),
    parent_wave_policy=summary.get("parent_wave_policy"),
    nearest_parent_baseline=nearest_parent_baseline,
    research_validation=summary.get("research_validation"),
    last_update_error=last_update_error,
)), on_reload=lambda: st.cache_data.clear())


@st.cache_data(show_spinner=False)
def data(release_id, path):
    return pd.read_parquet(Path(path) / "analysis.parquet")


frame = data(release["release_id"], str(release_path))


@st.cache_data(show_spinner=False)
def review_workload(release_id, state_dir, policy_hash, decisions, workspace_revision, _cfg):
    return queue_snapshot(_cfg, include_cases=True)


review_files = [Path(cfg['state_dir']) / ('review.sqlite' + suffix) for suffix in ('', '-wal')]
review_revision = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in review_files)
dispatch = review_workload(release['release_id'], cfg['state_dir'],
    digest([file_hash(Path(study2.__file__).parent/name) for name in ('review_dispatch.py','review_groups.py','review_core.py')]), decision_revision, review_revision, cfg)
if dispatch['release_id'] != release['release_id']:
    st.info('資料正在更新，請重新讀取目前版本。')
    st.stop()


@st.cache_data(show_spinner=False)
def sample_frames(release_id, path, state_dir, run_id):
    parent_path = Path(path) / "parent_longitudinal.parquet"
    parents = pd.read_parquet(parent_path) if parent_path.exists() else None
    db = connect(Path(state_dir), readonly=True)
    try:
        from study2.storage import record_metadata
        metadata = pd.DataFrame(record_metadata(db,run_id),columns=['submission_id','observed_at','claimed_wave'])
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
        from study2.storage import imported_source_counts as stored_source_counts
        counts = pd.DataFrame(stored_source_counts(db,run_id),columns=['source_label','role','wave','submissions'])
    finally:
        db.close()
    counts["source_type"] = counts["source_label"].map(lambda value: source_category(str(value)) if pd.notna(value) and value else "unknown")
    return counts.drop(columns="source_label")


@st.cache_data(show_spinner=False)
def canonical_parents(release_id,path):
    target=Path(path)/'parent_longitudinal.parquet'
    return pd.read_parquet(target) if target.exists() else None


manual_manifest_path=os.environ.get(ENVIRONMENT_KEY)
manual_inputs=load_eligibility(release_path,summary,frame,
    canonical_parents(release['release_id'],str(release_path)) if manual_manifest_path else None,
    manifest_path=manual_manifest_path)
eligibility=render_selector(st,manual_inputs)
published_imports=imported_source_counts(release['release_id'],cfg['state_dir'],release['run_id'])


overview, analysis, independent_parent_tab, evidence_tab, tracking_tab, method = st.tabs(
    ["資料品質及進度", "描述統計", "獨立家長分析", "配對證據", "親子追蹤", "統計口徑"])
with independent_parent_tab:
    from study2.parent_panel_dashboard import render_parent_panel
    render_parent_panel(release_path, summary,eligibility=eligibility)
with overview:
    intake_totals=published_imports.groupby('role')['submissions'].sum().to_dict()
    render_impact(st,eligibility,summary,intake_totals)
    st.caption('Published OFF/reference overview, raw intake, stages and review status are retained below.')
    cols = st.columns(4)
    for c, label, value in zip(cols, ["提交記錄", "學生跨期 AC", "同一成人跨期 BD" if summary.get("bd_requires_same_adult") else "家長回應跨期配對", "跨期親子 EF"], [summary["submissions"], summary["AC"], summary["BD"], summary["EF"]]):
        c.metric(label, f"{value:,}")
    st.caption("要核對組成首頁數字的個案，開啟「配對證據」→「最終分析樣本」；每行代表一組。候選比較的宗數另列，不等於最終樣本組數。")
    if summary.get('matching_policy', {}).get('allow_contact_bridge_components'):
        st.caption(f"本版有 {summary.get('auto_contact_bridge_groups',0):,} 個聯絡連通群組（{summary.get('auto_contact_bridge_submissions',0):,} 份提交）按已接受規則、孩子生日及性別一致而自動確認；其中 {summary.get('auto_contact_subgroups',0):,} 個是在較大待審群組內單獨確認的子群。子群內連結毋須重審；子群之間欠證據的連結及孤立問卷等待新資料，不直接派卡。單數問卷正常保留，T0／T1 另按日期選取。")
    st.subheader("各輪保留樣本及親子配對")
    if summary.get("bd_requires_same_adult"):
        st.caption(f"同一孩子的家長回應跨期共 {summary.get('parent_child_longitudinal',0):,} 組；其中BD只接納同一成人證據通過的組別。{summary.get('BD_alternative_followups',0):,} 組BD使用基線家長較早的合資格T1，與F的最新家長回應不同。")
        if summary.get('adult_identity_policy') == 'same_child_valid_equal_birth_year_any_exact_contact_relationship_informational':
            st.caption(f"BD 有 {summary.get('BD_any_exact_contact', 0):,} 組按其他聯絡欄的精確電話／電郵確認；本人聯絡即使不同也可使用。成人出生年份須有效且一致；與孩子關係保留供查看，不作配對門檻。多項聯絡逐項拆分，任一項精確一致即可。")
        elif summary.get("matching_policy", {}).get("allow_exact_general_contact_when_personal_missing"):
            st.caption(f"BD 有 {summary.get('BD_general_contact_fallback', 0):,} 組使用本人聯絡缺失的後備規則：其他精確電話／電郵一致，並通過成人年份、關係及孩子身份檢查。")
    st.dataframe(pd.DataFrame([
        {"輪次": "T0", "學生": summary["A"], "家長回應": summary["B"], "親子配對": summary["E"]},
        {"輪次": "T1", "學生": summary["C"], "家長回應": summary["D"], "親子配對": summary["F"]}]), hide_index=True, width="stretch")
    if student_anchored:
        phase_counts = summary.get('parent_phase_counts', {})
        if nearest_parent_baseline:
            st.caption(f"有 {summary.get('parent_T0_before_student_day',0):,} 份選定家長T0早於學生T0的香港日期，已保留有方向的日期差。未有可用學生基線的家長回應另列 {phase_counts.get('unanchored',0):,} 份。BD有 {summary.get('BD_parent_interval_under_90_days',0):,} 組家長自身相隔不足90日。")
        else:
            st.caption(f"家長歷史回應（早於學生T0）：{phase_counts.get('historical',0):,} 份；未有可用學生基線：{phase_counts.get('unanchored',0):,} 份。全部保留追查，未納入正式家長T0／T1。BD有 {summary.get('BD_parent_interval_under_90_days',0):,} 組家長自身相隔不足90日。")
    st.subheader("各階段數量")
    st.caption("本版從 2.1.2 的四份合併檔接入；1.3／2.1.1 的標準化沿用上游結果，不重複執行。各階段按提交、身份群組或配對組數計數，不能直接相加。")
    st.table(stage_overview(summary).style.hide(axis="index"))
    st.caption("2.1.5／2.1.6 的保留提交包括未滿 90 日及其他後續回應，不全部進入最終 T0／T1。身份群組也包括尚待釐清的群組，不能當作已確認的獨立孩子人數。")
    st.markdown("**各來源的 T0／T1 提交數**")
    source_role = st.radio("來源統計的填卷類別", ["all", "student", "parent"],
                           format_func=lambda value: {"all": "學生＋家長", "student": "只看學生", "parent": "只看家長"}[value],
                           horizontal=True, key="overview_source_role")
    source_counts = source_wave_counts(
        published_imports.copy(deep=True),
        eligibility.analytical_frame(frame) if eligibility.allowed else frame.copy(deep=True), None if source_role == "all" else source_role)
    st.dataframe(source_counts, hide_index=True, width="stretch")
    st.caption("匯入：2.1.2 合併檔的原始輪次，包含其後被排除的提交。最終：3.1.1 選定輪次，包括全部學校。原標 T1 可推定為 T0，因此兩組輪次分開列出。每份提交只計一次；學生與家長相加是回應數，不是孩子人數。")
    source_metadata=eligibility.metadata(reference=not eligibility.allowed)
    st.caption('Imports are canonical history; final columns use the active retained original slots, or explicitly OFF/reference if requested ON is unavailable.')
    st.download_button('Download current source counts',stamp_frame(source_counts,source_metadata).to_csv(index=False).encode('utf-8-sig'),
                       download_name(f"study2-source-counts-{source_role}-{release['release_id']}.csv",source_metadata),'text/csv')
    st.subheader("本版本原始來源")
    manifest = json.loads((release_path / "run_manifest.json").read_text())["inputs"]
    source_files = {s["source_id"]: s["file"] for s in manifest["sources"]}
    st.dataframe(pd.DataFrame([{"檔案": source_files.get(k, k), "原始提交數": n}
                              for k, n in summary.get("source_submission_counts", {}).items()]),
                 hide_index=True, width="stretch")
    st.caption("此版本只讀取以上登記檔案。原始提交數包括未完成及之後被排除的回應，並非獨立參與者人數。")
    st.caption("全部樣本按選定回應計數。身份尚未釐清時，不能把回應數直接當作已確認的獨立孩子人數。")
    render_current_review_workload(st, release_id=release['release_id'],
        decision_revision=decision_revision, exclusion_revision=manual_inputs.revision)
    with st.expander("資料核實與更新狀態"):
        st.subheader('Historical native dispatch (before accepted group/exclusion policy)')
        st.caption('The native routing figures below retain historical evidence and pending statuses. '
                   'They are not the current actionable worklist; use Current review workload above.')
        review_columns = st.columns(3)
        review_columns[0].metric('身份審核工作（群組／成人）', dispatch['remaining_general_reviews'])
        review_columns[1].metric('有聯絡的資料更正比較', dispatch['pending_routes'].get('correction', 0))
        review_columns[2].metric('無可用聯絡，不派審', dispatch['pending_routes'].get('untraceable', 0))
        st.metric('證據不足，待新資料（暫不合併）',dispatch['awaiting_evidence_work'])
        st.caption(f"其中孩子群組 {dispatch['awaiting_evidence_groups']:,} 個、成人比較 {dispatch['awaiting_evidence_adult_comparisons']:,} 宗。這些是未證實的連結，不是已確認不同身份，也不要求同事逐宗填卡。")
        st.caption('有可用電話不代表有核實依據。子群只有生日、性別及學校一致，或電話近似但沒有可核實來源時，等待新資料。Jarvis 登記原始紙本／既有紀錄的位置及具體問題後，才恢復一般派審；生日、性別矛盾及人工限制仍交既有更正／裁定流程。')
        st.caption(f"孩子身份每組只派一宗：{dispatch['child_groups_pending']:,} 組；成人比較 {dispatch['adult_comparisons_pending']:,} 宗。整組有矛盾而交指定執行者：{dispatch['child_groups_operator']:,} 組。已通過直接規則的兩份問卷列為群組證據，毋須重審；人工裁定經批准、套用及重新發布後更新正式配對。")
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
    st.download_button("Download published OFF/reference summary", (release_path / "summary.json").read_bytes(), "OFF-reference-study2-summary.json", "application/json")
with analysis:
    from study2.descriptive_dashboard import render_descriptive
    render_descriptive(release_path, summary, sample_frame, parent_frame, rule_names,eligibility=eligibility)

with method:
    if summary.get('independent_parent'):
        st.markdown('**獨立家長分析**：另見同名頁籤。沿用已確認孩子身份，不要求學生問卷；以最早合資格家長回應為共同基線，選至少90日後的最新回應。同一成人分支另要求有效一致出生年份及精確聯絡，T1可不同。成人電話差一位只供試算，不加入正式同一成人樣本。原有學生錨定樣本保持獨立。')
    if summary.get('matching_policy', {}).get('allow_contact_bridge_components'):
        st.markdown('**聯絡群組身份確認**：群組內孩子生日及有效性別一致，且已接受的直接規則能連起全部提交時，自動確認同一孩子。啟用子群確認的版本會逐個聯絡連通子群檢查，不因外圍缺少連結而擋住有充分證據的子群。不得切開既有人工身份群組；子群內有身份矛盾、人工不配對或失效決定時不自動通過。不同子群欠證據不等於已確認不同孩子；單數問卷正常保留，重填及輪次另按規則判斷。')
    if nearest_parent_baseline:
        st.markdown('''
        - **學生T0／T1**：最早合資格學生基線，及至少90日後的最新合資格學生T1。
        - **家長T1優先**：學生T1香港日期同日或之後的家長回應先列T1候選，選最新一份，包括原標T0的回應，不拿來填補T0。
        - **家長T0**：從其餘同一孩子的合資格回應中，按實際建立時間與學生T0的絕對差距選最近一份，可早於學生，不設硬上限；沒有學生T1時所有有可靠日期的家長回應均可作T0候選。等距候選留待核實。
        - **日期差**：保存家長減學生的香港曆日差及實際時間差；負數表示家長較早，正數表示家長較遲，未選回應仍可追查。
        - **成人及重填**：家長自身沒有90日門檻，BD仍須同一成人。30日重填只在同一輪、同一成人內處理，保護已選最近基線，不跨T0／T1去重。
        - **資料缺口**：沒有學生基線則另列；只有家長T1而沒有T0可進F，不進BD／EF。原始提交、標籤、身份裁定及永久ID保留。
        ''')
    elif student_anchored:
        st.markdown('''
        - **學生T0／T1**：保留最早合資格學生基線，選至少90日後的最新合資格學生T1。
        - **家長分輪**：按香港曆日。早於學生T0只列歷史；學生T0當日至學生T1前一日屬T0候選；學生T1同日或之後屬T1候選，原始標籤不作門檻。
        - **家長選取**：T0選最早候選（最接近學生基線），T1選最新候選。尚未有學生T1時，家長T0不設固定日期差上限。不設家長自身90日門檻。
        - **家長資料缺口**：未有學生基線則另列；有家長T1但沒有家長T0，可進入F，不進入BD／EF。原始提交及永久家庭ID保留。
        - **重填**：只在同一學生輪次內比較家長重填，不跨T0／T1刪除。BD仍須確認同一成人，另列實際測量間隔。
        ''')
    st.markdown("""
    - **追蹤孩子**：家長回應依問卷所指孩子連結，不能用家長電話把兄弟姊妹合併。
    - **學生T0**：最早的合資格原始回應。後來的短期重填不會取代學生T0；原填T1的首次回應保留原標籤及推定理由。
    - **學生T1**：最新、距學生T0至少90日的回應。使用現有建立時間，保留系統／批次日期來源。
    - **缺失日期**：單次回應可推定T0；多次回應的次序不明時先待審。
    - **正式配對**：只使用已確認的身份連結；待審候選不會被暫時當成已配對。
    - **量表計分**：所需題目完整才計分；缺題維持缺失，不當作零。
    - **分母**：每項指標使用其有效N；跨期樣本與每輪全部樣本的分母不同。
    - **首頁與描述統計**：首頁包括全部學校；描述統計預設只限主流學校，頁面會列明學校範圍及其他篩選造成的數量差。
    - **最終樣本與候選比較**：AC／BD／E／F每行是一組兩份選定回應；EF每行是一組四份選定回應。候選比較包括未被選為最終T0／T1的回應，一宗候選不是一組最終样本。
    - **BD家長身份**：兩份回應須指向同一孩子，成人出生年份有效且一致，所有聯絡欄中任一精確電話／電郵相同即可。多項聯絡逐項拆分，比對電話或電郵集合的交集；本人聯絡不同仍可使用其他共同聯絡。與孩子關係保留為原填資料，不作確認門檻。電話近似不作成人自動確認。逐宗人工裁定另行保留。
    - **電話近似及轉校**：本次接受同校且電話只差一個數字，以及相同聯絡但轉校；孩子完整生日及性別仍須相同，候選及整組不得有矛盾。電話互換兩位、電話近似兼轉校仍待審。
    - **親子身份與測量輪次**：身份確認與日期選取分開。親子須先確認指向同一孩子，再依當版輪次規則選取，輸出另保存日期差。
    - **年級／日期提示**：按香港時間、9月為學年分界及已知小學／中學階段作初步檢查；提示可涉及跳級、年級下降、跨學年不變、階段不明及批次日期。提示不會自行更正、拒配或排除回應。
    """)
with evidence_tab:
    st.caption('Final analytical samples use the current eligibility mode. Candidate review remains published OFF/reference and is not changed.')
    view = st.radio("配對證據檢視", ["最終分析樣本（對照首頁）", "候選比較（供審核）"], horizontal=True, key="evidence_view")
    if view.startswith("最終"):
        if not eligibility.allowed:
            st.info('Requested ON final samples are unavailable. Select OFF for canonical details.')
        else:
            try:
                sample = st.selectbox("最終樣本", list(SAMPLE_NAMES), format_func=SAMPLE_NAMES.get, key="final_sample")
                rows=eligibility.sample_rows(sample_frame,parent_frame,sample)
                expected=eligibility.sample_count(sample,rows,summary)
                count_columns = st.columns(2)
                unit = "份回應" if sample in "ABCD" else "組"
                count_columns[0].metric("Active original-member count" if eligibility.enabled else "首頁／版本數量", f"{expected:,} {unit}" if expected is not None else "此版本未列")
                count_columns[1].metric("最終樣本明細數量", f"{len(rows):,} {unit}")
                if expected is not None and len(rows) != expected:
                    st.error("最終樣本明細與發布摘要不一致，請先核對版本；不能用候選宗數替代。")
                else:
                    st.success("Detail agrees with the active original-membership projection." if eligibility.enabled else "明細數量與首頁／發布版本一致。")
                if sample == "EF":
                    st.caption("每行是一個孩子的學生T0、家長T0、學生T1、家長T1，共四份回應。可更換家長填卷人。")
                elif sample in "ABCD":
                    st.caption("每行是一份最終選定回應。包括全部學校，與首頁各輪樣本數一致。")
                else:
                    st.caption("每行是一組兩份最終選定回應，包括全部學校。只列實際納入該樣本的提交，不列其他重填或額外候選。")
                if sample == "BD":
                    st.caption("使用BD專用的同一成人選擇；家長T1可與D／F的最新家長回應不同。")
                if sample in {"E", "F", "EF"}:
                    st.caption('親子確認指向同一孩子；家長按學生香港日期分輪，日期差另列。' if student_anchored else '親子確認指向同一孩子，不限制學生與家長日期差。')
                display = sample_display(rows, sample)
                for column in display:
                    if column.endswith("_孩子身份規則"):
                        display[column] = display[column].fillna("").map(lambda value: "；".join(rule_names.get(rule, rule) for rule in value.split(";") if rule))
                    if column.endswith("_日期依據"):
                        display[column] = display[column].map({"system_creation":"系統建立時間", "batch_assigned_creation":"批次指定建立時間"}).fillna(display[column])
                st.dataframe(display, hide_index=True, width="stretch")
                evidence_metadata=eligibility.metadata()
                st.download_button("下載目前最終樣本明細",stamp_frame(display,evidence_metadata).to_csv(index=False).encode("utf-8-sig"),download_name(f"study2-{sample}-{release['release_id']}.csv",evidence_metadata),"text/csv")
                with st.expander("核對全部樣本數量"):
                    st.dataframe(eligibility.reconciliation(sample_frame,parent_frame,summary),hide_index=True,width="stretch")

            except ActiveEligibilityUnavailable:
                st.info('This native sample has no compatible original membership evidence for ON.')
    evidence_path = release_path / "candidate_evidence.parquet"
    if view.startswith("候選") and not evidence_path.exists():
        st.info("此舊版本沒有配對證據摘要。")
    elif view.startswith("候選"):
        st.subheader('Historical native candidate evidence')
        st.caption('The original native routing, filter options and evidence rows are retained. '
                   'Pending here is a historical native status before accepted group/exclusion policy, not a current assignment.')
        evidence = pd.read_parquet(evidence_path)
        group_rows = pd.DataFrame(dispatch.get('groups', []))
        if not group_rows.empty:
            evidence = pd.concat([evidence, group_rows.drop(columns='route')], ignore_index=True)
        routing = pd.DataFrame(dispatch['cases'])
        routing['dispatch_reason'] = routing['reasons'].map(lambda codes: '；'.join(REASONS[x] for x in codes))
        evidence = evidence.merge(routing.drop(columns='reasons'), on='case_id', how='left', validate='one_to_one')
        usage = st.selectbox('候選用途', ['一般身份審核', '證據不足，待新資料（暫不合併）', '資料更正（有可用聯絡）', '無可用聯絡，不派審', '全部候選（含背景參考）'], key='candidate_usage')
        selected_route = {'一般身份審核':'review','證據不足，待新資料（暫不合併）':'awaiting_evidence','資料更正（有可用聯絡）':'correction','無可用聯絡，不派審':'untraceable'}.get(usage)
        if selected_route:
            evidence = evidence[(evidence['route'] == selected_route) & evidence['status'].eq('pending')]
            st.caption('This filter retains the native pending comparisons from the historical routing snapshot. '
                       'Current actionable workload is shown in the overview panel; completed and background evidence remain available under all candidates.')
        if "review_warnings" not in evidence:
            evidence["review_warnings"] = ""
        only_hints = st.checkbox("只看有年級／日期提示的候選", key="only_review_hints")
        if only_hints:
            evidence = evidence[evidence["review_warnings"].fillna("").ne("")]
        st.caption("年級／日期提示供人工核實，不代表身份不同或自動拒配。親子日期差沒有拒配上限。")
        controls = st.columns(3)
        kind_names = {"identity":"孩子身份比較（同輪次或跨期）", "identity_group":"孩子群組自動確認", "family":"親子身份比較", "respondent":"成人身份比較", "dedup":"重複回應", "date":"日期資格"}
        status_names = {"confirmed":"規則通過／人工確認", "pending":"待審", "rejected":"未通過／已拒絕", "unmatched":"未配對"}
        kinds = controls[0].multiselect("候選類別", sorted(evidence["kind"].unique()), format_func=lambda x: kind_names.get(x,x))
        states = controls[1].multiselect("審核狀態", sorted(evidence["status"].unique()), format_func=lambda x: status_names.get(x,x))
        case_rules = controls[2].multiselect("候選規則", sorted(evidence["rule"].unique()), format_func=lambda x: rule_names.get(x, x))
        for column, values in [("kind", kinds), ("status", states), ("rule", case_rules)]:
            if values:
                evidence = evidence[evidence[column].isin(values)]
        st.metric('符合篩選的審核工作' if selected_route == 'review' else
                  '符合篩選的待新資料個案' if selected_route == 'awaiting_evidence' else "符合篩選的候選個案", len(evidence))
        if selected_route == 'review':
            st.caption('孩子身份每行是一個完整群組；提交 A／B 只代表證據缺口。開啟受控 Excel 的群組參考核實全組。成人身份仍按兩份家長問卷比較。')
        if selected_route == 'review':
            st.caption('這裡計算孩子群組加成人比較的審核工作數，不是參加者人數或 AC／BD／EF 組數。重現首頁研究樣本數，請切換「最終分析樣本」。')
        elif selected_route == 'awaiting_evidence':
            st.caption('每行是一個孩子群組或一宗成人比較。各已確認子群及其 T0／T1 保留；沒有新增不配對裁定。已有新問卷或具體可核實來源時再評估，這份清單不要求助手逐宗填卡。')
        else:
            st.caption('Original pair comparisons and group tasks use different units and cannot be added as people or workload. '
                       'Use the overview Current review workload panel for current assignments and final analytical samples for cohort counts.')
        st.caption("摘要只顯示欄位是否一致，不顯示完整電話、電郵或生日；詳細核實及修改使用受控Excel。")
        display_evidence = evidence.copy()
        display_evidence['route'] = display_evidence['route'].map(ROUTES)
        display_evidence["kind"] = display_evidence["kind"].map(lambda x: kind_names.get(x, x))
        display_evidence["status"] = display_evidence["status"].map(lambda x: status_names.get(x, x))
        display_evidence["rule"] = display_evidence["rule"].map(lambda x: rule_names.get(x, x))
        display_evidence = display_evidence.drop(columns=["reason"]).rename(columns={
            "case_id":"審核案例ID", "kind":"類別", "status":"狀態", "rule":"規則",
            'route':'派審分類', 'dispatch_reason':'派審分類原因',
            'group_id':'所屬審核群組', 'members':'群組提交數', 'passed_pairs':'已通過直接規則的比較數', 'missing_pairs':'缺少直接規則的比較數',
            'contact_components':'聯絡子群數', 'unresolved_pairs':'尚待核實的子群間比較數',
            "record_a":"提交A", "record_b":"提交B", "role_a":"填卷類別A", "role_b":"填卷類別B",
            "school_a":"學校A", "school_b":"學校B", "grade_a":"年級A", "grade_b":"年級B",
            "observed_at_a":"建立時間A", "observed_at_b":"建立時間B", "date_basis_a":"日期來源A", "date_basis_b":"日期來源B",
            "dob_agrees":"孩子生日一致", "gender_agrees":"孩子性別一致", "exact_contact":"聯絡完全一致",
            "one_digit_phone":"電話差一位", "school_agrees":"校名一致",
            "adult_personal_contact_agrees":"成人本人聯絡一致", "adult_any_contact_agrees":"成人任一聯絡一致", "adult_birthyear_agrees":"成人出生年份一致",
            "adult_relationship_agrees":"與孩子關係一致"})
        display_evidence = display_evidence.drop(columns=["review_warning_codes"], errors="ignore").rename(columns={"review_warnings":"年級／日期審核提示"})
        for col in ["填卷類別A", "填卷類別B"]:
            display_evidence[col] = display_evidence[col].map({"student":"學生", "parent":"家長"})
        for col in ["日期來源A", "日期來源B"]:
            display_evidence[col] = display_evidence[col].map({"system_creation":"系統建立時間", "batch_assigned_creation":"批次指定建立時間"})
        preview_limit = 1000 if selected_route == 'review' else 500
        st.caption('This table is historical native comparison/group evidence. Accepted group closures, researcher answers and '
                   'manual exclusions are accounted for in the separately bound Current review workload summary; '
                   'these retained rows do not reopen completed work.')
        st.dataframe(display_evidence.head(preview_limit), hide_index=True, width="stretch")
        if len(display_evidence) > preview_limit:
            st.caption(f"表格預覽前 {preview_limit:,} 宗；下載包含全部 {len(display_evidence):,} 宗篩選結果。")
        st.download_button("下載目前候選證據摘要", display_evidence.to_csv(index=False).encode("utf-8-sig"), "study2-pair-evidence.csv", "text/csv")

with tracking_tab:
    st.caption('Published OFF/reference administrative tracking. Analytical exclusions do not change registrations, invitations or decisions.')
    from study2.dyad_operator import STATES, FOLLOWUPS, readable_reason, safe_note
    st.subheader("永久親子追蹤")
    st.caption("每個永久ID追蹤同一孩子的家庭，換填卷家長仍沿用。兄弟姊妹各自登記。家長是否同一成人仍按BD規則判斷。")
    path = release_path / 'dyad_tracking.parquet'
    if not path.exists():
        st.info("目前發布版本尚未加入永久親子ID。登記及驗證完成後，此頁會顯示家庭追蹤。")
    else:
        @st.cache_data(show_spinner=False)
        def tracking_data(release_id, path):
            return pd.read_parquet(path)
        tracked = tracking_data(release['release_id'], str(path)).copy()
        counts = st.columns(4)
        counts[0].metric("有效親子追蹤ID", int(tracked['registration_state'].eq('active').sum()))
        counts[1].metric("暫停／尚待登記", int(tracked['registration_state'].ne('active').sum()))
        counts[2].metric("兩者完成合資格T1", int(tracked['followup_status'].eq('both_complete').sum()))
        counts[3].metric("至少一個角色未完成", int(tracked['followup_status'].isin(['student_only','parent_only','neither_complete']).sum()))
        st.caption("上列數量按目前發布的追蹤對應計算。收到回應、被選為合資格T1及已發邀請是不同狀態。待裁定項目不等於另一個已確認家庭。")
        controls = st.columns(3)
        search = controls[0].text_input("搜尋永久親子ID", key='dyad_search').strip()
        states = controls[1].multiselect("登記狀態", sorted(tracked['registration_state'].dropna().unique()),
            format_func=lambda x: STATES.get(x,x), key='dyad_states')
        followups = controls[2].multiselect("家庭T1完成情況", sorted(tracked['followup_status'].dropna().unique()),
            format_func=lambda x: FOLLOWUPS.get(x,x), key='dyad_followups')
        if search:
            search_db = connect(Path(cfg['state_dir']), readonly=True)
            try:
                from study2.dyads import canonical_id
                aliases = {r[0]:r[1] for r in search_db.execute('SELECT alias_id,canonical_id FROM dyad_aliases')}
                target = canonical_id(search,aliases)
            finally:
                search_db.close()
            if target != search:
                st.caption(f"此舊ID已經批准合併，現在對應：{target}。舊登記及邀請歷史保留。")
            tracked = tracked[tracked['dyad_id'].fillna('').str.contains(target, case=False, regex=False)]
        if states:
            tracked = tracked[tracked['registration_state'].isin(states)]
        if followups:
            tracked = tracked[tracked['followup_status'].isin(followups)]
        admin_db = connect(Path(cfg['state_dir']), readonly=True)
        try:
            from study2.dyads import exists
            if exists(admin_db):
                lifecycle = {r[0]:r[1] for r in admin_db.execute('SELECT dyad_id,lifecycle FROM dyad_registry')}
                tracked['administrative_state'] = tracked['dyad_id'].map(lifecycle)
                updated = admin_db.execute('SELECT MAX(at) FROM dyad_events').fetchone()[0]
                st.caption(f"行政登記更新時間：{updated or '尚未有紀錄'}。行政暫停／裁定可早於下一次研究發布；受控邀請匯出會重新驗證身份、日期及登記。")
            names = {'dyad_id':'永久親子ID','child_id':'本版孩子群組ID','registration_state':'本版登記狀態',
                'administrative_state':'目前行政狀態','registration_reason':'待處理原因','followup_status':'家庭T1完成情況',
                'student_school':'學生T0學校','parent_school':'家長T0所指學校',
                'student_t0_at':'學生T0日期','parent_t0_at':'家長T0日期','student_t1_at':'學生選定T1日期','parent_t1_at':'家長選定T1日期',
                'student_due_at':'學生最早T1日期','parent_due_at':'家長最早T1日期','family_due_at':'共同邀請建議日期',
                'student_date_basis':'學生T0日期依據','parent_date_basis':'家長T0日期依據',
                'student_received_count':'學生其他回應數','parent_received_count':'家長其他回應數',
                'student_short_interval_count':'學生未滿90日回應','parent_short_interval_count':'家長未滿90日回應',
                'student_other_count':'學生其他後續／重填','parent_other_count':'家長其他後續／重填',
                'identity_candidate_pending':'待核實身份候選數','adult_status':'填卷成人身份','adult_rule':'成人判斷依據',
                'analysis_t0_pair_available':'本版有T0親子測量','analysis_t1_pair_available':'本版有T1親子測量'}
            names.update(registered_student_id='首次登記學生提交',registered_parent_id='首次登記家長提交',
                         registered_at='永久登記時間',first_published_run_id='首次發布版本')
            view = tracked[[c for c in names if c in tracked]].copy()
            for col in ['registration_state','administrative_state']:
                if col in view:
                    view[col] = view[col].map(lambda x: {**STATES,'reserved':'待首次發布','retired':'已停用'}.get(x,x))
            view['followup_status'] = view['followup_status'].map(lambda x: FOLLOWUPS.get(x,x))
            view['registration_reason'] = view['registration_reason'].map(readable_reason)
            if 'adult_status' in view:
                view['adult_status'] = view['adult_status'].map({'same':'同一成人','different':'成人不同（依當版規則）','unconfirmed':'未確認'})
            view = view.rename(columns=names)
            st.dataframe(view, hide_index=True, width='stretch')
            st.download_button("下載目前家庭追蹤摘要", view.to_csv(index=False).encode('utf-8-sig'),
                               'study2-family-tracking.csv', 'text/csv')
            st.caption("摘要不包含完整電話、電郵或生日。指定執行者使用 Dyad Centre 匯出受控邀請清單及保存實際發送紀錄；此頁不會發送訊息。")
            choices = tracked['dyad_id'].dropna().unique().tolist()
            selected_id = st.selectbox("查看登記及邀請歷史", [''] + sorted(choices),
                                        format_func=lambda x: x or '請選擇永久親子ID', key='dyad_history')
            if selected_id:
                from study2.dyads import related_ids
                family_ids = related_ids(admin_db,selected_id)
                marks = ','.join('?' for _ in family_ids)
                events = pd.read_sql_query(f'SELECT at,kind,actor,reason FROM dyad_events WHERE dyad_id IN ({marks}) ORDER BY at,event_id', admin_db, params=family_ids)
                events['reason'] = events['reason'].map(safe_note)
                st.dataframe(events.rename(columns={'at':'時間','kind':'操作','actor':'執行者','reason':'理由'}), hide_index=True, width='stretch')
                invitation_events = []
                for item in admin_db.execute(f'SELECT at,payload_json FROM dyad_invitation_events WHERE dyad_id IN ({marks}) ORDER BY at,operation_id', family_ids):
                    payload = json.loads(item[1])
                    invitation_events.append({'保存時間':item[0], '角色':{'student':'學生','parent':'家長'}.get(payload['role']),
                        '事件':{'sent':'已發送','failed':'發送失敗','stop':'停止邀請','resume':'恢復邀請'}.get(payload['action']),
                        '實際日期':payload['occurred_at'],'執行者':payload['operator'],'方式':payload.get('method'),
                        '結果':safe_note(payload.get('result')),'理由':safe_note(payload['reason']),
                        '早於最早T1日期':payload.get('before_eligibility_date',False)})
                if invitation_events:
                    st.dataframe(pd.DataFrame(invitation_events), hide_index=True, width='stretch')
                else:
                    st.caption("沒有已保存的邀請紀錄。已收到T1不代表曾記錄發送邀請。")
        finally:
            admin_db.close()
