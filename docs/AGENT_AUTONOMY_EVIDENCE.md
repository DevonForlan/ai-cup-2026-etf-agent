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
- 真實 LLM 未啟用；目前敘事為決定性 Template，「LLM 自主性」證據待 `docs/REAL_LLM_SETUP.md` 完成後補充。
