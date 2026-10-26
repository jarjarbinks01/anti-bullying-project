# 描述統計及 4.1 報表操作說明

畫面、圖表及 Excel 使用同一個已發布版本及統計服務，不重新決定身份、輪次或配對，也不把舊 4.1 Excel 的數字當作目前結果。

## 操作步驟

1. 開啟「描述統計」的「研究總覽」，選「分析樣本」、填卷對象及學校範圍。預設為各輪全部樣本、學生、主流學校、全部組。
2. 按「首頁口徑：全部學校、取消篩選」，可重現該模式對應的正式樣本數。首頁包括非主流及未知學校，因此主流分析通常較少。
3. 先看樣本概況、量表總覽及資料可用性。「量表總覽」固定顯示 PHQ、FQOL、SEC。展開「其他指標及九個分組比較」，先選「指標類別」：PHQ、FQOL、SEC 的整組分布圖直接顯示在選單下方，毋須再展開或逐項切換。「總分及分量表」摘要移至同區的「下載目前分析及核對明細」，並排顯示 T0／T1 平均（SD）、有效 N 及缺失 N；PHQ 另列總分分組人數。欺凌指標及人口特徵在各自類別內選取。資料可用性同時列出目前整組指標。性別／學段在上方分組展開區。各輪 A–D／E–F 可以不同人。
4. 進階篩選可選學校、來源及孩子身份規則。留空代表不限，規則多選代表符合任一項，不能把規則數相加。
5. 展開「核對口徑、逐步排除數及資料版本」，分清未篩選、學校範圍、進階篩選及分組後的 N。
6. 填卷對象同時控制人口特徵及量表；學生和家長使用各自適用的指標。切換後仍適用的篩選保留，無效選項清除並提示。
7. 在「下載目前分析及核對明細」下載 CSV／Excel，或展開本版固定四份報表。固定報表為主流學校及九組，不受畫面篩選影響。

「深入分組」同時控制整組指標的摘要及下載。多個分組時，「分布圖分組」只控制圖表，摘要及下載仍包含所有已選分組。整組展示不合併分數、不改計分，各指標繼續各自扣除缺失；PHQ 的分類不計平均。PHQ 總分為 0–12，焦慮及抑鬱各為 0–6，各圖保留自己的量尺。

## 跨期比較工作台

1. 明確切換「跨期比較」，再選 AC／BD 或 EF、角色和學校範圍。這是另一個正式跨期樣本，N 可能與原來 A–D／E–F 不同，不會暗中把各輪樣本當成同一批人。
2. 選一個指標，查看正式配對 N、兩輪均有效、只有 T0 有效、只有 T1 有效、兩輪均缺失。後四項合計為正式配對 N。
3. 預設「逐人變化」，看 T1 減 T0 差值分布、平均差、差值 SD 和上升／不變／下降。二元欺凌指標改為四格轉移及百分點差；PHQ 分數分類只作分類分布，不求代碼平均差。
4. 「T0／T1 分布」作輔助核對，看同一批完整配對的箱形圖或共同分箱直方圖。直方圖T0在上、T1在下，兩圖共用分數範圍、分組界線及人數刻度，不再把兩輪柱子重疊。橫軸為分數、縱軸為人數；滑鼠提示顯示範圍及人數／有效N。PHQ整數分數的一格如1.5–2.5代表2分；FQOL／SEC則按相同範圍把相近小數分數分組。柱高差不能當作有多少人改變，需用「逐人變化」查看。展開數值摘要查看平均、樣本 SD、Q1、中位、Q3、最小／最大。N=1 只顯示點，不估算 SD。
5. 「子群比較」按基線孩子性別、學校階段或九組比較同一指標。未知學段留在全部組；九組互有重疊，不能相加。
6. 下載目前分析，Excel 分開分布摘要、共同分箱、配對摘要、二元四格或分類，以及篩選／版本。下載只含聚合統計，不含完整生日、聯絡或逐人配對行。

總覽標示 `wave_valid`，每輪各自扣缺失；工作台標示 `paired_valid`，兩輪分布及平均只用該指標兩輪均有效的相同單位。平均差等於這批完整配對的 T1 平均減 T0 平均。每項指標獨立處理缺失，不要求所有量表共同完整。

