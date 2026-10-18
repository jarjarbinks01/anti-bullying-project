"""Independent parent page. All data comes from the published release."""
from .parent_panel import ADULT, CHILD, BRANCH_NAMES
from .parent_panel_views import (panel_cohort, pairs_for_cohort, read_panel,
                                 reconcile_panel, verify_panel)

ADULT_RULES = {
    'same_adult_reported_birth_personal_contact': '成人出生年份及精確本人聯絡一致',
    'same_adult_reported_birth_any_exact_contact': '成人出生年份及任一精確聯絡一致',
    'reviewer_confirmed_same_adult': '人工確認同一成人',
    'reviewer_rejected_same_adult': '人工確認不同成人',
    'experimental_adult_one_digit_phone': '成人電話差一位（只供試算）',
    'no_exact_adult_contact': '沒有精確相同聯絡',
    'adult_birth_year_missing_or_invalid': '成人出生年份缺失或無效',
    'reported_birth_year_changed': '成人出生年份不同',
    'adult_decision_reopened': '成人證據更新，重新待審',
}
VERIFICATIONS = {'MATCH': '已核實相同（來源版本一致）', 'NONMATCH': '已核實不同',
                'UNRESOLVED': '人工資料不足', 'NOT_REVIEWED_CURRENT_VERSIONS': '尚無本版本核實標籤'}


def _pair_display(pairs, branch):
    columns = {
        'child_id': '孩子身份ID', 't0': '獨立T0提交ID', 't1': '獨立T1提交ID',
        'interval_days': '兩次相隔日數', 'T0_observed_at': 'T0建立時間', 'T1_observed_at': 'T1建立時間',
        'T0_school': 'T0學校', 'T1_school': 'T1學校', 'T0_grade': 'T0年級', 'T1_grade': 'T1年級',
        'T0_claimed_wave': 'T0問卷原標籤', 'T1_claimed_wave': 'T1問卷原標籤',
        'T0_anchored_wave': 'T0問卷的學生錨定輪次', 'T1_anchored_wave': 'T1問卷的學生錨定輪次',
        'adult_status': '成人身份狀態', 'adult_rule': '成人規則', 'verification_label': '人工核實標記',
        'T0_adult_identity_exception': 'T0人工例外', 'T1_adult_identity_exception': 'T1人工例外',
    }
    if branch == ADULT:
        columns['different_child_report_T1'] = '與孩子分支T1不同'
    display = pairs.reindex(columns=columns).copy()
    display['adult_status'] = display['adult_status'].map({'confirmed': '規則通過／人工確認',
                                                         'pending': '尚未確認', 'rejected': '未通過／人工拒絕'})
    display['adult_rule'] = display['adult_rule'].map(lambda v: ADULT_RULES.get(v, v))
    display['verification_label'] = display['verification_label'].map(VERIFICATIONS)
    for col in ['T0_adult_identity_exception', 'T1_adult_identity_exception']:
        display[col] = display[col].map({'accepted_typo_unknown_year': '已接受年份錯字，正確年份未確認'}).fillna('')
    return display.rename(columns=columns)


