# 程式閱讀指南

本指南供接手維護的同事閱讀程式。研究規則的完整定義見 [MATCHING_RULES.md](MATCHING_RULES.md)；日常派工及批准流程見 [REVIEW_CARDS_OPERATIONS.md](REVIEW_CARDS_OPERATIONS.md)。

## 第一次閱讀的順序

1. 先看 `study2/runner.py::run`，了解匯入、身份、輪次、輸出及發布的先後次序。
2. 看 `study2/matching.py::automatic_rule` 及 `link_records`，了解孩子身份證據如何變成已確認群組。
3. 看 `matching.py::select_waves`，再看 `parent_waves.py::select_parent_waves`，了解學生及家長的輪次選取。
4. 看 `respondents.py::adult_match`、`classify_adult` 及 `adult_followups`，了解同一成人 BD 如何另行確認。
5. 看 `review_groups.py::build_groups` 及 `review_dispatch.py::Router`，分清候選範圍和真正可交助手處理的問題。
6. 看 `review_core.py` 的五個工作流程接口，最後才看 Excel adapter 和 dashboard。

## 模組各自負責甚麼

| 模組 | 責任 | 閱讀入口 |
|---|---|---|
| `runner.py` | 串起 pipeline，驗證及發布版本 | `run`、`publish_release` |
| `merged.py`、`adapters.py` | 來源登記、標準化及匯入 | 由 `runner.run` 的呼叫追入 |
| `matching.py` | 孩子身份、人工限制、學生輪次及重填 | `link_records`、`select_waves` |
| `parent_waves.py` | 以學生為錨選取家長 T0/T1 | `select_parent_waves` |
| `respondents.py` | 同一孩子下的成人身份及 BD | `adult_followups` |
| `review_groups.py` | 建立完整比較範圍、凍結證據及展開群組裁定 | `build_groups`、`snapshot`、`commands` |
| `review_dispatch.py` | 分流可派審、更正、背景及待新資料 | `Router`、`summary` |
| `review_core.py` | 任務、交回、版本驗證、批准及套用 | `Context`、五個流程接口 |
| `review_excel.py` | 將審核任務寫成卡片及讀取答案 | 由 Review Centre 的操作追入 |
| `outputs.py` | 共用計分、分析輸出及摘要 | `write_outputs` |
| `dyads.py`、`dyad_operator.py` | 永久親子追蹤登記及邀請狀態 | 由 `runner.run` 和 Dyad Centre 追入 |
| `dashboard_views.py`、`dashboard.py` | 發布資料的統計口徑及顯示 | 對照 dashboard 分頁閱讀 |

## 孩子身份的閱讀重點

`link_records` 按以下順序執行：

1. 驗證人工決定是否仍適用。`_decision_source_changed` 區分身份證據更新與必須完全一致的來源版本。
2. 套用有效的 KEEP、EXCLUDE、日期及 LINK/UNLINK，再重建合資格成員。
3. 以生日、性別及聯絡產生候選。共同聯絡可產生背景比較，不能單獨證實孩子身份。
4. `_ambiguous_direct_nodes` 先找出未達成每對直接證據的範圍，避免按遇到的第一條連結決定結果。
5. 已啟用的聯絡連通規則，可確認通過整組證據檢查的子群。`_safe_contact_component` 要求完整身份、內部一致、沒有重新待審成員或人工不配對限制。
6. 保留候選及背景紀錄，再輸出身份成員。

`union` 的關鍵限制是：已有人工或已確認身份不能被子群處理切開；自動規則不能跨越有效 UNLINK。請勿把「有一條接通的路徑」誤當成任何成人或孩子規則都具有傳遞性。

## 輪次選取與成人身份分開

`select_waves` 在身份確認後才處理學生時間。它保留最早合資格 T0，再按短期重填及最少間隔選 T1。原標籤及所有提交繼續保存。

`select_parent_waves` 有三個明確階段：

- `_assign_parent_phases`：以香港曆日先保留學生 T1 同日或之後的家長回應作 T1。
- `_order_phase_responses`：排序；其餘家長回應選唯一最接近學生 T0 的基線。時間相同或距離相同不按來源次序猜選。
- `_select_phase_response`：在同一輪次內檢查同一成人後處理短期重填，保護已選的家長基線。

