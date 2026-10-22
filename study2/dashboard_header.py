"""Study 2 dashboard 頁首呈現元件。

本元件只接收已準備好的版本資訊、詳細說明及狀態訊息並呈現：
不讀檔、不連接資料庫、不計算研究統計。
版本時間、來源匯出時間及狀態訊息由呼叫端準備，觸發條件與既有頁首一致。
"""
from dataclasses import dataclass
from datetime import datetime

from .english_ui import st

TITLE = "Study 2 研究資料"
SHORT_NOTE = "本機研究原型 · 每項統計顯示有效樣本及缺失數"
RELOAD_LABEL = "重新讀取目前版本"
DETAILS_LABEL = "資料來源及研究規則"
NO_RELEASE_MESSAGE = "尚未發布資料。請先完成資料匯入及檢查。"
UNKNOWN = "未提供"
INVALID = "無效"
UNCONFIRMED = "未確認"

VALIDATION_PENDING = "程式檢查已通過；研究同事尚未建立人工核實案例集，實際配對準確度未驗證。"
SOURCE_TIME_UNKNOWN = "下載 agent 尚未提供匯出時間；版本產生時間只代表本機處理時間，不能證明來源資料最新。"
SOURCE_TIME_UNUSABLE = ("下載 agent 提供的匯出時間無法確認（無效或沒有時區）；"
                         "版本產生時間只代表本機處理時間，不能證明來源資料最新。")
UPDATE_FAILED_PREFIX = "最近一次更新失敗，仍顯示上一個已發布版本。"
UPDATE_FAILED_NO_DETAIL = "（失敗記錄未提供錯誤內容）"

MERGED_SOURCE_SCOPE = "merged_abcd"


@dataclass(frozen=True)
class HeaderFacts:
    """已準備好的頁首輸入；欄位為 None 代表舊版未提供該項資料。

    last_update_error：None 代表沒有更新失敗記錄；空字串代表失敗記錄存在
    但沒有錯誤內容。兩者意義不同，不可合併。
    created_at／source_exported_at：已發布的時間字串；沒有明確時區的時間
    不當作已確認，元件不補時區。
    """
    release_id: str
    created_at: str | None = None
    source_exported_at: str | None = None
    stale_after_days: int | None = None
    now: datetime | None = None
    source_scope: str | None = None
    bd_requires_same_adult: bool | None = None
    batch_creation_time_submissions: int | None = None
    parent_wave_policy: str | None = None
    nearest_parent_baseline: bool = False
    research_validation: str | None = None
    last_update_error: str | None = None


@dataclass(frozen=True)
class StatusMessage:
    """頁首狀態提示；level 對應 Streamlit 的呈現元件。"""
    level: str
    message: str


@dataclass(frozen=True)
class Header:
    """已排定的頁首內容。"""
    title: str
    note: str
    version_id: str
    created_line: str
    source_line: str
    reload_label: str
    statuses: tuple[StatusMessage, ...]
    details_label: str
    details: tuple[str, ...]


def _read_time(value: str | None) -> tuple[str, datetime | None]:
    """判定已發布時間是否可用；沒有時區的時間不當作已確認。

    回傳狀態：ok（可用）、missing（未提供）、invalid（不是有效時間）、
    unconfirmed（有效但沒有時區，無法確認屬於哪個時區）。沒有明確的時間來源
    政策前不補時區，亦不當作有效日期。
    """
    if value is None or str(value).strip() == "":
        return "missing", None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "invalid", None
    if parsed.tzinfo is None:
        return "unconfirmed", None
    return "ok", parsed


def _time_line(label: str, value: str | None) -> str:
    """時間的顯示行；不可用的時間明確標示，不當成有效日期。"""
    state, _ = _read_time(value)
    if state == "ok":
        return f"{label}：{value}"
    if state == "missing":
        return f"{label}：{UNKNOWN}"
    return f"{label}：{INVALID if state == 'invalid' else UNCONFIRMED}（{value}）"


def _freshness(facts: HeaderFacts) -> tuple[datetime | None, str | None]:
    """取用作計算日齡的時間及其名稱；名稱必須與實際使用的時間一致。

    來源匯出時間未確認時改用版本產生時間，並以「版本產生」標示；
    兩者都未確認時不計算日齡。
    """
    source_state, source_moment = _read_time(facts.source_exported_at)
    if source_state == "ok":
        return source_moment, "來源匯出"
    created_state, created_moment = _read_time(facts.created_at)
    if created_state == "ok":
        return created_moment, "版本產生"
    return None, None


