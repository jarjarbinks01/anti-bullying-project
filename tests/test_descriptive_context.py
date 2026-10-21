"""「目前分析」摘要卡的合成案例測試。

只用合成樣本、顯示名稱及訊息；不讀研究資料、不啟動正式 dashboard。
"""
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from study2.descriptive_context import (APPLIED_TITLE, CONTEXT_TITLE, N_EXPLANATION, NO_ADVANCED_FILTER,
                                        N_LABEL_OVERVIEW, N_LABEL_TREND, AnalysisContext, n_label, n_value)
from study2.descriptive_reports import write_reports
from test_descriptives import inputs

LONG_SCHOOL = '香海正覺蓮社佛教黃藻森學校（深水埗）、聖公會聖馬利亞堂莫慶堯中學（九龍城）'
OVERVIEW_REMINDER = ('兩輪各自有效回答。A–D／E–F 可以不同人；逐人變化請明確選取「跨期比較」的樣本及新 N。'
                     '完整設定及下載標示 wave_valid。')
PAIRED_REMINDER = ('這是明確選定的正式跨期樣本。與總覽的各輪 A–D／E–F 人數可能不同；指標缺失另扣。'
                   'BD 使用其實際選定 T1。')
TREND_REMINDER = ('以下按填卷日期篩選正式選定回應，輪次不重新選取；每期各自有效回答，'
                  '完整設定及下載標示 calendar_response。')


def context(**overrides):
    """合成分析摘要；預設為研究總覽、主流學校、全部孩子分組。"""
    values = dict(reading='研究總覽', sample='各輪全部樣本（A／B／C／D）', respondent='學生',
                  school_scope='主流學校', group='全部', anchor='該輪回應', n_t0=2547, n_t1=2310,
                  applied=(), reminder=OVERVIEW_REMINDER)
    values.update(overrides)
    return AnalysisContext(**values)


def render(card):
    """以合成摘要跑一次 Streamlit 呈現。"""
    script = ('import streamlit as st\n'
              'from study2.descriptive_context import AnalysisContext, render_analysis_context\n'
              f'render_analysis_context({card!r})\n')
    return AppTest.from_string(script).run()


def card_of(app):
    """取出帶有 N metric 的摘要卡容器。"""
    for container in app.container:
        if container.metric:
            return container
    raise AssertionError('未找到帶有 N metric 的摘要卡容器')


def captions_of(app):
    return [caption.value for caption in card_of(app).caption]


# --- 呈現層 ---

def test_case_a_overview_card_shows_analysis_setting_n_and_reminder():
    app = render(context())
    assert not app.exception
    assert [s.value for s in app.subheader] == [CONTEXT_TITLE]
    captions = captions_of(app)
    assert '閱讀方式：研究總覽' in captions
    assert '分析樣本：各輪全部樣本（A／B／C／D）' in captions
    assert '填卷對象：學生' in captions
    assert '學校範圍：主流學校' in captions
    assert '孩子分組：全部' in captions
    assert '分組依據：該輪回應' in captions
    assert N_EXPLANATION in captions
    assert NO_ADVANCED_FILTER in captions
    assert OVERVIEW_REMINDER in captions
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_OVERVIEW, '2,547 / 2,310')]


def test_case_a_card_is_directly_visible_and_not_hidden_in_an_expander():
    app = render(context())
    assert not app.expander
    assert app.container


def test_case_b_applied_conditions_are_all_visible_with_full_names():
    applied = (('學校', LONG_SCHOOL),
               ('資料來源', 'Qualtrics'),
               ('孩子身份配對規則', '同一學校及姓名一致、轉校跟進'))
    app = render(context(applied=applied))
    assert not app.exception
    captions = captions_of(app)
    assert any(APPLIED_TITLE in m.value for m in card_of(app).markdown)
    for label, value in applied:
        assert f'{label}：{value}' in captions
    assert NO_ADVANCED_FILTER not in captions
    # 條件沒有被省略號或截斷遮去
    text = '\n'.join(captions)
    assert LONG_SCHOOL in text
    assert '…' not in text
    assert '...' not in text


def test_case_c_reminder_is_shown_verbatim_for_the_paired_sample():
    app = render(context(reading='跨期比較', sample='同一人跨期樣本（AC／BD）',
                          anchor='學生T0', reminder=PAIRED_REMINDER))
    captions = captions_of(app)
    assert PAIRED_REMINDER in captions
    assert OVERVIEW_REMINDER not in captions


def test_case_d_trend_reading_marks_the_count_as_before_date_filter():
    app = render(context(reading='時段趨勢', reminder=TREND_REMINDER))
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_TREND, '2,547 / 2,310')]
    assert TREND_REMINDER in captions_of(app)


def test_case_e_zero_sample_is_shown_as_zero_without_inventing_counts():
    app = render(context(n_t0=0, n_t1=0))
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_OVERVIEW, '0 / 0')]


# --- 純邏輯 ---

def test_n_value_formats_the_merged_t0_t1_count():
    assert n_value(2547, 2310) == '2,547 / 2,310'
    assert n_value(0, 0) == '0 / 0'


