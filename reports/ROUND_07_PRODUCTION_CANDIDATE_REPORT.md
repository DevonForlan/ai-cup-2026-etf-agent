# Round 07 — Production Candidate Integration + Competition Readiness Closure（2026-10-05）

> AI 產生內容，需人工審閱。不構成投資、法律或財務建議。

## 1. Executive status
- **Claude CLI：CLAUDE_CLI_PRODUCTION_CANDIDATE**（Round 06B 為 EXPERIMENTAL_ONLY）。啟用方式：`--competition-profile prod`（primary = claude-cli，fallback = template）；全域預設仍為 Template。
- **Readiness：DRY_RUN_READY**（語意不變；NC-1 未確認 → 上限 DRY_RUN_READY）。新增欄位 `llm_runtime = CLAUDE_CLI_PRODUCTION_CANDIDATE`。
- **Quant 未修改**：`config/strategy_quant_v1.yaml`、`agent/portfolio|features|engine|risk|sim`、驗證器與 D-Plan 規則與 83af462 完全相同；W5 replay NAV 逐位元相同，24/24 日決策核心 hash 相同。
- **Release candidate：`4742d5a`**（Round 06 RC `83af462` 保留為參考，不覆寫歷史；未建 tag）。

## 2. Baseline
| 項目 | 值 |
|---|---|
| Round 07 開始 HEAD | `08769f5`（工作樹：Round 07 開始時僅本輪檔案變更） |
| Round 06 RC | `83af462`（DRY_RUN_READY） |
| Round 06B commits | `01bfba3`..`08769f5` |
| Round 07 commits | `dd98f4a`..`4742d5a`（見 §20） |

## 3. Claude CLI production candidate
架構：Data → Quant Core v1 → Decision → Facts / Evidence → **Claude CLI** → Narrative / Thesis / Counter-evidence / MOPS research → **Grounding / Validation** → D-Plan → Submission candidate。任何 Claude 失敗 → Template → D-Plan。
- `config/llm_claude_cli.yaml` 分節：enabled / provider / model / timeout / tools / session / fallback / deadline_guard / grounding / audit；`load_llm_config()` 攤平並**拒絕**：非 NARRATIVE_LOCKED（非 research_mode）、allowed tools 非空、session persistence / continue / resume、fallback ≠ template。
- 指令（不變，06B 驗證）：`claude -p --output-format stream-json --tools "" --disallowedTools <全部 + mcp__*> --permission-mode dontAsk --restricted --safe-mode --setting-sources "" --strict-mcp-config --no-session-persistence --max-turns 3 --json-schema …`；prompt 走 stdin，cwd 為每次呼叫的 sandbox（只含 prompt / schema / facts）。不使用 `--dangerously-skip-permissions`、bypassPermissions、`--continue` / `--resume`。
- `config/competition_prod.yaml` + `agent\competition_day.py --competition-profile prod`；明確 `--llm-provider template` 仍可覆蓋。PowerShell：`scripts\competition_dry_run.ps1 … -CompetitionProfile prod`。
- **MOPS Research Narrative Pipeline**（`agent/research/mops_research.py`、`mops_research_v1`）：PIT 可見的持股重大訊息（≤ 8 則、每檔 ≤ 2）→ 一次批次呼叫 → `event_type / summary / positive_evidence / negative_evidence / uncertainty / affected_tickers / fact_refs` → grounding → 證據圖。MOPS 公告 = Source + Observation（程式寫入原文主旨）；Claude 解讀 = Inference（premise_refs 只指向該 Observation），只附加到既有 Decision / NoTrade。LLM 不是證據來源，LLM 不產生交易。
- Narrative 一致性：新增 decision-contradiction gate（建議加碼 / 減碼、HOLD 卻描述交易、方向相反）→ FAIL → Template。

## 4. Auth
`claude auth status` 只讀四欄：`loggedIn=true`、`authMethod=claude.ai`、`subscriptionType=team`、`apiProvider=firstParty` → **READY**。其他 → DEGRADED → Template（不阻擋 Quant）。不輸出 email、組織名、token、credential 路徑。
授權：**AUTHORIZED_FOR_COMPETITION_USE** — organization-managed Team account authorized by employer for company competition participation（主辦方規則未禁止外部 LLM / agent framework；主辦方未特別點名 Claude Code CLI）。

## 5. Version pin
`supported_versions: ["2.1.289"]`。preflight 執行 `claude --version`：相同 → PASS；不同 → **WARNING_VERSION_DRIFT**（不阻擋；需重跑 `experiments\claude_cli_runtime\round07_regression.py`）。本次：**2.1.289 → PASS**。