def render_parent_panel(folder, summary):
    import streamlit as st
    from pathlib import Path
    import pandas as pd
    from .dashboard_views import SOURCE_NAMES
    from .outputs import descriptive_summary, excel_safe

    details = summary.get('independent_parent')
    if details is None:
        st.info('此歷史版本未包含獨立家長分析。')
        return
    data = read_panel(folder)
    verify_panel(data, details)
    st.subheader('獨立家長分析')
    st.caption('不要求學生問卷作錨點。沿用已確認孩子身份；最早合資格家長回應為共同T0，T1至少相隔90日。這些數字另行計算，不加進首頁BD／E／F／EF。')
    counts = st.columns(3)
    for col, label, key in zip(counts, ['獨立家長基線', '同一孩子跨期（可換填卷人）', '同一成人跨期'],
                               ['baselines', 'child_report_pairs', 'same_adult_pairs']):
        col.metric(label, f"{details[key]:,}")
    st.caption(f"同一成人樣本中有 {details['same_adult_alternative_T1']:,} 組使用不同的T1問卷。成人出生年份缺失或不同，不會自行否定孩子身份；尚未確認同一成人，也不等於已確認換了家長。逐宗人工裁定例外另列，未知年份不猜填。")
    branch = st.selectbox('獨立家長樣本', [CHILD, ADULT], format_func=BRANCH_NAMES.get, key='ipp_branch')
    controls = st.columns(3)
    wave = controls[0].selectbox('明細及回應下載輪次（下方統計固定兩輪）', ['T0', 'T1'], key='ipp_wave')
    options=['跨期樣本','全部獨立基線及追蹤'] if branch==CHILD else ['跨期樣本']
    scope_key='ipp_cohort_'+branch
    if st.session_state.get('ipp_cohort_branch')!=branch or scope_key not in st.session_state or st.session_state.get(scope_key) not in options:
        previous=st.session_state.get('ipp_cohort_selection','跨期樣本')
        st.session_state[scope_key]=previous if previous in options else '跨期樣本'
        if previous not in options:
            controls[1].caption('同一成人分支只提供跨期樣本，已清除全部基線選項。')
        st.session_state['ipp_cohort_branch']=branch
    selected_scope=controls[1].selectbox('獨立家長分析範圍',options,index=None,key=scope_key)
    st.session_state['ipp_cohort_selection']=selected_scope
    paired_only=selected_scope=='跨期樣本'
    mainstream = controls[2].selectbox('獨立家長學校範圍', ['全部學校', '只限主流學校'], key='ipp_scope') == '只限主流學校'
    from .descriptive_spec import VERSION
    new_reports = bool(summary.get('descriptive')) and summary['descriptive'].get('version') == VERSION
    if new_reports:
        from .descriptives import independent_cohort, filter_cohort
        measurements = pd.read_parquet(Path(folder)/'descriptive_measurements.parquet')
        report_rows = independent_cohort(data['analysis'], measurements, branch, paired_only)
        scope_report, _ = filter_cohort(report_rows, mainstream=mainstream)
        unfiltered = report_rows[report_rows['wave'].eq(wave)]
        scope_rows = scope_report[scope_report['wave'].eq(wave)]
    else:
        unfiltered = panel_cohort(data['analysis'], branch, wave, paired_only)
        scope_rows = panel_cohort(data['analysis'], branch, wave, paired_only, mainstream)
    filters = st.columns(4)
    gender = filters[0].selectbox('獨立樣本孩子性別', ['全部', '男', '女', '缺失'], key='ipp_gender')
    type_col = 'anchor_school_stage' if new_reports else 'school_type'
    school_col = 'anchor_school' if new_reports else 'school'
    source_col = 'anchor_source_type' if new_reports else 'source_type'
    for key, col in [('ipp_types',type_col), ('ipp_schools',school_col), ('ipp_sources',source_col)]:
        valid = set(scope_rows[col].dropna())
        if key in st.session_state and not set(st.session_state[key]) <= valid:
            st.session_state[key] = []
            st.caption('分支或資料範圍已改變，不再適用的進階篩選已清除。')
    types = filters[1].multiselect('獨立樣本學校類型', sorted(scope_rows[type_col].dropna().unique()), key='ipp_types')
    schools = filters[2].multiselect('獨立樣本學校', sorted(scope_rows[school_col].dropna().unique()), key='ipp_schools')
    sources = filters[3].multiselect('獨立樣本資料來源', sorted(scope_rows[source_col].dropna().unique()),
                                   format_func=lambda x: SOURCE_NAMES.get(x, x), key='ipp_sources')
    if new_reports:
        report_selected, _ = filter_cohort(report_rows, mainstream=mainstream, schools=schools,
                                           sources=sources, school_types=types)
        if gender != '全部':
            wanted = {'男': '0', '女': '1', '缺失': ''}[gender]
            report_selected = report_selected[report_selected['anchor_gender'].fillna('').eq(wanted)].copy()
        rows = report_selected[report_selected['wave'].eq(wave)].copy()
        st.caption('新版描述比較及明細按獨立家長T0的孩子性別、學校階段、學校與來源固定篩選整組；實際每輪資料仍保留。')
    else:
        rows = panel_cohort(data['analysis'], branch, wave, paired_only, mainstream,
                            None if gender == '全部' else {'男': '0', '女': '1', '缺失': ''}[gender], schools, types, sources)
    metrics = st.columns(3)
    metrics[0].metric('此輪未篩選 N', len(unfiltered))
    metrics[1].metric('學校範圍後 N', len(scope_rows))
    metrics[2].metric('目前獨立樣本 N', len(rows))
    st.caption(f'學校範圍排除 {len(unfiltered)-len(scope_rows):,} 份，其餘篩選排除 {len(scope_rows)-len(rows):,} 份。N是此輪回應數。預設跨期樣本、全部學校且清除其他篩選，可重現上方對應跨期組數。')
    st.subheader('配對明細')
    pairs = pairs_for_cohort(data['pairs'], rows, branch, wave)
    display = _pair_display(pairs, branch)
    st.dataframe(display, hide_index=True, width='stretch')
    st.caption('每行是一組兩份回應。選全部基線時，尚無T1的基線不會出現在配對表，可從選定回應下載查看。兩套輪次及原始輪次分開保存。')
    st.download_button('下載獨立家長配對明細', excel_safe(display).to_csv(index=False).encode('utf-8-sig'),
                       'study2-independent-parent-pairs.csv', 'text/csv')
    st.download_button('下載目前獨立家長選定回應', excel_safe(rows).to_csv(index=False).encode('utf-8-sig'),
                       'study2-independent-parent-responses.csv', 'text/csv')
    st.subheader('獨立家長描述統計')
    if new_reports:
        st.caption('上方輪次只控制明細及該輪回應下載；以下統計固定把 T0／T1 並排。')
        from .descriptive_workbench import render_overview,render_workbench
        from .descriptive_dashboard import _capability
        reading=st.radio('獨立家長統計閱讀方式',['研究總覽','跨期比較'],horizontal=True,key='ipp_reading')
        metadata={'branch':branch,'paired_only':paired_only,'mainstream':mainstream,
                  'gender':gender,'schools':schools,'sources':sources,'school_types':types}
        if reading=='研究總覽':
            render_overview(report_selected,'parent',summary['release_id'],prefix='ipp_overview',metadata=metadata)
        elif not paired_only:
            st.info('全部基線及追蹤不等於完整跨期樣本。請先把「獨立家長分析範圍」明確選為跨期樣本，再核對新 N。')
        elif not _capability(folder,summary):
            st.info('此發布未提供跨期探索能力；研究總覽仍可閱讀。')
        else:
            render_workbench(report_selected,'parent',summary['release_id'],prefix='ipp_workbench',metadata=metadata)
    else:
        _legacy_statistics(rows)

    _render_panel_audit(data, details)


