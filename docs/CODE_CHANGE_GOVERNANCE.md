# 比賽期間程式修改治理（Code Change Governance）

> 依據：主辦方 2026-10-07 Email 回覆「強烈建議完整保留修改紀錄、版本、原因與執行 log 等以供備查」；
> D-Plan 撰寫指南 v4.3 ⑦：影響決策行為的參數與提示詞模板皆屬程式碼，改參數就是改版，須換新的 `code_version`。
> 本文件適用 2026-10-26 ～ 2026-11-27 初賽期間（含賽前凍結期）。AI 產生內容，需人工審閱。

## 1. 每一次修改必須保留

| 項目 | 存放位置 |
|---|---|
| timestamp | git commit 時間 + `docs/STRATEGY_FREEZE_RECORD.md` 變更表 |
| reason（為何修改、觸發事件） | commit message + 變更表「原因」欄 |
| affected files | `git show --stat <sha>` |
| git diff | git 歷史（不得 rebase / force push 已用於比賽的 commit） |
| git SHA / code_version | D-Plan `agent_metadata.code_version`（`git:<sha>`）、`run_metadata.json`、`FINAL_FREEZE.json` |
| regression result（before / after） | 修改前後完整 pytest 摘要（passed / failed / 秒數），貼入變更表或 reports/ |
| D-Plan impact | 修改前後同一交易日 dry-run 的 D-Plan 差異（`agent/ops/compare_candidates.py`） |
| Quant fingerprint | W5 replay：NAV 與 24 日 `decision_core_hash` 是否與 baseline 相同；當日 `decision_fingerprint` |
| before / after behavior | 一段文字說明行為差異 |
| execution log | `logs/ops/<T>/`、`archive/<T>/<run_id>/`（唯讀、含 sha256 manifest） |

## 2. 分類

**ALLOWED_TECHNICAL_CHANGE**（純技術修正，可在比賽期間進行，需完成 §1 紀錄）：
- bug fix（有重現步驟與回歸測試）
- 資料來源失效（data source failure）、API 格式變更、parser 修正
- timeout / 重試 / 鎖定等執行面修正
- auth 修正（例：Claude CLI 登入狀態偵測）
- 提交格式相容（submission / D-Plan schema 依官方新版調整）
- 官方規則同步（依官網公告 / 官方文件 / 主辦方正式回覆）

**NOT_A_TECHNICAL_CHANGE**（不可視為技術修正；若發生即屬人工介入投資決策，禁止）：
- 因昨日虧損而手動改選股或排除標的
- 因某檔股票跌停 / 大漲而人工移除或加入
- 人工修改 weight、target、現金區間或任何委託股數
- 依績效結果調整因子權重、門檻或 rebalance 參數（調參）
- 手動編輯 D-Plan 內容或 FINAL 檔

> 判斷原則：修改的動機若是「結果（績效）」而非「錯誤 / 規則 / 資料可用性」，就不是技術修正。

## 3. 流程
1. 開分支或在乾淨工作樹上修改；先寫能重現問題的測試。
2. 修改 → 完整 pytest（0 failed）→ W5 fingerprint 比對 → 同日 dry-run 比對 D-Plan。
3. 若 Quant fingerprint 改變：**停止**，不得用於比賽，除非是官方規則要求且另有書面紀錄。
4. 獨立 commit（`fix(...)` / `chore(rules)` 等），訊息寫明 reason；更新 `docs/STRATEGY_FREEZE_RECORD.md`。
5. 新 commit 產生新 `code_version`；比賽模式拒絕未提交修改（preflight BLOCK）。

## 4. 本次紀錄範例（2026-10-13 官方規則同步）
- 分類：ALLOWED_TECHNICAL_CHANGE（官方規則同步）
- 內容：Active Share 官方定義（前 15 大、占 NAV、15%）、D-Plan v4.3、DataPack 匯入、首個交易日、重繳規則
- Quant fingerprint：W5 NAV 與 24/24 日 decision_core_hash 不變
- 報告：`reports/OFFICIAL_RULE_SYNC_2026-10-07.md`

## 5. GitHub 流程（2026-10-21 起；`docs/COLLABORATION_WORKFLOW.md`、`CLAUDE.md`）

- 每一次修改都要有 GitHub Issue、feature branch 與 PR。PR 必須填 `.github/PULL_REQUEST_TEMPLATE.md` 全部欄位。
  上面 §1 要求的紀錄（timestamp、reason、Issue、affected files、diff、git SHA、code_version、before / after、
  regression、Quant fingerprint、D-Plan impact）都寫在 PR 中。merge 後 git 歷史即為紀錄。