`adult_followups` 另行檢查 BD。有效人工決定優先，自動證據須符合成人年份及聯絡規則。`_consistent_adult_matches` 檢查所有競爭成人資料，防止某宗人工錯字例外經由第三份問卷傳遞。

這些函數會直接更新傳入的 record 字典。改動時必須保留處理順序，不能在身份未定前先把回應去重。

## 候選範圍不等於派審工作

`review_groups.build_groups` 使用 `Router.group_candidate` 建立科學比較範圍，保留已確認身份的全部成員。它描述尚未確認的連結，不會自行新增正式身份決定。

`Router` 有兩層：

- `_base_classify`：檢查類別、資格、身份矛盾、資料完整性及人工限制。供候選範圍建立使用。
- `classify`：再判斷有沒有具體資料可供核實。證據不足的連結轉為 `awaiting_evidence`，不要求同事猜測。

不可把 `build_groups` 的篩選改成一般派審資格，否則只因助手暫時沒有證據，科學候選範圍也會消失。待新資料也不是 NONMATCH，更不會凍結已確認子群的 T0/T1 或分析樣本。

`Context` 先載入發布版及原始候選，再建立科學群組，最後才覆上派審狀態及有效核實來源。`dispatch_signature` 刻意排除這個操作覆層及來源本身，避免簽章自我依賴。

## 審核接口與資料寫入

| 接口 | 做甚麼 | 正式決定是否改動 |
|---|---|---|
| `create_package` | 固定證據並指派任務，可產生 Excel | 否 |
| `submit_reviews` | 驗證及保存交回答案和修訂 | 否 |
| `preview_batch` | 檢查衝突並固定擬套用內容及版本 | 否 |
| `approve_batch` | 保存指定執行者批准 | 否 |
| `apply_batch` | 再驗證後寫入既有人工決定及核實標記 | 是，尚未發布 |

`apply_batch` 使用 pipeline 寫入鎖。一般保存審核答案只使用 review 工作區交易。套用之後仍要重跑、驗證及發布，dashboard 才切到新結果。

`register_review_evidence` 只登記指定執行者已確認存在的來源、位置及具體問題，不代表身份已確認。來源與完整證據版本綁定，證據改變後失效。

## 改程式時要守住的界線

- 提交 ID、候選 ID、身份 ID 及永久親子 ID 是資料契約，不能隨格式整理改寫。
- `identity_evidence`、`adult_evidence`、snapshot 欄位、排序及狀態字串供人工決定和版本驗證使用，不能隨意改名或省略。
- 人工決定優先；改動證據時應重新待審，不能靜默跳過版本檢查。
- source hash 也是規則／審核簽章的一部分。即使只改善可讀性，下次執行的規則簽章仍會改變，舊任務或已登記來源可能需要重新建立。不要為保留舊包而關掉檢查。
- 已發布資料不會因編輯 Python 自動重算。改動及測試應使用合成案例，正式重跑與發布另外處理。
- 原始資料、私人設定、資料庫、工作包及發布輸出不放進程式版本庫。

## 從哪些測試找例子

| 問題 | 合成案例測試 |
|---|---|
| 先身份後重填、日期界線 | `test_identity_before_dedup.py`、`test_identity_and_time.py` |
| 學生為錨的家長輪次 | `test_student_anchored_parents.py` |
| 成人聯絡、人工例外及競爭資料 | `test_adult_contact_policy.py`、`test_contact_fallback_and_hints.py` |
| 聯絡連通子群及矛盾限制 | `test_contact_bridge_components.py` |
| 整組審核及派審分流 | `test_review_groups.py`、`test_review_dispatch.py`、`test_actionable_review.py` |
| 工作包、版本承接、批准及套用 | `test_review_cards.py`、`test_store_and_review.py` |

先跑與改動直接相關的測試，再跑完整測試套件。單看配對總數相同不足以證明行為沒變，也要檢查成員、選定提交、排除原因、人工限制、輸出次序及拒絕路徑。
