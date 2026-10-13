# Round 08 — Pre-competition Daily Paper Trading + Final Operational Validation（2026-10-13）

> AI 產生內容，需人工審閱。所有賽前結果標示 **PRECOMPETITION_PAPER_RUN**，不是正式比賽成績、不上傳、不提交。
> 未新增投資策略；Quant Core v1 未修改。Round 08 之後不再新增功能（只做每日 paper run、官方規則相容、明確 bug fix、正式競賽操作）。

**ROUND08_STATUS = COMPLETE**
**PRECOMPETITION_OPERATIONAL_STATUS = READY**

## 1. 每日流程
```
16:00+  投信更新主動 ETF 持股（19:30 run 的 refresh 抓取）
17:00   AI_CUP_Precompetition_Evaluation_1700  → 評估前一晚對「今天」的 paper prediction
        前日 paper 結算 + 前一晚 FINAL 委託 + 今日真實均價 / 收盤（既有 deterministic simulator）
        → data/paper_ledger/settlement/<T>.json + reports/daily_evaluations/<T>_evaluation.md
19:30   AI_CUP_Precompetition_DryRun_1930     → 缺漏交易日回補 → paper chain（前一交易日 paper 結算；
        若 17:00 尚未跑，先內嵌補做 evaluation）→ competition_day dry-run（prod profile）
        → FINAL candidate + reports/daily_predictions/<T+1>_prediction.md
兩個工作：WakeToRun=False、StartWhenAvailable=True（當天登入後補跑）、跨過午夜不補前一天、當天已 PASS 不重跑、
MultipleInstances=IgnoreNew、允許電池；不儲存密碼。
```
Paper ledger 與正式帳本分開（`data/paper_ledger/`，不寫 `data/settlement/`）；19:30 以 `--replay-run data/paper_ledger`
讀取。評估只接受與 prediction 的 `settlement_hash` 相同的起點（否則 BLOCKED SETTLEMENT_CHAIN_MISMATCH）。

## 2. 完成條件
| # | 條件 | 結果 | 證據 |
|---|---|---|---|
| 1 | 19:30 prediction scheduler | **PASS** | 2026-10-13 21:24 工作排程器補跑（延遲 114 分）：真實 dry-run PASS、Claude READY、D-Plan v4.3 PASS、FINAL 產生 |
| 2 | prediction summary | **PASS** | `reports/daily_predictions/2026-10-14_prediction.md`；`tests/ops/test_round08.py` |
| 3 | 17:00 evaluation scheduler | **PASS** | `AI_CUP_Precompetition_Evaluation_1700` 由工作排程器觸發：0x0，`SKIPPED NO_PREDICTION_FOR_DATE`（10-13 無 prediction，正確） |
| 4 | settlement | **PASS** | 歷史驗證 3 日：結算可重現（同輸入重算 holdings / cash / NAV 完全相同）、委託對齊 |
| 5 | NAV | **PASS** | 獨立重算 Σ股數×收盤+現金 = NAV；3 日 paper NAV 996,269,165.84 = `run_sim` 996,269,165.8356（逐分相同） |
| 6 | evaluation report | **PASS** | `runtime/round08_hv/reports/2026-10-0{7,8}_evaluation.md`、`2026-10-12_evaluation.md`；報酬拆解檢查 PASS |
| 7 | duplicate guard | **PASS** | 19:30：已 PASS → `SKIP_ALREADY_PASSED`（實測）；17:00：同一 prediction 已 PASS → 略過；鎖檔防同時執行（測試） |
| 8 | missed-run catch-up | **PASS** | 19:30 工作 21:24 補跑（實測）；StartWhenAvailable 兩個工作皆設定 |
| 9 | no cross-day replay | **PASS** | 午夜後啟動 → `MISSED_PREVIOUS_DAY`（兩個工作；測試） |
| 10 | full pytest | **PASS** | 460 passed, 0 failed |
| 11 | Quant fingerprint | **UNCHANGED** | W5 NAV 1,014,240,575.839861741934859718、24/24 decision_core_hash = Round 06 baseline；strategy sha256 `f34fa02e…` |
| 12 | security scan | **PASS** | `agent/ops/security_scan.py` PASS；無 token / cookie / credential |

## 3. 歷史驗證（真實資料，08-P）
`experiments/round08_historical_validation.py`（隔離目錄 `runtime/round08_hv/`，不動真實 submissions / ledger；template 敘事以確保可重現）
| T | 起點 | 委託 | 持股 | NAV | 日報酬 | 檢查 |
|---|---|---|---|---|---|---|
| 2026-10-07 | INITIAL_CASH | 24 | 24 | 993,391,065.84 | -0.66% | 全 PASS |
| 2026-10-08 | PAPER_LEDGER（10-07） | 0 | 24 | 988,733,665.84 | -0.47% | 全 PASS |
| 2026-10-12 | PAPER_LEDGER（10-08） | 0 | 24 | 996,269,165.84 | +0.76% | 全 PASS |
結果：`reports/round08_historical_validation.json`（ALL_PASS = true）。

## 4. 即時驗證（08-Q）
最近一次 19:30 prediction：交易日 **2026-10-14**（10-13 21:24 產生）。10-14 收盤資料尚未存在 →
**WAITING_FOR_NEXT_MARKET_CLOSE**（未 mock）。2026-10-14 17:00 工作會自動評估；19:30 起 paper chain 由 10-14 結算延續。

## 5. 本輪發現與修正
- **價量資料缺口**：2026-10-06～10-08 未在 store（每日 refresh 只抓 T-1，電腦未開即缺）。已回補（公開 TWSE / TPEx）。
  10-14 的 prediction 是在回補前產生，回補後重算：同 24 檔、權重約低 2.6%（現金區間因廣度指標不同）——
  paper 評估照實評估已凍結的 prediction；19:30 排程現在先自動回補近 15 天缺漏交易日（`backfill_gaps`）。
- Preflight 的資料新鮮度只檢查 T-1；缺口由排程回補處理（Quant / gate 未修改）。

## 6. 操作
- 看 19:30 結果：`.\automation\check_last_scheduled_run.ps1`
- 看 17:00 評估：`.\automation\check_last_evaluation.ps1`
- 手動重跑：`Start-ScheduledTask -TaskName "AI_CUP_Precompetition_DryRun_1930"` / `"AI_CUP_Precompetition_Evaluation_1700"`
- KPI：NAV、報酬、MDD、週轉、費稅、合規；「上漲持股比例」僅 diagnostic only。Benchmark：未納入（無穩定來源，不阻擋）。
- 正式比賽前（10-26 19:30 首個窗口）需另行決定是否升級為 competition-day workflow（本輪未做）。
