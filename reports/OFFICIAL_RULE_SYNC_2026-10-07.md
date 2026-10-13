# 官方規則同步 — 2026-10-07 主辦方回覆整合 + 官網最新文件（執行日 2026-10-13）

> AI 產生內容，需人工審閱。維護作業，非新 Round。Quant 投資策略未修改。

## 1. 官網檢查日期
2026-10-13 10:10～10:20（+08:00），`https://esun-ai-challenge.tw` 活動頁「2026 Agent 基金經理人」。只讀取活動頁公開載入的資料與公開附件下載連結；未登入、未讀 cookie、未呼叫需登入或未公開端點。DataPack（每隊資料）需登入 → LOGIN_REQUIRED（未下載）。索引：`research/official_updates/OFFICIAL_UPDATE_INDEX.md`。

## 2. 是否發現新版規則
**是**：`AI CUP 2026玉山人工智慧公開挑戰賽_比賽辦法_1005更新.pdf`（2026-10-05 上傳）。變更：§六(十三) Active Share 改為「投資組合前 15 大 vs 各主動型 ETF 前 15 大、< 15% 禁止；不定期檢視，連續 2 個交易日 < 15% 有權取消資格」。其餘（20–30 檔、2330 25% / 其他 10%、現金 ≤ 25%、整股、費稅、24 個交易日、每日 25 次提交上限、警告 3 次取消資格、價格漂移 5 個交易日寬限）不變。

## 3. 是否發現新版 D-Plan
**是：D-Plan v4.3**（2026-10-12 上傳：schema、撰寫指南、正例 TEAM_042 / 反例 TEAM_043（2026-10-28）），並**新增 DataPack 規格書 v4.3**。官網公告：「請參賽隊伍務必更新規格文件」。差異：`research/official_updates/DPLAN_VERSION_DIFF.md`。Runtime 已升級為 v4.3（`schema_version "4.3"`）。

## 4. 新版附件清單（下載至 `research/official_updates/`）
`AI CUP 2026玉山人工智慧公開挑戰賽_比賽辦法_1005更新.pdf`、`D-Plan.schema_v4.3.json`、`D-Plan_撰寫指南_v4.3.md`、`D-Plan_TEAM_042_2026-10-28.json`、`D-Plan_TEAM_043_2026-10-28.json`、`DataPack_規格書_v4.3.md`。
未變更（sha256 與根目錄相同）：主動型 ETF 列表 v1（30 檔名單**未更新**）、150 檔清單 v1、策略說明文件範例 / 繳交格式 v1、Google Token Credit。根目錄原始檔未修改。

## 5. 2026-10-07 Email confirmed rules
| 項目 | 主辦方回覆 | 與官網最新版是否衝突 |
|---|---|---|
| Active Share Wi | 占整體 NAV 權重、計算包含現金、雙方持股聯集 | 辦法未寫 Wi 細節 → 採 Email |
| 前 N 大 / 門檻 | 雙方前 15 大聯集、< 15% 違規 | 與辦法_1005 一致 |
| Benchmark | 逐一比較每檔官方主動 ETF；自行取得最新持股（投信約 16:00 後更新）；不定期抽驗 | 一致 |
| 同日多次提交 | 一般交易日亦以 08:55 前最後一次成功提交為準 | 辦法另載每日 25 次上限（不衝突） |
| 比賽期間修改程式 | 強烈建議完整保留修改紀錄、版本、原因與執行 log | 指南 v4.3：改參數即改版（不衝突） |
| 第一個交易日 | 10/26 光復節補假休市；首個交易日 10/27；10/26 19:30 起可上傳 | 與官網公告 09-29 一致 |
| NC-1 / NC-3 | 尚未確認，主辦方調整新版 D-Plan 中 | **官網 10-12（晚於 Email）已發布 v4.3 + DataPack** → NC-1 結算部分由 DataPack 規格回答；NC-3 部分回答（見 §10、§11） |

