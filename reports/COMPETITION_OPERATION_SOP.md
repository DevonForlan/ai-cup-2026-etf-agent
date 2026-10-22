# Competition Operation SOP（比賽期間作業程序）

> AI 產生內容，需人工審閱後才能作為正式作業依據。本 SOP 整合既有文件，衝突時以下列文件為準：
>
> - `docs/COMPETITION_DAILY_RUNBOOK.md`
> - `docs/FINAL_OPERATOR_CHECKLIST.md`
> - `docs/EMERGENCY_RUNBOOK.md`
> - `docs/OFFICIAL_DATAPACK_INTEGRATION.md`
>
> 投資決策 = 凍結的 Quant v1（`config/strategy_quant_v1.yaml`，sha256 `f34fa02e…d2e0`）。Claude 只寫文字敘述，不能改標的、權重、委託。

## 0. 時間軸與角色

| 時間（Asia/Taipei） | 自動 / 人工 | 內容 |
|---|---|---|
| T 13:30 收盤 | — | 官方行情公布（約 15:00 後抓得到） |
| T 17:00 | 自動 | `AI_CUP_Precompetition_Evaluation_1700`：紙上評估（PRECOMPETITION 用；比賽期間僅診斷，見 §A-3） |
| T 19:00 後 | **人工** | 主辦方後台「文件繳交」→「下載資料包」→ 存入 `data\official_datapack\`（第 2 日起必做） |
| T 19:30 | 自動 | `AI_CUP_Precompetition_DryRun_1930`（依 `config/ops.yaml run_mode` 執行 PRECOMPETITION 或 COMPETITION）：資料更新 → DataPack 檢查 → Quant v1 → D-Plan → 驗證 → FINAL_CANDIDATE |
| T+1 08:55 前 | **人工** | 確認並上傳 `submissions\<T+1>\FINAL\D-Plan_<TEAM>_<T+1>.json`，記錄回執 |

注意：

- 送件窗口是 T+1 前一個**日曆日**的 19:30 到 T+1 的 08:55。
- 週五晚上沒有窗口，排程會記錄 `SKIPPED NO_SUBMISSION_WINDOW_TONIGHT`；週一的 D-Plan 在週日 19:30 產生。
- 10/26 是休市日，但 10/26 19:30 起是第一個送件窗口。

## A. 每日正常流程

### A-1 17:00 evaluation（自動）

1. 確認 `.\automation\check_last_evaluation.ps1` 的狀態是 `PASS`，或已理解的 `SKIPPED`。
2. 狀態是 `FAILED NAV_RECONCILIATION_FAILED` 時：先查 `logs\ops\<T+1>\data_health.md` 的 TWSE / TPEx 行情。
   - 2026-10-16 實際發生過：TWSE 抓取失敗，只寫進 TPEx。
   - 處理：重抓 `.venv\Scripts\python.exe agent\ops\refresh_daily.py --date <T+1> --only twse_prices,tpex_prices`，再跑 `.venv\Scripts\python.exe -m agent.ops.daily_evaluation --date <T>`。
3. Shadow metrics（研究用，選擇性）：`.venv\Scripts\python.exe research\risk_overlay\shadow_metrics.py`。只產生 `reports\shadow_metrics\`，不影響任何決策。

### A-2 19:00–19:30 前置（人工，第 2 日起）

1. 下載 DataPack → `data\official_datapack\`。只放主辦方原檔，不改檔、不放測試檔。
2. `.venv\Scripts\python.exe -m agent.ops.datapack_status --mode COMPETITION` → 要是 `Status: READY`。
3. `.venv\Scripts\python.exe -m agent.ops.competition_preflight` → 不可有 `BLOCKED`。這個工具只檢查，不改任何設定。

### A-3 19:30 prediction（自動）

1. `.\automation\check_last_scheduled_run.ps1` → 應看到：
   - `OVERALL_STATUS PASS`
   - `RUN_MODE COMPETITION`
   - `DATAPACK_STATUS PASS`（第 1 日為 `INITIAL_CAPITAL`）
   - `DPLAN_VERSION 4.3`
   - `DPLAN_VALIDATION PASS`
2. 狀態是 `BLOCKED`（例如 DataPack 太晚出現）：補放 DataPack 後，手動重跑同一支程式 `.\automation\run_precompetition_scheduled.ps1`。
   - 同日已 PASS 時會自動 `SKIP_ALREADY_PASSED`。
   - 跨過午夜：T 當天 00:00～08:29 會自動做 **cross-day catch-up**，只產生 trade_date = 今天的 D-Plan（§G）。08:30 之後不再產生新決策。
3. 比賽期間 17:00 evaluation 仍會執行，但它評估的是紙上帳。第 2 日起預期出現 `SETTLEMENT_CHAIN_MISMATCH`：
   - 這無害，正式起點只用 DataPack。
   - 處理方式見 `reports/PRECOMPETITION_OPERATIONAL_READINESS.md` 的提案 P-3。

### A-4 08:55 前（人工）

依 `docs/FINAL_OPERATOR_CHECKLIST.md`「上傳」逐項打勾：

- 只上傳 `submissions\<T>\FINAL\` 的單一檔案。
- 核對 SHA256、日期、Team ID。
- 上傳後記錄回執，狀態要到 `SUBMISSION_CONFIRMED`（submission status = `ACCEPTED`，見 §G-1）。

## B. 第一個比賽日（T = 2026-10-27）

1. **10/26 上午（GO / NO-GO 會議）**：
   - 依 `reports/COMPETITION_GO_NO_GO_CHECKLIST.md` 判定。
   - GO 之後，由人工決定並記錄兩件事：
     - 正式 Team ID：填入 `config/ops.yaml team.competition_team_id`（見 §D-7；**目前 BLOCKED：TEAM_ID_NOT_CONFIGURED**）。
     - `config/ops.yaml run_mode: COMPETITION`。
   - 兩者都是明確決策，工具不會自動切換。
2. **10/26 19:30**（休市日晚上，第一個窗口）：
   - 排程以 `--initial` 從初始資金 1,000,000,000 產生 T=10/27 的 D-Plan。
   - 不需要 DataPack；若後台已有 `as_of_date: null` 的資料包，也會被驗證。
3. **10/27 08:55 前**：人工上傳並記錄回執。

## C. 第二日起（T ≥ 2026-10-28）的 DataPack 流程

1. T−1 收盤、19:00 後下載 DataPack（as_of_date 必須 = T−1，依官方行事曆）。
2. 存入 `data\official_datapack\`，再執行 `datapack_status` 與 `competition_preflight`。
3. 19:30 排程依序執行：DataPack gate → 匯入官方結算 → Quant v1 → D-Plan。
4. **沒有 DataPack 一律 BLOCKED**：`DATAPACK_MISSING` / `DATAPACK_STALE` / `DATAPACK_INVALID`。
   - 不得 fallback 到 paper ledger、內部結算或重建持股；程式已強制，並有回歸測試。
5. `OfficialPortalProvider` = `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION`：不自動下載、不登入、不猜 API。

## D. 異常處理

| 情況 | 現象 | 處理 |
|---|---|---|
| D-1 排程沒跑（關機 / 睡眠） | `check_last_scheduled_run` 停在前一日 | 開機後 `StartWhenAvailable` 自動補跑：當晚為同日補跑；隔天 08:30 前為 cross-day catch-up（§G）。排程已跑過但 BLOCKED → 修正後手動 `.\automation\run_precompetition_scheduled.ps1`。08:30 之後不得再產生新決策 |
| D-2 Claude 不可用 / 逾時 | `CLAUDE_STATUS NOT_READY` 或 `GROUNDING TEMPLATE_FALLBACK` | 不用處理。敘述自動改 template，決策不變（rehearsal 已驗證 decision hash 相同）。可事後由操作者自行 `claude` 重新登入（互動式，不自動化） |
| D-3 DataPack 缺 / 舊 / 錯 | `BLOCKED DATAPACK_*` | 重新下載；仍錯 → 聯絡主辦方。**不手改檔、不跳過 gate** |
| D-4 行情過期 / 部分缺漏 | `data_health` BLOCK 或 preflight `market_data_freshness BLOCKED` | 重抓：`refresh_daily.py --date <T> --only twse_prices,tpex_prices`；官方未公布 → 依 `docs/EMERGENCY_RUNBOOK.md` §A |
| D-5 驗證失敗 | `DPLAN_VALIDATION FAIL` / 無 FINAL | 系統會先嘗試合法 fallback（維持前日組合）；仍失敗 → BLOCKED，不產生 FINAL。依 EMERGENCY_RUNBOOK §F；**不人工改 D-Plan** |
| D-6 疑似重複執行 | 工作管理員看到 2 個 python | 每個 venv python 會顯示**兩個**同命令列的程序（launcher + 子程序），屬正常。用 `competition_preflight` 的 `duplicate_processes` 判斷：顯示 2 logical runs 以上才是真重複 |
| D-7 Team ID 錯誤 / TEAM_TEST | preflight `team_id BLOCKED`、排程 `BLOCKED TEAM_ID_NOT_CONFIGURED` | 正式 Team ID 只填在 `config/ops.yaml team.competition_team_id`（P-1；依主辦方正式通知，不猜）。凍結策略檔不再被讀取，不要編輯 |
| D-8 行情不完整 | `MARKET_DATA_INCOMPLETE`（evaluation / 19:30 run） | 同 D-4 重抓；coverage gate（P-2）會在結算前擋下，不會再拖到 NAV 對帳 |
| D-9 Active Share 資料缺 / 舊 | COMPETITION：`BLOCKED ACTIVE_SHARE_DATA_MISSING` / `ACTIVE_SHARE_DATA_STALE`；PRECOMPETITION：WARNING | 重抓 ETF 持股：`refresh_daily.py --date <T> --only etf_holdings`；不可猜 benchmark 權重（P-5） |

## E. 禁止事項

- 人工修改投資決策、權重、標的、委託股數或現金。
- 繞過合規檢查、Active Share 檢查、D-Plan 驗證、DataPack freshness gate。
- 上傳 DRY-RUN / HISTORICAL / candidates / dplan_work 的檔案，或上傳非 `FINAL\` 的檔案。
- 修改 `config/strategy_quant_v1.yaml`，或在比賽期間啟用 risk overlay / shadow factor。
- 讓 Claude 或任何 LLM 決定曝險、標的、權重。
- 自動登入官方網站、讀取 cookie / token、猜私有 API、瀏覽器自動化。
- 把 synthetic / paper / 測試檔放進 `data\official_datapack\`。

## F. 每日保存的稽核資料

| 項目 | 位置 |
|---|---|
| 上傳檔 + SHA256 | `submissions\<T>\FINAL\`、`FINAL_CANDIDATE.txt` |
| 所有候選 + metadata（settlement_source / datapack / hash） | `submissions\<T>\candidates\<run_id>\` |
| 執行紀錄 | `logs\ops\<T>\`（preflight、data_health、competition_day_summary、operator_summary） |
| 排程紀錄 | `logs\scheduled\history.jsonl`、`logs\evaluation\history.jsonl` |
| DataPack 原檔與匯入副本 | `data\official_datapack\`、`data\settlement\datapack\` |
| 回執 / 截圖 | `submissions\<T>\receipt_*.png` + receipt 紀錄 |
| 封存 | `archive\<日期>\`（`scripts\archive_daily.ps1`） |
| 備份 | `scripts\backup_competition_state.ps1`，再複製到第二位置 |
| competition preflight | `logs\ops\competition_preflight\*.json` |

## G. 送件時間窗、跨日補跑與截止（2026-10-20 新增）

官方窗口：T−1 19:30 ～ T 08:55。內部政策（`config/ops.yaml deadline`、`agent/ops/submission_window.py`）：

| 時間（T = 交易日） | 排程 / 執行行為 | 狀態碼 |
|---|---|---|
| T−1 19:30 | 正常 prediction（19:30 工作） | `RUN`（run_kind NORMAL） |
| T−1 19:35 ～ 23:59 | 同日補跑（開機 / 喚醒後 StartWhenAvailable） | `RUN`（SAME_DAY_CATCHUP） |
| T 00:00 ～ 08:29:59 | **跨日補跑**：前一晚沒完成時，只產生 trade_date = **今天**的 D-Plan（絕不產生昨天的） | `RUN`（CROSS_DAY_CATCHUP） |
| T 08:00 | 若尚無 READY_FOR_UPLOAD | `SUBMISSION_WARNING_0800` |
| T 08:15 | 若尚無 READY_FOR_UPLOAD | `SUBMISSION_HIGH_WARNING_0815` |
| **T 08:30** | **內部決策截止**：不重跑 Quant、不產生新決策；只回報現有 submission 狀態 | `DECISION_WINDOW_CLOSED` |
| T 08:45 | 若尚未 ACCEPTED | `SUBMISSION_CRITICAL_WARNING_0845` |
| **T 08:55** | **官方截止**：不得產生新 candidate | `SUBMISSION_WINDOW_CLOSED` |

- 警告在排程執行、補跑或人工查詢時計算，沒有額外的高頻排程。
- 查詢：`.venv\Scripts\python.exe -m agent.submission.status --date <T>`
- 08:30 截止同時在排程（`scheduled_run.plan`）與 `agent\competition_day.py` 本身強制。人工執行也會回 `DECISION_WINDOW_CLOSED` / `SUBMISSION_WINDOW_CLOSED`，不會產生 D-Plan。
- 跨日補跑**不降低任何 gate**，以下各項都照常檢查：
  - 交易日、Team ID、DataPack（COMPETITION）、行情 coverage、ETF benchmark / Active Share、凍結 fingerprint、乾淨工作樹（COMPETITION）。
  - 今天已有 ACCEPTED / FILE_UPLOADED / SERVER_VALIDATED / SUBMITTED → `SUBMISSION_ALREADY_*`，不重新決策。
  - 今天已有 FINAL → `FINAL_ALREADY_EXISTS`，不重複產出。`--safe-retry` 可再產 candidate，FINAL 仍凍結。
- 實例：2026-10-19 19:30 的工作在 2026-10-20 08:54 才啟動 → 舊行為 `MISSED_PREVIOUS_DAY`；新行為 `DECISION_WINDOW_CLOSED`（08:54 > 08:30）。只回報既有 candidate，沒有 candidate 就不產生新決策。

### G-1 Submission 狀態機（只依證據前進；`agent/submission/status.py`）

| 狀態 | 需要的證據 |
|---|---|
| NOT_GENERATED | 沒有任何 candidate D-Plan |
| GENERATED | `submissions\<T>\candidates\<run_id>\D-Plan_*.json` 存在 |
| VALIDATED | candidate 的 `validation_report.json` ok（schema / ticker / numeric / compliance） |
| READY_FOR_UPLOAD | active FINAL 存在且 sha256 驗證通過。只有 competition 模式的 FINAL 才 `uploadable=true`，PRECOMPETITION 的 paper FINAL 永遠不可上傳 |
| FILE_UPLOADED | 已上傳到官方頁面（receipt `stage file_uploaded`） |
| SERVER_VALIDATED | 官方「檢核結果」明確 PASS（`stage server_validated` + `server_validation_result PASS`） |
| SUBMITTED | 已按「送出繳交」，尚無官方接受證據（`stage submitted`） |
| ACCEPTED | `official_status accepted` 且有官方 receipt / submission id 或歷史紀錄原文；sha256 與 FINAL 相同 |
| REJECTED | receipt `official_status rejected`（附 failure_reason） |
| SUBMISSION_UI_UNAVAILABLE | READY_FOR_UPLOAD，但 `config/ops.yaml submission.ui_status: UNAVAILABLE`（官方後台無上傳功能；不算 Agent failure） |
| SUBMISSION_WINDOW_CLOSED | 已過 08:55 且沒有 ACCEPTED / SUBMITTED / REJECTED 證據 |

- **READY_FOR_UPLOAD ≠ ACCEPTED**；FILE_UPLOADED / SERVER_VALIDATED / SUBMITTED 也都 ≠ ACCEPTED（Issue #4）。ACCEPTED 需要官方 submission id **或**歷史紀錄原文（`--history-entry`），只能由 receipt 設定：

  ```
  python -m agent.submission.receipt --date T --team-id ... --sha256 ... --official-status accepted --receipt-id ... --accepted-at ... --evidence <截圖> --confirmed-by "姓名"
  ```

- 多次上傳以「08:55 前最後一次**成功**」為準（`effective_submission`）。

### G-2 官方後台（只開瀏覽器）

- `config/ops.yaml submission.portal_url`：只由操作者填入官方後台網址，不猜。目前 `null`。
- `submission.ui_status`：目前 `NOT_YET_VERIFIED`（官網 10/20 10:00–18:00 系統更新，上傳介面尚未確認）。
- `.venv\Scripts\python.exe -m agent.submission.portal --status`：顯示 UI 狀態、URL 是否設定、submission 狀態、可否上傳。
- `.venv\Scripts\python.exe -m agent.submission.portal --open`：只在 READY_FOR_UPLOAD（competition FINAL）且 URL 已設定（https）時開啟瀏覽器。否則回 `SUBMISSION_PORTAL_URL_NOT_CONFIGURED` / `NOT_READY_FOR_UPLOAD`。
- 登入、選檔、上傳、送出全部人工。
- Providers：`ManualSubmissionProvider` ENABLED；`OfficialPortalProvider` = `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION`。