def _legacy_statistics(rows):
    import streamlit as st
    from .outputs import descriptive_summary
    st.info('此歷史版本未包含新版人口特徵；以下沿用舊量表摘要。')
    gender_counts = rows['gender'].fillna('').astype(str).map({'0': '男', '1': '女', '': '缺失'}).fillna('其他').value_counts().rename_axis('孩子性別').reset_index(name='回應數')
    gender_counts['分母'] = len(rows)
    gender_counts['比例'] = gender_counts['回應數'] / len(rows) if len(rows) else 0
    st.dataframe(gender_counts, hide_index=True, width='stretch')
    ages = rows['age_at_observation'].dropna()
    st.caption(f'孩子觀察時年齡：有效N={len(ages):,}；缺失N={len(rows)-len(ages):,}。沿用共用日期可信度及計分規則。')
    st.caption('PHQ描述填卷成人；孩子分支可換填卷人，不能將其PHQ差異直接當作同一成人變化。量表只使用完整所需題目，每項另列有效N及缺失N。')
    stats = descriptive_summary(rows)
    st.dataframe(stats.rename(columns={'metric': '指標', 'sample_n': '樣本N', 'valid_n': '有效N',
                                      'missing_n': '缺失N', 'mean_or_proportion': '平均／比例', 'sd': '標準差'}),
                 hide_index=True, width='stretch')
    st.download_button('下載獨立家長描述統計', stats.to_csv(index=False).encode('utf-8-sig'),
                       'study2-independent-parent-descriptives.csv', 'text/csv')


