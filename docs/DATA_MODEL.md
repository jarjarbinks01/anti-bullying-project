# 資料模型及識別規則

## 三種識別碼

`submission_id` 是一份原始提交的永久 ID；`version_id` 是該份提交的一個原始內容版本；`child_id` 是目前確認或暫定的孩子群組。重新分組不改提交 ID。孩子群組沿用上一已發布版本的提交錨點；分拆時只有包含錨點的群組保留舊 child_id。群組合併或分拆的歷史可按 run 查閱，不把 child_id 當成原始來源的識別碼。

Qualtrics 的 namespace 在設定中登記，現時用本機 survey 別名；接入真實下載 API 前，collector 必須把別名與實際 Survey ID 對應並固定。ResponseId 不能跨不同問卷直接當成全局身份。舊系統缺可靠 respondent ID，使用来源＋原始建立時間文字＋問卷版本的候選鍵；同批次碰撞或原始鍵變更時停止，不猜測合併。

目前四份合併 Excel 均沒有永久提交 ID，使用原始行登記機制：首次登記來源、工作表及原始行位置。`paper_registry` 保存原始內容指紋；重排、重複下載或新增行會對應原提交。原內容不再存在時，無法判斷是修改還是刪除，因此拒絕自動重用身份；使用受控答案修正或新來源登記。

## SQLite 表

| 表 | 一行代表甚麼 | 是否可以更新 |
|---|---|---|
| submissions | 一份提交及永久來源鍵 | 身份欄位不變 |
| submission_versions | 原始內容、首次標準化答案及來源位置 | 追加新內容版本 |
| paper_registry | 已登記的紙本原行 | 登記新行，未知修改停止 |
| runs | 一次完整執行、指紋、狀態及數量 | 執行狀態更新 |
| run_records | 該次執行採用哪個提交版本 | 每個 run 新建 |
| children | 孩子群組 ID 與錨點提交 | 歷史保留 |
| identity_members | 某次執行的提交→孩子分組 | 每個 run 新建 |
| normalized_records | 該次執行全部清理值、身份／日期／選擇決定 | 每個 run 新建 |
| decisions | 一項人工指令、理由、執行者及 supersedes | 追加，舊決定保留 |
| decision_events | 該次執行怎樣處理人工決定 | 每個 run 新建 |
| labels | 人工核實案例的目前標籤及來源版本 | 明確更新核實標籤 |
| releases | 一個已驗證版本及其輸出路徑 | 歷史保留 |
| release_candidates | 該版本的候選證據及狀態 | 每個版本新建 |
| publication | 唯一目前版本指標 | 驗證發布／回退時切換 |

parent 的 identity_members 指向「回應所指孩子」。BD 另要求成人出生年份、與孩子關係及精確聯絡一致，或有效人工 LINK_ADULT。本人精確聯絡優先；至少一份本人聯絡缺失時，可按已啟用的後備規則使用其他精確電話／電郵，見[現行規則](MATCHING_RULES.md)。`respondent_id` 是該孩子基線成人的分析識別碼，並非跨孩子永久成人登記。`bd_selected_wave`／`bd_match_rule` 保存成人專用輪次及證據；家庭 `selected_wave` 可與 BD 不同。成人決定用獨立 adult_pair target，證據更新重新待審。EF 只要求孩子一致，另列照顧者一致／變更／未知，不以成人 ID 跨孩子連結。

## 日期與原始值

目前 `observed_at` 保存由現有 `建立時間` 解析的分析時間，或人工核實时间。`date_basis` 分 system_creation／batch_assigned_creation；`time_confidence` 分 observed、manual_verified、accepted_creation_time、batch_only、unknown。按 Jarvis 2026-10-06 決定，紙本批次指定建立時間標為 accepted_creation_time，可計算90日，但不稱為實際日期核實；年齡不據此推定。`batch_at` 保存批次時間，`imported_at` 保存內容版本首次匯入時間。原值與日期政策均可追查。

原始答值在 submission_versions；每次轉換及人工修正後的答值在 normalized_records。排除使用狀態和原因，不刪提交。審核涉及聯絡資料與出生日期，審核包及備份需在研究團隊受控存放位置。

## 字典與版本

校名字典是唯一可修改的本機管理工作表，透過受控 schools 匯入。每次發布保存字典實體、副本指紋、來源清單、程式、映射函數、套件版本及人工決定 ID。字典 key 重複而內容衝突時拒絕執行。

`same_person_entry_id` 是提供舊格式的輸出欄，不能用來接收人工修正；人工修正只能用永久 submission_id 和來源 version_id。

## 分析視圖

`analysis.parquet` 是家庭／孩子每類別的選定T0／T1；`parent_longitudinal.parquet` 是同一成人BD的两輪回應，可包含家庭視圖中列為其他follow-up的回應。量表只在共用層對每份需要的提交計分一次。`candidate_evidence.parquet` 只含一致性摘要，不含完整電話、電郵、生日或成人出生年份；詳細證據在受控審核包與原始記錄。
# 共用審核工作區（新增）

本機 state 的 `review.sqlite` 與 `study2.sqlite` 分開。`packages` 保存固定工作包及 Excel 只讀內容校驗；`tasks` 保存永久提交、案例類型、指定審核者、原發布、證據／群組／規則版本及任務修訂；`reviews` 以每任務遞增答案修訂保留全部歷史；`batches` 保存固定預覽、批准及套用狀態；`events`／`carries` 保存派工、更正、裁定、承接及恢復事件；`followups` 保存資料不足的待複核工作。

共用接口位於 `study2/review_core.py`：`create_package`、`submit_reviews`、`preview_batch`、`approve_batch`、`apply_batch`。Excel adapter 位於 `study2/review_excel.py`，只處理輸出、識別及只讀內容校驗。舊平面工具亦使用 `validate_review_rows`／`commit_review_rows`，保留原有嚴格版本規則。

## 永久親子追蹤

`study2/dyads.py` 提供唯讀 `plan`、預留 ID 的 `stage`、發布前 `validate_staging` 及發布交易中的 `publish_memberships`。它讀取既有研究結果，不參與身份規則或量表計分。

`dyad_registry` 保存隨機永久 ID、不可覆寫的首次 T0 學生／家長提交、最初預留的 run、建立時間與身份證據。`first_published_run_id` 在首次成功發布時固定，與可能中斷的預留 run 分開。生命週期狀態另行更新；ID 永不刪除或重用。

`dyad_lineage` 保存已確認提交的身份證據簽章及目前是否有效。人工裁定可以停用舊追蹤依據，歷史仍保存。`dyad_memberships` 固定每個 run 的家庭、孩子群組、角色輪次及完成狀態。群組拆分或多個登記合併時，不自動挑選歸屬。

`dyad_events`、`dyad_resolutions` 和 `dyad_aliases` 保存有固定操作 ID 的裁定、前後依據與合併別名。`dyad_invitation_events` 是人工保存的行政事件，不推定問卷已收到，也不發送訊息。相同操作及相同實際邀請事件不重複寫入。

原始 `submission_id`、來源版本及審核規則不受行政 ID 影響。研究回退保留較新的行政歷史；追蹤 bundle 另保存發布後新增的登記、邀請、裁定及完整審核工作區。操作及還原方法見 [永久親子追蹤指南](DYAD_TRACKING_OPERATIONS.md)。

主庫新增 `review_applications`，固定批次 ID 與正式指令、核實標記在同一交易提交，避免兩個資料庫之間中斷導致重複套用。審核者答案永遠先保存在工作區；發布資料不讀未批准答案。核實標記的 `pre_review` 保存修正前判斷，工作區另保留全部審核／裁定歷史。
