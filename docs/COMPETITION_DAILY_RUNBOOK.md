# 比賽每日作業手冊（Competition Daily Runbook）

> AI 產生內容，依公司政策需人工審閱後使用。適用 `config/strategy_quant_v1.yaml`（Quant-only，Template 敘事）。
> **本系統永遠不會自動上傳。** 正式提交方式（NC-1）尚未由主辦方確認；人只上傳 `FINAL_CANDIDATE.txt` 指定的那一個檔案。

## 0. 時間軸（交易日 T）

| 時間 | 動作 | 指令（PowerShell，專案根目錄） | 產物 |
|---|---|---|---|
| T-1 15:30 後 | 前一日內部結算（需 T-1 收盤資料） | `scripts\archive_daily.ps1 -Date <T-1>` | `data\settlement\<T-1>_internal.json`、`audit\` |
| T-1 ~19:00 | **人工**：把主辦方 T-1 結算（庫存/現金/淨值）抄入 `data\settlement\<T-1>_official.json` 或 `.csv` | 範本見 §3 | `<T-1>_official.json` |
| T-1 19:30 | 送件窗口開啟。一鍵流程 | `scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -Date <T>` | `submissions\<T>\FINAL_CANDIDATE.txt` |
| T-1 ~19:45 | **人工**：讀 operator summary 與 `FINAL_CANDIDATE.txt`，核對 §2 清單後手動上傳 | （平台） | `submissions\<T>\receipt_*` |
| T 08:55 | 送件截止。之後不得再跑 competition 模式 | — | — |

第一個比賽日（NC-15：10/26 或 10/27 未確認）加 `-Initial`（從初始現金開始，無前日結算）。

## 1. 一鍵流程做了什麼（`agent\competition_day.py`）

```
DEADLINE GUARD → DATA REFRESH → SETTLEMENT + RECONCILIATION → PREFLIGHT → PIT SNAPSHOT →
QUANT CORE v1 → PORTFOLIO → COMPLIANCE → ORDERS → NARRATIVE → D-PLAN → VALIDATION →
SUBMISSION PACKAGE → FINAL_CANDIDATE → ARCHIVE → HEALTHCHECK
```

| 結果 STATUS | 意義 | 你要做的事 |
|---|---|---|
| `READY_TO_SUBMIT` | 驗證 PASS，FINAL_CANDIDATE 已產生 | 依 §2 核對後上傳 |
| `BLOCKED` | 有 BLOCK（資料、結算對帳、git、磁碟、驗證） | **不要上傳**；看 `reason`，照 `EMERGENCY_RUNBOOK.md` |
| `LATE_PAST_CUTOFF` | 已過 08:55 | 不上傳；記錄事件 |
| `DRY_RUN_OK` / `HISTORICAL_OK` | 演練模式 | 檔案標示 DRY-RUN，**絕不上傳** |

截止前保護（`config/ops.yaml` `deadline`）：
- 剩 ≤30 分：不做重型非關鍵資料更新（ETF、公司行動、MOPS）。
- 剩 ≤15 分：不呼叫 LLM（Template 敘事）、不重試。
- 剩 ≤10 分：跳過資料更新，只做量化 + 驗證 + 打包。
- 已過截止：不產生 FINAL。

## 2. 上傳前核對清單（每天，約 1 分鐘）

`submissions\<T>\FINAL_CANDIDATE.txt` 頂端：
1. `trade date` = 今天要送的 T（不是 T-1）。
2. `team` = 我們的隊伍編號；檔名 `D-Plan_<team>_<T>.json`。
3. `VALIDATION : PASS`；`MODE : COMPETITION`（看到 `DRY-RUN` 就**不要上傳**）。
4. 上傳 `UPLOAD THIS FILE` 所列路徑（`submissions\<T>\FINAL\` 裡**唯一**的檔案），不要從 `candidates\` 拿。
5. 可選：`certutil -hashfile <file> SHA256`，核對與 `SHA256` 一致。
6. 上傳後把平台回執存成 `submissions\<T>\receipt_<HHMM>.png/pdf/txt`。

同日多次執行：每次產生新的 `candidates\<run_id>\`；`FINAL\` 永遠只有最新一個合法檔；全部紀錄在 `final_history.jsonl`。
**是否「最後一次上傳為準」未確認（NC-10）**：原則上每日只上傳一次；若需重傳，先確認主辦方規則。

## 3. 主辦方結算抄錄格式

JSON（`data\settlement\YYYYMMDD_official.json`）：
```json
{"date": "2026-10-27", "source": "後台 庫存明細 / 淨值表（說明從哪裡抄）", "entered_by": "姓名",
 "entered_at": "2026-10-27T18:40:00+08:00", "holdings": {"2330": 17000},
 "cash": "123456789.00", "nav": "1000000000.00", "accrued_dividends": "0", "warnings": []}