新探索下載中的 `missing_n` 是該有效基礎扣除的人數。完整配對時，`wave_invalid_n` 只計本輪缺失／無效；`missing_detail` 另以 `other_wave_missing_or_invalid` 記錄本輪有效、但另一輪缺失／無效而未能進入完整配對的數量。所有原因相加等於 `missing_n`；不把另一輪缺失誤稱為本輪漏答。完整篩選在 Excel 的「篩選及版本」保存一次，數值表不重複整段設定文字。

箱形圖使用 linear 分位數，鬚為 1.5 IQR 內最遠實際值。箱鬚外觀察仍屬有效分布，保留在平均、N、直方圖及最小／最大，不是新增研究排除。兩輪／同次子群共用分箱，最後一箱含右端點。差值絕對值不超過 1e-9 只視為浮點相等，不是臨床改善門檻。

BD 必須使用 BD 的實際 T1。EF 家長及獨立家長同一孩子分支不提供成人 PHQ 或其分類的跨期選項；成人變化請明確切換同一成人分支。填卷人未確認不等於已確認換人。

獨立家長頁也有研究總覽、跨期比較及時段趨勢，使用共用核心；上方輪次只控制明細及該輪回應下載。選「全部獨立基線及追蹤」時不能直接開跨期工作台，須明確改為「跨期樣本」並核對新的 N；仍可使用時段趨勢。獨立分支的 T0／T1 及 90 日規則不變，數字不加進 BD／EF。

舊發布沒有探索能力時仍可閱讀研究總覽和既有報表，工作台會提示該版本未提供；不把未提供當成零，不讀另一發布的資料。

「獨立家長分析」的輪次選項控制該輪 N、配對明細及選定回應下載；研究總覽及跨期比較把兩輪並排，並按同一個基線篩選整組。其統計下載包含兩輪，不是只包含上方選定的一輪；時段趨勢則使用自己的輪次控制。

## 時段趨勢

用途是觀察「期間內填卷的正式選定回應如何變化」。每週或每月的填卷者可以不同；同一孩子的 T0 和 T1 也可以在不同時段出現。因此回應份數不是獨立參加者人數，折線不代表逐人改善或研究效果。

1. 在「描述統計」選好分析樣本、填卷對象、學校及其他篩選，再切換「時段趨勢」。總覽與趨勢沿用同一組樣本篩選；跨期比較維持其獨立設定。
2. 選每月（預設）或每週、T0／T1 或兩者，以及日期來源。
3. 初次進入的日期為目前樣本、輪次及日期來源下的可用範圍。輸入開始及結束日期，包含香港首尾兩日。換發布版本、分析樣本或角色時重設日期並提示；其餘篩選及日期來源變更保留已選日期，可出現空時段。
4. 選 PHQ、FQOL 或 SEC，整組總分及分量表直接顯示；PHQ 另有分數分類比例。欺凌及人口特徵在各自類別內選擇指標。
5. 核對期間內 T0／T1 N，再展開日期排除及來源。第一個 N 是原有篩選後、尚未做日期篩選的數目；下方才是指定期間內數目。
6. 查看每期回應數、指標折線及該輪學校／來源／性別／學段組成。圖上滑鼠提示包括實際涵蓋日期、有效／缺失 N、SD 或分子／分母。
7. 在「下載目前分析及核對明細」查看每期及全期間數值，下載六份彙總 CSV、同一內容的 Excel，或單獨下載設定 JSON。

獨立家長頁使用同一操作及計算核心，但保留其正式獨立家長輪次。上方的「明細及回應下載輪次」不控制時段趨勢，趨勢有自己的輪次及日期控制；兩套樣本不相加。可換填卷人分支的成人 PHQ 只描述各期填卷回應，不能繞過原有成人 PHQ 配對比較限制。

### 日期及分組政策