def test_n_label_marks_only_trend_reading_as_before_date_filter():
    assert n_label('研究總覽') == N_LABEL_OVERVIEW
    assert n_label('跨期比較') == N_LABEL_OVERVIEW
    assert n_label('時段趨勢') == N_LABEL_TREND


def test_component_does_not_read_data_or_touch_session_state():
    source = (Path(__file__).resolve().parent.parent / 'study2' / 'descriptive_context.py').read_text()
    for forbidden in ('import pandas', 'read_parquet', 'st.session_state', 'sqlite3', 'read_text('):
        assert forbidden not in source


# --- 與描述統計頁整合 ---

def build_release(folder, f, p, m):
    folder.mkdir(parents=True, exist_ok=True)
    m.to_parquet(folder / 'descriptive_measurements.parquet', index=False)
    pd.DataFrame([{'child_id': c, 'caregiver_status': 'identity_unconfirmed'} for c in ['one', 'two']]
                 ).to_parquet(folder / 'descriptive_caregivers.parquet', index=False)
    details = write_reports(folder, m, f, p, 'synthetic-release')
    f.to_parquet(folder / 'analysis.parquet', index=False)
    p.to_parquet(folder / 'parent_longitudinal.parquet', index=False)
    return {'release_id': 'synthetic-release', 'descriptive': details}


def descriptive_app(folder, summary):
    return AppTest.from_string(
        'import pandas as pd\nfrom study2.descriptive_dashboard import render_descriptive\n'
        + 'from pathlib import Path\np=Path(' + repr(str(folder)) + ')\n'
        + 'render_descriptive(p,' + repr(summary) + ',pd.read_parquet(p/"analysis.parquet"),'
        + 'pd.read_parquet(p/"parent_longitudinal.parquet"),'
        + '{"exact":"同一學校及姓名一致","transfer":"轉校跟進"})', default_timeout=60).run()


def test_case_f_card_is_wired_into_the_descriptive_page(inputs, tmp_path):
    f, p, m, _ = inputs
    summary = build_release(tmp_path / 'synthetic-release', f, p, m)
    app = descriptive_app(tmp_path / 'synthetic-release', summary)
    assert not app.exception
    assert CONTEXT_TITLE in [s.value for s in app.subheader]
    captions = captions_of(app)
    assert '分析樣本：各輪全部樣本（A／B／C／D）' in captions
    assert '填卷對象：學生' in captions
    assert '學校範圍：主流學校' in captions
    assert '孩子分組：全部' in captions
    assert '分組依據：該輪回應' in captions
    assert NO_ADVANCED_FILTER in captions
    assert OVERVIEW_REMINDER in captions
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_OVERVIEW, '2 / 2')]


def test_case_f_applied_conditions_appear_in_the_card_without_changing_n(inputs, tmp_path):
    f, p, m, _ = inputs
    summary = build_release(tmp_path / 'synthetic-release', f, p, m)
    app = descriptive_app(tmp_path / 'synthetic-release', summary)
    app.multiselect(key='ds_sources').set_value(['qualtrics']).run()
    assert not app.exception
    captions = captions_of(app)
    assert '資料來源：Qualtrics' in captions
    assert NO_ADVANCED_FILTER not in captions
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_OVERVIEW, '2 / 2')]


def test_case_f_paired_reading_shows_the_paired_reminder(inputs, tmp_path):
    f, p, m, _ = inputs
    summary = build_release(tmp_path / 'synthetic-release', f, p, m)
    app = descriptive_app(tmp_path / 'synthetic-release', summary)
    app.radio(key='ds_reading').set_value('跨期比較').run()
    assert not app.exception
    captions = captions_of(app)
    assert PAIRED_REMINDER in captions
    assert OVERVIEW_REMINDER not in captions
    assert '分析樣本：同一人跨期樣本（AC／BD）' in captions


def test_case_f_group_filter_is_reflected_in_the_card_without_changing_n(inputs, tmp_path):
    f, p, m, _ = inputs
    summary = build_release(tmp_path / 'synthetic-release', f, p, m)
    app = descriptive_app(tmp_path / 'synthetic-release', summary)
    app.selectbox(key='ds_group').set_value('female').run()
    assert not app.exception
    captions = captions_of(app)
    assert '孩子分組：女' in captions
    assert [(m.label, m.value) for m in card_of(app).metric] == [(N_LABEL_OVERVIEW, '1 / 1')]


def test_case_d_trend_reading_labels_the_card_count_as_before_date_filter(inputs, tmp_path):
    f, p, m, _ = inputs
    summary = build_release(tmp_path / 'synthetic-release', f, p, m)
    app = descriptive_app(tmp_path / 'synthetic-release', summary)
    app.radio(key='ds_reading').set_value('時段趨勢').run()
    assert not app.exception
    metric = card_of(app).metric[0]
    assert metric.label == N_LABEL_TREND
    assert metric.value == '2 / 2'
    assert TREND_REMINDER in captions_of(app)