## 6. Fallback
TemplateProvider 永久保留。觸發：CLI_NOT_FOUND、NOT_AUTHENTICATED、USAGE_LIMIT、RATE_LIMIT、TIMEOUT、NONZERO_EXIT、INVALID_JSON、SCHEMA_FAIL、GROUNDING_FAIL、TOOL_VIOLATION、DECISION_CONTRADICTION、BUDGET_EXHAUSTED。
Runtime budget（沿用 deadline guard，08:46 行為未改）：NORMAL = 敘事 + thesis + 研究；RESTRICTED（≤ 30 分）= 只 1 次市場敘事；NO_LLM（≤ 15）= Template；PACKAGE_ONLY（≤ 10）= 只量化 + 驗證 + 打包。
測試：CLI 不存在時 `competition_day` 仍 DRY_RUN_OK、validation PASS、`LLM: … STATUS=DEGRADED FALLBACK=template`。

## 7. Grounding
未知 fact ID、新 ticker、無來源數字、禁止指令 / 交易指令、與決策矛盾 → FAIL → Template（未放寬）。
實測：smoke 2/2 通過、real dry-run 3 次呼叫 0 失敗、研究推論 4/4 通過、0 rejected。

## 8. Decision invariance
- W5 replay（2026-08-28 ～ 10-02，24 日）：NAV **1,014,240,575.839861741934859718**（= Round 06 baseline）、0 warning / 0 驗證失敗 / 0 fallback；**24/24 日 decision_core_hash 與 Round 06 baseline 相同**。
- 真實資料（2026-10-06）：Claude 路徑與 Template 路徑 decision_core_hash 相同（`sha256:732a92f2…`）。
- 測試：研究開啟 / 關閉、grounding 失敗、逾時、bad JSON → decisions / orders / no-trade 完全相同。

## 9. Real-data dry run（PRECOMPETITION_REAL_DATA_DRY_RUN）
`.venv\Scripts\python.exe agent\competition_day.py --date 2026-10-06 --team-id TEAM_TEST --mode dry-run --competition-profile prod --initial`（真實時鐘、真實 refresh、無 mock）
| 項目 | 結果 |
|---|---|
| 狀態 | DRY_RUN_OK，degradation **L0**，validation PASS（27 PASS / 1 N/A / 6 NOT_IMPLEMENTED） |
| LLM | `LLM: PRIMARY=claude-cli STATUS=READY FALLBACK=template`；呼叫 3、失敗 0、p95 67.9 s、研究推論 4 |
| D-Plan | sources 12、observations 30、inferences 28、decisions 24、orders 24（上限內） |
| 組合 | risk_on / increase、24 檔、現金 8.04%、Active Share 0.395 |
| SLA | quant 1.06 s、narrative+D-Plan 115.9 s（上限 300）、refresh 93.1 s、無 breach |
| 稽核 | `archive/20261006/20261005_230844_gitc4fdcb5-dirty/`、`logs/llm/20261006/calls.jsonl` |
第一次嘗試因未加 `--initial`（dry-run 無前日結算）在 preflight BLOCK，未呼叫 Claude；加上與 Round 06 相同的 `--initial` 後通過。
**RC 乾淨工作樹重跑**（`git:4742d5a`，23:37 ～ 23:39）：DRY_RUN_OK、L0、validation PASS、preflight 僅 `etf_holdings_freshness` WARN（git_clean / llm_availability PASS）；Claude 3 次呼叫 0 失敗、p95 64.9 s、研究推論 4；`agent_metadata` = anthropic / claude-opus-5-5（第一次執行時為 other / unknown，已修正並加測試）；decision_core_hash `sha256:732a92f2…`（與前次及 Template 相同）。封存：`archive/20261006/20261005_233904_git4742d5a/`。

Round 07 真實 Claude 呼叫合計：smoke 1 + dry-run 3 + RC dry-run 3 = **7 次，0 失敗**（另 2 次 `claude auth status` / `--version` 健康檢查）。

## 10. Real-window status
執行時間 2026-10-05 23:06 ～ 23:10（+08:00），位於交易日 2026-10-06 的送件窗口（10-05 19:30 ～ 10-06 08:55）內，真實時鐘、未使用模擬時鐘 → **REAL_WINDOW_REHEARSAL 完成（dry-run）**。
既有 Round 06 FINAL（template、dry-run）被保留：`FINAL ACTION: KEPT_DIFFERENT`（DECISION_DIFFERENCE — 輸入變更：資料快照 `c1230697…` → `30a60df3…`；同資料下 Claude / Template 決策相同）。未執行 replace-final（需真人操作者姓名與理由）。

## 11. Trading calendar
`config/trading_calendar_2026.yaml`：TWSE 官方 2026 休市日（`https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&queryYear=115`，retrieved_at、sha256、effective_range 2026）；`config/ops.yaml market_holidays` 填入 18 個平日休市日。
**2026-10-26：TWSE 休市日（否，不是交易日）**。2026-10-26 ～ 11-27 TWSE 交易日 24 天（10-27 ～ 11-27），與辦法「24 個交易日」及官方範例 2026-10-27 一致。記錄為 `official_market_calendar`；**NC-15 仍 OPEN**（主辦方未確認第一個比賽交易日）。