```
或 CSV（`YYYYMMDD_official.csv`）：`ticker,shares` 每檔一列，另加 `__CASH__,<金額>`、`__NAV__,<金額>`、`__ACCRUED__,<金額>`。

對帳（`config/ops.yaml` `reconciliation`）：股數任何差異 → BLOCK；現金差 ≤5 元 MATCH、≤2,000 元 MINOR、更大 BLOCK；
NAV 相對差 >0.005% BLOCK；警告清單不同 → BLOCK。**BLOCK 時系統不會自行選邊**，見緊急手冊 §B。

## 4. 每日檢查點與檔案位置

| 項目 | 位置 |
|---|---|
| 資料健康 | `logs\ops\<T>\data_health.md/.json` |
| Preflight | `logs\ops\<T>\preflight.json/.log` |
| 一鍵流程紀錄 / 摘要 | `logs\ops\<T>\competition_day.log`、`competition_day_summary.json`、`operator_summary.txt` |
| 健康度 | `python agent\ops\healthcheck.py --date <T> --mode competition` → HEALTHY / DEGRADED / BLOCKED |
| 送件包 | `submissions\<T>\candidates\<run_id>\`（D-Plan、validation_report、portfolio.csv、orders.csv、facts.json、sources_manifest.json、data_health.json、reconciliation.json、run_metadata.json、manifest.json、README.txt） |
| 不可變封存 | `archive\<T>\<run_id>\`（ARCHIVE_MANIFEST.json 含每檔 sha256） |
| ETF 每日快照 | `data\raw\active_etf\<YYYYMMDD>\`（不覆寫，manifest 含 hash / URL / 抓取時間 / 公布時間） |
| MOPS 營收首見 | `data\observations\mops_revenue_first_seen.parquet`（append-only） |
| 稽核索引 | `python agent\ops\audit.py` → `audit\` |

## 5. 不要做的事
- 不要在 `agent\` 或 `config\` 有未提交修改時跑 competition 模式（preflight 會 BLOCK）。
- 不要修改 `config\strategy_quant_v1.yaml`（凍結；hash 不符 → BLOCK）。
- 不要手改 `submissions\` 或 `archive\` 內任何檔案（hash 會不符，FINAL 會被拒）。
- 不要在 `.env` 以外的地方放 API key；不要把 key 貼到任何 log / 對話。
- 不要用瀏覽器自動化或腳本上傳；不要呼叫任何未公告的官方 API。

## 6. Round 06 更新（2026-10-05）

**送件窗口開啟日**：實作依 `competition.yaml opens_prev_day` = 交易日 T 的**前一個日曆日** 19:30（週一的 D-Plan → 週日 19:30 起；週五晚上產生的週一 D-Plan 會被 C6 拒絕）。「前一日」是日曆日或交易日**未確認**，請向主辦方確認；在確認前依日曆日作業。

**每日流程（取代 §0 的相關列）**
| 時間 | 動作 |
|---|---|
| T-1 收盤後 | `scripts\archive_daily.ps1 -Date <T-1>` → 內部結算 + `reports\ops_daily\<T-1>_EOD.md` |
| 主辦方公布 T-1 結算後 | `docs\OFFICIAL_SETTLEMENT_ENTRY_SOP.md`（A/B 雙重輸入 → 對帳 → `--confirm`）。未確認 → competition **BLOCK** |
| T-1 19:30 起 | `scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -Date <T>` |
| 之後 | 依 `docs\FINAL_OPERATOR_CHECKLIST.md` 上傳 + 記錄回執（`python -m agent.submission.receipt ...`） |
| 每日 | `scripts\backup_competition_state.ps1` |

**FINAL 凍結**：第一次合法執行產生 FINAL 後即凍結。之後再跑只產生 candidate：
- `FINAL ACTION: KEPT_IDENTICAL` → 決策相同，什麼都不用做。
- `FINAL ACTION: KEPT_DIFFERENT` → console / 報告列出差異類別（DECISION / DATA / CONFIG / CODE）與原因；若確定要換：
  `.venv\Scripts\python.exe agent\ops\final.py replace-final --date <T> --team-id TEAM_XXX --run-id <新 run_id> --reason "原因" --operator "姓名"`（截止後拒絕；舊紀錄保留）。
- 兩個 candidate 比較：`agent\ops\compare_candidates.py <A> <B>`。

**提交狀態**：`NOT_READY → READY_TO_SUBMIT →（上傳 + 回執）→ SUBMITTED_UNVERIFIED / SUBMISSION_CONFIRMED / REJECTED / UNKNOWN`。檔案產生 ≠ 已提交；只有回執 hash / 隊名 / 日期都吻合且平台 accepted + 回執編號才是 `SUBMISSION_CONFIRMED`。

**休市日**：`config\ops.yaml market_holidays` 只填 TWSE 官方休市日。過去休市由歷史資料自動推得；未登記的未來休市會讓 T-1 行情看似過期 → BLOCK（保守）。

**每日報告**：`reports\ops_daily\<T>_OPERATOR_SUMMARY.md`（上傳前）、`<T>_EOD.md`（收盤後）。Console 決定性資訊永遠在**最後 15 行**。

**斷網**：`agent\competition_day.py --offline` 只用 store 內已有資料：T-1 行情已存 → DEGRADED（L2）可送；沒有 → BLOCK。

**其他工具**：`scripts\soak_test.ps1`、`scripts\verify_release.ps1 -Sha <sha>`、`agent\ops\readiness.py`、`agent\ops\security_scan.py`、
`agent\ops\rehearsal.py`（多日彩排）、`agent\ops\restore_drill.py`（重開機演練）。

## 7. Round 07 每日流程（Claude CLI 為主、Template 為 fallback）
指令全文：`docs\DAILY_COMMANDS.md`。

1. **T-1 收盤後**：`scripts\archive_daily.ps1 -Date <T-1>`（內部結算）→ 主辦方公布後 `settlement_entry.py`（官方結算，雙重輸入）。
2. **Refresh**：一鍵流程內自動（行情、法人、月營收、MOPS、ETF 持股；optional 來源失敗只降級）。
3. **Preflight**：`scripts\preflight.ps1 -Mode competition -CompetitionProfile prod`。
4. **Claude auth / 版本**：同一個 preflight 印出 `LLM: PRIMARY=claude-cli STATUS=READY|DEGRADED FALLBACK=template`；只讀 `loggedIn / authMethod / subscriptionType / apiProvider`。DEGRADED 不阻擋。
5. **Data readiness**：preflight 的 T-1 可見性 + data health（BLOCK 才處理，見 EMERGENCY_RUNBOOK §A）。
6. **competition_day**：`scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -Date <T> -CompetitionProfile prod`
   （Quant Core v1 決策 → Facts / Evidence → Claude CLI 敘事 + MOPS 研究推論 → grounding → D-Plan）。
7. **Validation**：自動；FAIL → 自動 fallback（維持前日組合）；仍 FAIL → BLOCK。
8. **Final candidate**：`submissions\<T>\FINAL_CANDIDATE.txt`；第一份 competition FINAL 會取代同日 dry-run FINAL，之後凍結（換檔需 replace-final + 姓名 + 理由）。
9. **人工上傳**（截止 T 日 08:55）。
10. **記錄回執**：`python -m agent.submission.receipt ...`。
11. **結算**（T 日收盤後）→ **對帳**（次日一鍵流程自動 reconciliation）。

**Claude 失敗 → Template**：未登入 / 額度 / 逾時 / JSON / 版本 / CLI 不存在，全部自動改 Template，D-Plan 決策不變（見 EMERGENCY_RUNBOOK Round 07 表）。
接近截止：≤30 分只呼叫一次市場敘事；≤15 分不呼叫 Claude；≤10 分只打包。

**Claude Code 版本（2026-10-13）**：已驗證 2.1.289、2.1.291（`reports/CLAUDE_CLI_VERSION_VALIDATION_2.1.291.md`）、**2.1.296**（`reports/CLAUDE_CLI_VERSION_VALIDATION_2.1.296.md`）。其他版本 preflight 顯示 `WARNING_VERSION_DRIFT`（不阻擋），需重跑 `round07_regression.py` 後才列入。

## 8. 2026-10-13 官方規則同步（主辦方 Email 2026-10-07 + 官網 10-05 / 10-12）
**正式時序（每個交易日 T）**
1. **T-1 16:00 後**：各投信陸續更新主動 ETF 最新持股 → 一鍵流程的 refresh 抓取（30 檔逐一比較 Active Share）。
2. **T-1 19:00 後**：官方當日淨值 / 結算 → 登入後台「文件繳交」→「下載資料包」（DataPack，人工）→ `python -m agent.ops.datapack ...` 匯入。
   `missing` 含 `prev_settlement` 時 `account` 為 null → 稍後重新下載，不可當成空手。
3. **T-1 19:30**：送件窗口開啟 → Agent 執行（Quant → Active Share → Claude 敘事 → grounding → D-Plan v4.3 → 驗證 → FINAL_CANDIDATE）。
4. 人工上傳（不自動提交）；每日上限 25 次；**08:55 前最後一次成功提交生效**（被拒收的上傳不取代先前成功的提交）。
**首日**：2026-10-26 休市；第一個交易日 **2026-10-27**，窗口 **2026-10-26 19:30 ～ 10-27 08:55**，加 `--initial`（DataPack `as_of_date` 為 null、全現金）。
**Active Share（官方）**：雙方前 15 大聯集、占 NAV、含現金，逐一比較所有官方主動 ETF，**< 15% 違規**、連續 2 日可取消資格；內部安全目標 30% 只是策略緩衝。
**每日合規摘要**：operator summary 的 `COMPLIANCE` 區塊（Universe / 檔數 / 2330 / 個股 / 現金 / Active Share 官方與內部 / 策略一致性 / D-Plan / 人工介入 / Claude / Overall）。

## 9. Round 08 賽前紙上交易（2026-10-13）
17:00 評估（前一晚 prediction × 今日真實均價 → paper 結算 / NAV / 報告）→ 19:30 預測（缺口回補 → paper chain → dry-run → 摘要）。
Paper ledger：`data\paper_ledger\`（與正式 `data\settlement\` 分開）。兩個工作皆不喚醒、當天補跑、不跨日、已 PASS 不重跑。
正式比賽（10-27 起）仍依本手冊第 7、8 節；第一天加 `--initial`，不使用 paper ledger。詳見 `docs\ROUND08_FINAL_VALIDATION.md`。
