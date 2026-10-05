# 緊急應變手冊（Emergency Runbook）

> AI 產生內容，需人工審閱。原則：**寧可不送，也不送錯的檔案；不送屬於「未提交」，送了非法組合會吃警告。**
> NC-3（各 C-check 是拒收或警告）與 NC-4（未提交的處置）皆未確認；以下做法以最保守假設設計。

## 判斷表

| 症狀（operator summary / reason） | 等級 | 處置 |
|---|---|---|
| `data:twse_prices` / `data:tpex_prices` FAILED 或 STALE | BLOCK | §A |
| `settlement_reconciled: BLOCK` | BLOCK | §B |
| `settlement_available: no previous settlement` | BLOCK | §C |
| `git_clean: dirty` | BLOCK（competition） | §D |
| `strategy_freeze` 不符 | BLOCK（competition） | §D |
| `disk_space` | BLOCK | §E |
| `D-Plan validation FAIL even after deterministic fallback` | BLOCK | §F |
| `previous_portfolio_legal` WARN（現金漂移 / 零股 / 超限） | WARN | §G（通常自動處理） |
| ETF / 法人 / 公司行動 FAILED | WARN | 可送；隔日補抓 |
| SOX / ADR / 美股 / 夜盤 / MOPS FAILED | WARN | 可送（OPTIONAL 永不阻擋合法的 Quant D-Plan） |
| LLM timeout / 429 / invalid JSON | 自動降級 | Template 敘事（L1），D-Plan 仍需 PASS |
| 剩餘時間 <10 分 | PACKAGE_ONLY | 只跑量化 + 驗證 + 打包，不更新資料、不用 LLM |
| 已過 08:55 | LATE | 不產生 FINAL，不上傳 |

降級層級：**L0** Quant + 已核准的真實 LLM 敘事 → **L1** Quant + Template 敘事 → **L2** Quant + 快取/過期的非關鍵資料 → **L3** 決定性 fallback（維持前日組合）。
**每一層都必須通過完整 validator**；L3 不是保證合法（見 §G），驗證不過就 BLOCKED、不產生 FINAL。

## §A 關鍵行情資料缺失
1. 重試：`scripts\refresh_daily.ps1 -Date <T> -Only twse_prices,tpex_prices`（官方網站暫時不穩常見於 14:00–15:00）。
2. 若 T-1 行情已在 store（之前抓過），refresh 不會重抓、會顯示 OK（cached）。
3. 仍失敗：**不要**用 T-2 收盤價硬算（derive-orders 以 T-1 收盤計股數，會錯）。記錄事件；若到 08:45 仍無資料 → 當日不送。

## §B 結算對帳 BLOCK（內部 vs 主辦方不一致）
1. 打開 `data\settlement\<T-1>_reconciliation.json` 看 `diffs`。
2. 人工判斷哪邊對：常見原因＝主辦方抄錄錯誤、除權息/配股處理差異（NC-7）、成交價格差異、手續費進位（NC-5）。
3. **主辦方數字正確**（人工確認後）→ 明確執行：
   `.venv\Scripts\python.exe agent\ops\reconcile.py --date <T-1> --accept-official --confirmed-by "姓名" --note "依據"`
   內部帳改為主辦方的持股/現金/NAV（保留策略狀態），舊檔保存為 `<T-1>_internal_superseded_<時間>.json`，
   決定寫入 `<T-1>_reconciliation.json` 的 `human_decision`。之後重跑一鍵流程即可（對帳變 MATCH）。
4. **抄錄錯誤** → 修正 official 檔重跑。
5. **懷疑主辦方帳有誤** → 不要改官方檔內容；聯絡主辦方。平台實際執行的是主辦方帳，所以下一次下單通常仍應以官方帳為起點
   （執行步驟 3，`--note` 註明爭議），否則依內部帳算出的股數可能造成非法委託。
