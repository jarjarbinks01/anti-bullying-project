# 程式庫與本機資料

Git 根目錄是 `pipeline_v3`。其他研究資料夾位於 Git 工作區外；工作區內的設定、資料和結果亦不提交。

## 可提交

- Dashboard、`study2` 共用核心及已審查的欄位轉換程式。
- 合成案例測試，不以真實個案代替測試資料。
- 通用研究規則、資料模型、階段及操作文件。
- 不含真實路徑或欄位登記的 `config.example.json`。
- `study2/assets/review_template.xlsx`：只含版面、通用標籤及樣式，固定指紋；不是已填審核包。

## 只留本機

原始問卷及合併檔、校名字典、SQLite、備份、完整／失敗批次清單、發布結果、審核包及裁定歷史、逐個案驗證工具、實際統計報告、截圖、本機設定、環境與密鑰。

`config.local.json` / `config.merged.json` 及既有資料庫保留原位置。Git 初始化不重新讀入、刪除或重新登記研究提交，也不切換 Dashboard 的資料版本。

## 提交檢查

`.gitignore` 預設排除檔案，只開放明確列出的程式與文件。`tools/repository_guard.py` 再檢查暫存內容；即使用強制加入，未批准的資料檔也會被拒絕。

```sh
git config core.hooksPath .githooks
git status --short
python3 tools/repository_guard.py --staged
python3 tools/repository_guard.py --history HEAD
```

`pre-commit` 檢查整個暫存版本；`pre-push` 檢查即將推送的本機歷史。新 clone 的 hooks 不會自行啟用，必須執行上面的設定。沒有安裝 hooks 的電腦亦須在推送前執行 guard。Git 檢查不能判斷任意一段文字是否為真實個案；程式／文件有新增內容時仍要逐檔核對。

未知資料檔不需要放寬 allowlist。新增共用程式或通用文件時，同時更新 `.gitignore`、guard 的路徑清單及測試。範本變更須先確認所有工作表都沒有身份、回應、批次或審核資料，再更新固定指紋。

## 安裝與本機續用

程式安裝及第一次來源登記見 [README](../README.md)。已有研究 state 的電腦不重複 `init`。來源變更依既有受控流程處理；不能為了讓 Git 看起來乾淨而刪除本機檔案。

升級程式前保留可還原備份。研究規則改變時重新驗證、產生新發布版本及審核所需個案；Git commit 不是資料發布，不能代替研究批准。


## Checkpoint retention modes

`checkpoint_policy.latest_complete_only: true` permits the existing verified latest-checkpoint cleanup. When the flag is false or absent, checkpoint completion preserves every earlier checkpoint and recovery asset, and does not rewrite the existing tracking-ledger pointer. Creating or reusing a checkpoint still verifies recovery before updating its current-checkpoint pointer. Git changes do not alter a live local retention policy or initiate cleanup.

## Lean recovery (opt in)

Set `recovery_policy.mode` to `lean` and explicitly inventory external controls
and runtime dependencies in `recovery_policy.required_assets` (an empty list is
valid only when there are no external dependencies). Each entry supplies an
absolute `path`, a `dependencies/`-relative `restore_path`, and a `kind` of `file`
or `directory`. Do not register secrets or an entire virtual environment.

Lean recovery reuses content-verified unchanged review/ledger snapshots and
immutable checkpoint assets. The final bundle captures eligibility manifests,
review dispositions and registered dependencies; changed bundles still undergo
restore, integrity and foreign-key verification before atomic promotion.
`CHECKPOINT_RETENTION_PLAN.json` is review-only: lean mode never deletes historical
backups, even when the legacy latest-only setting is enabled. Keep a designated
previous rollback and any external launch dependencies in `protected_paths`.

Seven presentation-only modules are excluded from the scientific fingerprint;
shared calculations and unknown modules remain included. Full code provenance
is still captured. Switching fingerprint schemes can trigger a one-time new
calculation. Existing records, decisions and deployed snapshots are not changed
by installing this code. Repeated full hashing and the first changed checkpoint
remain costs; this is not an incremental database-backup implementation.