| 發布日期證據 | 預設處理 |
|---|---|
| `time_confidence=observed` 且 `date_basis=system_creation` | 納入系統記錄日期 |
| `time_confidence=manual_verified` | 納入人工核實日期；優先於原本批次標記，原來源仍保留 |
| `accepted_creation_time` 且 `batch_assigned_creation` | 預設排除，可選加入並提示批次登記可能造成高峰 |
| 缺失、無效時間，或其他未能判定的來源組合 | 排除並另列，加入批次日期也不會納入 |

只使用已發布 `observed_at`，不使用檔案時間、匯入時間或發布時間補填。沿用 pipeline 的時間解讀：帶時區時間轉香港，無時區時間先依既有 UTC 約定解讀，再轉香港；不在圖表層修正來源時間。原始值為數字時不猜 Unix 時間。

每週為星期一至星期日，每月為曆月。首尾不足完整週／月在時間軸加「＊」，提示及下載保存完整時段與實際涵蓋日期。例如 2025-09-03 至 2026-03-30 有七個月份，九月及三月是部分月份，不把它們推算成整月。

沒有回應的時段仍保留：回應數為0，平均及比例留空，折線斷開。有回應但指標均缺失也不顯示為0分／0%。有效 N=1 可計平均，不估算樣本SD。全期間結果由所選回應直接計算，不能平均各月平均。類別只計各類人數及比例，不取代碼平均；SEN 多選沿用原分母，合計可超過100%。

日期排除按「現有篩選後 → 輪次選擇 → 有效日期及已知來源 → 日期來源選擇 → 指定期間」依序列出。各步排除互斥，各輪最後 N 加本輪各步排除等於原有篩選後 N。日期來源核對則顯示每類日期在篩選前及期間內數目。

每期組成使用該輪實際學校、來源、孩子性別及學段，未知另列；上方樣本篩選仍沿用各模式既定的學生／基線錨點。這兩種用途分開標示，避免把固定基線篩選誤讀成每期實際學段。

欺凌題目回顧過去三個月，三月圖點代表三月填卷者的回顧回答，不是三月事件發生率。月間變化也可能來自不同學校、來源或填卷者；第一版不加平滑線、顯著性檢定或因果結論。

### 版本、下載及維護

時段功能標示 `basis=calendar_response`，政策版本 `study2_calendar_response_v1`。設定保存發布、報表、字典及趨勢版本、角色、樣本及分組錨點、香港時區、日期範圍、間隔、日期來源、輪次、指標及全部既有篩選。CSV 每行附完整設定；Excel 在「設定及版本」保存一次。每期統計、全期間統計、回應數、日期排除、日期來源及樣本組成各自一張表，只包含彙總，不新增提交 ID、完整生日或聯絡資料。

`descriptive_trends` 驗證欄位並重用 `descriptives.statistics` 的定義、分母及缺失處理，無須重新計分。`descriptive_trend_charts` 只讀彙總結果，`descriptive_trend_dashboard` 共用控制、快取與下載。快取包括所選資料、發布／政策／報表／字典版本及完整設定。任意日期範圍在唯讀畫面計算，不修改發布檔或另建一套正式樣本。

缺少必要日期或來源版本欄位的舊發布會提示不支援，不讀取即時資料庫、原始 Excel 或其他版本補欄位。沒有可用日期時顯示來源診斷，不推定一段填卷期間。

日期篩選不得重選問卷：正式T0在期間外而T1在期間內，T1仍是T1；正式選定T1在期間外，不改取期間內另一份較早問卷。matching、pairing、短期重填、90日規則、永久ID、人工裁定、既有計分及正式樣本均維持原結果。批次日期的圖表選項也不放寬年齡可用性。

| 模式 | 用途 | 分組及篩選依據 |
|---|---|---|
| 各輪全部 A／B／C／D | 每輪選定回應，兩輪可不同人 | 各輪回應所指孩子 |
| 各輪親子 E／F | 每輪已確認親子，兩輪可不同家庭 | 該輪學生決定性別、學校及階段；來源／規則用所選角色 |
| 同一人跨期 AC／BD | 同一學生或成人的兩輪回應 | 學生 T0 或 BD 家長 T0 所指孩子，整組篩選 |
| 跨期親子 EF | 兩輪都有學生及家長，共四份回應 | 學生 T0；四份共同篩選，家長可能換人 |

