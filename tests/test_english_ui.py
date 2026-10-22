"""Presentation must not change sample selection, identifiers or published data."""
import copy

import pandas as pd
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

from study2.english_ui import EnglishUI, display_frame, display_figure, english


def test_widget_translates_labels_but_returns_original_values_and_preserves_keys():
    app = AppTest.from_string('''
from study2.english_ui import st
choice = st.radio('閱讀方式', ['研究總覽', '跨期比較'], key='mode')
st.text('paired' if choice == '跨期比較' else 'overview')
''').run()
    assert not app.exception
    assert app.radio[0].label == 'Reading mode'
    assert app.radio[0].options == ['Research overview', 'Longitudinal comparison']
    app.radio(key='mode').set_value('跨期比較').run()
    assert not app.exception
    assert app.session_state['mode'] == '跨期比較'
    assert app.text[0].value == 'paired'


def test_nested_controls_keep_formatters_and_school_names():
    app = AppTest.from_string('''
from study2.english_ui import st
with st.expander('進階篩選（留空代表不限）'):
    left, right = st.columns(2)
    left.selectbox('填卷對象', ['s', 'p'], format_func={'s':'學生','p':'家長'}.get, key='role')
    right.multiselect('學校', ['香港中學（小學部）'], key='school')
''').run()
    assert not app.exception
    assert app.selectbox[0].options == ['Student', 'Parent']
    assert app.multiselect[0].options == ['香港中學（小學部）']
    app.selectbox(key='role').set_value('p').run()
    assert app.session_state['role'] == 'p'


def test_display_frame_is_a_copy_with_numeric_values_and_raw_fields_preserved():
    frame = pd.DataFrame({'學校A':['香港中學（小學部）'], '提交A':['SUB_example'],
                          '理由':['家長同意，另一份待核'], '孩子性別':['女'],
                          '有效 N':[123], '缺失 N':[4], '規則':['同校、聯絡及孩子身份一致']})
    before = frame.copy(deep=True)
    shown = display_frame(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert shown['School A'].iloc[0] == frame['學校A'].iloc[0]
    assert shown['Submission A'].iloc[0] == 'SUB_example'
    assert shown['Reason'].iloc[0] == frame['理由'].iloc[0]
    assert shown['Child gender'].iloc[0] == 'Female'
    assert shown['Valid N'].iloc[0] == 123
    assert shown['Missing N'].iloc[0] == 4
    assert shown['Rule'].iloc[0] == 'Same school, contact and child identity'


def test_figure_copy_preserves_data_and_translates_categories_and_hover():
    fig = go.Figure(go.Bar(x=[.25,.75],y=['符合門檻','不符合門檻'],
                          name='全部 T0',customdata=[[1,4],[3,4]]))
    fig.update_layout(title='PHQ 總分',xaxis_title='佔有效回答比例')
    before = copy.deepcopy(fig.to_plotly_json())
    shown = display_figure(fig)
    assert fig.to_plotly_json() == before
    assert tuple(shown.data[0].x) == (.25,.75)
    assert tuple(shown.data[0].y) == ('Meets threshold','Below threshold')
    assert shown.data[0].customdata == fig.data[0].customdata
    assert shown.layout.title.text == 'PHQ total'


def test_dynamic_text_and_names_are_not_confused():
    assert english('孩子分組：女') == 'Child grouping: Female'
    assert english('學校：香港中學（小學部）') == 'School: 香港中學（小學部）'
    assert english('香港中學（小學部）') == '香港中學（小學部）'
    assert english('SUB_123_RUN_456') == 'SUB_123_RUN_456'
    assert english('家長減學生香港日期差（日）') == 'Parent minus student Hong Kong date (days)'


def test_download_payload_callback_and_cache_pass_through_unchanged():
    class Recorder:
        cache_data = object()
        session_state = {}
        def download_button(self,*args,**kwargs):
            self.args=args;self.kwargs=kwargs
            return True
    target=Recorder(); ui=EnglishUI(target)
    payload='學校,樣本N\n香港中學,2\n'.encode()
    callback=lambda:None
    assert ui.download_button('下載目前分析 Excel',payload,'原始.xlsx',on_click=callback)
    assert target.args == ('Download current analysis Excel',payload,'原始.xlsx')
    assert target.kwargs['on_click'] is callback
    assert ui.cache_data is target.cache_data
    assert ui.session_state is target.session_state
