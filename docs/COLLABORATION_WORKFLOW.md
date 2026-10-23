# Collaboration Workflow — Owner + Claude Code + GitHub + ChatGPT Review

> 適用於本 repository 的長期開發流程。AI 產生內容，需人工審閱。角色與禁止事項的正式版本在 `CLAUDE.md`。
> **Single source of truth**：協作與 GitHub Shared State / handoff 規則在本文件（§7）；Owner Decision、merge 邊界、scope 與投資行為治理在 `docs/CODE_CHANGE_GOVERNANCE.md`。其他文件只放 pointer。

## 1. 流程

```
Owner 核准 Issue / Sprint
  → Claude Code：feature branch → 實作 → tests → (必要時) local freeze regression → push → Draft PR
  → CI（secret scan / quant-freeze-check / validate / pytest）PASS
  → PR 轉為 Ready for review（Implementation Recommendation = READY_FOR_REVIEW）
  → ChatGPT Review（Blocking / Non-blocking；APPROVE / APPROVE_WITH_FOLLOW_UP / REQUEST_CHANGES / DO_NOT_MERGE）
  → Claude Code 修正 → push 同一 branch → CI → 逐項回覆 → 第二輪 Review
  （每一步的狀態寫回 GitHub：status comment + agent:* label，見 §7）
  → Owner：MERGE（squash，刪 branch）/ DO_NOT_MERGE
```

- Claude Code 不 merge、不開 auto-merge、不 force push、不 rewrite history，日常不直推 `master`。
- 唯一例外：2026-10-21 的 bootstrap，把既有 `master` 歷史推上空 repo。之後不再直推。

## 2. Issue 類型與 branch

| Issue type | Branch prefix | 注意 |
|---|---|---|
| FEATURE | `feat/` | 不得改投資行為 |
| BUG | `fix/` | 附重現步驟 |
| OPS | `ops/` | 排程、資料、送件、DataPack |
| RESEARCH / EXPERIMENT | `research/` | 事前登錄 gate；保留負面結果；不得直接進 production |
| DOCS | `docs/` | 不需昂貴模擬 |
| COMPETITION_RULE_CHANGE | `ops/` 或 `fix/` | Owner 核准；記錄規則來源與 DQ 風險 |
| SECURITY | `fix/` | — |
| TECH_DEBT | `fix/` / `feat/` | 不改行為 |
| PROMOTION | `feat/` | 研究升級 production；需 freeze 前後比較與 Owner 決策 |

每個 Issue 一個 branch / 一個 PR；不相關的修改不合併。並行最多 2～3 條 track（低耦合可用 worktree）。

## 3. CI

| 層級 | 何時 | 內容 |
|---|---|---|
| FAST（`ci.yml`） | 每個 PR、push master | secret scan、quant-freeze-check（策略 hash + 凍結路徑 diff，需 Owner label 才能改）、syntax / import / config / schema、完整 pytest（合成 fixtures，約 5 分鐘） |
| FULL（`full-regression.yml`） | 手動 / 每晚 | 上述全部 |
| LOCAL freeze regression | 會影響決策路徑的 PR、release、比賽期間修改 | `scripts\ci\local_freeze_regression.py`：W5 NAV、24 decision hashes、凍結路徑。需要本機 `data/history`，不上 GitHub |

CI integrity：

- 不得刪有效測試、降低標準、hard-code 結果、skip / xfail 真 bug、移除 security test。
- 測試規格要改，PR 必須說明 WHY。

## 4. Review 回覆格式

```
Review item: <comment link / summary>
Resolution: fixed | rebutted (evidence) | follow-up #<issue> | won't fix (reason)
Modified file: <path>
Commit: <sha>
Test result: <command> -> <result>
```

## 5. Sprint 回報格式（GitHub 上以 §7.2 status comment 為準）

