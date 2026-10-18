"""Plotly adapters over finished, aggregate exploration results only."""
import plotly.graph_objects as go

COLORS = {'T0':'#247b91','T1':'#df8751','delta':'#386d6b'}


def distribution_chart(summary, variable, *, histogram=None):
    fig=go.Figure()
    if histogram is not None:
        for (group,wave),block in histogram.groupby(['group_label','wave'],sort=False):
            fig.add_trace(go.Bar(name=f'{group} {wave}', x=(block['bin_left']+block['bin_right'])/2,
                y=block['count'],width=(block['bin_right']-block['bin_left'])*.95,
                marker_color=COLORS[wave],opacity=.7,
                customdata=block[['bin_left','bin_right','denominator','right_inclusive']],
                hovertemplate='%{customdata[0]:.3f} 至 %{customdata[1]:.3f}<br>n=%{y} / %{customdata[2]}<extra>%{fullData.name}</extra>'))
        fig.update_layout(barmode='overlay',xaxis_title=variable.unit,yaxis_title='有效人數')
    else:
        for row in summary.to_dict('records'):
            if not row['valid_n']:
                continue
            name=f"{row['group_label']} {row['wave']}"
            if row['valid_n']==1:
                fig.add_trace(go.Scatter(name=name,x=[name],y=[row['mean']],mode='markers',
                    marker={'color':COLORS[row['wave']],'size':10},text=['N=1'],hovertemplate='%{y:.3f}<br>N=1<extra></extra>'))
            else:
                fig.add_trace(go.Box(name=name,x=[name],q1=[row['q1']],median=[row['median']],q3=[row['q3']],
                    lowerfence=[row['lower_whisker']],upperfence=[row['upper_whisker']],
                    marker_color=COLORS[row['wave']],boxpoints=False,
                    hovertemplate='Q1=%{q1:.3f}<br>中位=%{median:.3f}<br>Q3=%{q3:.3f}<extra>%{fullData.name}</extra>'))
        values=summary[['minimum','maximum']].stack()
        if len(values):
            lo,hi=values.min(),values.max();pad=max((hi-lo)*.08,.1)
            fig.update_yaxes(range=[lo-pad,hi+pad])
        fig.update_layout(yaxis_title=variable.unit,showlegend=False)
    fig.update_layout(title=variable.label,height=310,margin=dict(l=10,r=10,t=45,b=75 if histogram is not None else 45),
                      legend={'orientation':'h','yanchor':'top','y':-.28,'x':0},font={'size':13})
    return fig


def category_chart(categories, variable):
    fig=go.Figure()
    for wave,block in categories.groupby('wave',sort=False):
        labels=block['category'] if block['group'].nunique()==1 else block['group_label']+'：'+block['category']
        text=[f"{r['count']:,}/{r['denominator']:,} ({r['proportion']:.1%})" if r['denominator'] else '無有效回答'
              for r in block.to_dict('records')]
        fig.add_trace(go.Bar(name=wave,x=block['proportion'],y=labels,orientation='h',
            text=text,textposition='auto',marker_color=COLORS[wave],
            hovertemplate='%{text}<extra>%{fullData.name}</extra>'))
    title=variable.label.replace('：','：<br>')
    categories_n=len(categories.drop_duplicates(['group','category_code']))
    height=max(310,170+44*categories_n);top=70 if '<br>' in title else 45
    fig.update_layout(title={'text':title,'font':{'size':14}},barmode='group',height=height,
        margin=dict(l=10,r=10,t=top,b=95),
        legend={'orientation':'h','yanchor':'top','y':-65/max(50,height-top-95),'x':0},xaxis_title='佔有效回答比例')
    fig.update_xaxes(range=[0,1],tickformat='.0%')
    return fig


def transition_chart(transitions):
    fig=go.Figure(go.Bar(x=transitions['transition'],y=transitions['count'],
        text=[f"{r['count']:,}/{r['denominator']:,}" for r in transitions.to_dict('records')],textposition='auto',
        marker_color=['#8baeb0','#247b91','#df8751','#386d6b']))
    title=transitions['variable'].iloc[0].replace('：','：<br>')
    fig.update_layout(title={'text':title,'font':{'size':14}},height=350,yaxis_title='兩輪均有效人數',
        margin=dict(l=10,r=10,t=75,b=40))
    return fig


def subgroup_chart(pairs):
    numeric=pairs['kind'].iloc[0]=='continuous'
    field='mean_change' if numeric else 'change_percentage_points'
    label='平均差（T1 減 T0）' if numeric else '百分點差（T1 減 T0）'
    fig=go.Figure(go.Bar(x=pairs['group_label'],y=pairs[field],
        text=[f"N={int(n):,}" for n in pairs['paired_valid_n']],textposition='outside',marker_color='#247b91'))
    fig.add_hline(y=0,line_color='#777')
    title=pairs['variable'].iloc[0].replace('：','：<br>')
    fig.update_layout(title={'text':title,'font':{'size':14}},height=370,yaxis_title=label,
        margin=dict(l=10,r=10,t=75,b=40))
    return fig
