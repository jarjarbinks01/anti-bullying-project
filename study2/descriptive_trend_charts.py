"""Charts consume only finished calendar-response aggregates."""
import pandas as pd
import plotly.graph_objects as go

from .descriptive_charts import COLORS


def _labels(rows):
    return rows['period_id'] + rows['partial_period'].map({True: '＊', False: ''})


def _layout(figure, rows, title, ytitle):
    labels = list(dict.fromkeys(_labels(rows)))
    figure.update_layout(title={'text': title, 'font': {'size': 15}}, height=360,
        xaxis_title='填卷時段（＊為部分時段）', yaxis_title=ytitle,
        margin=dict(l=10, r=10, t=60, b=100),
        legend={'orientation': 'h', 'y': -.4},
        # Month-like strings otherwise become a date axis and Plotly silently
        # drops the starred partial periods as invalid dates.
        xaxis={'type': 'category', 'categoryorder': 'array', 'categoryarray': labels,
               'tickangle': -45 if len(labels) > 6 else 0})
    return figure


def response_chart(counts):
    figure = go.Figure()
    for wave, block in counts.groupby('wave', sort=False):
        figure.add_trace(go.Bar(name=wave, x=_labels(block), y=block['sample_n'],
            marker_color=COLORS[wave],
            customdata=block[['covered_start', 'covered_end', 'batch_date_n', 'manual_date_n']],
            hovertemplate='%{customdata[0]} 至 %{customdata[1]}<br>回應 N=%{y}'
                '<br>批次日期 N=%{customdata[2]}<br>人工核實日期 N=%{customdata[3]}<extra>%{fullData.name}</extra>'))
    figure.update_layout(barmode='group')
    return _layout(figure, counts, '每期回應數', '回應份數')


def indicator_chart(stats, variable):
    """Every bin remains in each trace, so missing values break the line."""
    rows = stats[stats['variable_id'].eq(variable.key)]
    continuous = variable.kind == 'continuous'
    figure = go.Figure()
    for (wave, code), block in rows.groupby(['wave', 'category_code'], sort=False, dropna=False):
        category = '' if continuous or variable.kind == 'binary' else str(block['category'].iloc[0])
        custom = block[['covered_start', 'covered_end', 'sample_n', 'valid_n', 'missing_n']].copy()
        if continuous:
            custom['detail'] = block['sd'].map(lambda v: '缺失' if pd.isna(v) else f'{v:.3f}')
            hover = '平均=%{y:.3f}<br>SD=%{customdata[5]}'
        else:
            custom['detail'] = block['numerator'].fillna(0).astype(int)
            hover = '比例=%{y:.1%}<br>分子=%{customdata[5]}；分母=%{customdata[3]}'
        style = {}
        if category:
            codes = [c for c, _ in variable.categories]
            style['dash'] = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot'][codes.index(code) % 6]
        figure.add_trace(go.Scatter(name=wave + ('：' + category if category else ''),
            x=_labels(block), y=block['mean' if continuous else 'proportion'],
            mode='lines+markers', connectgaps=False, line={'color': COLORS[wave], **style},
            customdata=custom,
            hovertemplate='%{customdata[0]} 至 %{customdata[1]}<br>' + hover
                + '<br>樣本 N=%{customdata[2]}；有效 N=%{customdata[3]}；缺失 N=%{customdata[4]}<extra>%{fullData.name}</extra>'))
    title = variable.label.replace('：', '：<br>')
    _layout(figure, rows, title, variable.unit if continuous else '佔有效回答比例')
    if not continuous:
        figure.update_yaxes(range=[0, 1], tickformat='.0%')
    if len(figure.data) > 6:
        figure.update_layout(height=500, margin={'b': 170})
    return figure
