"""獨立家長頁三層計數的合成測試。

只用合成發布（G1／G2／G3）；不讀真實案例、不使用現行研究樣本數。
整合測試經實際 render_parent_panel，不 mock 核心 cohort、filter、wave_counts
或成人身份保護。
"""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from study2.common import file_hash
from study2.parent_panel import ADULT, CHILD
from study2.parent_panel_context import (DETAIL_METRIC_LABELS, DETAIL_TITLE, OVERVIEW_LABEL,
                                          STATISTICS_TITLE, UNLIMITED, PanelDetailFacts,
                                          PanelOverviewFacts, PanelStatisticsFacts,
                                          joined_values, render_detail_panel,
                                          render_release_overview, render_statistics_panel,
                                          statistics_count_line)
from study2.parent_waves import POLICY
from study2.runner import run
from test_identity_and_time import rec
from test_store_and_review import source

# G1 主流／Qualtrics／男／T0+T1／同成人已確認
# G2 非主流／paperform／女／T0+T1／同成人未確認（電話差一位）
# G3 主流／舊線上系統／女／只有 T0／沒有跨期
SPEC = [
    ("p_g1_t0", 0, "61234501", "2012-01-01", "0", "Example School", "example_qualtrics"),
    ("p_g1_t1", 120, "61234501", "2012-01-01", "0", "Example School", "example_qualtrics"),
    ("p_g2_t0", 0, "61234502", "2012-02-02", "1", "Other School", "paperform_g2"),
    ("p_g2_t1", 120, "61234512", "2012-02-02", "1", "Other School", "paperform_g2"),
    ("p_g3_t0", 0, "61234503", "2012-03-03", "1", "Example School", "legacy_g3"),
]


def _build(root, records):
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    raw = root / "1.1_raw_file"
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / "synthetic.csv"
    path.write_text("synthetic data,not human identifiers\n")
    mapping = root / "mappings"
    mapping.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"raw_name": "Example School", "normalized_key": "example school", "action": "map",
         "canonical_school_name": "Example School", "school_type": "primary"},
        {"raw_name": "Other School", "normalized_key": "other school", "action": "map",
         "canonical_school_name": "Other School", "school_type": "international"},
    ]).to_excel(state / "school_dictionary.xlsx", index=False)
    cfg = {"project_root": str(root), "state_dir": str(state), "release_dir": str(root / "releases"),
           "mapping_dir": str(mapping), "mapping_hashes": {}, "duplicate_days": 30,
           "minimum_followup_days": 90, "parent_wave_policy": POLICY, "bd_requires_same_adult": True,
           "matching_policy": {"allow_one_digit_phone": True},
           "sources": [{"source_id": "source", "pattern": "synthetic.csv", "kind": "system", "role": "student"}]}
    manifest = {"manifest_version": 1,
                "sources": [{"source_id": "source", "file": path.name, "sha256": file_hash(path)}]}
    fake = SimpleNamespace(STUDENT_COLUMNS=list(records[0]["answer"]) if records else ['adult_demographics_01'],
                            PARENT_COLUMNS=list(records[0]["answer"]) if records else ['adult_demographics_01'])
    with patch("study2.runner.input_records", side_effect=lambda *_: copy.deepcopy(records)), \
            patch("study2.runner.modules", return_value=(fake, None, None)):
        summary = run(cfg, manifest)
    return cfg, summary


def _records(spec):
    rows = []
    for sid, day, phone, dob, gender, school, survey in spec:
        r = rec(sid, day=day, role="parent", dob=dob, gender=gender, phone_value=phone, school=school)
        r.update(source_kind="system", claimed_wave="T0" if day == 0 else "T1", batch_at=None,
                 date_basis="system_creation")
        r["answer"].update({"school_from_parent": school, "adult_demographics_01": 3,
                            "adult_demographics_03": dob, "adult_demographics_04": gender,
                            "adult_demographics_05": 1980, "Survey": survey})
        r["answer"].update({f"parent_PHQ_{i:02d}": 0 for i in range(1, 5)})
        rows.append(source(r))
    return rows


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    """G1／G2／G3 合成發布：整版 3／2／1，孩子分支全部基線 T0=3／T1=2。"""
    root = tmp_path_factory.mktemp("parent_panel_release")
    cfg, summary = _build(root, _records(SPEC))
    folder = str(Path(cfg["release_dir"]) / summary["release_id"])
    return folder, summary