## 6. Active Share changes
| 項目 | 舊 | 新（官方） |
|---|---|---|
| official_threshold | 0.20 | **0.15**（`config/competition.yaml active_share_min`） |
| top_n | 10 | **15**（雙方前 15 大聯集） |
| weight_basis | 未確認（取三種解讀最小值） | **占 NAV** |
| include_cash | 未確認 | **true**；benchmark ETF 現金權重投信未揭露 → `NEED_CONFIRMATION`：現金項只在雙方皆已知時加入，否則不加入（較低 = 保守），**不補 0** |
| comparison | 30 檔各比、取最小 | 同（逐一比較所有官方主動 ETF、最新可得持股） |
| DQ | 連續 2 日 | 同（連續 2 個交易日 < 15%） |
| internal_safety_target | 0.30 | **0.30（策略緩衝，非官方）**；15%～30% → WARNING |
實作：`agent/engine/active_share.py` 新增 `official_active_share` / `compute_official_active_share`（只新增，原函式不變）；D-Plan 驗證器 `R_ACTIVE_SHARE` 改用官方算法（`agent/engine/validate_dplan.py`）；訊息不再寫死 20%（`agent/engine/compliance.py`）。Quant Core v1 內部 30% 安全檢查仍用原（凍結）指標，決策路徑不變。
W5 replay 官方 Active Share：最低 41.6%（舊指標 36.0%），全部 ≥ 15%。

## 7. Submission changes
- 每交易日 **08:55 前最後一次成功提交生效**（NC-10 RESOLVED）。區分「最後一次上傳」與「最後一次成功提交」：被拒收 / 未定的上傳不取代先前成功提交（`agent/submission/receipt.py effective_submission`）。
- 每日上限 25 次（辦法 §二(八)）。
- 仍為 prepare-only：不登入、不自動上傳、不猜端點。

## 8. First trade date
- 名義期間 2026-10-26 ～ 2026-11-27；**2026-10-26 休市**；**第一個交易日 2026-10-27**；首次繳交窗口 **2026-10-26 19:30 ～ 10-27 08:55**；共 24 個交易日。**NC-15 RESOLVED**（官網公告 2026-09-29 + Email 2026-10-07 + TWSE 行事曆）。
- 設定：`config/competition.yaml first_trade_date / first_submission_window`、`config/trading_calendar_2026.yaml organizer_first_trade_date`。

## 9. Code change governance
新增 `docs/CODE_CHANGE_GOVERNANCE.md`：每次修改保留 timestamp / reason / affected files / git diff / SHA / code_version / regression / D-Plan impact / Quant fingerprint / before-after；分類 ALLOWED_TECHNICAL_CHANGE vs 績效導向人工作法（禁止）。NC-9 PARTIALLY RESOLVED。

## 10. Unresolved NC-1
- **結算**：DataPack 規格書 v4.3（2026-10-12，晚於 Email）定義前日結算來源 = 後台「文件繳交」→「下載資料包」（需登入、人工）→ **RESOLVED（官方文件）**。新增 `agent/ops/datapack.py`（嚴格驗證 team / trade_date / `missing` / NAV 恆等式 → 既有官方結算檔 + 確認紀錄；`null` 不當空手）。
- **提交**：平台人工上傳（每日 25 次）；實際上傳頁與回執格式需登入確認 → **OPEN（NEED_CONFIRMATION）**。
- `config/organizer_clarifications.yaml`：NC-1 = partially_confirmed → readiness 不升級。

## 11. Unresolved NC-3
- v4.3 已載明「未通過即整份退回」：引用完整性、決策覆蓋、整股；DataPack 作廢原因：insufficient_funds / oversell / no_price / compliance_fail / dplan_reference_chain / dplan_decision_coverage / dplan_round_lot；incident 分 warn（不計取消資格）/ fail（計違規天數）。
- 未寫處置：C12（posture、現金區間）、C14（funding_for）、時間戳 → **OPEN**。我們維持所有 FAIL 視為拒收（保守）。不自行猜測 C3/C4/C5/C7/C8/C10。