BD 使用其實際選定家長 T1，不能用家庭 F 的另一份回應代替。九組互有重疊，不可相加。跨期固定 T0 分組，小六升中一仍屬基線小學組；每輪實際年級及階段另保留。來源及規則也以基線為準，避免兩輪篩選出不同人卻仍稱配對分析。

一條龍學校優先用既有年級的 P／S／F 等學段證據，不按執行當日年齡推定。主流資格與學段分開：主流但學段未知可進全部組，不進小學或中學組。主流學校內有 SEN 的孩子不因 SEN 被排除。

## 分母及缺失

- 樣本 N 是該模式、角色及輪次的正式回應數；跨期在扣指標缺失前兩輪組數一致。
- 連續值為平均及樣本 SD，年齡另有最小／最大值。只有一份有效值時 SD 缺失。
- 分類為人數／有效分母（%），另列該題缺失 N。有效 N 加缺失 N 等於樣本 N。
- 已確認範圍的連續指標另列「超出有效範圍 N」，屬於缺失 N 的一部分；不從樣本 N 刪除。BMI及兄弟姊妹總數也會包含必要分項超範圍而不可計算的個案。
- SEN 多選以有效回答該題的人數作分母，包括回答沒有 SEN 的人，各類比例可合計超過 100%。
- 缺失、無效及「沒有」與具體 SEN 同選不推定為有／沒有 SEN。缺失原因可展開，包括日期未達可信度及來源編碼待核。
- 空樣本或沒有有效值不顯示成 0 分或 0%。配對差要求兩輪該指標均有效，先逐人計算 T1 減 T0 再求平均，不能用兩個有效人群的平均相減。

家長 PHQ 描述填卷成人，學生 PHQ 描述學生本人；家長 SEC 及欺凌題目描述孩子。FQOL、SEC 及欺凌平均分沿用共用平均，PHQ 加總。所需題目完整才計分，圖表及匯出不再次計分。PHQ 分數組別僅呈現分布，不作診斷。

EF 及獨立家長可換填卷人分支不提供成人 PHQ 配對差，請改選 BD 或獨立家長同一成人分支。出生年份不同本身不標成已確認換人，成人身份狀態另列。

## 問卷核對及人口特徵

變項已對照中英學生及家長問卷範本與標準化映射。程式字典在 `study2/descriptive_spec.py`，每版附有 `descriptive_dictionary.json`。

| 變項 | 核對及處理 |
|---|---|
| 學生身高／體重 | 原題 cm／kg；身高100–200、體重20–100，含上下限，不自動換算可能錯填單位 |
| 兄弟姊妹 | 各分項0–5、總數0–10，含上下限；四項均有效才加總，缺項不當零，分項或總數超範圍列缺失 |
| 成人性別 | 原問卷未獨立收集，顯示未收集，不從稱謂推定 |
| 填卷人關係 | `adult_demographics_06`：父親、母親、其他 |
| 主要照顧者 | `adult_demographics_07`：父母、祖父母、家傭、其他；不把多個單選代碼當作一個合法值 |
| 教育程度 | 原 0–1 小學或以下、2–5 中學／職業培訓／預科、6–7 大專／大學、8 碩士及以上 |
| 婚姻及同住 | 不方便提供為有效婚姻選項；同住 0 是、1 否 |
| 子女人數 | 1、2、3、4 個或以上，不求代碼平均；只解讀已確認的 Qualtrics 編碼 |
| SEN | 0 ADHD、1 ASD、2 SpLD、3 沒有、4 其他；缺失、無效及矛盾分開 |

成人只有出生年份，年齡是有效觀察年份減出生年份的估算。孩子重用既有觀察日期年齡，均遵守原日期可信度；允許批次時間分輪不放寬年齡計算。人工接受年份錯字而正確年份未知時不猜填年齡。Jarvis於2026-10-17確認沿用舊4.1描述範圍：孩子5–20歲、成人20–70歲，含上下限。範圍只影響描述統計，原始值、既有觀察年齡欄及樣本均保留。

