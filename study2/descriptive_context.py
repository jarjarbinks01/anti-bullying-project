"""描述統計「目前分析」摘要呈現元件。

只接收已計好的 N 及已準備好的文字／條件並呈現：
不接收 DataFrame、不自行計 N、不讀檔、不連資料庫、不查或清理 session_state。
文字使用 st.caption 顯示，沿用 Streamlit 的 Markdown 行為；
本元件未加入截斷或省略處理。
"""
from dataclasses import dataclass

from .english_ui import st

CONTEXT_TITLE = "目前分析"
APPLIED_TITLE = "已套用條件"
N_EXPLANATION = "N 按所選填卷對象的回應計數；各指標有效 N 另扣缺失。"
NO_ADVANCED_FILTER = "目前篩選：無進階篩選。"

N_LABEL_OVERVIEW = "目前 T0／T1 N"
N_LABEL_TREND = "日期篩選前 T0／T1 N"
TREND_READING = "時段趨勢"


@dataclass(frozen=True)
class AnalysisContext:
    """已準備好的分析設定摘要。

    n_t0／n_t1 是所選填卷對象的回應數，不是獨立孩子人數、家庭數、
    配對完整有效 N 或量表有效 N。applied 是已套用條件的顯示名稱，
    每項為（類別，顯示內容）。
    """
    reading: str
    sample: str
    respondent: str
    school_scope: str
    group: str
    anchor: str
    n_t0: int
    n_t1: int
    applied: tuple[tuple[str, str], ...] = ()
    reminder: str = ""


def n_label(reading: str) -> str:
    """T0／T1 N 的 metric 標籤；時段趨勢明確標示為日期篩選前。"""
    return N_LABEL_TREND if reading == TREND_READING else N_LABEL_OVERVIEW


def n_value(n_t0: int, n_t1: int) -> str:
    """合併的 T0／T1 N 顯示值；零樣本如實顯示 0 / 0。"""
    return f"{n_t0:,} / {n_t1:,}"


def render_analysis_context(context: AnalysisContext) -> None:
    """呈現「目前分析」摘要卡；內容直接可見，不放進 expander。"""
    with st.container(border=True):
        st.subheader(CONTEXT_TITLE)
        st.caption(f"閱讀方式：{context.reading}")
        st.caption(f"分析樣本：{context.sample}")
        st.caption(f"填卷對象：{context.respondent}")
        st.caption(f"學校範圍：{context.school_scope}")
        st.caption(f"孩子分組：{context.group}")
        st.caption(f"分組依據：{context.anchor}")
        st.metric(n_label(context.reading), n_value(context.n_t0, context.n_t1))
        st.caption(N_EXPLANATION)
        if context.applied:
            st.markdown(f"**{APPLIED_TITLE}**")
            for label, value in context.applied:
                st.caption(f"{label}：{value}")
        else:
            st.caption(NO_ADVANCED_FILTER)
        st.caption(context.reminder)