def _bd_rule(facts: HeaderFacts) -> str:
    """BD 規則只跟隨已發布旗標；舊版未提供旗標時不推定同一成人。"""
    if facts.bd_requires_same_adult is True:
        return "BD 要求同一成人填卷人。"
    if facts.bd_requires_same_adult is False:
        return "BD 不要求同一成人填卷人，只要求同一孩子。"
    return "BD 是否要求同一成人填卷人，此版本未提供。"


def _batch_date_line(facts: HeaderFacts) -> str:
    """批次日期政策；舊版沒有該欄位時不補零。"""
    if facts.batch_creation_time_submissions is None:
        return "按研究負責人決定，使用目前建立時間；批次指定日期的行數此版本未提供。日期來源標記保留。"
    return (f"按研究負責人決定，使用目前建立時間；其中 {facts.batch_creation_time_submissions:,} 行是批次指定日期。"
            "日期來源標記保留。")


def _detail_lines(facts: HeaderFacts) -> tuple[str, ...]:
    """收合區內容：資料來源、批次日期政策及學生錨定規則。"""
    lines = ["本機原型：確認配對與待審個案分開呈現。"]
    if facts.source_scope == MERGED_SOURCE_SCOPE:
        lines.append("資料來源：2.1.2 的四份 A／B／C／D 合併 Excel。電話差一位及轉校規則已啟用；" + _bd_rule(facts))
        lines.append(_batch_date_line(facts))
    if facts.parent_wave_policy:
        if facts.nearest_parent_baseline:
            lines.append('學生錨定樣本：先保留學生T1同日或之後的家長回應作T1；其餘選最接近學生T0的家長基線，'
                         '可早於學生，不設日期差上限。家長自身沒有90日門檻，原始標籤保留。獨立家長分析另見同名頁籤。')
        else:
            lines.append('以學生為錨：學生T1至少相隔90日；家長按學生兩輪的香港曆日分段，'
                         '不設家長自身90日門檻。原始問卷標籤保留。')
    return tuple(lines)


def build_header(facts: HeaderFacts) -> Header:
    """把已準備好的版本資訊排成頁首內容；不讀檔、不連資料庫、不計統計。"""
    statuses: list[StatusMessage] = []
    if facts.research_validation == "not_yet_reviewed":
        statuses.append(StatusMessage("warning", VALIDATION_PENDING))
    # None 代表沒有失敗記錄；空字串代表失敗記錄存在但沒有錯誤內容，兩者不可混淆。
    if facts.last_update_error is not None:
        detail = facts.last_update_error or UPDATE_FAILED_NO_DETAIL
        statuses.append(StatusMessage("error", UPDATE_FAILED_PREFIX + detail))
    source_state, _ = _read_time(facts.source_exported_at)
    if source_state == "missing":
        statuses.append(StatusMessage("info", SOURCE_TIME_UNKNOWN))
    elif source_state != "ok":
        statuses.append(StatusMessage("info", SOURCE_TIME_UNUSABLE))
    moment, moment_name = _freshness(facts)
    age = None
    if moment is not None and facts.now is not None and facts.now.tzinfo is not None:
        age = (facts.now - moment).days
    if age is not None and facts.stale_after_days is not None and age > facts.stale_after_days:
        statuses.append(StatusMessage("warning", f"{moment_name}已 {age} 日，請檢查每星期匯出是否完成。"))
    return Header(
        title=TITLE,
        note=SHORT_NOTE,
        version_id=facts.release_id,
        created_line=_time_line("版本產生時間", facts.created_at),
        source_line=_time_line("來源匯出時間", facts.source_exported_at),
        reload_label=RELOAD_LABEL,
        statuses=tuple(statuses),
        details_label=DETAILS_LABEL,
        details=_detail_lines(facts),
    )


def render_header(header: Header, on_reload=None, ui=None) -> None:
    """呈現頁首：版本資訊、重新讀取按鈕、狀態提示及收合的資料來源及研究規則。"""
    ui = ui or st
    ui.title(header.title)
    ui.caption(header.note)
    version_column, action_column = ui.columns([4, 1])
    with version_column:
        ui.markdown(f"**資料版本：** {header.version_id}")
        ui.caption(header.created_line)
        ui.caption(header.source_line)
    with action_column:
        ui.button(header.reload_label, on_click=on_reload, width="stretch")
    for status in header.statuses:
        getattr(ui, status.level)(status.message)
    with ui.expander(header.details_label):
        for line in header.details:
            ui.caption(line)


def render_missing_release(ui=None) -> None:
    """沒有已發布版本時的提示；停止後續讀取由呼叫端負責。"""
    ui = ui or st
    ui.title(TITLE)
    ui.caption(SHORT_NOTE)
    ui.info(NO_RELEASE_MESSAGE)