BMI只在身高與體重均在已確認範圍內時，以kg／米平方計算連續值，不以成人界線替兒童分類。需要分類時須另確認研究採用的兒童參照。有效範圍只屬描述統計政策，不可用來改身份、答案或輪次。

目前保留的限制：非 Qualtrics 子女人數編碼待核；成人性別未收集；中英 FQOL 同意／滿意文字有差異，沿用現有共同計分；不作兒童 BMI 分類。這些限制不排除整份回應、不改身份或輪次。

日後修改有效範圍須先由研究負責人確認，再由指定執行者更新 `descriptive_spec.REPORT_RANGES`、說明及字典／報表版本，先測試範圍邊界，再建立新的候選發布及核對有效／缺失數。不要手改已發布的 Parquet 或 Excel。新版本只改描述值的可用性，原始答案及正式樣本仍須守恆。

## 發布及輸出

沿用 Run Pipeline，在候選版本生成並核對後才發布，無須另手動匯入 4.1。獨立家長沿用自己的分支及輪次，使用共用統計核心，數字不併入 BD／E／F／EF。

| 發布項目 | 每行／內容 |
|---|---|
| `descriptive_measurements.parquet` | 每提交必要人口特徵、可用性原因、學段及來源版本；無完整生日或聯絡資料 |
| `descriptive_statistics.parquet` | 四模式、兩角色、九組及兩輪的數值統計 |
| `descriptive_changes.parquet` | 適用樣本逐人配對差統計 |
| `descriptive_caregivers.parquet` | EF 成人身份狀態 |
| `descriptive_dictionary.json` | 變項、分類、單位、來源及限制 |
| `descriptive_manifest.json` | 規格、樣本數、統計行數與四份指紋 |
| `descriptive_distribution_summary.parquet` | 每輪各自有效／完整配對兩輪／差值的分位數及數值摘要 |
| `descriptive_histograms.parquet` | 共同分箱、頻數、分母及有效基礎 |
| `descriptive_pair_summary.parquet` | 每指標四類缺失、完整配對平均、差值及升降／二元比例 |
| `descriptive_pair_transitions.parquet` | 二元指標四格轉移，只用兩輪均有效單位 |
| `descriptive_categories.parquet` | 分類分布及有效分母 |
| `descriptive_exploration_manifest.json` | 獨立探索版本、覆蓋範圍、方法及五份檔案指紋 |
| `4.1_descriptive/` | 四份新版本報表，原資料根目錄舊檔不覆寫 |

完整 Excel 有 Scales、student、parent、統計明細、口徑及版本，適用模式另有配對差。矩陣供閱讀，數值長表保留原精度。舊發布沒有新增欄位時，保留舊量表摘要並顯示更新提示。

## 維護及驗收

`descriptive_spec` 定義變項；`descriptive_data` 整理人口特徵；`descriptives` 擁有樣本、篩選、分母及配對差；`descriptive_reports` 匯出；`descriptive_dashboard` 處理圖及頁面。分類鍵包含變項及代碼，不能以顯示名稱合併。

`descriptive_exploration` 擁有探索分位數、分箱、完整配對和轉移，`descriptive_charts` 只消費聚合結果，`descriptive_workbench` 共用兩個頁面的結果及下載。快取包含發布、探索版本、角色、樣本、指標及完整篩選。`descriptive_exploration_outputs` 在候選版本寫入並驗證檔案，缺失、指紋或覆蓋錯誤會阻止發布。舊 4.1 規格版本維持不變，新增探索版本獨立管理。

驗收需逐筆比對原正式樣本、獨立家長選定 ID、分數、來源及人工歷史。另測試分母、缺失、升中、BD 特有選取、換家長、空群組、全缺失及匯出失敗保留舊版本；程式通過之外仍需實際檢查瀏覽器與每張 Excel 工作表。

家長 PHQ 跨期比較須由正式同一成人樣本證明連續性。`acbd` 名稱本身不是證據；若缺少 `parent_longitudinal.parquet` 而退回同一孩子家長回應，停用 PHQ 總分、分量表及分類的配對比較。各輪描述統計仍保留。固定報表與 dashboard 共用此檢查。

## Static G1/G2 numeric output (`study2_g12_v1`)