## 12. Quant unchanged
- `config/strategy_quant_v1.yaml` 未修改（sha256 `f34fa02e…` = freeze 值）；Revenue YoY 0.7 / MoM 0.3、目標 25 檔、分級權重、rebalance_every 100、EMA 0.4、entry 20 / hold 35、min hold 5、threshold 2%、swap 0.05、max new 3/day、regime（use_v0 未啟用）皆不變。
- `agent/portfolio`、`agent/features`、`agent/risk`、`agent/sim` 無修改；`agent/engine` 只在 Active Share 官方算法（新增函式）、驗證器 Active Share 段與訊息文字變更。
- **W5 replay**：NAV 1,014,240,575.839861741934859718（= baseline）、**24/24 日 decision_core_hash 與 Round 06 baseline 相同**、0 違規 / 0 驗證失敗 / 0 fallback（v4.3 schema + 官方 15% 規則下）。
- 真實資料 2026-10-12：Claude 路徑與 Template 路徑 decision_core_hash 相同（`sha256:9998f9ea…`）。

## 13. Regression result
`.venv\Scripts\python.exe -m pytest -o addopts="" -q` → **439 passed, 0 failed, 169.27 s**。新增 `tests/ops/test_rule_sync_1007.py`（20 項：14.99% FAIL / 15.00% PASS / 30% 內部目標、前 15 大聯集、現金項、所有官方 ETF 取最小、舊指標不變、首日 10/27、10/26 非交易日、首次窗口 10/26 19:30、最後一次成功提交、v4.3 schema、DataPack 解析 / 拒收 / NAV 恆等式 / 首日 / 匯入、每日合規摘要）；更新 4 項因規則變更而過時的測試（20% → 15%、NC 狀態）。安全掃描 PASS（4,009 檔），0 token / cookie / OAuth / API key / 帳號識別。

## 14. Dry-run result（PRECOMPETITION_REAL_DATA_DRY_RUN）
| 執行 | 結果 |
|---|---|
| **最新資料：交易日 2026-10-13**（10:3x 真實 refresh，價量至 10-12） | **BLOCKED**：`etf_holdings_freshness: oldest latest-date 2026-10-02 (11 days)`（> 10 天 BLOCK；Active Share 安全規則，未放寬）。原因：中信投信公開 API 對 00983A / 00995A / 00406A 持續回 `ResultCode=1`「Token 無效或過期」（白天；Round 07 夜間正常）。Claude READY（2.1.296，`WARNING_VERSION_DRIFT`）；未呼叫 Claude。 |
| 補充：交易日 2026-10-12（ETF 新鮮度 ≤ 10 天之最近交易日；historical 模式，deadline clock 2026-10-11 20:00） | **HISTORICAL_OK**，L0；Claude 2 次呼叫 0 失敗（MOPS 研究推論 0：視窗內無公告）；D-Plan **v4.3** 驗證 PASS（27 PASS / 1 N/A / 6 NOT_IMPLEMENTED）；官方 Active Share **46.65%**（內部目標 30% PASS）；每日合規摘要全 PASS、Overall READY；FINAL candidate 產生（`submissions/20261012/FINAL/`，historical，非正式提交）；Claude = Template 決策 hash |
未上傳、未登入。

## 15. Final readiness
**DRY_RUN_READY**（不變）。NC-15 / NC-10 已解決；NC-1（提交）與 NC-3 仍未完全確認；最新真實 preflight 因中信 ETF 資料過期為 BLOCK。
**Commit：未建立**——依指示「dry-run PASS 才 commit」，最新資料日（10-13）dry-run 為 BLOCKED（資料來源問題，非程式錯誤）。

## 補記（2026-10-13 22:05）：最新資料 dry-run 已 PASS → 建立 commit
- 中信投信持股於晚間恢復（最舊 ETF 持股日 2026-10-08，6 天，WARN）。
- 交易日 **2026-10-14** 真實資料 dry-run（真實時鐘、送件窗口內、`--competition-profile prod`）：**DRY_RUN_OK**、L0、D-Plan v4.3 驗證 PASS、官方 Active Share 41.10%、Claude 3 次 0 失敗、Claude = Template 決策 hash；排程器 21:24 補跑亦 PASS。
- 全部測試 449 passed / 0 failed；W5 fingerprint 不變；安全掃描 PASS → 依指示建立 commit。
