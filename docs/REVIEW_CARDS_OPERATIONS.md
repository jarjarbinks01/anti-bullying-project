# 指定執行者指南：審核工作區及批准

本輪新增「Review Centre.command」，以中文選單完成匯出、收回、預覽、批准、套用、核實報告及裁定。舊「Export Review.command」及平面 `review-export`／`review-import` 保留，供校名、日期、去重、答案及新增漏配個案修正。日常入口待同事試用驗收後才切換。

舊平面包的身份比較亦使用相同過濾，不會因 `--limit 0` 匯出全部而重新混入矛盾或無可用聯絡的比較。平面包仍可抽查已有結論的正常身份比較，並保留其他修正及提交索引；需要更正資料時由 Jarvis 使用 `NEW_RECORD`，不把更正工作偽裝成身份審核。

## 日常流程

1. 雙擊 **Review Centre.command**，選「匯出審核卡」，指定審核者及宗數，預設 20。一般派工只從有完整一致孩子身份、兩方均有有效電話或電郵的待審比較中，按類型及規則抽樣。生日／性別矛盾、已排除提交、無可用聯絡、待更正資料及有效人工不配對限制不會混入。指定 ID、獨立重審及重新指派同樣受此限制。有效任務不重派。
2. 把工作包交同事。對同一個案安排第二位獨立重審時，要明確指定個案及 `--independent`，不能以相同審核者作獨立重審。
3. 同事交回後，選「收回審核包」。整包空白可收回但不新增答案；已開始而缺一項、非法選項或修改證據／结构，整包拒絕保存並顯示個案及缺漏欄位。有效答案只寫入 `review.sqlite`，不改主資料庫。
4. 選「預覽答案」，打開本機 HTML 預覽。無衝突結果列出擬套用效果；資料不足保留配對及建立待辦；分歧、相反人工決定、身份矛盾及連鎖指令另列。不同人的答案不互相覆蓋。
5. Jarvis 閱讀預覽後，選「Jarvis 批准」並填理由。單機原型依靠指定執行者保管電腦及 state 目錄；輸入姓名不是登入或權限驗證。
6. 選「套用已批准決定」。Pipeline 忙碌時結果保持「已批准、待套用」，稍後重試即可。預覽後有新答案、發布或人工決定，須重新預覽及批准。
7. 用既有 **Prepare Batch.command → Run Pipeline.command** 重跑及發布。Dashboard 只讀已發布版本；收回、批准及套用本身不切換 Dashboard。

## 裁定及重審

「裁定」只採納一個已存在的審核結果，保留 Jarvis 理由、其他答案及被取代的人工決定，再生成新預覽。一般身份資料矛盾須先用舊包的 `SET_FIELD` 修正、重跑發布，再重新派發。

2026-10-09 起，共用核心支援 Jarvis 明確裁定的 `accepted_typo_unknown_year`（主管接受出生年份錯字、正確年份未確認），並保留當時的 `equivalent_relationship_wording`（兩份均填其他關係，原文稱呼同義）裁定歷史。2026-10-15 起關係不再是成人身份門檻，新的關係差異不用申請例外。出生年份例外仍須用 `preview_batch(..., adjudications=...)` 或 `review_operator.resolve(..., adult_identity_exception=...)` 指定類型、確認來源及理由。例外綁定兩個提交、同一孩子和成人證據，不修改原始值或標準化答案，也不沿連鎖配對豁免第三人的矛盾。證據或孩子分組改變須重新核實。正確出生年份未知不能猜測；資料庫記錄 `adult_birth_year_status=unconfirmed` 及例外來源。

成人資料缺失而無明確矛盾的個案，仍可由 Jarvis 依現有證據逐宗接受人工連結。這不提高自動規則的寬鬆程度。主管例外與自動通過須在核實報告分開追查。

### 2026-10-15：所有聯絡欄的成人確認規則及審核提示

合併資料設定使用 `matching_policy.adult_contact_scope="any_exact"`，取代只容許本人聯絡缺失時使用其他聯絡的舊設定。兩份家長回應先分配至同一已確認孩子，成人出生年份須有效、一致；全部聯絡欄逐項拆分，任一精確電話或電郵相同即可，兩份本人聯絡都有填但不同亦可使用共同的其他聯絡。分號、逗號、斜線及換行可分開多項聯絡；電話正規化後須為有效八位數，電郵不分大小寫。成人聯絡差一位不能自動通過。與孩子關係及「其他」文字保留供查看，不作確認門檻。年份缺失或矛盾仍須人工核實。這項規則同時用於家長短期重填及 BD 選擇，整個成人分組仍檢查有沒有矛盾。

