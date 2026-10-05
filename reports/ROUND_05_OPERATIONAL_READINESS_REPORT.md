# ROUND 05 — Operational Readiness Report

日期：2026-10-05　｜　git：`7ce1ffc`（起點）→ 本報告 commit　｜　依公司政策：AI 產生內容，需人工審閱。

> **一句話結論**：營運層（每日資料更新、ETF 每日快照、MOPS 營收首見帳、結算對帳、preflight、截止保護、一鍵流程、送件包、FINAL_CANDIDATE、不可變封存、稽核索引、手冊）已完成並通過 3 組 dry run 與 16 項故障注入。過程中找到並修正 2 個真問題（現金漂移時再平衡失敗、模擬時鐘被寫成觀測時間）。**真實 LLM 驗證 BLOCKED（無 API key）**；正式提交機制（NC-1）未公告 → 最高只能評為 **DRY_RUN_READY**。

---

## 1. Round 05 做了什麼

| 項目 | 檔案 | commit |
|---|---|---|
| 營運設定（資料重要度、對帳容忍度、preflight、截止保護、路徑、凍結 hash） | `config/ops.yaml` | `29db140` |
| 每日資料更新（10 個來源、狀態欄位、CRITICAL/IMPORTANT/OPTIONAL） | `agent/ops/refresh_daily.py` | `29db140`、`df6d042` |
| ETF 每日快照（不覆寫，manifest 含 hash/URL/抓取/公布時間） | `data/raw/active_etf/YYYYMMDD/` | 同上 |
| MOPS 營收 first_seen（append-only；replay 只用 first_seen_at ≤ cutoff） | `data/observations/mops_revenue_first_seen.parquet` | 同上 |
| SettlementProvider（ManualFile JSON/CSV、Replay、FutureOfficialAPI stub） | `agent/ops/settlement.py` | `29db140` |
| 對帳 MATCH / MINOR_DIFFERENCE / BLOCK；人工 `--accept-official` | `agent/ops/reconcile.py` | `29db140`、`c0f24e9` |
| 內部結算（T 收盤後） | `agent/ops/settle_internal.py` | `29db140` |
| Preflight PASS/WARN/BLOCK（git、設定 hash、凍結、schema、150 檔、prompt、Python、套件、磁碟、時間、窗口、資料、ETF 新鮮度、結算、前日組合合法性、LLM） | `agent/ops/preflight.py` | `29db140`、`cf6e084` |
| 截止保護 NORMAL/RESTRICTED/NO_LLM/PACKAGE_ONLY/PAST_CUTOFF | `agent/ops/deadline.py` | `29db140` |
| 一鍵流程（永不上傳） | `agent/competition_day.py` | `29db140` 起 |
| 送件包 + manifest + FINAL_CANDIDATE | `agent/ops/package_submission.py` | `29db140`、`df6d042` |
| 不可變封存 | `agent/ops/archive_run.py` | `29db140` |
| 健康度 HEALTHY/DEGRADED/BLOCKED | `agent/ops/healthcheck.py` | `29db140` |
| 稽核索引 | `agent/ops/audit.py` → `audit/` | `c0f24e9` |
| 敘事審查工具（template vs LLM、A–I 檢查、成本） | `agent/ops/llm_review.py` | `976a188` |
| 真實 provider 解析強化（空回應/安全阻擋/非 JSON → 回退；GOOGLE_API_KEY） | `agent/llm/providers/http_providers.py` | `976a188` |
| PowerShell 腳本（無 exit、無排程） | `scripts/*.ps1` | `cf6e084` |
| 手冊 | `docs/*.md` | `c0f24e9` |
| **Bug fix**：現金漂移時再平衡 | `agent/portfolio/constructor.py` | `d6a45ca` |
| **Bug fix**：觀測時間戳用實際時鐘 | `agent/ops/refresh_daily.py` | `df6d042` |

本輪**沒有**做訊號研究、因子調整、持股數 / turnover / Crash Guard 調整。`config/strategy_quant_v1.yaml` **未修改**。

## 2. Tests
`.venv\Scripts\python.exe -m pytest` → **267 passed / 0 failed / 267 total**（Round 04 的 225 + 本輪 42）。

