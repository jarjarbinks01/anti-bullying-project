"""Shared researcher UI for overview and longitudinal exploration."""
import json

import pandas as pd

from .descriptive_charts import category_chart, distribution_chart, subgroup_chart, transition_chart
from .descriptive_exploration import VERSION, comparison_variables, explore, mode_of, scale_display
from .descriptive_spec import GROUPS, STATUS_LABELS, variables
from .descriptives import adult_continuity_confirmed, display_table, statistics


DETAIL_FAMILIES = {
    'PHQ': 'PHQ 心理健康',
    'FQOL': 'FQOL 家庭生活質素',
    'SEC': 'SEC 社交情緒能力',
    'bullying': '欺凌指標（過去三個月）',
    'demographics': '人口特徵',
}


def _family_variables(role, family):
    """Group existing definitions for display, without combining their scores."""
    options = variables(role)
    if family in {'PHQ', 'FQOL', 'SEC'}:
        members = [v for v in options if v.key.startswith(family + '_')
                   or (family == 'PHQ' and v.key == 'phq_band')]
        return sorted(members, key=lambda v: v.key != family + '_total')
    if family == 'bullying':
        return [v for v in options if v.section == 'scales'
                and v.key.startswith(('TBV_', 'TBP_', 'CBV_', 'CBP_'))]
    return [v for v in options if v.section == role]


def cached_explore(rows,role,groups,release_id,*,paired=False,selected_variables=None,metadata=None):
    import streamlit as st
    @st.cache_data(show_spinner=False,max_entries=48)
    def compute(data,who,split,release,capability_version,complete,chosen,filters):
        return explore(data,who,split,release,paired=complete,selected_variables=chosen,metadata=filters)
    return compute(rows,role,tuple(groups),release_id,VERSION,paired,selected_variables,metadata)


def select_variable(st, label, options, key, default=0, context=None):
    ids=[v.key for v in options];labels={v.key:v.label+' ['+v.key+']' for v in options}
    base=key
    if context:
        # A new widget identity is essential when its option set changes.
        # Deleting session_state alone can leave React displaying an old label.
        key=base+'_'+context
        if st.session_state.get(base+'_context')!=context:
            previous=st.session_state.get(base+'_selection')
            if previous in ids:
                st.session_state[key]=previous
            elif previous:
                st.session_state.pop(key,None)
                st.caption('原指標不適用於目前樣本，已重新選取。')
            st.session_state[base+'_context']=context
    if key in st.session_state and st.session_state[key] not in ids:
        del st.session_state[key]
        st.caption('原指標不適用於目前樣本，已重新選取。')
    if key not in st.session_state:
        previous=st.session_state.get(base+'_selection')
        st.session_state[key]=previous if previous in ids else ids[default]
    chosen=st.selectbox(label,ids,index=None,format_func=labels.get,key=key)
    st.session_state[base+'_selection']=chosen
    return next(v for v in options if v.key==chosen)


def _number(value):
    return '缺失' if value is None or pd.isna(value) else f'{value:.2f}'


def _chart_result(st, result, var, key, histogram=False):
    if var.kind=='continuous':
        summary=result['distribution_summary'];summary=summary[summary['variable_id'].eq(var.key)&summary['wave'].ne('delta')]
        hist=result['histograms'];hist=hist[hist['variable_id'].eq(var.key)&hist['wave'].ne('delta')]
        if summary['valid_n'].sum():
            st.plotly_chart(distribution_chart(summary,var,histogram=hist if histogram else None),width='stretch',key=key)
        else:
            st.info(var.label+'：沒有有效資料')
        for r in summary.to_dict('records'):
            st.caption(f"{r['wave']} {r['group_label']}：平均 {_number(r['mean'])}，SD {_number(r['sd'])} {var.unit}；有效 N={r['valid_n']:,}")
        if 'unexpected_display_range_n' in summary and summary['unexpected_display_range_n'].sum():
            st.warning('有已判有效值超出預期量尺，圖表及下載已保留，未新增排除。')
        if summary['outside_whisker_n'].sum():
            st.caption(f"箱鬚外共有 {int(summary['outside_whisker_n'].sum()):,} 個分布觀察；仍計入平均、N 及直方圖。最小／最大值見摘要。")
    else:
        data=result['categories'];data=data[data['variable_id'].eq(var.key)]
        if data['denominator'].sum():
            st.plotly_chart(category_chart(data,var),width='stretch',key=key)
        else:
            st.info(var.label+'：沒有有效資料')