The static exporter adds a fixed projection of the existing exploration results;
it does not change scoring, identity, wave selection or statistical definitions.
For every supported source, school scope and group, continuous paired rows keep
the original inference and add the following availability detail:

| Field | Meaning |
|---|---|
| `pairs_n` | Formal units whose two exact selected submission/version slots are in scope |
| `paired_valid_n` | Valid for this metric in both waves |
| `only_t0_valid_n`, `only_t1_valid_n`, `both_missing_n` | The other three mutually exclusive availability states |
| `paired_missing_n` | Formal N minus both-valid N, not either wave's missing N |
| `t0_mean`, `t1_mean` | Means of exactly the same per-metric both-valid pairs |
| `mean_change`, `sd_change`, `p_value`, `cohen_dz`, `inference_status` | Original paired calculation, without display rounding |
| `pair_detail_status` | `available`, `not_provided` or `suppressed` |

The four state counts sum to formal N when detail is available. T1 paired mean
minus T0 paired mean equals mean change. Each-wave overview means can differ
because their valid respondents can differ. The overview audit shows both bases
in separate columns. It also shows sample, valid, missing and outside-range N:
sample N = valid N + missing N, and outside-range N is included in missing N.

The overview paired block intersects displayed submissions with the formal
reference using submission and version together, after applying each displayed
group. It never substitutes the overview's parent T1 for the formal BD slot.
The all-independent-parent overview uses the formal same-child branch as its
paired reference and keeps its unpaired baselines in its per-wave columns.
Parent PHQ retains the original whole-cohort adult-continuity gate before any
complete-slot restriction. Missing score columns or legacy minimal callers
without exploration anchor metadata retain original inference but mark new
detail `not_provided`; the interface does not fill it from wave means.

Minimum zero remains the researcher default. With an explicit positive minimum,
any positive small availability state suppresses the whole paired numeric
partition, including both means and original inference. Its paired histogram
also hides counts and edges so the same protected both-valid N is not repeated
in a download. Zero is still zero; unavailable and suppressed values remain
distinct. This does not claim to prevent every cross-projection differencing
attack. The accepted first-tab exact-scope guard remains unchanged.

CSV downloads contain raw numeric columns separately from formatted display
columns. They never parse rounded labels back into numbers. Per-row variable ID,
label and category code retain their identity. Fixed metadata includes release,
snapshot time, report/dictionary/inference/projection versions, mode, respondent,
school/source/group scope, grouping/source anchors and the result basis.
`selection_variable` is separate from a row's metric; overview tests retain
`test_basis=paired_valid` alongside `basis=wave_valid`. Missing old metadata is
explicitly `not_provided`, rather than borrowed from another release.

Histogram CSV uses the currently plotted bins and a valid denominator summed
from those numeric bins only when all are visible. It remains all-source only.
Period and monthly CSV retain numeric mean, SD and available counts, effective
complete-month endpoints, Hong Kong timezone and batch-date inclusion. Periods
remain all-source/all-group, calendar-response summaries with no paired test.
No new histogram variables, quantiles, grade projection, daily boundaries or
research records are added to the public payload.

## Optional grade multi-select (protected researcher minimum0)

The descriptive and independent-parent tabs offer P1–P6, S1–S6 and Unknown.
All includes Unknown and uses the existing published views unchanged. Known
grades excludes Unknown. No grades is an empty selection: sample/valid counts
are zero and undefined numerical summaries remain unavailable. Repeated choices
do not duplicate participants. These controls do not affect the first tab.

Per-wave student grade comes from the selected student response. Per-wave
student-anchored parent grade comes from the unique corresponding selected
student. Formal AC, actual BD and EF use selected student baseline grade for
both waves. Independent-parent branches use the selected parent's reported
child grade at each wave, or at independent baseline for longitudinal views.
Existing gender/school/source anchors remain unchanged. CSV includes the grade
anchor separately, including when it differs from the parent grouping anchor.

Grade requires the existing cleaned integer 1–6 and published valid school stage
status. Invalid, conflicting or missing values, or ambiguous/missing student
linkage, become Unknown. Neither stage nor baseline grade is inferred from age,
promotion, another respondent or follow-up. A nonempty legacy artifact without
the required fields has unavailable custom-grade capability, while All remains
usable. An empty supported cohort is genuine zero.