新增：`tests/ops/test_ops_units.py`（provider parser、結算匯入、對帳、資料健康、first-seen、截止階段、preflight、現金漂移偵測、送件包/manifest、FINAL 唯一與錯檔拒絕、封存、wall clock）、
`tests/ops/test_competition_day.py`（兩日 E2E + 官方結算、股數不符 BLOCK、缺官方結算、現金漂移、LLM timeout/429/bad JSON、LLM 與 template 委託相同、PACKAGE_ONLY、過截止、OPTIONAL 失敗不阻擋、CRITICAL 失敗阻擋、人工 accept-official、healthcheck）、
`tests/portfolio/test_cash_drift_r05.py`（regression；舊程式 3 項失敗）。

**Baseline**：Quant v1 W5 replay NAV **1,014,240,575.84**，0 違規 / 0 驗證失敗 / 0 fallback，與 Round 04 完全相同（`sim_runs/round05_baseline_quant_v1/`）。
修 bug 前後 W1–W5 五個窗口 final NAV、turnover 逐位元相同。

## 3. Real LLM status
**REAL_LLM_STATUS = BLOCKED_NO_API_KEY**。GEMINI_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY 在 process、User、Machine 環境與 `.env` 皆不存在（只檢查有無，未讀值）。
依指示未開帳號、未購買額度、未建立資源、未建立金鑰。使用者步驟見 `docs/REAL_LLM_SETUP.md`（Google Token Credit：9/20–10/19 寄課程截圖 → 序號 → 11/30 前兌換，12/31 到期）。
`reports/round05_llm_narrative_review.csv` 與 `round05_llm_cost.csv` 以明確的 BLOCKED 列輸出（沒有任何假數字）。

## 4. Provider / Model
預定 Google Gemini（主辦方提供 credit）。`config/llm_narrative_v1.yaml` 目前 `provider: template`、`model: null`；模型 ID 與價格需使用者依 Google 官方文件填入（程式不猜）。
Adapter 經 recorded-shape 單元測試，**從未實際呼叫**。

## 5. Narrative grounding
真實 LLM：無資料（BLOCKED）。
管線驗證（**mock，不是 LLM**，`reports/round05_mock_pipeline_check/`，10 日）：A 來源 100%、B Fact ID 100%、C 數字 100%、D ticker 100%、E 指令污染 0、F 決策未變 100%、G 市場觀點一致 100%、I validator 100%；
H counter_evidence 90%（mock 在 08-28 丟掉一個 template 有的反證 → 檢查器有抓到，證明檢查有效）。
H 的定義：counter_evidence 在 schema 是選填，template 在事實無負面訊號時留空；規則是「LLM 不得丟掉事實支持的反證」，不要求憑空生成。

## 6. Narrative fallback rate
真實 LLM：N/A。Mock：0%。故障注入（timeout / 429 / invalid JSON）：100% 回到 Template，D-Plan 全數 PASS。

## 7. LLM latency
真實 LLM：N/A（BLOCKED）。Mock 數值（< 0.01 s）沒有意義，不列為依據。截止保護：剩 ≤15 分鐘不呼叫 LLM、不重試。

## 8. LLM tokens / cost
真實 LLM：N/A。價格未設定 → 成本欄 `PRICE_NOT_CONFIGURED`（不自行假設價格）。啟用後成本 = provider 回傳 usage × config 價格。

## 9. Human review
`reports/human_review/README.md`：BLOCKED，無可審內容。審查包格式已建好（mock 範例：`reports/round05_mock_pipeline_check/human_review/YYYY-MM-DD_review.md`，Template vs LLM 並排、事實、來源、A–I 結果、人工勾選欄）。

## 10. Daily data automation status
Dry run B（2026-10-05 12:03，實際網路）：10 個來源全部 OK，資料健康 PASS，總耗時 165 s。

| 來源 | 重要度 | 結果 | 耗時 s |
|---|---|---|---|
| TWSE / TPEx 行情 | CRITICAL | OK（T-1 已在 store，不重抓） | 1.5 / 0.4 |
| TWSE / TPEx 法人 | IMPORTANT | OK 100 / 50 檔 | 1.8 / 1.8 |
| ETF 持股 | IMPORTANT | OK 1,336 列；快照 27/30（00983A、00995A、00406A 當下回空，store 仍有前次資料） | 108.0 |
| 公司行動 | IMPORTANT | OK | 16.9 |
| MOPS 營收 first_seen | OPTIONAL | OK，新首見 2 筆（8046、6510 的 9 月營收） | 3.9 |
| MOPS 重大訊息 | OPTIONAL | OK | 14.4 |
| TAIFEX 夜盤 | OPTIONAL | OK | 3.9 |
| 美股/SOX/TSM/匯率 | OPTIONAL | OK | 12.4 |

