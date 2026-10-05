# Agent 自主性證據（Agent Autonomy Evidence）

> AI 產生內容，需人工審閱。目的：說明每一份 D-Plan 由 Agent 自主產生、人工只負責「資料抄錄與上傳」，並指出每一步的可驗證證據。
> 正式審查方式與所需格式未由主辦方說明；本文件只整理我們保存的證據。

## 1. 分工

| 步驟 | 由誰執行 | 人工能否改變決策 | 證據 |
|---|---|---|---|
| 公開資料抓取（TWSE/TPEx/ETF/MOPS/TAIFEX/美股/匯率/公司行動） | Agent（`agent/ops/refresh_daily.py`） | 否 | `logs/ops/<T>/data_health.json`（每來源狀態、筆數、抓取時間）、ETF 快照 manifest（hash/URL/時間）、store manifest hash |
| 前日結算 | Agent 內部帳 + 人工抄錄主辦方帳 | 人工只輸入「事實」（持股/現金），不能輸入權重或標的 | `data/settlement/*_internal/official/reconciliation.json`；人工決定寫在 `human_decision` |
| 特徵、評分、選股、權重、現金、委託股數 | Agent（Quant Core v1，決定性） | 否（設定凍結，hash 檢查） | 封存的 `config/` 快照與 hash、`run_metadata.json`、`portfolio.csv`、`orders.csv` |
| 合規檢查與 fallback | Agent（validator + 降級規則） | 否 | `validation_report.json/.md`、`degradation_level` |
| 敘事（market_view / inference 文字） | Agent（Template；真實 LLM 尚未啟用） | 否 | D-Plan 內文、`facts.json`；若用 LLM：`logs/llm/<T>/calls.jsonl`（可 replay） |
| 選出 FINAL | Agent（嚴格檢查：隊名、日期、檔名、hash、驗證） | 人工可決定「不送」，不能改內容 | `FINAL_CANDIDATE.txt`、`final_history.jsonl` |
| 上傳 | **人工**（提交機制未公告，NC-1） | — | 平台回執 `submissions/<T>/receipt_*` |

## 2. 可驗證性
- **不可竄改**：每次執行產生 `archive/<T>/<run_id>/`，`ARCHIVE_MANIFEST.json` 記錄每個檔案 sha256；檔案設為唯讀；同 run_id 拒絕覆寫。
- **D-Plan 一致性**：上傳檔 sha256 = `FINAL_CANDIDATE.txt` = `run_metadata.json.dplan_sha256` = `audit/runs/RUNS.json`。
- **程式版本**：D-Plan `agent_metadata.code_version` = `git:<sha>`；competition 模式拒絕未提交修改。
- **資料版本**：`run_metadata.json.data_snapshot_hash` = 當時 parquet store 各檔 hash 的 hash（不複製原始資料）。
- **PIT**：營運時以實際時鐘作為資料可見截止（`as_of_override`）；觀測時間戳一律用實際時間（Round 05 修正）。
- **重現**：`python agent\competition_day.py --date <T> --mode historical --replay-run <sim_run>` 以相同資料與結算重算；
  Round 05 dry run A 重現 W5 2026-10-02 的委託與市場觀點與 baseline 完全相同。

## 3. 稽核索引
`python agent\ops\audit.py` → `audit/`：架構文件與模組 hash、prompt 版本與 hash、設定檔 hash（含凍結紀錄）、所有封存執行的 manifest hash。

## 4. 已知限制
- 人工上傳是必要步驟（無公開 API）；上傳時間與實際上傳檔案只能以平台回執證明。
- （Round 07 更新）真實 LLM 敘事以 Claude Code CLI 為主、Template 為 fallback，見文末 Round 07 補充。

## Round 06 補充
- 上傳證據：`submissions/<T>/receipts.jsonl`（人工記錄的平台回執，append-only）+ `submission_state.json`（狀態機歷史）；`SUBMISSION_CONFIRMED` 需回執 sha256 = FINAL sha256。
- 決策指紋：`run_metadata.json.decision_fingerprint`（策略 hash + 資料快照 hash + 結算 hash + 程式版本 + 組合 / 委託；不含時間與敘事文字），相同輸入重跑必相同。
- FINAL 凍結紀錄：`submissions/<T>/FINAL_FREEZE.json`，替換需 `final.py replace-final`（人名 + 理由），歷史不刪。
- 官方結算人工輸入：`data/settlement/<T>_confirmation.json`（輸入檔 sha256、雙重輸入結果、操作者、截圖參照）。
- 稽核完整性：`audit/COMPLETENESS.json`。

## Round 07 補充：Claude Code CLI 敘事 / 研究路徑（2026-10-05）
**授權狀態：AUTHORIZED_FOR_COMPETITION_USE** — organization-managed Team account authorized by employer for company competition participation。
（主辦方規則未禁止外部 LLM / agent framework / 合法第三方工具；主辦方未特別點名 Claude Code CLI。本文件不記錄任何帳號、組織或 email 資訊。）

| 步驟 | 由誰執行 | 人工能否改變決策 | 證據 |
|---|---|---|---|
| 選股、權重、現金、委託 | Quant Core v1（決定性，設定凍結） | 否 | `decision_fingerprint`、`decision_core_hash`（與 Template 執行相同） |
| 市場觀點 / thesis / counter-evidence | Claude Code CLI（`claude -p`，NARRATIVE_LOCKED：無工具、無 session、sandbox cwd） | 否 | `logs/llm/<T>/calls.jsonl`（prompt hash、模型、版本、usage、grounding verdict；可 replay） |
| MOPS 公告研究解讀 | Claude Code CLI（`mops_research_v1`，一次批次呼叫） | 否 | D-Plan：MOPS 公告 = Source + Observation（原文主旨，程式寫入）；Claude 解讀 = Inference（`premise_refs` 指向該 Observation） |
| Grounding / 驗證 | Python 決定性 reviewer | 否（不可放寬） | 未知 fact ID、新 ticker、無來源數字、交易指令、與量化決策矛盾 → 丟棄 → Template |
| Fallback | 自動（未登入、額度、逾時、JSON、版本、CLI 不存在、截止前預算） | 否 | operator summary `LLM: PRIMARY=claude-cli STATUS=… FALLBACK=template`、`competition_day_summary.json.llm_runtime` |

- **人工不實質編輯**：敘事與研究文字由 Claude 產生、由程式驗證後直接寫入 D-Plan；操作者沒有編輯 D-Plan 的步驟，且 FINAL 有 sha256 凍結。
- **LLM 不是證據來源**：Claude 的輸出只會成為 Inference 節點，不會成為 Source / Observation；Claude 無法新增或刪除任何標的、權重或委託（資料結構上僅能附加到既有 Decision / NoTrade）。
- **可重現**：同一 prompt hash 以 ReplayProvider 重放；Template 與 Claude 兩條路徑的決策指紋相同（Round 06B 15 日重放 + Round 07 測試）。
- **憑證**：Python 只呼叫官方 `claude` 執行檔；不讀取、不複製、不儲存任何 token / credential；`claude auth status` 只取 `loggedIn / authMethod / subscriptionType / apiProvider` 四欄。