## 12. CTBC ETFs（00983A / 00995A / 00406A）
來源：中國信託投信官網公開 API（匿名頁面 token → `etf/ETFHoldingWeight`），合法公開資料。
| ETF | 狀態 | 最新持股日 | 檔數 |
|---|---|---|---|
| 00983A | OK（海外基金，揭露落後） | 2026-10-02 | 43 |
| 00995A | OK | 2026-10-05 | 57 |
| 00406A | OK | 2026-10-05 | 63 |
白天曾觀察到 3 次 token 皆失敗；`fetch_ctbc` 現在回報 API ResultCode（不再顯示為「無資料」）。若再失敗：STALE_FALLBACK + age 追蹤，安全規則不變，不捏造。

## 13. Active Share
公式未改（§26）；策略目標 30%（官方 20%）。真實 2026-10-06：最低 Active Share 0.395。

## 14. Settlement
未重建；NC-1 未解決。Manual adapter（`ManualFileSettlementProvider` + `settlement_entry.py` 雙重輸入）、future interface（`agent/submission/future_api.py`）、audit、reconciliation 測試全數 PASS（tests/ops）。

## 15. Submission
prepare-only：產生 FINAL + 人工上傳 + 回執記錄。無瀏覽器自動化、無自動登入、無猜測 endpoint。
修正：同日先有 dry-run FINAL 時，第一份 competition FINAL 會被「KEPT」→ 現在 competition 取代非 competition FINAL（`SUPERSEDED_NON_COMPETITION`，歷史保留）；非 competition 永不取代 competition FINAL。回歸測試 `tests/ops/test_round07.py`。

## 16. Open NCs
見 `docs/OPEN_NC_LIST.md`：NC-1 結算 OPEN、NC-1 提交 OPEN、NC-2 OPEN、NC-3 OPEN、NC-9 OPEN、NC-10 OPEN、NC-15 OPEN。本輪關閉：無（Claude 成功不關閉任何 NC）。

## 17. Readiness
**DRY_RUN_READY**（不變）。COMPETITION_READY 需：NC-1 結算 + 提交確認、NC-15 確認、關鍵來源可靠、最新真實 preflight 非 BLOCK。`llm_runtime: CLAUDE_CLI_PRODUCTION_CANDIDATE`（不影響等級）。

## 18. Security
- Repo 掃描（`agent/ops/security_scan.py`）+ 補充掃描（runtime、logs、experiments、submissions、archive、D-Plan）：token / cookie / OAuth / API key / 公司機密 = **0**；Round 07 新增內容無個人帳號識別資訊（auth 輸出只有四個白名單欄位）。
- 既有發現（LOW，Round 07 前即存在）：13 個已追蹤檔案（`logs/development/*.log`、`reports/leaderboard_r04*.csv`、`audit/settlement/LEDGER.json`、`agent/README.md`）含本機 Windows 使用者目錄路徑。非憑證；對外分享前建議改為 `%USERPROFILE%`。
- 新文件以 `$env:USERPROFILE` 表示專案路徑。

## 19. Test results
**417 passed / 0 failed**（Round 06B 386 + Round 07 新增 31：`tests/llm/test_mops_research.py` 14、`tests/ops/test_round07.py` 16、`tests/llm/test_claude_cli.py` +1）。Quant decision fingerprint：W5 24/24 日與 Round 06 baseline 相同。

## 20. Release SHA
| 項目 | SHA |
|---|---|
| 新 PRODUCTION_CANDIDATE（Round 07 RC） | `4742d5a` |
| 前一個 RC（Round 06，保留為參考） | `83af462` |
| Round 06B 結束 | `08769f5` |

## 21. Remaining blockers
1. NC-1（官方結算取得方式、正式提交方式）— 主辦方。
2. NC-15（主辦方第一個比賽交易日）— 主辦方。
3. 策略說明文件人工審閱與繳交（2026-10-21 ～ 10-26；草稿 `docs/STRATEGY_DESCRIPTION_DRAFT.md`）。
（Claude CLI 不是 blocker：任何失敗 → Template。）

## 22. Next action
- 向主辦方確認 NC-1 / NC-15（附 TWSE 行事曆）。
- 人工審閱並填寫策略說明文件（官方 docx 副本）。
- 比賽前一週：重跑 `round07_regression.py`（1 auth + 1 smoke）確認 CLI 版本 / 登入；版本若漂移，評估後更新 `supported_versions`。
- 每日依 `docs/DAILY_COMMANDS.md` 執行。
