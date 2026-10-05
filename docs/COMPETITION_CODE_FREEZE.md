# 比賽程式凍結（Competition Code Freeze）

> AI 產生內容，需人工審閱。NC-9（比賽期間是否允許修改程式）**未確認**：在主辦方回覆前，不得自行認定賽中可改程式。

## 何時凍結
- **Release candidate**：`reports/ROUND_06_RELEASE_CANDIDATE.md` 建議的 SHA（Round 06 結束時）。
- **正式凍結**：第一個比賽交易日（NC-15：10/26 或 10/27）前一個工作日 18:00，由隊伍負責人確認後，人工建立 tag（`git tag competition-freeze <sha>`；Agent 不自動建立 tag）。
- 凍結後每日執行前：`scripts\verify_release.ps1 -Sha <freeze sha>`（不 checkout、不 reset，暫存 worktree 跑 smoke tests）。

## 凍結範圍

| 類別 | 凍結後 |
|---|---|
| `config/strategy_quant_v1.yaml`（hash 寫在 `config/ops.yaml freeze`） | **禁止修改**（preflight competition BLOCK） |
| 選股 / 權重 / turnover / 持股數 / Crash Guard / LLM 訊號 | **禁止修改** |
| `config/competition.yaml`、D-Plan schema、150 檔清單、主動 ETF 清單（官方輸入） | 只在主辦方正式更新時改，需 `docs/ORGANIZER_CLARIFICATIONS.md` 紀錄 |
| `config/ops.yaml` 的 `market_holidays` | 允許（只能填官方 TWSE 休市日） |
| `config/organizer_clarifications.yaml` | 允許（只能依官方回覆，含來源） |
| 營運層（refresh / 打包 / 封存 / 報告）bug fix | 僅限 bug（見流程），不得改 D-Plan 決策內容 |
| 文件、runbook | 允許 |

## Bug fix 核准流程（凍結後）
1. 開 issue 紀錄：症狀、影響（是否影響 D-Plan 決策）、證據（log / archive run_id）。
2. 判斷是否影響決策路徑（`agent/portfolio`、`agent/pipeline.py`、`agent/features`、`agent/engine`、`agent/risk`）：
   - 影響決策 → 需隊伍負責人書面核准，且 NC-9 未確認時**預設不改**（以 runbook 人工處置替代）。
   - 不影響決策 → 可修，但必須：regression test、獨立 commit、`docs/STRATEGY_FREEZE_RECORD.md` 新增一列、重跑 W5 baseline（NAV 必須相同）、`verify_release` PASS。
3. 更新 `reports/ROUND_06_RELEASE_CANDIDATE.md` 的 recommended SHA；不刪除舊 SHA 紀錄。

## Rollback 流程
1. 確認目標 SHA：`scripts\verify_release.ps1 -Sha <old sha>` → PASS。
2. **人工**執行（Agent 不自動 reset）：先 `git stash` 或確認工作樹乾淨，再 `git checkout <old sha>`（或 `git switch -c rollback-<date> <old sha>`）。
3. `scripts\preflight.ps1 -Mode competition` → 不得 BLOCK。
4. 營運狀態（settlement / submissions / archive）不隨 git 回滾；如需還原用 `agent\ops\backup.py restore` 到新資料夾比對，**不要覆蓋**現有紀錄。
5. 在 `logs\ops\<T>\manual_decision.md` 記錄 rollback 原因、時間、操作者。

## 每日備份
`scripts\backup_competition_state.ps1`（不含 `.env` / API key / 原始資料）→ 複製到第二位置（IT 核准的媒體）。
