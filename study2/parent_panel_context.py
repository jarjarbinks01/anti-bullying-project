"""獨立家長頁的呈現元件：把三層計數分開說明。

只接收已準備好的文字、條件、整數與顯示狀態：
不接收 DataFrame、不自行篩選或計 N、不讀檔、不連資料庫、不讀寫 session_state。
本元件不改共用 descriptive_context，獨立家長頁的計數層次及 metric 相容要求不同。
"""
from dataclasses import dataclass

import streamlit as st

OVERVIEW_LABEL = "本版總覽（未套用下方篩選）"
DETAIL_TITLE = "目前明細及下載"
STATISTICS_TITLE = "目前統計分析"
UNLIMITED = "不限"

DETAIL_METRIC_LABELS = ('此輪未篩選 N', '學校範圍後 N', '目前獨立樣本 N')
TREND_READING = "時段趨勢"


@dataclass(frozen=True)
class PanelOverviewFacts:
    """本版總覽的說明；三個 metric 本身仍由既有程式呈現。"""
    note: str
    label: str = OVERVIEW_LABEL


@dataclass(frozen=True)
class PanelDetailFacts:
    """目前明細及下載的已準備說明；N 是該輪回應數。"""
    branch: str
    scope: str
    wave: str
    school_scope: str
    gender: str
    school_types: tuple[str, ...]
    schools: tuple[str, ...]
    sources: tuple[str, ...]
    grouping_basis: str
    unfiltered_n: int
    scope_n: int
    current_n: int
    exclusion_note: str


@dataclass(frozen=True)
class PanelStatisticsFacts:
    """目前統計分析的已準備說明；N 是兩輪統計實際收到的回應數。"""
    reading: str
    branch: str
    scope: str
    school_scope: str
    gender: str
    conditions: tuple[tuple[str, str], ...]
    grouping_basis: str
    n_t0: int
    n_t1: int
    notes: tuple[str, ...] = ()


def joined_values(values) -> str:
    """多選顯示；空複選明確表示不限。"""
    return '、'.join(values) if values else UNLIMITED


def statistics_count_line(reading: str, n_t0: int, n_t1: int) -> str:
    """兩輪 N 的合併計數行；時段趨勢明確標示為日期篩選前。"""
    prefix = '日期篩選前統計樣本' if reading == TREND_READING else '統計樣本'
    return f"{prefix} T0 N：{n_t0:,}；T1 N：{n_t1:,}"


def render_release_overview(facts: PanelOverviewFacts, ui=None) -> None:
    """本版總覽提示；置於原三個 metric 之前，數值本身不變。"""
    ui = ui or st
    ui.caption(facts.label)
    ui.caption(facts.note)


def render_detail_panel(facts: PanelDetailFacts, ui=None) -> None:
    """目前明細及下載：分支、範圍、輪次、篩選及三個既有 metric。"""
    ui = ui or st
    with ui.container(border=True):
        ui.subheader(DETAIL_TITLE)
        ui.caption(f"分支：{facts.branch}")
        ui.caption(f"分析範圍：{facts.scope}")
        ui.caption(f"明細及回應下載輪次：{facts.wave}")
        ui.caption(f"學校範圍：{facts.school_scope}")
        ui.caption(f"孩子性別：{facts.gender}")
        ui.caption(f"已選學校類型：{joined_values(facts.school_types)}")
        ui.caption(f"已選學校：{joined_values(facts.schools)}")
        ui.caption(f"已選資料來源：{joined_values(facts.sources)}")
        ui.caption(f"分組依據：{facts.grouping_basis}")
        metrics = ui.columns(3)
        for column, label, value in zip(metrics, DETAIL_METRIC_LABELS,
                                        (facts.unfiltered_n, facts.scope_n, facts.current_n)):
            column.metric(label, value)
        ui.caption(facts.exclusion_note)


def render_statistics_panel(facts: PanelStatisticsFacts, ui=None) -> None:
    """目前統計分析：兩輪 N 及條件；不新增 st.metric，以免改變既有 metric 次序。"""
    ui = ui or st
    with ui.container(border=True):
        ui.subheader(STATISTICS_TITLE)
        ui.caption(f"閱讀方式：{facts.reading}")
        ui.caption(f"分支：{facts.branch}")
        ui.caption(f"分析範圍：{facts.scope}")
        ui.caption(f"學校範圍：{facts.school_scope}")
        ui.caption(f"孩子性別：{facts.gender}")
        if facts.conditions:
            ui.caption("已套用條件")
            for label, value in facts.conditions:
                ui.caption(f"{label}：{value}")
        else:
            ui.caption("已套用條件：無進階篩選。")
        ui.caption(f"固定基線依據：{facts.grouping_basis}")
        ui.write(statistics_count_line(facts.reading, facts.n_t0, facts.n_t1))
        for note in facts.notes:
            ui.caption(note)