def downloads(st, result, prefix, *, stats=None, scale_family=None):
    from .descriptive_dashboard import filtered_workbook
    from .outputs import excel_safe
    basis=result['metadata']['basis']
    if stats is not None:
        # Both the overview and its grouped detail route need the
        # same reproducible CSV metadata. Do not mutate the caller's table.
        stats=stats.copy()
        stats['basis']='wave_valid'
        stats['filters_json']=json.dumps(result['metadata'],ensure_ascii=False,sort_keys=True)
    with st.expander('下載目前分析及核對明細'):
        if stats is not None:
            if scale_family:
                st.markdown('**'+DETAIL_FAMILIES[scale_family]+'：總分及分量表**')
                st.caption('數值為平均（SD）；每個指標各自計算有效 N 及缺失 N，不要求整組量表同時完整。')
                st.dataframe(display_table(stats[stats['kind'].eq('continuous')]),hide_index=True,width='stretch')
                if scale_family=='PHQ':
                    st.markdown('**PHQ 總分分組**')
                    st.caption('數值為人數／有效回答人數（%），只描述分數分布，不作臨床診斷。')
                    st.dataframe(display_table(stats[stats['variable_id'].eq('phq_band')]),hide_index=True,width='stretch')
            else:
                st.dataframe(display_table(stats),hide_index=True,width='stretch')
            st.download_button('下載每輪各自有效統計 CSV',excel_safe(stats).to_csv(index=False).encode('utf-8-sig'),
                f'study2-{prefix}-wave_valid-statistics.csv','text/csv',key=prefix+'_statistics_csv')
        labels={'distribution_summary':'分布摘要','histograms':'共同分箱及頻數','pair_summary':'完整配對摘要',
                'pair_transitions':'二元四格轉移','categories':'分類分布'}
        for name,title in labels.items():
            data=result[name]
            if data.empty:
                continue
            st.dataframe(data.drop(columns=['filters_json'],errors='ignore'),hide_index=True,width='stretch')
            st.download_button('下載'+title+' CSV',excel_safe(data).to_csv(index=False).encode('utf-8-sig'),
                f'study2-{prefix}-{basis}-{name}.csv','text/csv',key=prefix+'_'+name+'_csv')
        st.download_button('下載目前分析 Excel',filtered_workbook(stats,pd.DataFrame(),result['metadata'],exploration=result),
            f'study2-{prefix}-{basis}.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key=prefix+'_xlsx')


def render_overview(rows,role,release_id,*,prefix,groups=('all',),metadata=None):
    import streamlit as st
    result=cached_explore(rows,role,groups,release_id,metadata=metadata)
    stats=statistics(rows,role,groups,release_id)
    stats['basis']='wave_valid';stats['filters_json']=json.dumps(result['metadata'],ensure_ascii=False,sort_keys=True)
    defined={v.key:v for v in variables(role)}
    st.subheader('樣本概況')
    demo=['dem_child_gender','dem_stage','dem_child_age' if role=='student' else 'dem_relationship']
    for col,key in zip(st.columns(3),demo):
        with col:
            _chart_result(st,result,defined[key],prefix+'_demo_'+key)
    st.subheader('量表總覽')
    for col,key in zip(st.columns(3),['PHQ_total','FQOL_total','SEC_total']):
        with col:
            _chart_result(st,result,defined[key],prefix+'_main_'+key)
    if role=='parent':
        st.caption('PHQ 描述填卷成人；SEC 及欺凌描述孩子。各輪總覽可能不同填卷人，不解讀成成人逐人變化。')
    st.caption('PHQ 加總；FQOL／SEC 為題目平均。圖表使用原量尺。各輪各自有效回答，不以平均差推斷研究效果。')
    with st.expander('其他指標及九個分組比較'):
        family=st.selectbox('指標類別',list(DETAIL_FAMILIES),format_func=DETAIL_FAMILIES.get,key=prefix+'_detail_family')
        members=_family_variables(role,family)
        grouped=family in {'PHQ','FQOL','SEC'}
        if not grouped:
            var=select_variable(st,'深入查看指標',members,prefix+'_detail_'+family,context=role)
            members=[var]
        compare=st.selectbox('深入分組', ['all','gender','stage','nine'],
            format_func={'all':'目前單組','gender':'孩子性別','stage':'基線／該輪學校階段','nine':'九組（互有重疊，不可相加）'}.get,key=prefix+'_detail_group')
        extra_groups={'all':groups,'gender':('male','female'),'stage':('primary','secondary'),'nine':tuple(GROUPS)}[compare]
        selected_keys=[v.key for v in members]
        extra=cached_explore(rows,role,extra_groups,release_id,selected_variables=selected_keys,metadata=metadata)
        detail_stats=(stats if tuple(extra_groups)==tuple(groups)
                      else statistics(rows,role,extra_groups,release_id))
        detail_stats=detail_stats[detail_stats['variable_id'].isin(selected_keys)].copy()
        order={key:i for i,key in enumerate(selected_keys)}
        detail_stats=detail_stats.sort_values('variable_id',key=lambda s:s.map(order),kind='stable')
        if grouped:
            chart_result=extra
            if len(extra_groups)>1:
                chart_group=st.selectbox('分布圖分組',extra_groups,format_func=GROUPS.get,key=prefix+'_detail_chart_group_'+compare)
                st.caption('摘要表及下載保留所有已選分組；以下圖表只顯示「'+GROUPS[chart_group]+'」。')
                chart_result={name:(data[data['group'].eq(chart_group)] if isinstance(data,pd.DataFrame) and 'group' in data else data)
                              for name,data in extra.items()}
            for start in range(0,len(members),2):
                for col,var in zip(st.columns(2),members[start:start+2]):
                    with col:
                        _chart_result(st,chart_result,var,prefix+'_detail_chart_'+var.key)
        else:
            if family=='bullying':
                st.caption('觀察時段為過去三個月。')
            _chart_result(st,extra,members[0],prefix+'_detail_chart')
        if compare!='all':
            st.caption('使用目前篩選後樣本再分組；未知性別／學段不被猜填。九組互有重疊。')
        downloads(st,extra,prefix+'_detail',stats=detail_stats,scale_family=family if grouped else None)
    st.subheader('資料可用性')
    main_keys=set(demo+['PHQ_total','FQOL_total','SEC_total']+selected_keys)
    shown=stats[stats['variable_id'].isin(main_keys)].drop_duplicates(['variable_id','wave','group'])
    _availability(st,shown)
    with st.expander('全部指標的缺失原因及有效範圍'):
        _availability(st,stats.drop_duplicates(['variable_id','wave','group']))
        st.caption('有效範圍沿用已確認規則。成人性別未獨立收集，非 Qualtrics 子女人數仍屬編碼待核。原答案與樣本不受影響。')
    downloads(st,result,prefix,stats=stats)
    return stats


def _availability(st,stats):
    detail=stats[['variable','group_label','wave','valid_n','missing_n','outside_range_n','missing_detail']].copy()
    detail['missing_detail']=detail['missing_detail'].map(lambda s:'；'.join(STATUS_LABELS.get(k,k)+': '+str(v) for k,v in json.loads(s).items()) or '無')
    st.dataframe(detail.rename(columns={'variable':'指標','group_label':'分組','wave':'輪次','valid_n':'有效 N',
        'missing_n':'缺失 N','outside_range_n':'超範圍 N','missing_detail':'缺失原因'}),hide_index=True,width='stretch')


def render_workbench(rows,role,release_id,*,prefix,metadata=None):
    import streamlit as st
    options=comparison_variables(mode_of(rows),role,rows)
    if not options:
        st.info('先選擇正式跨期樣本，才可比較同一批單位。')
        return
    default=next((i for i,v in enumerate(options) if v.key=='PHQ_total'),0)
    var=select_variable(st,'跨期比較指標',options,prefix+'_variable',default,context=mode_of(rows)+'_'+role)
    view=st.radio('比較視角',['T0／T1 分布','逐人變化','子群比較'],horizontal=True,key=prefix+'_view')
    grouping=st.selectbox('子群依據',['all','gender','stage','nine'],
        format_func={'all':'全部','gender':'孩子基線性別','stage':'基線學校階段','nine':'九組（互有重疊，不可相加）'}.get,
        key=prefix+'_groups') if view=='子群比較' else 'all'
    groups={'all':('all',),'gender':('male','female'),'stage':('primary','secondary'),'nine':tuple(GROUPS)}[grouping]
    result=cached_explore(rows,role,groups,release_id,paired=True,selected_variables=[var.key],metadata=metadata)
    pairs=result['pair_summary']
    st.caption('本指標兩輪均有效的同一批單位。每項指標分開扣缺失；不是全部量表共同完整才納入。完整設定及下載標示 paired_valid。')
    missing=pairs[['group_label','pairs_n','paired_valid_n','only_t0_valid_n','only_t1_valid_n','both_missing_n']]
    st.dataframe(missing.rename(columns={'group_label':'分組','pairs_n':'正式配對 N','paired_valid_n':'兩輪均有效 N',
        'only_t0_valid_n':'只有 T0 有效','only_t1_valid_n':'只有 T1 有效','both_missing_n':'兩輪均缺失'}),hide_index=True,width='stretch')
    if role=='parent' and not adult_continuity_confirmed(rows):
        st.info('目前樣本未有完整的同一成人確認證據，PHQ 跨期比較已停用。各輪 PHQ 描述統計仍可查看。')
    st.caption(scale_display(var)['direction']+'；只作描述，不代表臨床改善或研究造成的效果。')
    if view=='T0／T1 分布':
        histogram=(st.radio('分布圖',['箱形圖','直方圖'],horizontal=True,key=prefix+'_distribution')=='直方圖'
                   if var.kind=='continuous' else False)
        _chart_result(st,result,var,prefix+'_distribution_chart',histogram)
        if var.kind=='continuous':
            st.caption('兩輪及子群共用量尺／分箱；linear 分位數，鬚為 1.5 IQR 內最遠實際值。N=1 顯示單點，不估算 SD。')
    elif view=='逐人變化':
        if var.kind=='continuous':
            hist=result['histograms'];hist=hist[hist['wave'].eq('delta')]
            summary=result['distribution_summary'];summary=summary[summary['wave'].eq('delta')]
            if summary['valid_n'].sum():
                fig=distribution_chart(summary,var,histogram=hist);fig.add_vline(x=0,line_color='#777')
                fig.update_layout(title=var.label+'（T1 減 T0）')
                st.plotly_chart(fig,width='stretch',key=prefix+'_change_chart')
            else:
                st.info('沒有兩輪均有效的差值。')
            st.dataframe(pairs[['group_label','paired_valid_n','t0_mean','t1_mean','mean_change','sd_change','up_n','same_n','down_n']].rename(columns={
                'group_label':'分組','paired_valid_n':'兩輪均有效 N','t0_mean':'T0 平均','t1_mean':'T1 平均',
                'mean_change':'平均差','sd_change':'差值 SD','up_n':'上升','same_n':'不變','down_n':'下降'}),hide_index=True,width='stretch')
            st.caption('先逐人計算 T1 減 T0；平均差等於同一批完整配對的 T1 平均減 T0 平均。不變只用 1e-9 浮點容差。')
        elif var.kind=='binary':
            st.plotly_chart(transition_chart(result['pair_transitions']),width='stretch',key=prefix+'_transition')
            r=pairs.iloc[0]
            st.write(f"T0 比例：{_number(r['t0_proportion']*100 if r['paired_valid_n'] else None)}%；T1 比例：{_number(r['t1_proportion']*100 if r['paired_valid_n'] else None)}%；差：{_number(r['change_percentage_points'])} 百分點。")
        else:
            st.info('有序分類只比較兩輪分類分布，不以分類代碼計平均差或升降。')
            _chart_result(st,result,var,prefix+'_category_change')
    else:
        st.caption('整組按 T0 錨點篩選及分組。升中或轉校不會在兩輪換組；九組互有重疊，不可相加。')
        if var.kind in {'continuous','binary'}:
            st.plotly_chart(subgroup_chart(pairs),width='stretch',key=prefix+'_subgroups')
        else:
            _chart_result(st,result,var,prefix+'_subgroups_category')
        st.caption(f"目前樣本的基線學段未知：{rows.loc[rows['wave'].eq('T0'),'anchor_school_stage'].isna().sum():,} 組；留在全部組。")
    if var.kind=='continuous':
        with st.expander('兩輪數值摘要（同一批完整配對）'):
            st.dataframe(result['distribution_summary'].drop(columns=['filters_json']),hide_index=True,width='stretch')
    downloads(st,result,prefix)