def _render_panel_audit(data, details):
    import streamlit as st
    with st.expander('成人電話差一位試算及核實狀態'):
        st.warning('以下是未納入正式同一成人樣本的規則試算，不是已確認配對或準確率。人工限制、出生年份及整組矛盾檢查仍然有效。')
        import pandas as pd
        count_labels = {'one_digit_candidates': '電話差一位候選比較', 'experiment_pairs': '試算跨期組數',
                        'experiment_overlap_children': '與正式樣本共同的孩子群組', 'experiment_added_children': '試算新增孩子群組',
                        'experiment_held_exact_children': '試算因歧義暫緩的原正式群組', 'experiment_changed_T1': '共同群組中T1改變'}
        st.dataframe(pd.DataFrame([{'項目': title, '數量': details[key]} for key, title in count_labels.items()]),
                     hide_index=True, width='stretch')
        sensitivity = data['sensitivity'].rename(columns={'child_id': '孩子身份ID', 't0': '共同T0提交ID',
            'exact_T1': '正式同一成人T1', 'experiment_T1': '試算T1', 'experiment_rule': '試算規則', 'comparison': '與正式結果比較'})
        sensitivity['與正式結果比較'] = sensitivity['與正式結果比較'].map({
            'experiment_added_child': '只在試算出現', 'experiment_held_exact_child': '試算暫緩，正式保留',
            'different_T1': '選中不同T1', 'identical_pair': '兩份選取一致'})
        sensitivity['試算規則'] = sensitivity['試算規則'].map(lambda v: ADULT_RULES.get(v, v))
        st.dataframe(sensitivity.drop(columns=['experimental_only']), hide_index=True, width='stretch')
        candidate_columns = {'child_id': '孩子身份ID', 't0': '獨立T0提交ID', 't1': '後續提交ID',
                             'interval_days': '相隔日數', 'exact_status': '正式成人規則狀態',
                             'exact_rule': '正式成人規則', 'one_digit_candidate': '電話差一位候選',
                             'verification_label': '人工核實標記'}
        candidates = data['candidates'].reindex(columns=candidate_columns).copy()
        candidates['exact_status'] = candidates['exact_status'].map({'confirmed': '規則通過／人工確認', 'pending': '尚未確認', 'rejected': '未通過／人工拒絕'})
        candidates['exact_rule'] = candidates['exact_rule'].map(lambda v: ADULT_RULES.get(v, v))
        candidates['verification_label'] = candidates['verification_label'].map(VERIFICATIONS)
        st.dataframe(candidates.rename(columns=candidate_columns), hide_index=True, width='stretch')
        st.download_button('下載成人電話差一位試算', data['sensitivity'].to_csv(index=False).encode('utf-8-sig'),
                           'study2-parent-one-digit-experiment.csv', 'text/csv')
        st.caption('核實標記只計同版本的既有人工標籤。NOT_REVIEWED_CURRENT_VERSIONS表示尚無本版本核實標籤；不能用child_id一致當作準確率。')
    with st.expander('核對發布數量及處理狀態'):
        st.dataframe(reconcile_panel(data, details), hide_index=True, width='stretch')
        st.write(details['audit_status_counts'])
        st.caption('全部家長追查表及完整本機Excel位於發布資料夾的 independent_parent.xlsx。原始提交不刪除，排除及日期待處理另留原因。')
