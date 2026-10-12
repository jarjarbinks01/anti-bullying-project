# 指定執行者指南：審核工作區及批准

本輪新增「Review Centre.command」，以中文選單完成匯出、收回、預覽、批准、套用、核實報告及裁定。舊「Export Review.command」及平面 `review-export`／`review-import` 保留，供校名、日期、去重、答案及新增漏配個案修正。日常入口待同事試用驗收後才切換。

## 日常流程

1. 雙擊 **Review Centre.command**，選「匯出審核卡」，指定審核者及宗數，預設 20。按案例類型、狀態及規則輪流抽樣，覆蓋已確認、待審及已拒絕案例，只派發兩份提交的身份比較。有效任務不重派。
2. 把工作包交同事。對同一個案安排第二位獨立重審時，要明確指定個案及 `--independent`，不能以相同審核者作獨立重審。
3. 同事交回後，選「收回審核包」。整包空白可收回但不新增答案；已開始而缺一項、非法選項或修改證據／结构，整包拒絕保存並顯示個案及缺漏欄位。有效答案只寫入 `review.sqlite`，不改主資料庫。
4. 選「預覽答案」，打開本機 HTML 預覽。無衝突結果列出擬套用效果；資料不足保留配對及建立待辦；分歧、相反人工決定、身份矛盾及連鎖指令另列。不同人的答案不互相覆蓋。
5. Jarvis 閱讀預覽後，選「Jarvis 批准」並填理由。單機原型依靠指定執行者保管電腦及 state 目錄；輸入姓名不是登入或權限驗證。
6. 選「套用已批准決定」。Pipeline 忙碌時結果保持「已批准、待套用」，稍後重試即可。預覽後有新答案、發布或人工決定，須重新預覽及批准。
7. 用既有 **Prepare Batch.command → Run Pipeline.command** 重跑及發布。Dashboard 只讀已發布版本；收回、批准及套用本身不切換 Dashboard。

## 裁定及重審

「裁定」只採納一個已存在的審核結果，保留 Jarvis 理由、其他答案及被取代的人工決定，再生成新預覽。一般身份資料矛盾須先用舊包的 `SET_FIELD` 修正、重跑發布，再重新派發。

2026-10-09 起，共用核心另支援 Jarvis 明確裁定的兩類成人身份例外：`accepted_typo_unknown_year`（主管接受出生年份錯字、正確年份未確認），以及 `equivalent_relationship_wording`（兩份均填其他關係，原文稱呼同義）。用 `preview_batch(..., adjudications=...)` 或 `review_operator.resolve(..., adult_identity_exception=...)` 指定類型、確認來源及理由。例外綁定兩個提交、同一孩子和成人證據，不修改原始值或標準化答案，不豁免父親／母親關係不同，也不沿連鎖配對豁免第三人的矛盾。證據或孩子分組改變須重新核實。正確出生年份未知不能猜測；資料庫記錄 `adult_birth_year_status=unconfirmed` 及例外來源。

成人資料缺失而無明確矛盾的個案，仍可由 Jarvis 依現有證據逐宗接受人工連結。這不提高自動規則的寬鬆程度。主管例外與自動通過須在核實報告分開追查。

### 2026-10-09：已接受的聯絡後備規則及審核提示

合併資料設定啟用 `matching_policy.allow_exact_general_contact_when_personal_missing`。成人出生年份及關係仍須有效、一致，「其他」關係仍須有相同說明；本人聯絡精確一致優先。至少一份回應沒有可用本人聯絡時，可以其他聯絡欄位的精確電話或電郵一致支持同一成人判斷。兩份均有本人聯絡但互不一致，不適用後備規則；只差一位的成人聯絡不能單憑這個後備規則通過。成人回應先分配至同一已確認孩子，整組成人證據仍須一致。年份／關係缺失或矛盾仍須按既有人工核實流程處理。這項規則同時用於家長短期重填及 BD 選擇，避免两處判斷不同。

新增規則代號 `same_adult_reported_birth_relationship_general_contact_fallback`；Dashboard、BD 的 `adult_match_rule` 及版本摘要可追查後備規則使用量。

既有成人證據未變時，已確認的人工成人配對優先。新增自動候選若與人工配對的另一端不一致，該自動候選待審，不取消原人工配對，也不把出生年份錯字例外延伸至第三份回應。多個人工結果本身互相矛盾時仍整組待審。已接受但正確年份未知的原提交，即使不再選入BD，仍保留 `adult_birth_year_status=unconfirmed`。

候選新增 `review_warning_codes`／`review_warnings`，Dashboard 候選比較及新匯出的審核卡顯示中文提示，舊平面包亦列出提示。檢查年級下降、升級數多於日期跨越學年數、跨學年年級不變、學校及年級階段不一致、混合學校階段不明、建立時間缺失及批次指定日期。P1–P6、S1–S6 按學段連續排序；香港時間每年9月作初步學年分界，屬審核提示的工作假設。未知學段不猜測為小學或中學。這些提示不改身份狀態、不更正答案、不新增排除條件，也不設定親子填卷日期差上限。

短期重填先確認孩子及成人身份，再按30日內較新後續回應規則選擇。較早的後續回應仍保留在原始及處理紀錄，標為短期重填。生日不同而未有裁定支持的其他回應，不自行更正或合併。表格數量的奇偶不作身份或去重條件。真實個案裁定及日期留在本機審核紀錄，不放入程式庫。