@pytest.fixture(scope="module")
def empty_release(tmp_path_factory):
    """沒有家長回應的合成發布。"""
    root = tmp_path_factory.mktemp("parent_panel_empty")
    cfg, summary = _build(root, [])
    folder = str(Path(cfg["release_dir"]) / summary["release_id"])
    return folder, summary


def panel_app(folder, summary):
    return AppTest.from_string(
        'from study2.parent_panel_dashboard import render_parent_panel\n'
        + 'render_parent_panel(' + repr(folder) + ', ' + repr(summary) + ')', default_timeout=30).run()


def text_of(app):
    """頁面上所有可讀文字，包含 caption、markdown、subheader 及提示。"""
    parts = []
    for name in ('caption', 'markdown', 'subheader', 'info', 'warning', 'error', 'success'):
        parts += [element.value for element in getattr(app, name)]
    return '\n'.join(parts)


def container_with(app, title):
    for container in app.container:
        if any(title in heading.value for heading in container.subheader):
            return container
    raise AssertionError(f'未找到標題為 {title} 的容器')


def detail_metrics(app):
    return [(metric.label, metric.value) for metric in container_with(app, DETAIL_TITLE).metric]


def statistics_text(app):
    return text_of(container_with(app, STATISTICS_TITLE))


# --- 純呈現元件 ---

def test_component_renders_prepared_facts_without_counting():
    app = AppTest.from_string(
        'from study2.parent_panel_context import PanelDetailFacts, render_detail_panel\n'
        'render_detail_panel(PanelDetailFacts(branch="同一孩子，填卷人可不同", scope="跨期樣本", wave="T0",'
        ' school_scope="全部學校", gender="全部", school_types=(), schools=(), sources=(),'
        ' grouping_basis="獨立家長T0所指孩子", unfiltered_n=3, scope_n=2, current_n=1,'
        ' exclusion_note="原排除數說明。"))\n').run()
    assert not app.exception
    container = app.container[0]
    assert [heading.value for heading in container.subheader] == [DETAIL_TITLE]
    captions = [caption.value for caption in container.caption]
    assert '分支：同一孩子，填卷人可不同' in captions
    assert '分析範圍：跨期樣本' in captions
    assert '明細及回應下載輪次：T0' in captions
    assert '已選學校類型：' + UNLIMITED in captions
    assert '已選學校：' + UNLIMITED in captions
    assert '已選資料來源：' + UNLIMITED in captions
    assert '分組依據：獨立家長T0所指孩子' in captions
    assert [(m.label, m.value) for m in container.metric] == list(zip(DETAIL_METRIC_LABELS, ['3', '2', '1']))
    assert '原排除數說明。' in captions


def test_component_statistics_panel_adds_no_metric():
    app = AppTest.from_string(
        'from study2.parent_panel_context import PanelStatisticsFacts, render_statistics_panel\n'
        'render_statistics_panel(PanelStatisticsFacts(reading="研究總覽", branch="同一孩子、同一成人",'
        ' scope="跨期樣本", school_scope="全部學校", gender="女", conditions=(),'
        ' grouping_basis="獨立家長T0所指孩子", n_t0=0, n_t1=0))\n').run()
    assert not app.exception
    container = app.container[0]
    assert not container.metric
    assert not app.metric
    body = '\n'.join([c.value for c in container.caption] + [m.value for m in container.markdown])
    assert '閱讀方式：研究總覽' in body
    assert '分支：同一孩子、同一成人' in body
    assert '分析範圍：跨期樣本' in body
    assert '學校範圍：全部學校' in body
    assert '孩子性別：女' in body
    assert '已套用條件：無進階篩選。' in body
    assert '固定基線依據：獨立家長T0所指孩子' in body
    assert '統計樣本 T0 N：0；T1 N：0' in body


def test_statistics_count_line_marks_trend_as_before_date_filter():
    assert statistics_count_line('研究總覽', 3, 2) == '統計樣本 T0 N：3；T1 N：2'
    assert statistics_count_line('跨期比較', 3, 2) == '統計樣本 T0 N：3；T1 N：2'
    assert statistics_count_line('時段趨勢', 3, 2) == '日期篩選前統計樣本 T0 N：3；T1 N：2'
    assert statistics_count_line('研究總覽', 0, 0) == '統計樣本 T0 N：0；T1 N：0'