新規則代號為 `same_adult_reported_birth_personal_contact` 及 `same_adult_reported_birth_any_exact_contact`。Dashboard、BD 的 `adult_match_rule` 及版本摘要可追查使用量；舊後備規則代號僅保留用來解讀歷史發布。人工成人證據快照新增全部聯絡；舊快照只有在原來源版本及原證據均可驗證時才承接，否則重新待審，不改寫原裁定。

既有成人證據未變時，已確認的人工成人配對優先。新增自動候選若與人工配對的另一端不一致，該自動候選待審，不取消原人工配對，也不把出生年份錯字例外延伸至第三份回應。多個人工結果本身互相矛盾時仍整組待審。已接受但正確年份未知的原提交，即使不再選入BD，仍保留 `adult_birth_year_status=unconfirmed`。

候選新增 `review_warning_codes`／`review_warnings`，Dashboard 候選比較及新匯出的審核卡顯示中文提示，舊平面包亦列出提示。檢查年級下降、升級數多於日期跨越學年數、跨學年年級不變、學校及年級階段不一致、混合學校階段不明、建立時間缺失及批次指定日期。P1–P6、S1–S6 按學段連續排序；香港時間9月1日至翌年8月31日為研究負責人已確認的學年定義，跨學年正常升一級。小六轉中一按連續學段6→7比較，原整理值維持6→1，不視為倒退。未知學段不猜測為小學或中學。這些提示不改身份狀態、不更正答案、不新增排除條件，也不設定親子填卷日期差上限。

短期重填先確認孩子及成人身份，再按30日內較新後續回應規則選擇。較早的後續回應仍保留在原始及處理紀錄，標為短期重填。生日不同而未有裁定支持的其他回應，不自行更正或合併。表格數量的奇偶不作身份或去重條件。真實個案裁定及日期留在本機審核紀錄，不放入程式庫。

相容輸出的 A–D 及 AC／BD 表保留 `adult_birth_year_status` 和 `adult_identity_exception_type`。分析成人出生年份或成人年齡時，`adult_birth_year_status=unconfirmed` 不作有效年份；保留的問卷原值只供追查。這項標記不影響孩子生日或孩子年齡。

身份證據、候選群組或研究規則改變，舊包不能匯入或套用。新匯出會把失效任務標為待重新派發並保存事件。亦可使用 `review-reopen` 明確重新開啟任務。證據未改而來源只新增非身份答案，工作包可承接新發布版本，`carries` 留下承接紀錄；工作包仍顯示原發布的固定證據及來源位置。

只有一份未配對提交或新增漏配候選，繼續由 Jarvis 用旧平面工具建立 `NEW`，不能由同事改卡片 ID。未交回答案的工作包可重新指派；已交回答案則保留原審核者及歷史，另行安排新任務。

## 操作入口

在 `pipeline_v3` 內執行，下列使用示例 ID，不是真實工作包／批次。

