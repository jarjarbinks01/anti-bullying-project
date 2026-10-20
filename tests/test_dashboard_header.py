"""Study 2 dashboard 頁首呈現元件測試。

只用合成版本、時間及訊息；不讀研究資料庫、不啟動正式 dashboard。
"""
from datetime import datetime, timezone
from pathlib import Path

from study2.dashboard_header import (DETAILS_LABEL, NO_RELEASE_MESSAGE, RELOAD_LABEL, TITLE,
                                     HeaderFacts, build_header, render_header, render_missing_release)

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
CREATED = "2026-10-18T10:00:00+00:00"
EXPORTED = "2026-10-19T09:00:00+00:00"


class _Slot:
    """結構用的空 context manager。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """最小 Streamlit 呈現介面記錄器；只記錄，不做真實呈現。"""

    def __init__(self):
        self.calls = []
        self.titles = []
        self.captions = []
        self.markdowns = []
        self.buttons = []
        self.errors = []
        self.warnings = []
        self.infos = []
        self.expanders = []
        self.columns_spec = None

    def title(self, text):
        self.titles.append(text)
        self.calls.append(("title", text))

    def caption(self, text):
        self.captions.append(text)
        self.calls.append(("caption", text))

    def markdown(self, text):
        self.markdowns.append(text)
        self.calls.append(("markdown", text))

    def button(self, label, on_click=None, **kwargs):
        self.buttons.append({"label": label, "on_click": on_click, "kwargs": kwargs})
        self.calls.append(("button", label))

    def error(self, text):
        self.errors.append(text)
        self.calls.append(("error", text))

    def warning(self, text):
        self.warnings.append(text)
        self.calls.append(("warning", text))

    def info(self, text):
        self.infos.append(text)
        self.calls.append(("info", text))

    def columns(self, spec):
        self.columns_spec = spec
        return [_Slot(), _Slot()]

    def expander(self, label, expanded=False):
        self.expanders.append({"label": label, "expanded": expanded})
        self.calls.append(("expander", label))
        return _Slot()


def facts(**overrides):
    """正常發布版本的合成事實；覆寫欄位可造出警告情況。"""
    base = dict(release_id="RUN-20261018-abc", created_at=CREATED, source_exported_at=EXPORTED,
                stale_after_days=8, now=NOW, source_scope="merged_abcd", bd_requires_same_adult=True,
                batch_creation_time_submissions=1234, parent_wave_policy="student_anchored_hk_nearest_v2",
                nearest_parent_baseline=True, research_validation="reviewed_sample", last_update_error=None)
    base.update(overrides)
    return HeaderFacts(**base)


def test_case_a_normal_header_shows_version_times_and_action():
    header = build_header(facts())
    assert header.title == TITLE
    assert header.version_id == "RUN-20261018-abc"
    assert header.created_line == f"版本產生時間：{CREATED}"
    assert header.source_line == f"來源匯出時間：{EXPORTED}"
    assert header.reload_label == RELOAD_LABEL
    assert header.statuses == ()

    recorder = Recorder()
    render_header(header, on_reload=lambda: None, ui=recorder)
    assert recorder.titles == [TITLE]
    assert recorder.markdowns == ["**資料版本：** RUN-20261018-abc"]
    assert f"版本產生時間：{CREATED}" in recorder.captions
    assert f"來源匯出時間：{EXPORTED}" in recorder.captions
    assert [button["label"] for button in recorder.buttons] == [RELOAD_LABEL]


def test_case_a_version_time_and_source_time_are_labelled_separately():
    header = build_header(facts())
    assert header.created_line != header.source_line
    assert header.created_line.startswith("版本產生時間：")
    assert header.source_line.startswith("來源匯出時間：")


def test_case_b_all_four_statuses_are_visible_outside_the_expander():
    header = build_header(facts(source_exported_at=None, research_validation="not_yet_reviewed",
                                last_update_error="匯入失敗：檔案損壞",
                                created_at="2026-09-01T00:00:00+00:00"))
    levels = [status.level for status in header.statuses]
    assert levels == ["warning", "error", "info", "warning"]
    messages = [status.message for status in header.statuses]
    assert any("實際配對準確度未驗證" in message for message in messages)
    assert any("最近一次更新失敗，仍顯示上一個已發布版本。" in message for message in messages)
    assert any("尚未提供匯出時間" in message for message in messages)
    assert any("已 49 日" in message for message in messages)

    recorder = Recorder()
    render_header(header, on_reload=lambda: None, ui=recorder)
    assert recorder.warnings and recorder.errors and recorder.infos
    expander_index = next(index for index, call in enumerate(recorder.calls) if call[0] == "expander")
    status_indexes = [index for index, call in enumerate(recorder.calls) if call[0] in {"warning", "error", "info"}]
    assert status_indexes and max(status_indexes) < expander_index


def test_case_c_details_keep_the_original_source_and_research_rules():
    header = build_header(facts())
    details = "\n".join(header.details)
    assert "2.1.2 的四份 A／B／C／D 合併 Excel" in details
    assert "電話差一位及轉校規則已啟用" in details
    assert "BD 要求同一成人填卷人" in details
    assert "1,234 行是批次指定日期" in details
    assert "日期來源標記保留" in details
    assert "學生錨定樣本" in details
    assert "不設日期差上限" in details

    recorder = Recorder()
    render_header(header, on_reload=lambda: None, ui=recorder)
    assert recorder.expanders == [{"label": DETAILS_LABEL, "expanded": False}]


def test_case_d_reload_button_keeps_the_original_cache_clear_callback():
    recorder = Recorder()
    cleared = []
    header = build_header(facts())
    render_header(header, on_reload=lambda: cleared.append(True), ui=recorder)
    button = recorder.buttons[0]
    assert button["label"] == RELOAD_LABEL
    assert callable(button["on_click"])
    button["on_click"]()
    assert cleared == [True]

    source = (REPO / "dashboard.py").read_text()
    assert "on_reload=lambda: st.cache_data.clear()" in source
    assert source.count("st.cache_data.clear()") == 1


def test_case_e_missing_optional_fields_are_not_fabricated():
    header = build_header(HeaderFacts(release_id="old-run", created_at=None, source_exported_at=None,
                                      stale_after_days=8, now=NOW, source_scope="merged_abcd",
                                      batch_creation_time_submissions=None))
    assert header.created_line == "版本產生時間：未提供"
    assert header.source_line == "來源匯出時間：未提供"
    assert not any("0 行" in line for line in header.details)
    assert any("批次指定日期的行數此版本未提供" in line for line in header.details)
    assert not any("日，請檢查每星期匯出是否完成" in status.message for status in header.statuses)


def test_case_e_a_release_outside_merged_scope_has_no_merged_source_line():
    header = build_header(HeaderFacts(release_id="old-run", created_at=CREATED, source_exported_at=EXPORTED,
                                      now=NOW, source_scope="registered_sources"))
    assert not any("2.1.2 的四份 A／B／C／D 合併 Excel" in line for line in header.details)


def test_case_e_a_real_zero_count_is_still_shown_as_zero():
    header = build_header(facts(batch_creation_time_submissions=0))
    assert any("其中 0 行是批次指定日期" in line for line in header.details)


def test_case_e_unknown_source_time_is_not_reported_as_updated_to_version_time():
    header = build_header(facts(source_exported_at=None))
    assert header.source_line == "來源匯出時間：未提供"
    assert header.created_line != header.source_line
    assert any("不能證明來源資料最新" in status.message for status in header.statuses)


def test_case_f_missing_release_prompt_and_stop_are_preserved():
    recorder = Recorder()
    render_missing_release(ui=recorder)
    assert recorder.titles == [TITLE]
    assert recorder.infos == [NO_RELEASE_MESSAGE]
    assert NO_RELEASE_MESSAGE == "尚未發布資料。請先完成資料匯入及檢查。"

    source = (REPO / "dashboard.py").read_text()
    block = source.split("if not release:")[1][:200]
    assert "render_missing_release()" in block
    assert "st.stop()" in block


def test_bd_rule_follows_the_published_flag():
    same = build_header(facts(bd_requires_same_adult=True))
    assert any("BD 要求同一成人填卷人" in line for line in same.details)
    different = build_header(facts(bd_requires_same_adult=False))
    assert any("BD 不要求同一成人填卷人" in line for line in different.details)
    assert not any("BD 要求同一成人填卷人" in line for line in different.details)

    unpublished = build_header(facts(bd_requires_same_adult=None))
    assert not any("BD 要求同一成人填卷人" in line for line in unpublished.details)
    assert not any("BD 不要求同一成人填卷人" in line for line in unpublished.details)
    assert any("BD 是否要求同一成人填卷人，此版本未提供。" in line for line in unpublished.details)


def test_staleness_label_matches_the_timestamp_actually_used():
    stale = build_header(facts(source_exported_at="不是日期", created_at="2026-09-01T00:00:00+00:00"))
    assert any(status.message.startswith("版本產生已") for status in stale.statuses)
    fresh = build_header(facts(source_exported_at=EXPORTED, created_at="2026-09-01T00:00:00+00:00"))
    assert not any("日，請檢查每星期匯出是否完成" in status.message for status in fresh.statuses)


def test_component_does_not_read_files_or_connect_a_database():
    source = (REPO / "study2" / "dashboard_header.py").read_text()
    for forbidden in ("sqlite3", "read_text(", "open(", "connect("):
        assert forbidden not in source


# --- r2：Codex P2-1 及 P2-2 回歸 ---

def test_present_failure_record_with_empty_message_still_shows_the_error():
    header = build_header(facts(last_update_error=""))
    errors = [status for status in header.statuses if status.level == "error"]
    assert len(errors) == 1
    assert errors[0].message.startswith("最近一次更新失敗，仍顯示上一個已發布版本。")
    assert "未提供錯誤內容" in errors[0].message


def test_absent_failure_record_shows_no_error():
    header = build_header(facts(last_update_error=None))
    assert not [status for status in header.statuses if status.level == "error"]


def test_failure_record_keeps_the_original_error_text_unchanged():
    header = build_header(facts(last_update_error="匯入失敗：來源檔案損壞"))
    errors = [status for status in header.statuses if status.level == "error"]
    assert errors[0].message == "最近一次更新失敗，仍顯示上一個已發布版本。匯入失敗：來源檔案損壞"


def test_invalid_source_timestamp_keeps_the_unknown_source_notice():
    header = build_header(facts(source_exported_at="not-a-date"))
    assert any(status.level == "info" and "不能證明來源資料最新" in status.message
               for status in header.statuses)
    assert "無效" in header.source_line
    assert "not-a-date" in header.source_line


def test_source_timestamp_without_timezone_is_not_treated_as_confirmed():
    header = build_header(facts(source_exported_at="2026-10-19", created_at="2026-09-01T00:00:00+00:00"))
    assert any(status.level == "info" and "不能證明來源資料最新" in status.message
               for status in header.statuses)
    assert "未確認" in header.source_line
    stale = [status for status in header.statuses if "日，請檢查每星期匯出是否完成" in status.message]
    assert stale and stale[0].message.startswith("版本產生已")


def test_version_timestamp_without_timezone_is_not_shown_as_a_valid_date():
    header = build_header(facts(created_at="2026-10-18", source_exported_at=None))
    assert "未確認" in header.created_line
    assert not any("日，請檢查每星期匯出是否完成" in status.message for status in header.statuses)


def test_confirmed_timezone_timestamps_are_used_as_is():
    header = build_header(facts())
    assert header.created_line == f"版本產生時間：{CREATED}"
    assert header.source_line == f"來源匯出時間：{EXPORTED}"
    assert not any("不能證明來源資料最新" in status.message for status in header.statuses)
    assert not any(status.level == "error" for status in header.statuses)


def test_unusable_source_time_falls_back_to_the_version_label_for_staleness():
    header = build_header(facts(source_exported_at="not-a-date", created_at="2026-09-01T00:00:00+00:00"))
    stale = [status for status in header.statuses if "日，請檢查每星期匯出是否完成" in status.message]
    assert len(stale) == 1
    assert stale[0].message.startswith("版本產生已")
    assert not stale[0].message.startswith("來源匯出已")


def test_naive_now_does_not_produce_a_staleness_claim():
    header = build_header(facts(now=datetime(2026, 10, 20, 12, 0)))
    assert not any("日，請檢查每星期匯出是否完成" in status.message for status in header.statuses)
