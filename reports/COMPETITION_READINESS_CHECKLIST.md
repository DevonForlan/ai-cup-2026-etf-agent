# Competition Readiness Checklist（2026-10-05，Round 05）

> AI 產生內容，需人工審閱。等級：**PASS** 已完成並驗證｜**WARN** 可用但有已知限制｜**BLOCKED** 未能完成或受外部條件阻擋。

## 總評：**DRY_RUN_READY**

| 等級 | 定義 | 狀態 |
|---|---|---|
| DEV_READY | 測試全過、baseline 不變、核心模組完成 | ✅ |
| DRY_RUN_READY | 一鍵流程可在演練中產生合法送件包；故障注入與截止保護驗證；手冊完成 | ✅ |
| COMPETITION_READY | 另需：正式提交與結算取得方式確認（NC-1）、真實窗口 competition 模式演練、首日確認 | ❌（NC-1 未確認 → 最高 DRY_RUN_READY） |

## 逐項

| # | 項目 | 等級 | 依據 / 說明 |
|---|---|---|---|
| 1 | Quant Core v1 | PASS | 凍結 `f4dfb66`，hash 檢查；W1–W5 replay 不變 |
| 2 | Competition Engine / Validator | PASS | 267 tests；D-Plan v4.2 schema + C-checks |
| 3 | NAV simulator | PASS | W5 NAV 1,014,240,575.84 與 Round 04 相同 |
| 4 | D-Plan 產生 | PASS | dry run A 與 baseline 委託相同 |
| 5 | 前日組合不合法時的處理（現金漂移） | PASS | `d6a45ca` 修正 + regression test |
| 6 | 資料：TWSE / TPEx 行情 | PASS | dry run B 實抓 OK；失敗 → BLOCK |
| 7 | 資料：法人 | PASS | 實抓 OK |
| 8 | 資料：ETF 持股 | WARN | 27/30 當日快照成功；3 檔當下回空（用前次資料）；5 檔發行商只提供最新日 → 必須每日抓；端點非官方文件化 |
| 9 | 資料：公司行動 | PASS | 實抓 OK |
| 10 | 資料：MOPS 營收 first_seen | PASS | append-only 帳 + PIT 過濾；時間戳 bug 已修並更正 |
| 11 | 資料：重大訊息、夜盤、美股、SOX、TSM、匯率 | WARN | 實抓 OK；Yahoo 非官方 API（OPTIONAL，失敗不阻擋） |
| 12 | 資料健康報告 | PASS | `logs/ops/<T>/data_health.json/.md` |
| 13 | Settlement：內部帳 | PASS | `settle_internal.py`；E2E 兩日測試 |
| 14 | Settlement：主辦方帳取得 | BLOCKED | NC-1：無公告方式；目前只能人工抄錄 JSON/CSV |
| 15 | Reconciliation | PASS | MATCH/MINOR/BLOCK + 人工 accept-official；不自動選邊 |
| 16 | Preflight | PASS | 20 項；competition 模式 BLOCK 規則經測試 |
| 17 | Deadline guard | PASS | dry run C 五階段 |
| 18 | Safe degradation L0–L3 | PASS | 每層需 validator PASS；L3 不假設合法 |
| 19 | LLM narrative（real） | BLOCKED | 無 API key；需使用者依 `docs/REAL_LLM_SETUP.md` 設定 |
| 20 | LLM 失敗回退 | PASS | timeout / 429 / invalid JSON → Template，D-Plan PASS |
| 21 | competition_day 一鍵流程 | PASS | A/B/C dry run；永不上傳 |
| 22 | Submission package | PASS | 全部必要檔 + manifest；不可覆寫 |
| 23 | FINAL_CANDIDATE | PASS | 唯一、醒目、錯隊名/日期/hash/驗證失敗拒絕；DRY-RUN 不顯示 upload |
| 24 | Archive | PASS | 唯讀、拒絕覆寫、manifest hash |
| 25 | Audit | PASS | `audit/` 索引（6 runs） |
| 26 | Healthcheck | PASS | HEALTHY/DEGRADED/BLOCKED 經測試 |
| 27 | Runbooks | PASS | 每日 / 緊急 / 凍結 / 自主性 / LLM 設定 |
| 28 | PowerShell 腳本 | PASS | 解析 0 錯誤、無 exit、未建排程 |
| 29 | Submission mechanism（上傳） | BLOCKED | NC-1 未公告；人工上傳 FINAL 檔 |
| 30 | 真實窗口演練（19:30–08:55，competition 模式） | WARN | 尚未進行；建議 10/26 前至少兩晚實跑（dry-run 模式） |
| 31 | Organizer unknowns | WARN | NC-1…NC-10、NC-15、C12 未確認（見報告 §18） |
| 32 | 首個交易日 | WARN | NC-15：10/26 或 10/27；`-Initial` 參數已備 |