`snapshot.grade` declares `study2_descriptive_grade_v1`, the protected researcher
profile and matching release/report/dictionary versions. Each `view.grade`
partitions its existing group/source/school/mode projection into the 13 disjoint
grade cells. `statistics_schema` and `pairs_schema` define stable metric keys;
`statistic_fields` and `pair_fields` name the numeric vector columns. Each cell
has explicit T0/T1 sample counts. A cell empty in both waves has null vectors,
an explicit zero representation under those schemas. Missing cells are invalid,
not an empty selection. The existing column-table snapshot and protected app
assets carry the capability; no record IDs or membership arrays are exported.

Wave cells retain sample/valid/missing/outside-range counts, numeric mean and
centred sum of squares M2, or categorical numerator/denominator. Formal pair
cells retain G1 availability states, metric-specific complete-pair T0/T1 moments
and difference moments. Only G1-confirmed available pair details are projected.
Whole-scope adult PHQ eligibility is fixed before grade partitioning; selecting
a smaller grade subset cannot enable an ineligible parent PHQ result.

Custom subsets combine counts and weighted moments, including between-cell
variation: combined M2 is the sum of each cell's M2 plus
`n_cell * (mean_cell - combined_mean)^2`. Sample SD is `sqrt(M2/(n-1))` for n>1;
one-response means remain visible, while their undefined SD is unavailable.
Paired change combines per-person difference moments on complete pairs, not
the difference between separately valid wave means. No valid small result is
masked in the minimum0 researcher profile.

Custom per-wave overview disables the entire paired block, including availability,
complete-pair means, differences and inference: no joint T0/T1-grade cube exists.
Select the explicit longitudinal view for stable baseline-grade comparisons.
Custom longitudinal p-values/dz, grade-filtered monthly trends, distributions
and transitions are unavailable in this minimum version. No All-grade result
is substituted under a custom label. All retains its accepted inference,
histograms and period views.

CSV retains G2 raw precision, metric identity, basis and public metadata, adding
canonical `filter_grade_codes`, stable `grade_anchor` and `grade_format`.
Display anchor labels are English. All outputs for a custom selection use the
same validated pooled result. Invalid/missing capabilities clear custom result
and download UI; selecting All explicitly restores the published aggregate view.
The browser independently checks active policy, supported versions, complete
unique cells, finite moments and count/moment reconciliation. Positive-threshold
legacy callers omit the entire header and all grade data; this compatibility
boundary adds no masking to the minimum0 researcher configuration.


## Full student AC CSV for local research

Use a new private directory for each export. The command reads the currently published release and does not run the pipeline or change the publication. ON is the default and requires an explicit accepted, release-bound exclusion manifest:

```sh
python -m study2 --config private/config.json student-ac-export --output private/ac-export-v1 --exclusion-manifest private/accepted-exclusions.json --manual-exclusions on --dataset-version student_ac_full_v1
# To export the published reference membership, choose --manual-exclusions off explicitly.
```

Each wide row contains one selected student's T0 and T1. The exporter uses native `project_eligibility(...).members['AC']`; removing either selected response removes the whole pair and never selects a replacement. A missing score does not remove an otherwise valid AC pair. All schools, sources, grades and dates are retained; no parent response rows are joined.

The fields are separated into `T0_`/`T1_` and `record__`, `current__`, `source__`, `analysis__`: record/version/date provenance, current corrected answers, original source-cell values, and published analytical fields. Full numerical precision is retained; structured values are JSON text, and missing values remain blank. The CSV uses UTF-8 with BOM. Import identifiers and source strings into Excel as Text to preserve leading zeros and original date text.

The new directory also records column definitions and release/source/manifest provenance. Existing output is never overwritten. Source hashes, exact pair membership and all-cell CSV round trips are checked before the exporter returns successfully; a changed current publication or input blocks completion. This export contains individual-level research data and must remain local, outside Git and aggregate dashboard/deployment folders. It is separate from the aggregate-only dashboard downloads.
