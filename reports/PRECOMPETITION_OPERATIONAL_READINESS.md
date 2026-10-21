# Pre-competition Operational Readiness + Shadow Observation（2026-10-16）

> AI 產生內容，需人工審閱。本輪未修改 Quant v1、production scheduler、competition_day、DataPack integration、正式 prediction logic；未啟用 COMPETITION mode；未登入、未上傳、未提交、未 commit。

## 1. 現況盤點

| 項目 | 結果 |
|---|---|
| git HEAD | `23f2428`（master）；tracked 變更：`.gitignore`（data/research/）、`reports/round06_readiness.json`（pytest 產生的報告） |
| 未 commit | 3 輪研究（factor / risk overlay）+ 本輪新增工具與文件，見 §9 |
| Quant v1 | sha256 `f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0`；W5 NAV 1,014,240,575.839861741934859718；24/24 decision hash 相同 |
| pytest | 全部 PASS（數量見 §8） |
| D-Plan | v4.3 schema；rehearsal D-Plan schema / ticker / numeric PASS |
| DataPack | ManualFileProvider ENABLED；OfficialPortalProvider `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION`；gate 回歸測試 19/19 PASS |
| Claude CLI | READY（claude.ai 登入）；版本 2.1.301 不在 pinned 清單（WARNING_VERSION_DRIFT，fallback 已驗證） |
| 排程 | 19:30 `AI_CUP_Precompetition_DryRun_1930`、17:00 `AI_CUP_Precompetition_Evaluation_1700`：Ready、IgnoreNew、StartWhenAvailable、上次結果 0；時間未改 |
| run_mode / team_id | `PRECOMPETITION` / `TEAM_TEST` |
| DataPack 目錄 | `data\official_datapack\` 存在，0 檔（正確：比賽前不會有） |
| 磁碟 | 86.8 GB free；logs / submissions / archive 可寫 |

## 2. 今日發現並處理的營運事件

**10/16 17:00 evaluation（20:51 補跑）FAILED：`NAV_RECONCILIATION_FAILED`**

- 原因：TWSE 盤後行情抓取 3 次失敗（`GET failed after 3 tries`），10/16 只寫進 TPEx 50 檔。evaluation 只檢查「日期存在」，沒有檢查覆蓋率。
- 獨立 NAV 對帳把它擋下，沒有寫出錯誤結果。
- 處理（只做資料補抓與標準 evaluation 指令，未改程式）：
  - 重抓 TWSE 行情與法人資料 → 10/16 有 150/150 檔。
  - 重跑 `python -m agent.ops.daily_evaluation --date 2026-10-16` → PASS（+0.88%，累計 −5.12%，合規 PASS）。
- 若沒有處理：週日 19:30 的 paper chain 會沿用這個不完整的日期，因為 backfill 也只看「日期存在」。
- 比賽路徑不受影響：19:30 的 competition_day 遇到 CRITICAL 來源 STALE 會 BLOCK（rehearsal fault 3b 已驗證）。
- 見提案 P-2。

## 3. Team ID 稽核

| 位置 | 類型 | 比賽前需修改？ |
|---|---|---|
| `config/strategy_quant_v1.yaml: team_id: TEAM_TEST` | **正式 runtime 來源**：`agent/ops/scheduled_run.py` 與 `datapack_status` 從這裡讀 | **是**，但這是凍結檔：改了 sha256 就會變，preflight / healthcheck 在比賽模式會 BLOCK。→ 提案 P-1 |
| `config/strategy.yaml: team_id: TEAM_TEST` | 舊 Round 02 研究設定，正式流程不使用 | 否 |
| `agent/run_daily.py`（預設值）、`agent/competition_day.py` / `agent/README.md` / `scripts/competition_dry_run.ps1`（docstring 範例） | 範例 / CLI 預設 | 否（正式流程傳入 `--team-id`） |
| `experiments/round08_historical_validation.py`、`experiments/precompetition_e2e_rehearsal.py` | 研究 / rehearsal | 否 |
| `tests/**`（58 處）、`tests/ops/conftest.py` | test fixture | **不能改** |
| `audit/`、`reports/`、`submissions/`（歷史紀錄） | 歷史產物 | 不能改 |

結論：**TEAM_ID_NOT_CONFIGURED（BLOCKING）**。我不猜正式 Team ID。`competition_preflight` 對 TEAM_TEST / TEAM_SIM / TEAM_XXX 一律 BLOCKED。

## 4. 變更提案（都還沒實作，等待確認）

### P-1 Team ID 與凍結策略檔脫鉤（BLOCKER）

- 新增 `config/ops.yaml: team_id: <官方 ID>`（營運設定，不是策略）。
- `scheduled_run.py` / `datapack_status.py` / `competition_preflight.py` 改為優先讀 ops.yaml，找不到才讀策略檔。
- 凍結檔不動，sha256 不變。
- decision_core_hash 含 team_id，所以正式 ID 的 D-Plan hash 本來就會與 TEAM_SIM 基準不同。凍結驗證繼續用 W5 基準（TEAM_SIM）。
- 需要回歸測試；屬營運 bug 修正，依 `docs/CODE_CHANGE_GOVERNANCE.md`。

### P-2 行情覆蓋率檢查

- `daily_evaluation.evaluate` 與 `scheduled_run.backfill_gaps`：一個日期只有在 TWSE 與 TPEx 都有資料、≥ 150 檔時才算「存在」；否則重新抓取，仍不足就 `BLOCKED MARKET_DATA_INCOMPLETE`。
- 目前 `competition_preflight` 已會偵測（`market_data_freshness`）。

### P-3 17:00 evaluation 在 COMPETITION 期間

- 目前只評估 paper chain；第 2 日起預期出現 `SETTLEMENT_CHAIN_MISMATCH`，無害但會干擾判讀。
- 選項 A：在 evaluation 中依 run_mode 改為「SKIPPED (COMPETITION: official settlement = DataPack)」。
- 選項 B：切換比賽模式時停用該工作。建議 A。

### P-4 SHADOW_SCHEDULER_CHANGE_PROPOSAL

- 不新增排程。在既有 `automation/run_precompetition_evaluation.ps1` 的 evaluation 呼叫**之後**，加一段獨立 try/catch：

  ```powershell
  # --- research-only shadow observation (never affects the evaluation result or any decision) ---
  try {
      $sh = & $Py (Join-Path $Root 'research\risk_overlay\shadow_metrics.py') 2>&1 | Out-String
      Add-Content -Path (Join-Path $Root 'logs\shadow\shadow.log') -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format o), $sh.Trim())
  } catch {
      Add-Content -Path (Join-Path $Root 'logs\shadow\shadow.log') -Encoding UTF8 -Value ("{0} SHADOW_FAILED {1}" -f (Get-Date -Format o), $_.Exception.Message)
  }
  ```

- 順序：正式 evaluation 完成並寫完 status → shadow（約 1–2 分鐘；工作時限 PT1H 足夠）。
- shadow 失敗只寫自己的 log，不改 evaluation 的 `latest_status.json`。
- 與 19:30 不重疊：17:00 + ≤ 5 分鐘；StartWhenAvailable 補跑時也是先 evaluation 再 shadow；19:30 工作的 IgnoreNew 只作用於同一工作。
- 在核准前：手動執行 `.venv\Scripts\python.exe research\risk_overlay\shadow_metrics.py`。

### P-5 Active Share 無法計算時的處置

- 目前 ETF 持股缺漏時，Active Share 會顯示 UNKNOWN，但不會阻擋執行。
- 官方 < 15% 為違規、連續 2 日可取消資格。
- 建議：在 COMPETITION 模式下，Active Share UNKNOWN 且組合有變動（有委託）時改為 BLOCK；純持有日維持 WARN。
- 目前 ETF 資料 30/30 齊全，實際風險低。

## 5. 重複程序調查

**結論：不是重複執行，是正常的 parent / child。**

- 實測：用 `.venv\Scripts\python.exe` 啟動一個程序，系統出現兩個 `python.exe`，命令列完全相同：
  - PID 18560：venv launcher，`.venv\Scripts\python.exe`。
  - PID 23808：真正的直譯器 `Python313\python.exe`，父程序 = 18560。
- 因此「2 個 scheduled_run + 2 個 competition_day.py」= 各 1 次執行（scheduled_run 再以 subprocess 啟動 competition_day）。
- 歷史紀錄：
  - 10/14 起每個 scheduled_date 只有 1 次 PASS。
  - 10/13 21:31 第二次觸發被 `SKIP_ALREADY_PASSED` 擋下，證明防重複有效。
  - `submissions/20261014` 的 4 個 candidates 來自 10/13 的人工設定測試，不是排程重複。
- 同 run_id / 同輸出：每次執行的 run_id 含時間戳，candidate 資料夾各自獨立；FINAL 只標記一次，之後凍結。
- 資料寫入有 FileLock；evaluation 有 `evaluation.lock`。
- 兩個工作皆 `MultipleInstances=IgnoreNew`。
- 不需要修改排程。`competition_preflight` 的 `duplicate_processes` 會把 launcher 配對合併後再判斷，並有單元測試。

## 6. E2E rehearsal（隔離：`runtime/e2e_rehearsal/`）

- 條件：T = 2026-10-19；模擬時鐘 2026-10-18 19:45（週日窗口）；真實資料更新；paper ledger 10/16 當起點；真實 Claude CLI。
- 流程結果：

| 步驟 | 結果 |
|---|---|
| data refresh / freshness | PASS |
| settlement source | PRECOMPETITION_PAPER_LEDGER（10/16） |
| Quant v1 → compliance | 全部 PASS（150 universe、24 檔、2330 ≤ 25%、其他 ≤ 10%、現金 < 25%） |
| Active Share | 46.95%（官方 ≥ 15%、內部目標 30%） |
| Claude CLI narrative | 3 calls、0 failed、grounding PASS |
| D-Plan | v4.3；schema / ticker / numeric PASS；24 no-trade（持有日）、0 orders |
| prediction report | 隔離輸出 |
| evaluation 相容性 | 可讀取 FINAL；10/19 行情尚未存在 → 預期 `MARKET_DATA_NOT_AVAILABLE` |

- **Claude 不能改決策**：Claude 執行與 template 執行的 decision_core_hash 完全相同（`sha256:24861165…`）。
- 補充：第一次以真實時鐘（週五晚上）執行時，所有 run 都被 `submission_window_open` 正確擋下，因為窗口週日 19:30 才開。

## 7. Failure injection

| # | 情境 | 結果 | 決策是否受影響 |
|---|---|---|---|
| 1 | Claude CLI 不可用 | DRY_RUN_OK，template 敘述 | 否（hash 相同） |
| 2 | Claude 逾時（1 秒硬上限） | 6/6 calls TIMEOUT → template，DRY_RUN_OK | 否（hash 相同） |
| 3a | 行情過期（refresh 已跳過） | 明確 L3 fallback（`fallback: true`、`degradation_level 3`：維持前日合法組合），有記錄 | 依設計改為 fallback，不是靜默 |
| 3b | 行情過期（真實 refresh 路徑，TWSE 無法連線） | **BLOCKED**：`data:twse_prices STALE`，無 FINAL | — |
| 4 | 缺法人資料 | DRY_RUN_OK（IMPORTANT 來源；Quant v1 不使用） | 否 |
| 5 | 缺 ETF 持股 | DRY_RUN_OK，但 Active Share = **UNKNOWN**（preflight WARN、compliance summary 明示 UNKNOWN）；不阻擋 → 見提案 P-5 | 否 |
| 6 | DataPack 格式錯誤 | BLOCKED `DATAPACK_INVALID`；缺檔 → `DATAPACK_MISSING` | — |
| 7 | DataPack 過期 | 單元測試 `test_stale_and_not_ready_datapacks`、`test_gate_missing_stale_invalid_and_pass` PASS → `DATAPACK_STALE`；rehearsal 用 TEAM_042 範例檔時因隊伍不符被視為 MISSING（也是 BLOCKED） | — |
| 8 | 重複排程觸發 | 第二次 → `SKIP_ALREADY_PASSED`；Windows IgnoreNew | — |
| 9 | D-Plan 不合法 | schema 驗證拒絕（5 個錯誤：版本、ticker 格式、必要欄位等） | — |
| 10 | log 目錄無法寫入 | 立即拋出例外（大聲失敗），沒有任何 D-Plan 寫出 | — |

沒有任何情境靜默產生錯誤 D-Plan。

## 8. 測試

- 新增 `tests/ops/test_competition_preflight.py`（5 項）。
- DataPack + preflight 測試 24/24 PASS。
- 全量 pytest：**484 passed**（3 分 52 秒）。
- 注意：有一個既有測試會覆寫 tracked 的 `reports/round06_readiness.json`（寫入 fixture 值），已用 `git checkout` 還原；建議日後讓該測試寫入 tmp 路徑。

## 9. 本輪新增 / 修改的檔案（皆未 commit）

| 檔案 | 類型 | 進入正式決策路徑？ |
|---|---|---|
| `agent/ops/competition_preflight.py` | 新工具，只讀 | 否（沒有正式程式 import 它） |
| `tests/ops/test_competition_preflight.py` | 測試 | 否 |
| `research/risk_overlay/shadow_metrics.py` | 研究（擴充，未新增第二份實作） | 否 |
| `data/shadow_metrics/shadow_history.csv`、`reports/shadow_metrics/*_shadow.md` | 研究輸出 | 否 |
| `experiments/precompetition_e2e_rehearsal.py`、`runtime/e2e_rehearsal/` | rehearsal（隔離） | 否 |
| `reports/COMPETITION_OPERATION_SOP.md`、`reports/COMPETITION_GO_NO_GO_CHECKLIST.md`、本檔、`research/future_research_backlog.md` | 文件 | 否 |
| 資料：`data/history`（TWSE 10/16 補抓）、`data/paper_ledger/settlement/2026-10-16.json`、`reports/daily_evaluations/2026-10-16_evaluation.md` | 標準營運產物（與排程相同的指令） | 否 |
| `reports/round06_readiness.json` | 由 pytest 產生（測試副作用） | 否 |

---

## 10. 2026-10-16 收尾：P-1 / P-2 / P-5 已實作，P-3 為提案，P-4 暫緩

### 10.1 P-1 Team ID 解耦（已實作）

- `config/ops.yaml` 新增 `team:` 區塊：
  - `competition_team_id: null`（null = TEAM_ID_NOT_CONFIGURED）
  - `precompetition_team_id: TEAM_TEST`
- `agent/ops/team.py`：
  - `resolve(mode)`：COMPETITION 只接受非 placeholder 的正式 ID。
  - placeholder 清單：TEAM_TEST*、TEAM_SIM、TEAM_XXX、TEAM_REHEARSAL、空值。
- 讀取端：
  - `scheduled_run.py`：COMPETITION 未設定 → `BLOCKED TEAM_ID_NOT_CONFIGURED`，不執行 competition_day。
  - `datapack_status.py`。
  - `competition_preflight.py`。
  - `competition_day.py` CLI：`--mode competition` 遇到 placeholder，或與 ops.yaml 不一致 → 回傳 2。library 函式不變，測試 fixture 不受影響。
- 凍結檔：`config/strategy_quant_v1.yaml` 未修改（sha256 不變），runtime 不再讀它的 team_id。
- test fixture 中的 TEAM_TEST 全部保留。

### 10.2 P-2 Market coverage gate（已實作）

- `agent/ops/market_coverage.py`：
  - 一個日期 = COMPLETE 才可用：TWSE 與 TPEx 各 ≥ 95% universe 有有效收盤價；所有持股都有有效收盤價；有委託的個股有 vwap 與 volume。
  - 否則為 INCOMPLETE；完全沒有資料為 MISSING。
- 接入點：
  - `daily_evaluation`：日期不完整也會重抓；仍不完整 → `BLOCKED MARKET_DATA_INCOMPLETE`，在結算前擋下。另外檢查持股與委託價格。
  - `scheduled_run.backfill_gaps`：最近 10 個交易日中不完整的日期也會重抓。
  - `competition_day`：T−1 coverage 檢查，dry-run 與 competition 都會 BLOCK。
  - `competition_preflight`。
- `config/ops.yaml market_coverage.min_market_share: 0.95`。
- 回歸測試重現 10/16：
  - 第 2 天、T 只有 TPEx → `MARKET_DATA_INCOMPLETE`，沒有寫入 ledger。
  - 對照組：關掉 gate → 仍是原本的 `NAV_RECONCILIATION_FAILED`。

### 10.3 P-5 Active Share 來源 gate（已實作，依 mode）

- `agent/ops/active_share_gate.py`：

| 情況 | COMPETITION | PRECOMPETITION |
|---|---|---|
| 沒有 benchmark 持股 / 官方清單中有 ETF 沒有持股 | BLOCK `ACTIVE_SHARE_DATA_MISSING` | WARN |
| 最舊持股 > 10 日（`etf_stale_days_block`） | BLOCK `ACTIVE_SHARE_DATA_STALE` | BLOCK（沿用既有行為，未放寬） |
| 3–10 日 | WARN `ACTIVE_SHARE_DATA_AGING` | WARN |
| 執行後 Active Share 無法計算（UNKNOWN） | BLOCK，不產生 FINAL | WARN（notes 記錄 `ACTIVE_SHARE_UNKNOWN`） |

- 不猜 benchmark 權重。官方 15%、內部目標 30% 不變（有測試）。
- fixture store 使用其合成快照（只要求存在）。真實 store 只計非合成資料。

### 10.4 P-3 詳細提案（未實作）

**現象**：比賽開始後，17:00 `AI_CUP_Precompetition_Evaluation_1700` 從第 2 個比賽日（評估日 10/28）起，預期每天 `BLOCKED SETTLEMENT_CHAIN_MISMATCH`。

| 問題 | 說明 |
|---|---|
| 哪個欄位 | `logs/evaluation/latest_status.json` 的 `status=BLOCKED`、`blocked_reason=SETTLEMENT_CHAIN_MISMATCH`、`start_candidates=["PAPER_LEDGER","INITIAL_CASH"]` |
| 哪段程式 | `agent/ops/daily_evaluation.py` `evaluate()` 第 3 步（約 165–176 行）：候選起點只有 paper ledger（`data/paper_ledger/settlement/<T−1>.json`）與初始資金，且要求 `settlement_hash(候選) == run_metadata.json` 的 `settlement_hash` |
| 為什麼發生 | `settlement_hash = sha256(holdings, str(cash), str(nav))`。比賽日 D-Plan 的起點是**官方 DataPack** 結算（competition_day 匯入的 `data/settlement/<T−1>_official.json`）；paper ledger 是模擬成交。兩者的 cash / nav 幾乎不可能到小數位完全一致（官方取整、實際成交、作廢委託） → hash 不同 |
| 第 1 天 | 10/27 的 D-Plan 起點 = 初始資金 → 評估 PASS，會寫 paper ledger 10/27（模擬），無害 |
| 是否影響 NAV | 不影響官方 NAV。只是 paper NAV 序列在 10/27 之後停止更新 |
| 是否影響 DataPack | 否。evaluation 不讀也不寫 `data/official_datapack/`、`data/settlement/` |
| 是否影響正式 D-Plan | 否。COMPETITION 的 19:30 不走 paper chain（`competition_preparation` 只用 DataPack gate）；evaluation 只讀 FINAL，不修改（既有測試驗證 sha256 不變） |
| 實際風險 | 每天一個 BLOCKED 狀態造成誤判 / 噪音；狀態檔 label 仍是 `PRECOMPETITION_PAPER_RUN` |

**建議修改**（擇一）：

- **選項 B（建議先做，最小）**：`evaluate()` / `run()` 在 `run_mode == COMPETITION` 時回傳 `SKIPPED`、`blocked_reason = "COMPETITION_MODE: official settlement = DataPack"`，不寫 paper ledger。
  - 約 10 行程式 + 2 個測試。
  - 只改 17:00 evaluation 的行為，不動決策、排程時間、DataPack、D-Plan。
- **選項 A（之後）**：COMPETITION 時改用官方 DataPack 結算當起點，做「模擬 vs 官方」差異診斷。
  - 寫到獨立目錄 `data/competition_eval/`，label `COMPETITION_DIAGNOSTIC`。
  - 約 60–100 行 + 測試；需要真實 DataPack 範例驗證後再做。

**Production behavior 改動程度**：低。只影響 17:00 的診斷工作；正式投資決策、19:30 run、DataPack gate 都不變。

### 10.5 P-4

暫緩。`shadow_metrics.py` 未加入任何排程，維持手動研究工具。

### 10.6 Git 整理建議（未 commit；未刪除任何研究成果）

| 群組 | 建議 commit | 內容 |
|---|---|---|
| **A. Factor Research** | 是 | `agent/research/factor_lab.py`<br>`research/factor_research/`（腳本、`ACCEPTANCE_GATE.md`、`FACTOR_*.md`、`results/*.csv/json`，約 1.9 MB）<br>`reports/FACTOR_RESEARCH_SUMMARY.md`<br>`.gitignore`（data/research/） |
| **B. Risk Overlay Research** | 是 | `research/risk_overlay/`（`overlay_lab.py`、`run_overlay_study.py`、`signal_study.py`、`analyze_overlay.py`、`case_1015.py`、報告與 `results/*.csv/json`）<br>`reports/RISK_OVERLAY_SUMMARY.md`<br>`research/future_research_backlog.md` |
| **C. Competition Operational Readiness** | 是（P-1/P-2/P-5 + 工具 + 測試 + 文件） | `agent/ops/competition_preflight.py`、`team.py`、`market_coverage.py`、`active_share_gate.py`<br>`agent/competition_day.py`、`agent/ops/daily_evaluation.py`、`datapack_status.py`、`scheduled_run.py`<br>`config/ops.yaml`<br>`tests/ops/test_competition_preflight.py`、`test_p1_p2_p5.py`<br>`experiments/precompetition_e2e_rehearsal.py`<br>`reports/COMPETITION_OPERATION_SOP.md`、`COMPETITION_GO_NO_GO_CHECKLIST.md`、本檔 |
| **D. Shadow / 每日產物** | 選擇性 | `research/risk_overlay/shadow_metrics.py`（程式 → 隨 B commit）<br>`data/shadow_metrics/shadow_history.csv`、`reports/shadow_metrics/*_shadow.md`（研究紀錄；建議 commit 一次快照，或加入 .gitignore 只留本機）<br>`reports/daily_predictions/2026-10-15/16_prediction.md`、`reports/daily_evaluations/*.md`（與既有 10-14 一致 → 建議 commit） |

建議加入 `.gitignore`（runtime 產物，不應 commit）：

- `research/*/results/*.log`（main.log、analyze.log、stress_placebo.log）
- `research/risk_overlay/results/probe.csv`（機制測試）
- `runtime/` 已忽略：`e2e_rehearsal`、`overlay_bt`、`factor_bt`

不應 commit（已忽略）：

- `sim_runs/`（含 freeze check 的 W5 重跑）
- `logs/`
- `data/paper_ledger/`
- `data/history/`
- `submissions/`、`archive/`

### 10.7 驗證

- 全量 pytest **505 passed**（484 → 新增 21）。
- Quant v1：sha256 `f34fa02e…d2e0` 不變；W5 NAV 1,014,240,575.839861741934859718；24/24 decision hash 相同；凍結路徑（strategy、features、portfolio、pipeline、run_sim、sim、engine）git diff 為空。
- 修改檔案的行尾已對齊 HEAD（CRLF / LF 不變），diff 只有實際修改，共 81 行。
- 已知小問題（未修改）：既有 `preflight.git_info()` 解析 `git status` 時把第一個路徑的首字元截掉（顯示 `gent/competition_day.py`），只影響顯示。

---

## 11. 最終驗證（2026-10-19 17:05）

### 11.1 週末實際排程（新程式已上線）

| 執行 | 結果 |
|---|---|
| 10/17、10/18 17:00 evaluation | SKIPPED `NO_TRADING_DAY`（正確） |
| 10/16（週五）、10/17 19:30 | SKIPPED `NO_SUBMISSION_WINDOW_TONIGHT`（正確） |
| 10/18（週日）19:30 → T=10/19 | **PASS**；`team_id TEAM_TEST`（來源 `config/ops.yaml:team.precompetition_team_id`，P-1 生效）；backfill 無缺口（P-2）；paper ledger 10/16 起點；Active Share 46.95%；D-Plan 4.3 PASS；FINAL 產生 |
| 10/19 17:00 evaluation | **PASS**：market data OK（coverage gate 通過）、NAV reconciliation PASS、日報酬 −1.22%、累計 −6.28%、合規 PASS、Active Share 47.40% |

### 11.2 新發現的 WARNING

1. **Claude 週用量上限**：週日 19:30 的 3 個 Claude 呼叫都回 `USAGE_LIMIT: You've hit your weekly limit`（重置時間 13:00）。
   - 依設計改用 template 敘述，決策不受影響。
   - 比賽期間若再撞到上限，敘述會是 template。請在 10/26 前確認用量；本輪研究與 rehearsal 也消耗了用量。
2. **Rehearsal 的 LLM 呼叫紀錄寫進真實 log**：10/16 的隔離 rehearsal 有重導 ops 路徑，但 LLM call log 仍寫到 `logs/llm/20261019/calls.jsonl`（5 筆 1.0 秒 TIMEOUT 注入紀錄）。
   - 只影響稽核 log；log 已被 gitignore，D-Plan 不受影響。
   - 未刪除。日後 rehearsal 應同時重導 `llm.log_root`。

### 11.3 P-3 建議

`P3_RECOMMENDATION = DEFER_SAFE`

- 第一次出現在 10/28 的 evaluation。
- 不影響官方 NAV、DataPack、D-Plan、隔日起點（COMPETITION 起點只來自 DataPack）。
- 10/27 前不需處理。SOP §A-3 已註明這是預期現象。
- 若想消除噪音，可在 10/28 前做選項 B（約 10 行，需另外核准）。

### 11.4 Commit groups（不 commit，等待確認）

| 群組 | 檔案 | 建議 |
|---|---|---|
| A. Factor Research | `agent/research/factor_lab.py`、`research/factor_research/**`（不含 `*.log`）、`.gitignore`（data/research/） | COMMIT |
| B. Risk Overlay Research | `research/risk_overlay/**`（程式、報告、`results/*.csv/json`；含 `shadow_metrics.py`）、`research/future_research_backlog.md` | COMMIT；`results/*.log`、`results/probe.csv` → GITIGNORE |
| C. Operational Readiness（P-1 / P-2 / P-5） | `agent/ops/team.py`、`market_coverage.py`、`active_share_gate.py`、`competition_preflight.py`<br>`agent/competition_day.py`、`agent/ops/daily_evaluation.py`、`datapack_status.py`、`scheduled_run.py`<br>`config/ops.yaml`<br>`tests/ops/test_p1_p2_p5.py`、`test_competition_preflight.py`<br>`experiments/precompetition_e2e_rehearsal.py` | COMMIT（比賽前必須，否則 `UNCOMMITTED_WORKTREE`） |
| D. Documentation | `reports/COMPETITION_OPERATION_SOP.md`、`COMPETITION_GO_NO_GO_CHECKLIST.md`、`PRECOMPETITION_OPERATIONAL_READINESS.md`、`FACTOR_RESEARCH_SUMMARY.md`、`RISK_OVERLAY_SUMMARY.md` | COMMIT |
| E. Generated outputs | `reports/daily_predictions/2026-10-15/16/19_prediction.md`、`reports/daily_evaluations/*.md` | COMMIT（與既有 10-14 檔一致）；或日後統一 GITIGNORE |
| | `data/shadow_metrics/`、`reports/shadow_metrics/` | KEEP LOCAL + GITIGNORE（每天變動的研究產物） |
| | `runtime/`、`logs/`、`sim_runs/`（含 freeze check 重跑）、`data/paper_ledger/`、`data/history/`、`submissions/`、`archive/` | 已 GITIGNORE；KEEP LOCAL，不 commit |

建議新增 `.gitignore`：

```
research/*/results/*.log
research/risk_overlay/results/probe.csv
data/shadow_metrics/
reports/shadow_metrics/
```

---

## 12. Submission readiness + cross-day catch-up（2026-10-20）

- **時間窗**：`agent/ops/submission_window.py`。
  - 19:30 正常；當晚同日補跑。
  - T 00:00～08:29:59 跨日補跑，只做 trade_date = 今天。
  - 08:30 `DECISION_WINDOW_CLOSED`，排程與 competition_day 都強制。
  - 08:55 `SUBMISSION_WINDOW_CLOSED`。
  - 警告：`SUBMISSION_WARNING_0800`、`SUBMISSION_HIGH_WARNING_0815`、`SUBMISSION_CRITICAL_WARNING_0845`。
  - 設定在 `config/ops.yaml deadline`。
- **排程**：`scheduled_run.plan` 改寫。
  - 已 PASS → SKIP；已 ACCEPTED / UPLOADED → `SUBMISSION_ALREADY_*`；已有 FINAL → `FINAL_ALREADY_EXISTS`（`--safe-retry` 可重產 candidate）。
  - 狀態紀錄新增 `run_kind`、`window_phase`、`submission_state`、`deadline_warnings`。
  - 排程時間未改；仍只有 17:00 / 19:30 兩個工作。
- **2026-10-20 實例**：10/19 19:30 的工作 10/20 08:54:17 才啟動。
  - 舊紀錄：`MISSED_PREVIOUS_DAY`。
  - 新邏輯（有回歸測試）：`DECISION_WINDOW_CLOSED`，不跑 Quant。
- **Submission 狀態機**：`agent/submission/status.py`，依證據推導，見 SOP §G-1。
  - 底層既有的 `base.py` 狀態機不變。
  - receipt 新增 `accepted_at`、`failure_reason`、`evidence_files`。
- **Portal**：`agent/submission/portal.py`。
  - `--status` / `--open`（只開瀏覽器）。
  - `config/ops.yaml submission.portal_url: null`，`ui_status: NOT_YET_VERIFIED`。
  - `OfficialPortalProvider` DISABLED。
  - 無任何 login / upload / submit / cookie 程式碼（有測試）。
- **測試**：
  - 新增 `tests/ops/test_submission_window.py`（40 項）。
  - 5 個舊測試依新政策更新期望：08:47 / 08:56 / 09:05 不再產生決策；RESTRICTED 階段改測 08:26；午夜後改為 CROSS_DAY_CATCHUP。
  - 全量 **545 passed**。
- **Quant v1**：sha256 不變；W5 NAV 相同；24/24 decision hash 相同；凍結路徑無 diff。