Track / Issue · Branch · PR URL · Changed files · Tests（例：560 passed, 0 failed）· CI · Quant Freeze · Experimental
Results · Known Limitations · Open Decisions · Implementation Recommendation（READY_FOR_REVIEW / NOT_READY / BLOCKED）

## 6. Evidence

- 比賽期間的 D-Plan、DataPack、receipt、submission evidence、execution logs、prompt / model 版本保留在本機（gitignored）。
- Git 只存 metadata：hash、timestamp、reference path、version（例如 `run_metadata.json` 的 hash 會寫進報告）。

## 7. GitHub = Shared State / Handoff / Control Plane（2026-10-23 起，強制）

GitHub 是 Owner、Claude Code、ChatGPT 共用的**正式狀態**。Owner 不需要把 Claude Code 的 terminal 輸出、session log、
測試結果轉貼給 ChatGPT；ChatGPT 只讀 GitHub（Issue、PR、comments、labels、commits、CI、repository docs）就能判斷進度、
blocker、待決事項與能否 merge。

### 7.1 資訊來源優先順序

1. GitHub Issue / Pull Request（body）
2. Issue / PR comments
3. labels、commits、CI / Actions
4. Repository docs
5. 本機證據（Claude Code session、terminal、memory、local logs、screenshots）

第 5 層只是 execution evidence。凡會影響後續實作、review、Owner Decision、blocker、merge、比賽營運、Quant freeze、
送件、DataPack 或排程的資訊，都必須摘要寫回 1–3 層。沒寫回 = `HANDOFF_INCOMPLETE`。

### 7.2 每次實質工作後的 status comment（固定格式）

寫在最相關的 Issue 或 PR，不能只在 terminal 回報：

```
## Execution Result
PASS / FAIL / BLOCKED / PARTIAL

## Scope

## Changes
- branch / HEAD commit SHA / PR
- changed files
- behaviour changed? (yes/no + what)
- Quant impact / submission impact / DataPack impact / scheduler impact

## Tests            (each: PASS / FAIL / NOT_RUN — never claim a test that did not run)
- targeted tests:
- full pytest: X passed, Y failed
- secret scan:
- config validation:
- quant freeze check:
- local freeze regression:

## CI               (workflow · check · PASS / FAIL / PENDING · failure reason)

## Quant Freeze     (strategy SHA · W5 NAV · 24/24 decision hashes · frozen path diff — or NOT_RUN)

## Known Limitations

## Blockers         (NONE or specific)

## Next Step

## Decision Required   (NONE / Owner Decision Required / ChatGPT Review Required)
```

### 7.3 ChatGPT review handoff

送 review 前必須：PR body 是目前真實狀態；PR 有一則完整 status comment（7.2）；branch / HEAD 明確；CI、Quant freeze、
Known Limitations、剩餘工作明確。然後加 label `agent:review`。

只看 GitHub、不看 Claude session，ChatGPT 必須能回答：Why、What changed、How it works、Which files、Tests、CI、
Quant freeze、Risks、Known limitations、Blockers、Rollback、Next step、是否需要 Owner 決策、是否可 review / merge。
做不到 = `NOT_READY_FOR_REVIEW`。

ChatGPT 與 PR 作者共用 GitHub 帳號時無法正式 Approve（GitHub 不允許 review 自己的 PR）。這不代表沒有 review：
review 結果以 PR comment 記錄：

```
CHATGPT_REVIEW_RECOMMENDATION = APPROVE | APPROVE_WITH_FOLLOW_UP | CHANGES_REQUESTED | BLOCKED
```

### 7.4 Workflow labels

| Label | 意義 |
|---|---|
| `agent:ready` | 已核准、可開始 |
| `agent:working` | Claude Code 實作中 |
| `agent:review` | 等 ChatGPT review（GitHub evidence 已齊） |
| `agent:changes-requested` | review 要求修改 |
| `agent:blocked` | 有 blocker（見 comment） |
| `agent:merge-ready` | 技術上可 merge，等 Owner |
| `agent:done` | 完成 |
| `owner:decision` | 等 Owner 決策（見 Owner Decision Required comment） |