def test_joined_values_marks_empty_multiselect_as_unlimited():
    assert joined_values(()) == UNLIMITED
    assert joined_values(['A', 'B']) == 'A、B'


def test_component_has_no_data_or_state_access():
    source = (Path(__file__).resolve().parent.parent / 'study2' / 'parent_panel_context.py').read_text()
    for forbidden in ('import pandas', 'read_parquet', 'st.session_state', 'sqlite3', 'read_text(',
                      'st.cache', 'def filter_cohort', 'def independent_cohort'):
        assert forbidden not in source


# --- 整合：總覽、明細與統計三層 ---

def test_case_a_overview_and_detail_are_separate(release):
    folder, summary = release
    app = panel_app(folder, summary)
    assert not app.exception
    assert [m.value for m in app.metric[:3]] == ['3', '2', '1']
    body = text_of(app)
    assert OVERVIEW_LABEL in body
    assert '第一項是選定的獨立家長 T0 回應數' in body
    assert '三項不是互斥分類，不能相加' in body
    assert detail_metrics(app) == [('此輪未篩選 N', '2'), ('學校範圍後 N', '2'), ('目前獨立樣本 N', '2')]
    detail = text_of(container_with(app, DETAIL_TITLE))
    assert '分支：同一孩子，填卷人可不同' in detail
    assert '分析範圍：跨期樣本' in detail
    assert '明細及回應下載輪次：T0' in detail
    assert 'N是此輪回應數' in detail