相容輸出的 A–D 及 AC／BD 表保留 `adult_birth_year_status` 和 `adult_identity_exception_type`。分析成人出生年份或成人年齡時，`adult_birth_year_status=unconfirmed` 不作有效年份；保留的問卷原值只供追查。這項標記不影響孩子生日或孩子年齡。

身份證據、候選群組或研究規則改變，舊包不能匯入或套用。新匯出會把失效任務標為待重新派發並保存事件。亦可使用 `review-reopen` 明確重新開啟任務。證據未改而來源只新增非身份答案，工作包可承接新發布版本，`carries` 留下承接紀錄；工作包仍顯示原發布的固定證據及來源位置。

只有一份未配對提交或新增漏配候選，繼續由 Jarvis 用旧平面工具建立 `NEW`，不能由同事改卡片 ID。未交回答案的工作包可重新指派；已交回答案則保留原審核者及歷史，另行安排新任務。

## 操作入口

在 `pipeline_v3` 內執行，下列使用示例 ID，不是真實工作包／批次。

```sh
# 匯出一位同事的 20 宗
.venv/bin/python -m study2 review-cards --reviewer '同事代號' --output review_packages/new_cards.xlsx

# 限定類型；identity=孩子身份（跨期或同輪次），family=親子，respondent=同一成人
.venv/bin/python -m study2 review-cards --reviewer '同事代號' --kind family --limit 20 --output review_packages/new_family.xlsx

# 指定另一位同事獨立重審個案，可重複 --case-id
.venv/bin/python -m study2 review-cards --reviewer '另一位同事' --case-id CASE_EXAMPLE --independent --output review_packages/second_review.xlsx

.venv/bin/python -m study2 review-receive returned_cards.xlsx
.venv/bin/python -m study2 review-preview --output review_packages/preview.html
.venv/bin/python -m study2 review-approve RB_EXAMPLE --reason '已核對預覽及無衝突結果'
.venv/bin/python -m study2 review-apply RB_EXAMPLE
.venv/bin/python -m study2 review-report

# 採納某一已存在的答案；輸出新預覽後重新批准
.venv/bin/python -m study2 review-resolve RB_EXAMPLE --case-id CASE_EXAMPLE --review-id REV_EXAMPLE --reason '裁定理由' --output review_packages/resolved.html
.venv/bin/python -m study2 review-reopen TASK_EXAMPLE --reason '資料已修正，重新取證'
```

每次匯出使用新檔名，不覆寫舊工作包。舊包不轉成新任務，版本限制維持原規則。

## 核實報告及口徑

`review-report` 分开列出原規則的人工一致、不一致、程式待審、資料不足及独立重審一致／分歧。程式待審不是「程式判斷不同」。coverage 的分母是當前發布中有兩份提交的身份候選，分子是有審核答案的不同案例；雙人審核不重複計算覆蓋。

同事更正答案，前一版本仍存於 `reviews`，原規則報告採用每個任務修訂的最新答案，並保留失效或重新開啟任務的歷史核實；目前覆蓋另外只計有效任務。同一個案重審不同證據版本，不混入獨立重審一致率。審核歷史與批准／套用事件永久保留。發布的 validation 表使用每個已批准標記所保存的修正前程式判斷，不能把人工修正後的配對率當作原演算法準確率。分層抽樣不能推算全體 precision/recall。

## 兩個資料庫、備份及中斷

| 檔案 | 保存內容 |
|---|---|
| 本機 state 的 `study2.sqlite` | 正式提交、配對、人工指令、核實標記、發布與固定批次套用標記 |
| 同一 state 的 `review.sqlite` | 工作包、固定證據、任務、答案歷史、承接、批次預覽、批准、套用及待複核工作 |
| `state/review_backups/` | 套用前及每次發布前的 SQLite 一致備份，包括未發布答案 |

審核資料庫保存答案只取得自身的短交易，不使用 pipeline 整輪鎖。正式套用使用既有主寫入鎖。固定批次 ID、正式指令及 `review_applications` 標記在主資料庫同一交易寫入；若程序在主資料庫提交後中斷，重試相同批次會恢復工作區狀態，不重複建立指令。

還原先建立全新的副本，不覆寫正在運行的檔案：

```sh
.venv/bin/python -m study2 restore '/完整路徑/review_備份.sqlite' --destination '/新的本機資料夾/review.sqlite'
```

套用前備份保留「已批准、待套用」及尚未發布答案。主資料庫以既有發布備份另行還原到新資料夾；兩個檔案不能任意混用不同時點。以新設定檔指向副本後，先核對發布、任務與核實報告，再重試固定批次。工作區尚未同步而主資料庫已有批次標記時可安全恢復；證據不同則重新審核。不要在正式配置直接覆蓋 live database。

## 同事試用驗收

兩位同事各 20 宗，其中 5 宗重疊、獨立審核，共 35 宗不同個案。兩包不帶其他同事答案。先在 Mac／Windows Excel 開啟、選下拉選單、填理由、跳轉、儲存及交回。執行者記錄：能否自行完成、有沒有跨案例填錯、所有分歧能否追查，以及有效答案能否完成批准、套用、重跑及發布。

只有完成同事試用及兩個 Excel 桌面環境驗收後，才取代日常平面匯出入口。程式自動測試及版面渲染不等同同事試用，也不證明真實配對準確度。