```sh
# 匯出一位同事的 20 宗
.venv/bin/python -m study2 review-cards --reviewer '同事代號' --output review_packages/new_cards.xlsx

# 看實際一般審核、資料更正及不派審的比較數；不把背景候選當工作量
.venv/bin/python -m study2 review-queue

# 品質抽查需明確指定用途；仍會排除孩子生日／性別矛盾及無可用聯絡
.venv/bin/python -m study2 review-cards --purpose validation --reviewer '核實同事' --output review_packages/quality_sample.xlsx

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

`identity_review_queue` 另列派審分類及工作量；`pending_candidates_total` 是原始待審比較數，`reviewable_comparisons_before_grouping` 是過濾後、合組前的比較數，`remaining_general_reviews` 是尚待處理的孩子群組加成人比較數。已派發不等於完成。無可用聯絡不列為補資料待辦；電話缺失但有效電郵存在可繼續追查。舊工作包只為派工格式改變而不失效，原有證據與答案仍可收回；有真正身份、群組或研究規則變動則仍須重審。

## 群組卡操作

### 只派具體可核實的問題

派工政策 `actionable_evidence_v1` 將「沒有共同聯絡或其他可核實來源」列為 `awaiting_evidence`。有電話可追查不等於有資料可核實；疑似錯字亦不自動代表原件存在。這類個案不要求助手逐宗填卡，不產生 NONMATCH，原問卷、子群、輪次和永久 ID 照常保留。

1. 在 Review Centre 選 8，Jarvis 登記個案 ID、來源類別、實際可查閱位置，以及具體要核對的問題。孩子身份使用完整 GROUP ID。
2. 登記代表 Jarvis 已確認該來源可供審核者查閱。單純重看同一批合併 Excel 不算新增核實來源；原始標籤、年級或兩個不同電話本身亦不夠。
3. 再使用原有匯出入口。新卡會顯示登記的問題及來源位置，仍只填三項黃色欄位，並經原有收回、批准、套用及發布流程。
4. 來源登記是有版本的歷史紀錄，重複登記同一資料不新增紀錄，改登記保留舊版。身份證據、群組、候選或研究規則變動時，原登記失效，需重新確認來源。

CLI 對應入口：

```sh
python -m study2 --config config.merged.json review-evidence-add --case-id GROUP_example --source 既有收集紀錄 --reference '收集名冊第7行，可在研究室查閱' --question '核對SG001與SG002是否記錄同一孩子的收集編號'
python -m study2 --config config.merged.json review-waiting-export --output outputs/awaiting_evidence_new_snapshot
```

第二個入口唯讀建立固定版本 SQLite、manifest 及說明檔，不覆寫已有資料夾，不改主資料庫或舊固定資料集。`cases` 是等待新證據的群組／成人比較，`members` 只含身份與來源資訊，`comparisons` 保留直接聯絡規則及目前同組狀態。這是參考資料集，不是填答工作包。

Dashboard 的「一般身份審核」只計有核實依據的工作；「證據不足，待新資料（暫不合併）」分開列出孩子群組及成人比較。這是操作派工狀態，正式樣本仍引用原發布版本。舊卡及已交回歷史不刪除；題目或版本失效時不得以舊卡繼續套用。

2026-10-16 起，啟用 `allow_contact_bridge_components` 及 `allow_contact_subgroups` 的合併資料版本逐個自動確認孩子身份完整一致、沒有人工不配對或失效決定的聯絡連通子群，不要求較大候選群組全部連通。既有人工／已確認身份不得被切開。一般孩子身份派工只要求判斷「尚有未連起子群」之間的缺口及孤立提交；程式保存自動群組及直接連結證據，不把自動確認記成同事答案。單數問卷正常保留，輪次及重填另外處理。這是正式研究規則變更，舊工作包按既有規則版本檢查；已自動通過的個案毋須重填，仍待審的個案須重新匯出，保留舊包及所有已收回答案。既有固定版本待審資料集亦不覆寫，更新後應另建新版本。

1. 指定執行者使用原有 `review-cards` 入口，預設每包 20 宗。孩子身份改派 `GROUP_…`，成人身份仍派兩份比較。正在處理的舊比較會佔用其相關群組，避免重複派工。`--purpose validation` 是另行安排的逐對品質抽查，不是日常待審清單；重新指派保留原工作包的用途。
2. 同事先開啟每宗的「群組參考」，查看全組 R001、R002 等提交、SG 子群摘要及聯絡連結表。綠色並列文字「已通過直接規則」或「已確認子群內的間接連結」毋須逐對重審；只核實跨子群缺口及孤立問卷。欠聯絡證據不等於已確認不同孩子。審核卡上方兩份只代表證據缺口，結論仍適用於全部 R 編號。
3. 三項輸入不變。確認相同表示全組均指向同一孩子。確認不同時，在理由列出分組及證據，例如「R001、R003 一組，R002 另一組」。資料不足會保留正式配對，保存一宗群組待辦。
4. 收回、預覽及批准入口不變。確認相同經批准後轉成組內明確 LINK；確認不同先進例外，Jarvis 核對 R 編號與永久提交 ID 後，提交完整分組，才能批准組內 LINK 及組間 UNLINK。

指定執行者的分組 JSON 格式是提交 ID 的二維陣列，例如 `[["SUB_a","SUB_c"],["SUB_b"]]`。每份提交必須出現一次，不能遺漏或重複。使用 `review-resolve … --group-partition partition.json`，再按原流程預覽、批准及套用。程式不會自行解析同事的理由文字來拆分身份。群組程式、全組證據或候選改變會令群組卡失效；原始逐對卡仍使用其既有證據檢查。

Dashboard「一般身份審核」每行為一個孩子群組或一宗成人比較。所有原始比較保留在「全部候選」，並列出所屬審核群組。正式 AC／BD／E／F／EF 樣本只在批准、套用、重跑及發布後更新。

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