- **Investment Behavior Change**（選股、排序、因子與權重、組合權重、rebalance、持有政策、委託股數、現金政策、
  risk overlay、regime、門檻、參數、會改變決策的 prompt / 模型行為）：
  - 必須先有 Owner 核准的 Issue（PROMOTION 或 COMPETITION_RULE_CHANGE）。
  - PR 要有 Owner 加上的 label `owner-approved-investment-change`。CI 的 `quant-freeze-check` 沒有這個 label 會擋下
    凍結路徑的修改。
  - 需附 freeze 前後比較。
  - 不得因近期績效而修改。
- **Technical / Operational Change**（parser、資料源、API 格式、timeout、auth、排程、送件格式、schema 相容、DataPack /
  receipt parser）：依 Issue 處理，附本機 `scripts\ci\local_freeze_regression.py` 結果，證明 Quant 不變。
- **Research ≠ production**：研究結果升級正式策略只能經由 PROMOTION Issue（production 設計 → 實作 → regression →
  freeze 比較 → PR → ChatGPT Review → Owner 決策）。負面結果必須保留。
- **Merge**：只有 Owner 能決定 merge（squash 優先）。不 auto-merge、不 force push、不 rewrite 歷史。
- 比賽期間的 D-Plan、DataPack、receipt、log 等原始證據留在本機。Git 只保留 metadata（hash、時間、路徑、版本）。

## 6. Owner Decision、Merge 邊界、Scope（2026-10-23 起；GitHub Shared State 見 `docs/COLLABORATION_WORKFLOW.md` §7）

### 6.1 必須由 Owner 在 GitHub 決定的事項

Quant / 投資行為、strategy config、`run_mode` 切換、auto-upload 啟用、送件政策、排程行為、DataPack 來源 / fallback、
架構、schema、API、credential 模型、security 邊界、browser automation 政策、外部服務、付費相依、資料源、部署模式、
breaking behaviour、merge 順序、互斥的實作選項。

這些不能只在 Claude Code session 裡問。流程：

1. 在相關 Issue / PR 留 `## Owner Decision Required` comment（6.2）。
2. 加 label `owner:decision`。
3. 停止依賴該決策的工作；不相關且安全的工作可以繼續。

### 6.2 Owner Decision Required（固定格式）

```
## Owner Decision Required
### Context
### Why a decision is required        (why Claude Code cannot decide)
### Option A                          (implementation · benefits · drawbacks · risks · competition impact · downstream impact)
### Option B
### Option C                          (only if a real third option exists)
### Recommendation
DO NOT IMPLEMENT THE RECOMMENDATION UNTIL OWNER APPROVES.
### Impact if deferred                (blocked work / PRs / competition operations)
### Owner Action                      (reply: Choose A / B / C — or Decision 1: A/B, Decision 2: A/B)
```

### 6.3 Owner Decision（決定後、繼續實作前寫回）

```
## Owner Decision
Chosen option:
Decision date:
Approved scope:
Competition impact:
Quant impact:
Submission impact:
Consequence:
Follow-up work:
Superseded options:
Owner approval source:              (e.g. "Owner reply in Claude Code session 2026-10-23 23:40", or the comment link)
```

寫回後移除 `owner:decision`。沒有這筆紀錄就繼續實作 = `OWNER_DECISION_NOT_FORMALIZED`。

### 6.4 Merge 邊界

Claude Code、ChatGPT、任何 agent / worker 都不 merge；只有 Owner merge。PR 技術上可 merge 時加 `agent:merge-ready`，
並留下：

```
IMPLEMENTATION_STATUS = COMPLETE
CHATGPT_REVIEW_STATUS = APPROVED | APPROVED_WITH_FOLLOW_UP
OWNER_MERGE_DECISION = PENDING
```

### 6.5 不得自行擴張重大 scope

完成一項工作後可以：修 CI、處理 review、補測試、文件、不改行為的整理、分析、提案、整理證據。不得自行開始（需要
Issue + Owner 核准）：新的 Quant 研究、新策略、架構替換、breaking schema、新部署模式、security 模型變更、新資料供應者、
啟用比賽 auto-upload、切換 COMPETITION `run_mode`。協作工具與治理文件的變更不得改變投資行為。