def test_case_b_switching_detail_wave_does_not_change_statistics_n(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.selectbox(key='ipp_cohort_' + CHILD).set_value('全部獨立基線及追蹤').run()
    assert not app.exception
    assert detail_metrics(app) == [('此輪未篩選 N', '3'), ('學校範圍後 N', '3'), ('目前獨立樣本 N', '3')]
    assert '統計樣本 T0 N：3；T1 N：2' in statistics_text(app)
    app.selectbox(key='ipp_wave').set_value('T1').run()
    assert not app.exception
    assert detail_metrics(app) == [('此輪未篩選 N', '2'), ('學校範圍後 N', '2'), ('目前獨立樣本 N', '2')]
    assert '統計樣本 T0 N：3；T1 N：2' in statistics_text(app)


def test_case_c_same_adult_branch_offers_only_paired_and_keeps_unconfirmed_out(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.selectbox(key='ipp_cohort_' + CHILD).set_value('全部獨立基線及追蹤').run()
    app.selectbox(key='ipp_branch').set_value(ADULT).run()
    assert not app.exception
    assert app.selectbox(key='ipp_cohort_' + ADULT).options == ['跨期樣本']
    assert '同一成人分支只提供跨期樣本，已清除全部基線選項。' in text_of(app)
    assert '統計樣本 T0 N：1；T1 N：1' in statistics_text(app)
    pairs = app.dataframe[0].value
    assert 'p_g2_t0' not in set(pairs['獨立T0提交ID']) | set(pairs['獨立T1提交ID'])
    assert 'p_g1_t0' in set(pairs['獨立T0提交ID'])


def test_case_d_applied_conditions_are_shown_and_change_the_statistics_n(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.selectbox(key='ipp_cohort_' + CHILD).set_value('全部獨立基線及追蹤').run()
    app.selectbox(key='ipp_scope').set_value('只限主流學校').run()
    app.selectbox(key='ipp_gender').set_value('女').run()
    assert not app.exception
    body = statistics_text(app)
    assert '學校範圍：只限主流學校' in body
    assert '孩子性別：女' in body
    assert '學校類型：' + UNLIMITED in body
    assert '學校：' + UNLIMITED in body
    assert '資料來源：' + UNLIMITED in body
    assert '統計樣本 T0 N：1；T1 N：0' in body


def test_case_e_zero_sample_is_shown_as_zero(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.selectbox(key='ipp_scope').set_value('只限主流學校').run()
    app.selectbox(key='ipp_gender').set_value('女').run()
    assert not app.exception
    assert detail_metrics(app) == [('此輪未篩選 N', '2'), ('學校範圍後 N', '1'), ('目前獨立樣本 N', '0')]
    assert '統計樣本 T0 N：0；T1 N：0' in statistics_text(app)


def test_case_f_trend_reading_marks_the_summary_as_before_date_filter(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.radio(key='ipp_reading').set_value('時段趨勢').run()
    assert not app.exception
    body = statistics_text(app)
    assert '日期篩選前統計樣本 T0 N：2；T1 N：2' in body
    assert '時段趨勢還有自己的輪次及日期控制' in body
    # 趨勢區保留自己的輪次及日期控制，明細輪次沒有取代它
    keys = [selectbox.key for selectbox in app.selectbox]
    assert 'ipp_trend_waves' in keys and 'ipp_trend_interval' in keys
    assert app.selectbox(key='ipp_wave').value == 'T0'
    assert app.date_input
    assert '期間內' in '\n'.join(metric.label for metric in app.metric)


def test_case_g_blocked_combination_is_still_blocked(release):
    folder, summary = release
    app = panel_app(folder, summary)
    app.selectbox(key='ipp_cohort_' + CHILD).set_value('全部獨立基線及追蹤').run()
    app.radio(key='ipp_reading').set_value('跨期比較').run()
    assert not app.exception
    body = text_of(app)
    assert '全部基線及追蹤不等於完整跨期樣本' in body
    assert '分析範圍：全部獨立基線及追蹤' in body


def test_case_g_capability_shortfall_still_blocks_the_workbench(release):
    folder, summary = release
    without_exploration = {**summary,
                           'descriptive': {k: v for k, v in summary['descriptive'].items()
                                           if k != 'exploration'}}
    app = panel_app(folder, without_exploration)
    app.radio(key='ipp_reading').set_value('跨期比較').run()
    assert not app.exception
    body = text_of(app)
    assert '此發布未提供跨期探索能力' in body
    assert '獨立家長描述統計' in body


def test_case_h_legacy_release_keeps_the_existing_entry(release):
    folder, summary = release
    app = panel_app(folder, {k: v for k, v in summary.items() if k != 'independent_parent'})
    assert not app.exception
    assert '此歷史版本未包含獨立家長分析。' in text_of(app)
    assert not app.metric


def test_case_h_legacy_statistics_entry_adds_no_two_wave_n(release):
    folder, summary = release
    app = panel_app(folder, {**summary, 'descriptive': None})
    assert not app.exception
    body = text_of(app)
    assert '此歷史版本未包含新版人口特徵' in body
    assert '統計樣本 T0 N' not in body
    assert STATISTICS_TITLE not in body


def test_case_h_empty_parent_release_keeps_the_existing_entry(empty_release):
    folder, summary = empty_release
    app = panel_app(folder, summary)
    assert not app.exception
    assert [m.value for m in app.metric[:3]] == ['0', '0', '0']
    assert '統計樣本 T0 N：0；T1 N：0' in statistics_text(app)


def test_case_i_metric_count_is_unchanged(release):
    folder, summary = release
    app = panel_app(folder, summary)
    assert not app.exception
    assert len(app.metric) == 6
    assert [m.label for m in app.metric[:3]] == ['獨立家長基線', '同一孩子跨期（可換填卷人）', '同一成人跨期']
    assert [m.label for m in app.metric[3:6]] == list(DETAIL_METRIC_LABELS)


def test_case_j_exports_and_statistics_receive_the_same_data(release, monkeypatch):
    folder, summary = release
    captured = {}
    import study2.descriptive_workbench as workbench
    original = workbench.render_overview

    def spy(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(workbench, 'render_overview', spy)
    app = panel_app(folder, summary)
    assert not app.exception
    assert '統計樣本 T0 N：2；T1 N：2' in statistics_text(app)
    rows, role = captured['args'][0], captured['args'][1]
    assert role == 'parent'
    assert captured['kwargs']['metadata'] == {'branch': CHILD, 'paired_only': True, 'mainstream': False,
                                              'gender': '全部', 'schools': [], 'sources': [], 'school_types': []}
    assert int(rows['wave'].eq('T0').sum()) == 2
    assert int(rows['wave'].eq('T1').sum()) == 2
    assert set(rows['submission_id']) == {'p_g1_t0', 'p_g1_t1', 'p_g2_t0', 'p_g2_t1'}
    assert 'p_g3_t0' not in set(rows['submission_id'])
    labels = [button.label for button in app.download_button]
    assert '下載獨立家長配對明細' in labels
    assert '下載目前獨立家長選定回應' in labels
    assert len(app.dataframe[0].value) == 2
