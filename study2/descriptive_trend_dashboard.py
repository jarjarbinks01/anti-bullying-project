"""Shared read-only calendar controls, plots and reproducible downloads."""
import json

from .common import PipelineError
from .descriptive_spec import DICTIONARY_VERSION, VERSION as REPORT_VERSION
from .descriptive_trends import (TABLE_NAMES, VERSION, calendar_trends, date_diagnostics, date_extent,
                                 download_table, workbook_bytes)
from .descriptive_trend_charts import indicator_chart, response_chart
from .descriptive_workbench import DETAIL_FAMILIES, _family_variables, select_variable


def cached_trends(rows, role, release_id, **settings):
    from .english_ui import st

    @st.cache_data(show_spinner=False, max_entries=48)
    def compute(data, who, release, policy_version, options):
        return calendar_trends(data, who, release, **options)

    return compute(rows, role, release_id, (VERSION, REPORT_VERSION, DICTIONARY_VERSION), settings)


def render_trends(rows, role, release_id, *, prefix, metadata=None):
    from .english_ui import st

    st.subheader('時段趨勢')
    st.caption('按香港填卷日期查看已發布的正式選定回應。各時段填卷者可以不同；學校、來源及樣本組成可能影響數值，不能解讀為逐人變化或研究效果。')
    controls = st.columns(3)
    interval = controls[0].selectbox('時間間隔', ['month', 'week'],
        format_func={'month': '每月', 'week': '每週（星期一至星期日）'}.get, key=prefix+'_interval')
    wave_choice = controls[1].selectbox('趨勢輪次', ['both', 'T0', 'T1'],
        format_func=lambda v: 'T0及T1（分開顯示）' if v == 'both' else v, key=prefix+'_waves')
    include_batch = controls[2].selectbox('趨勢日期來源', [False, True],
        format_func=lambda v: '加入批次指定日期' if v else '系統記錄及人工核實日期', key=prefix+'_batch')
    waves = ('T0', 'T1') if wave_choice == 'both' else (wave_choice,)
    try:
        extent = date_extent(rows, include_batch=include_batch, waves=waves)
    except PipelineError as exc:
        st.info(str(exc)+'。此頁不讀取其他版本或即時資料庫補資料。')
        return None
    if include_batch:
        st.warning('已加入批次指定日期；圖中聚集可能反映批次登記，不能當作實際填卷高峰。')
    else:
        st.caption('批次指定日期預設不納入趨勢；此選項不改變正式T0／T1及年齡計算。')
    if extent is None:
        st.info('目前樣本、輪次及日期來源沒有可用填卷日期。請核對篩選或日期來源。')
        st.dataframe(date_diagnostics(rows).rename(columns={'wave': '輪次',
            'date_quality': '日期分類', 'date_quality_label': '日期來源', 'input_n': '回應N'}),
            hide_index=True, width='stretch')
        return None
    context = (release_id, role, (metadata or {}).get('mode'), (metadata or {}).get('branch'))
    key = prefix+'_dates'
    if st.session_state.get(prefix+'_date_context') != context or key not in st.session_state:
        if prefix+'_date_context' in st.session_state:
            st.caption('發布版本、樣本或填卷對象已改變，日期已重設為目前可用範圍。')
        st.session_state[key] = extent
        st.session_state[prefix+'_date_context'] = context
    # Explicit bounds keep the date picker valid for data outside today's decade.
    from datetime import date
    dates = st.date_input('填卷日期範圍（香港日期，包含首尾兩日）',
        min_value=date(1678, 1, 1), max_value=date(2261, 12, 31),
        format='YYYY/MM/DD', key=key)
    if len(dates) != 2:
        st.info('請選擇開始及結束日期。')
        return None
    family = st.selectbox('趨勢指標類別', list(DETAIL_FAMILIES),
        format_func=DETAIL_FAMILIES.get, key=prefix+'_family')
    members = _family_variables(role, family)
    if family not in {'PHQ', 'FQOL', 'SEC'}:
        members = [select_variable(st, '趨勢指標', members, prefix+'_variable_'+family, context=role)]
    if family == 'bullying':
        st.caption('月份代表填卷月份；問卷回顧過去三個月，圖表不是該月事件發生率。')
    if role == 'parent' and family == 'PHQ':
        st.caption('PHQ描述每份問卷的填卷成人；目前只計各期回應，不提供成人逐人差值。')
    try:
        result = cached_trends(rows, role, release_id, start=dates[0], end=dates[1],
            interval=interval, include_batch=include_batch, waves=waves,
            variable_ids=[v.key for v in members], metadata=metadata)
    except (PipelineError, ValueError) as exc:
        st.info(str(exc))
        return None
    n = result['counts'].groupby('wave')['sample_n'].sum()
    metrics = st.columns(2)
    for col, wave in zip(metrics, ['T0', 'T1']):
        col.metric('期間內 '+wave+' 回應 N', f'{int(n.get(wave, 0)):,}' if wave in waves else '未選取')
    audit = result['exclusions']
    last = audit[audit['stage'].eq('指定期間內')]['remaining_n'].sum()
    excluded = audit['excluded_n'].sum()
    st.caption(f'現有篩選後 {len(rows):,} 份＝期間內 {last:,} 份＋依序排除 {excluded:,} 份。每份只計一次；兩輪合計是回應份數。')
    with st.expander('核對日期排除數及來源'):
        st.dataframe(audit[['wave', 'stage', 'remaining_n', 'excluded_n']].rename(columns={
            'wave': '輪次', 'stage': '步驟', 'remaining_n': '保留N', 'excluded_n': '本步排除N'}),
            hide_index=True, width='stretch')
        st.dataframe(result['date_quality'][['wave', 'date_quality_label', 'input_n', 'included_n']].rename(columns={
            'wave': '輪次', 'date_quality_label': '日期來源', 'input_n': '日期篩選前N', 'included_n': '期間內N'}),
            hide_index=True, width='stretch')
    st.plotly_chart(response_chart(result['counts']), width='stretch', key=prefix+'_response_chart')
    st.caption('＊只涵蓋部分週／月；空時段保留。滑鼠移至圖上可核對實際日期及分母。')
    for start in range(0, len(members), 2):
        for col, var in zip(st.columns(2), members[start:start+2]):
            with col:
                st.plotly_chart(indicator_chart(result['statistics'], var), width='stretch', key=prefix+'_chart_'+var.key)
    st.subheader('每期樣本組成')
    composition = result['composition']
    from .descriptive_trends import COMPOSITION
    dimension = st.selectbox('核對組成', list(COMPOSITION), format_func=COMPOSITION.get, key=prefix+'_composition')
    st.caption('以下使用該輪實際回應資料；上方樣本篩選仍沿用該分析模式既定錨點。未知值另列，不猜填。')
    display = composition[composition['dimension'].eq(dimension)]
    display = display[['covered_start', 'covered_end', 'wave', 'category', 'count', 'denominator', 'proportion']].copy()
    from .dashboard_views import SOURCE_NAMES
    labels = SOURCE_NAMES if dimension == 'source_type' else {'0': '男', '1': '女'} if dimension == 'dem_child_gender' else {'primary': '小學', 'secondary': '中學'} if dimension == 'school_stage' else {}
    display['category'] = display['category'].map(lambda v: labels.get(v, v))
    st.dataframe(display.rename(columns={'covered_start': '開始', 'covered_end': '結束', 'wave': '輪次',
        'category': '類別', 'count': '回應N', 'denominator': '分母', 'proportion': '比例'}), hide_index=True, width='stretch')
    with st.expander('下載目前分析及核對明細'):
        st.caption('每個指標各自扣除缺失；全期間統計直接使用相關回應，不平均各月平均。SD為樣本標準差，N=1不估算。')
        for name, title in TABLE_NAMES.items():
            data = result[name]
            st.markdown('**'+title+'**')
            st.dataframe(data.drop(columns=['release_id', 'basis', 'trend_version'], errors='ignore'), hide_index=True, width='stretch')
            st.download_button('下載'+title+' CSV', download_table(result, name).to_csv(index=False).encode('utf-8-sig'),
                f'study2-{prefix}-calendar_response-{name}.csv', 'text/csv', key=prefix+'_csv_'+name)
        st.json(result['metadata'])
        st.download_button('下載時段趨勢 Excel', workbook_bytes(result),
            f'study2-{prefix}-calendar_response.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', key=prefix+'_xlsx')
        st.download_button('下載時段趨勢設定', json.dumps(result['metadata'], ensure_ascii=False, indent=2).encode('utf-8'),
            f'study2-{prefix}-calendar_response-settings.json', 'application/json', key=prefix+'_settings')
    return result