政策：CRITICAL 失敗/過期 → BLOCK；IMPORTANT → WARN（降級 L2）；OPTIONAL → WARN，**永不阻擋合法的 Quant D-Plan**（故障注入驗證）。
**Bug（已修，`df6d042`）**：B 以模擬時鐘（10-04 20:00）執行，first_seen_at、ETF 快照資料夾、fetched_at 被寫成模擬時間（比實際早約 16 小時 → replay 會提早看見資料）。
改為所有觀測時間戳使用實際時鐘；2 筆錯誤 first-seen 依 `refresh.log` 實際時間更正，記錄於 `data/observations/corrections.jsonl`；快照資料夾更名並附 `CORRECTION.json`。`monthly_revenue` 未受影響（既有列較保守）。

## 11. Settlement reconciliation status
完成：內部帳（`settle_internal.py`）、主辦方帳抄錄（JSON/CSV）、對帳（股數任一差異 BLOCK；現金 ≤5 MATCH、≤2,000 MINOR、更大 BLOCK；NAV 相對差 >0.005% BLOCK；警告不同 BLOCK；門檻在 config）。
BLOCK → 不產生 D-Plan、等人工；系統不選邊；人工以 `reconcile.py --accept-official --confirmed-by` 明確採用官方帳（保留策略狀態與舊檔）。
Dry run A/B/C 以 replay 結算對帳皆 MATCH。**主辦方結算的實際取得方式未確認（NC-1）**。

## 12. Preflight status
完成，20 項檢查；standalone CLI 會讀結算帳。2026-10-06 實測：無前日結算 → BLOCK（正確）；`--initial` → WARN（資料健康未跑、ETF 最舊 5 天）。
competition 模式 BLOCK 條件：git 不乾淨、策略 hash 不符凍結、schema 缺、universe ≠150、Python/套件、磁碟 <5 GB、CRITICAL 資料、無前日結算、對帳 BLOCK 或無官方結算、前日持股缺價。

## 13. Live dry run results

| Run | 內容 | 結果 |
|---|---|---|
| A 歷史 | W5 2026-10-02，replay 結算，`scripts/competition_dry_run.ps1 -Mode historical` | HISTORICAL_OK，validation PASS，**委託與市場觀點與 baseline D-Plan 完全相同**，8.4 s |
| B 當日營運 | 交易日 2026-10-05，實際網路更新全部來源，時鐘模擬 10-04 20:00（PIT 截止），replay 結算 | DRY_RUN_OK，PASS，171 s（資料 165 s、量化+D-Plan+驗證 2.5 s、打包 1.1 s、封存 0.7 s） |
| C 比賽時鐘 | 交易日 2026-10-01，19:30 / 08:30 / 08:42 / 08:47 / 08:57 五次 | 見 §15 |

尚未在真實 19:30–08:55 窗口以真實 T-1 收盤資料跑過 competition 模式（今日時間不在窗口內）。

## 14. Failure injection results
`reports/round05_failure_injection.csv`：**16/16 符合預期**。

| 注入 | 結果 |
|---|---|
| TWSE 失敗、TPEx 失敗 | BLOCKED，無 FINAL |
| ETF 失敗、MOPS 失敗、美股+夜盤失敗 | DRY_RUN_OK，L2，PASS |
| LLM timeout / 429 / invalid JSON | DRY_RUN_OK，Template（L1），PASS |
| 磁碟不足 | BLOCKED |
| competition + 乾淨 git + 對帳 MATCH | READY_TO_SUBMIT |
| competition + git dirty | BLOCKED |
| 結算股數不符 1 張 | BLOCKED（settlement_reconciled） |
| 08:50（PACKAGE_ONLY）+ LLM 設定 | DRY_RUN_OK，Template，不更新資料 |
| 08:58 過截止 | LATE_PAST_CUTOFF，無 FINAL |
| 法人 + 隔夜特徵缺失 | DRY_RUN_OK，PASS |

**Bug（已修，`d6a45ca`）**：E2E 測試注入現金漂移時發現：前日組合因現金 >25% 不合法，完整再平衡卻失敗而回退到同一個不合法組合（每天吃警告）。
原因 1：不交易區間保留所有被稀釋的持股，交易中的少數標的受上限卡住 → 委託後現金仍 27%。原因 2：NO_TRADE 標的宣告 water-fill 目標而非目前權重 → 權重和 >100%，假的 R_CASH_NEG。
修正：現金目標不可行時解除不交易區間；NO_TRADE 宣告目前權重。W1–W5 不變；regression test 在舊程式失敗。