- 同一 Issue / PR 只能有一個 `agent:*` 狀態（`agent:working` 與 `agent:review` 不可並存）。
- 正常流轉：ready → working → review → (changes-requested → working → review) → merge-ready → done。
- `owner:decision` 可與一個 `agent:*` 並存；Owner 決定並寫回 GitHub 後移除。
- 既有分類 labels（`type:*`、`owner-approved-investment-change`）照用，不改名。

查詢：`label:owner:decision` = 所有待 Owner 決策；`label:agent:review` = 所有待 ChatGPT review。

### 7.5 Blocker handoff

官方 portal、登入 / SSO、權限、API 限制、外部資料（TWSE / TPEx）不可用或過期、CI、Playwright、Task Scheduler、
環境、相依套件、merge conflict、DataPack 不可用、送件窗口不可用、官方檢核行為未知等 blocker，寫在 GitHub 並加
`agent:blocked`：

```
## Blocker
Observed evidence:
Timestamp:
Environment:
Affected scope:
What was attempted:
Safe work that can continue:
Work that must stop:
Owner Decision required: YES / NO
Workaround:
```

### 7.6 本機證據與敏感資料

本機證據（portal discovery、截圖、送件證據、Task Scheduler、PowerShell 輸出、行情更新、DataPack、local freeze
regression、`data/history`、receipt、SHA256、browser profile、local pytest、Claude 執行 log）不整包上傳。寫回 GitHub
用 **redacted summary**：timestamp、environment、purpose、command / operation、observed result、PASS / FAIL、相關錯誤、
artifact 的本機相對路徑與用途、結論。例如：`Portal discovery evidence: local, gitignored, data/portal_discovery/<ts>/`。

GitHub 永遠不能出現：password、API key、token、cookie、browser session / storage state、credential、private key、
CSRF token、secret env、帳號資料、個人資料。含帳號 email 的截圖留在本機；文字中以 `account_email = [REDACTED]` 表示。

### 7.7 比賽相關狀態

以下狀態必須在 GitHub 可見（只寫摘要，不寫每日 receipt / 帳號資料）：run_mode、下一個比賽交易日、送件準備度、
Portal E2E、auto-upload、DataPack 準備度、排程準備度、Quant freeze、Active Share 相關變更、送件 blocker、官方規則變更。
例：`AUTO_UPLOAD_STATUS = IMPLEMENTED_DISABLED_PENDING_E2E`、`REAL_E2E_STATUS = PENDING`、`QUANT_FREEZE = PASS`。

比賽開始後，正常的每日排程執行只留本機證據。發生 failure、blocker、code fix、規則解讀改變、送件 / DataPack
事故、portal 改版、重試行為改變、人工介入或影響比賽的 bug 時，必須建立或更新 GitHub Issue。

### 7.8 技術限制：`TECHNICAL_ENFORCEMENT_LIMITATION`

Private repo + GitHub Free：branch protection / rulesets API 回 HTTP 403（需 Pro 或 public，Issue #7）。不要重複嘗試。
替代措施：auto-merge disabled、squash-only、merge 後自動刪 branch、文件化的 Owner-only merge、CI checks、
禁止日常直推 `master`。

### 7.9 狀態用語

| 狀況 | 狀態 |
|---|---|
| 重要狀態沒寫回 GitHub | `HANDOFF_INCOMPLETE` |
| 等 review 但 GitHub evidence 不足 | `NOT_READY_FOR_REVIEW` |
| 需要 Owner 決策但只在 Claude session 問過 | `OWNER_DECISION_NOT_FORMALIZED` |
| 技術完成但缺 tests / CI / Quant freeze / known limitations / next step 紀錄 | `IMPLEMENTATION_HANDOFF_INCOMPLETE` |

Owner 決策與 merge 邊界的正式規則：`docs/CODE_CHANGE_GOVERNANCE.md` §6。