6. 系統**永遠不會自動選邊**；任何決定記錄在 `logs\ops\<T>\` 下的人工紀錄（建議 `manual_decision.md`）。

## §C 沒有前日結算
- 第一天：加 `-Initial`。
- 非第一天：先跑 `scripts\archive_daily.ps1 -Date <T-1>`（內部結算，需 T-1 收盤資料與 T-1 的 FINAL）；
  若 T-1 沒有送件，內部結算視為未提交（維持 T-2 持股）。

## §D git 不乾淨 / 策略設定 hash 不符
- `git status` 查看。非預期修改 → `git stash` 或還原；**不要**在比賽期間修改策略。
- 若為必要 bug fix（NC-9 未確認是否允許）：獨立 commit、加 regression test、在 `docs\STRATEGY_FREEZE_RECORD.md` 記錄，code_version 會更新。

## §E 磁碟不足（< 5 GB）
- 可刪：`out\`、`logs\runs\`、`sim_runs\` 舊研究輸出、`data\cache\`。
- 不可刪：`archive\`、`submissions\`、`data\settlement\`、`data\observations\`、`data\raw\active_etf\`、`logs\llm\`。

## §F 驗證失敗連 fallback 也失敗
- 代表前日組合在 T-1 收盤已不合法且再平衡也無法修正（例如持股缺價、標的被移出名單、股數異常）。
- 看 `submissions\<T>\candidates\*\validation_report.md`（若有）或 `logs\ops\<T>\run\validation.json` 的 FAIL 項目。
- 不要手改 D-Plan JSON。通報、記錄；判斷「不送」與「送非法組合」何者風險較低（NC-3/NC-4 未確認，預設不送）。

## §G 前日組合不合法（現金漂移 / 零股 / 權重超限）
- Round 04 規則：被動現金漂移使現金 >25% 也算警告，**不能**假設維持前日組合是合法的。
- Round 05 修正：此時量化流程會解除「不交易區間」並完整再平衡（regression test：`tests/portfolio/test_cash_drift_r05.py`）。
- 零股（配股，NC-7）無法以整張委託調整，強制 NO_TRADE；若因此違規，依 §F。

## 聯絡與紀錄
每次緊急處置：時間、症狀、決定、依據、執行人，寫在 `logs\ops\<T>\manual_decision.md`，並在隔日 `audit.py` 時一併索引。

## Round 06 新增情境

| 症狀 | 處置 |
|---|---|
| `settlement_confirmed: no confirmation record` / `NOT confirmed` / `CHANGED after confirmation` | 依 `docs/OFFICIAL_SETTLEMENT_ENTRY_SOP.md` 重新雙重輸入並 `--confirm`；官方 JSON 被改過必須重新輸入 |
| settlement_entry `DOUBLE_ENTRY_MISMATCH` | A/B 檔不一致：回到官方畫面逐列核對，不要直接採用任一份 |
| settlement_entry `NAV != sum(shares x close) + cash` | 股數 / 現金抄錯，或官方 NAV 含應收股利（NC-7）：核對後重填；不要調高容忍度 |
| data `CACHED`（DEGRADED） | 來源連不上但 T-1 資料已在 store：可送；事後補抓 |
| T-1 行情 `STALE` 但 T-1 其實是休市日 | 將官方休市日填入 `config/ops.yaml market_holidays` 後重跑（只填官方公告日期） |
| ETF `STALE_FALLBACK`（例：中信 00983A / 00995A / 00406A） | 沿用已存持股（已標示）；持續 >3 交易日 → WARN，>10 日 preflight BLOCK：人工查看發行商網站 |
| `clock_skew` WARN / BLOCK | 校正 Windows 時間（設定 → 時間 → 立即同步），重跑 |
| `FINAL ACTION: KEPT_DIFFERENT` | 決策與已凍結 FINAL 不同：看 `final_comparison`；確定才 `final.py replace-final` |
| 提交狀態 `UNKNOWN` | 回執 hash / 隊名 / 日期與 FINAL 不符：可能上傳了錯的檔 → 立即核對平台上的檔案 |
| 殘留 `.partial` 資料夾 | 上次執行中斷的半成品，**永遠不是有效輸出**；保留作證據即可，重跑會用新 run_id |
| `LockTimeout`（鎖檔被持有） | 先確認沒有其他 agent 程序在跑；擁有者程序已結束且鎖檔 >120 秒會自動回收並記錄 `logs/ops/lock_recovery.jsonl` |
| 主機故障 | 新機器：`git clone` + 建 venv → `agent/ops/backup.py restore --zip <備份> --target <新資料夾>` → 依 `agent/ops/restore_drill.py` 的流程驗證後再跑 |

## Round 07 新增：Claude CLI / 資料 / 提交（2026-10-05）
原則：**Claude 只寫敘事**。任何 Claude 問題 → Template 敘事 → D-Plan 照常產生、決策完全相同。Claude 問題一律**不阻擋**。
operator summary 會顯示 `LLM: PRIMARY=claude-cli STATUS=READY|DEGRADED FALLBACK=template`。

| 情境 | 現象 | 系統自動 fallback | 操作者動作 | 是否阻擋 |
|---|---|---|---|---|
| Claude 未登入 | `STATUS=DEGRADED (NOT_AUTHENTICATED)` | Template 敘事 | 照常上傳。比賽日結束後在本機自己的終端機執行 `claude` 重新登入（不可在程式內處理登入） | 否 |
| Usage limit（額度用完） | LLM 日誌 `USAGE_LIMIT`；`llm.failed ≥ 1` | 當次及之後的呼叫全改 Template，不重試 | 照常上傳；不要換帳號、不要繞過額度 | 否 |
| Timeout | `TIMEOUT`（單次 120 s / 全日 300 s 預算） | 子程序終止（含整個程序樹）→ Template | 照常上傳 | 否 |
| Invalid JSON / schema 錯 | `INVALID_JSON` / `SCHEMA_FAIL` | Template | 照常上傳 | 否 |
| Grounding / 矛盾失敗 | 未知 fact ID、新 ticker、無來源數字、交易指令、與決策矛盾 | 該段文字丟棄 → Template | 照常上傳（gate 不放寬） | 否 |
| 版本漂移 | preflight `WARNING_VERSION_DRIFT`（非 2.1.289） | 仍可使用；若呼叫失敗 → Template | 當天照常；收盤後跑 `experiments\claude_cli_runtime\round07_regression.py` 一次確認後再更新 `supported_versions` | 否 |
| 找不到 CLI | `STATUS=DEGRADED (CLI_NOT_FOUND)` | Template | 照常上傳；收盤後重裝官方 Claude Code | 否 |
| 接近截止 | deadline RESTRICTED（≤30 min） | 只呼叫 1 次市場敘事；thesis / 研究 → Template | 無 | 否 |
| 更接近截止 | NO_LLM（≤15）/ PACKAGE_ONLY（≤10） | 不呼叫 Claude；PACKAGE_ONLY 只做量化 + 驗證 + 打包 | 立即上傳 FINAL | 否 |
| MOPS 過期 / 抓取失敗 | data health WARN（optional 來源） | 研究段落沒有新公告 → 無研究推論；量化不受影響 | 照常上傳 | 否 |
| ETF 持股過期（含中信 00983A / 00995A / 00406A） | `etf_holdings` STALE_FALLBACK + age | 沿用最近一次持股（記錄 age），Active Share 安全緩衝不降低 | 照常上傳；收盤後重跑 refresh | 否（除非全部 ETF 都無資料 → 依 §A） |
| 提交平台無法使用 | 上傳失敗 | 無（程式不會自動上傳） | 依主辦方指示（NC-1 提交方式未確認）；保留 FINAL 與截圖，聯絡主辦方 | 人工處理 |
| 官方結算無法取得 | 次日 preflight：無官方結算 | 競賽模式 BLOCK（不猜持股）；dry-run 可用內部結算 | 依 §C；用 `settlement_entry.py` 人工輸入（NC-1 未確認） | 是（競賽模式） |