## 15. Deadline guard results
Dry run C（`reports/round05_dry_run_C.json`）：

| 時鐘 | 階段 | LLM | 資料更新 | 結果 |
|---|---|---|---|---|
| 09-30 19:30 | NORMAL | 用（mock） | 允許 | DRY_RUN_OK L0 |
| 10-01 08:30 | RESTRICTED | 用 | 只允許關鍵 | DRY_RUN_OK L0 |
| 10-01 08:42 | NO_LLM | 停用 | 只允許關鍵 | DRY_RUN_OK L1 |
| 10-01 08:47 | PACKAGE_ONLY | 停用 | 跳過 | DRY_RUN_OK L1 |
| 10-01 08:57 | PAST_CUTOFF | — | — | LATE，無 FINAL |

FINAL 目錄始終只有 1 個檔；`final_history.jsonl` 4 筆。是否「最後一次上傳為準」未確認（NC-10）→ 手冊規定每日上傳一次。
單次量化 + D-Plan + 驗證 2–5 s；完整資料更新約 3 分鐘（ETF 佔 2/3）。
另記：一次 10 日 mock 審查曾耗時約 25 分鐘，重跑為 12.6 s，無法重現、原因未查明；比賽時以 operator summary 的各階段耗時監看。

## 16. Submission package
`submissions/YYYYMMDD/candidates/<run_id>/`：D-Plan、validation_report.json/.md、portfolio.csv、orders.csv、facts.json、sources_manifest.json、data_health.json、reconciliation.json、preflight.json、agent_state.json、run_metadata.json（trade_date、generated_at、git_sha、git_dirty、python_version、strategy/competition/unconfirmed/ops/llm config hash、prompt_versions、data_snapshot_hash、settlement_hash、dplan_sha256、provider、model、llm_replay_id、degradation、各階段耗時）、README.txt、manifest.json（filename/sha256/size/created_at）。
FINAL：通過隊名、日期、檔名、hash、驗證、manifest 完整性檢查才複製到 `FINAL/`（唯一一檔）並寫 `FINAL_CANDIDATE.txt`；非 competition 模式標示 DRY-RUN、不出現 “UPLOAD THIS FILE”。錯隊名 / 錯日期 / hash 被改 / 驗證失敗 → 拒絕（測試）。

## 17. Audit evidence
`audit/`：架構文件 + 每個模組 sha256、prompt 版本與 hash、所有 config hash + 凍結紀錄、封存索引（目前 6 個 run 的 ARCHIVE_MANIFEST sha256）。不複製原始資料，以 store manifest hash 指向。
`archive/YYYYMMDD/<run_id>/` 唯讀、拒絕覆寫。`docs/AGENT_AUTONOMY_EVIDENCE.md` 說明人機分工與證據鏈。`docs/STRATEGY_FREEZE_RECORD.md` 列出凍結後所有決策路徑變更。

## 18. Remaining NC rules（皆未確認；未建立 ORGANIZER_CLARIFICATIONS.md，因尚無主辦方回覆）
NC-1 正式提交與結算取得方式（**阻擋 COMPETITION_READY**）｜NC-2 Active Share 定義｜NC-3 各 C-check 拒收或警告｜NC-4 未提交/不交易處置｜NC-5 手續費進位｜NC-6 25% 現金與 20/30 檔是否含等號｜NC-7 配股零股｜NC-8 MDD 是否含初始 NAV｜NC-9 比賽中可否修 bug｜NC-10 同日多次提交以何者為準｜NC-15 首個交易日 10/26 或 10/27｜C12 預估是否含費用。
另：`competition.yaml` 記載每日最多 25 次提交（辦法 §二(八)）。

## 19. 是否已達 competition-ready
**DRY_RUN_READY**（不是 COMPETITION_READY）。
- 已達：DEV_READY（測試、baseline、模組）＋ DRY_RUN_READY（一鍵流程、dry run A/B/C、故障注入、送件包、封存、手冊）。
- 未達 COMPETITION_READY 的原因：(1) 正式提交機制與官方結算取得方式未公告（NC-1）；(2) 尚未在真實 19:30–08:55 窗口以真實 T-1 資料跑過 competition 模式；(3) 首個交易日未確認（NC-15）。
- 真實 LLM：BLOCKED（無 API key）→ 比賽使用 Template 敘事，不影響 Quant D-Plan。
- 詳細逐項：`reports/COMPETITION_READINESS_CHECKLIST.md`。
